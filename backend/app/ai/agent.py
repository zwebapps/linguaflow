"""The AI Language Tutor — a LangChain tool-calling agent streamed as SSE.

This is the core of the product: the model is given the domain tools from
`app.ai.tools.registry` and decides what to call. RAG passages are pre-retrieved
and injected as *fenced, scrubbed* reference material.

## LangChain version note (important)

Built against **LangChain 1.x**. `create_tool_calling_agent` / `AgentExecutor` were
removed from `langchain.agents`; the current API is `create_agent(...)`, which returns
a LangGraph `CompiledStateGraph`. We stream with `astream_events(version="v2")` and map
its events onto our SSE protocol (API_CONTRACT.md §2):

| LangChain event                            | our SSE event         |
|--------------------------------------------|-----------------------|
| `on_chat_model_stream` w/ `tool_calls`     | `tool_call`           |
| `on_chat_model_stream` w/ `content`        | `token`               |
| `on_tool_start`                            | `status` (calling…)   |
| `on_tool_end`                              | `tool_result`         |
| `on_chat_model_end`                        | accumulate usage      |

Event ORDER is part of the frontend contract, so it is asserted in tests.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.languages import native_name
from app.ai.languages import target as target_language
from app.ai.openrouter import estimate_cost, make_llm
from app.ai.prompts import build_context_block, looks_like_injection
from app.ai.router import AIResult, load_policy, record_usage
from app.ai.tasks import TaskType
from app.db.models import Message, Thread, User

log = structlog.get_logger(__name__)

# The agent may loop model→tool→model; bound it so a confused model can't spin.
MAX_ITERATIONS = 6

# How much of the conversation the tutor is reminded of. Six turns covers the
# follow-ups learners actually make ("and the plural?", "again in English")
# without letting an hour-long thread dominate the prompt; the per-turn cap
# stops one pasted essay from crowding out the other five.
HISTORY_TURNS = 6
HISTORY_CHARS_PER_TURN = 2000

# Words that mean "this is a grammar question", which routes to the stronger
# reasoning model rather than the cheaper conversational one.
_GRAMMAR_HINTS = (
    "grammar", "grammatik", "case", "kasus", "dativ", "dative", "akkusativ",
    "accusative", "genitiv", "nominativ", "conjugat", "konjugier", "declen",
    "deklin", "tense", "zeitform", "präteritum", "praeteritum", "perfekt",
    "subjunctive", "konjunktiv", "plural", "artikel", "article", "adjective ending",
    "word order", "wortstellung", "preposition", "präposition",
)


def pick_task(message: str) -> TaskType:
    """Grammar questions deserve the reasoning model; chat gets the fast one."""
    low = (message or "").lower()
    return (
        TaskType.GRAMMAR_EXPLAIN
        if any(h in low for h in _GRAMMAR_HINTS)
        else TaskType.CONVERSATION
    )


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """One SSE frame, with `data` serialised to JSON.

    The serialisation is NOT optional: `sse_starlette` renders a non-str `data`
    with `str()`, which emits a Python dict repr — single-quoted keys that
    `JSON.parse()` rejects. Every event would fail to parse in the browser.
    """
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


def _status(stage: str, label: str) -> dict[str, Any]:
    return _sse("status", {"stage": stage, "label": label})


def _title_from(message: str) -> str:
    clean = " ".join((message or "").split())
    return (clean[:60].rstrip() + "…") if len(clean) > 60 else (clean or "New conversation")


async def load_history(
    db: AsyncSession,
    thread_id: uuid.UUID,
    *,
    limit: int = HISTORY_TURNS,
) -> list[tuple[str, str]]:
    """The last few turns of a thread, oldest first, as (role, content) pairs.

    Without this the tutor answers every message as if it were the first: it
    can't resolve "say that again in English", loses the topic between turns,
    and re-asks a question the learner just answered.

    The window is bounded rather than the whole thread — a long conversation
    would otherwise grow the prompt without limit, and the far end of it stops
    being relevant well before it stops costing tokens.

    SQL only bounds how much is READ (with headroom for rows the filter below
    drops); which turns actually survive is decided here, in Python, so the
    rules are visible and testable without a database.
    """
    rows = (
        (
            await db.execute(
                select(Message.role, Message.content)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit * 2)
            )
        )
        .tuples()
        .all()
    )
    turns = [
        (role, content[:HISTORY_CHARS_PER_TURN])
        for role, content in reversed(rows)
        # An assistant row is inserted blank and filled as it streams, so a
        # failed turn leaves one behind; replaying it is noise at best and a
        # provider error at worst.
        if role in ("user", "assistant") and (content or "").strip()
    ]
    return turns[-limit:]


async def _build_tools(db: AsyncSession, user: User) -> list[Any]:
    """Tools are optional — a missing registry must not take the tutor down."""
    try:
        from app.ai.tools.registry import build_tools

        return list(build_tools(db, user))
    except Exception as exc:
        log.warning("tool_registry_unavailable", error=str(exc))
        return []


async def stream_tutor_turn(
    db: AsyncSession,
    user: User,
    *,
    thread: Thread,
    message: str,
    context: dict[str, Any] | None = None,
    model_override: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one tutor turn, yielding SSE frames in the contract's order.

    Persists the user + assistant messages and records model usage. Any failure is
    surfaced as an `error` frame rather than a dropped connection — the frontend
    shows an inline retry.
    """
    context = context or {}
    started = time.perf_counter()

    cefr = str(context.get("cefr_level") or user.cefr_level or "A1")
    task = pick_task(message)
    policy = await load_policy(db, str(task))
    chain = [model_override] if model_override else policy.chain
    model = chain[0]

    # Read the thread BEFORE the new message is written, so the window is
    # unambiguously "what was said before this turn".
    history = await load_history(db, thread.id)

    # Persist the learner's message immediately so a mid-stream failure doesn't
    # lose it from the thread.
    db.add(Message(thread_id=thread.id, role="user", content=message))
    if thread.title in (None, "", "New conversation"):
        thread.title = _title_from(message)
    await db.commit()

    assistant = Message(thread_id=thread.id, role="assistant", content="", model=model)
    db.add(assistant)
    await db.commit()
    await db.refresh(assistant)

    yield _sse(
        "start",
        {
            "thread_id": str(thread.id),
            "message_id": str(assistant.id),
            "model": model,
        },
    )

    if looks_like_injection(message):
        # Not blocked: a learner may innocently ask about "instructions". Logged,
        # and the system prompt is re-asserted below regardless of message content.
        log.warning(
            "prompt_injection_suspected",
            user_id=str(user.id),
            thread_id=str(thread.id),
            preview=message[:120],
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────
    yield _status("retrieving", "Searching the knowledge base…")
    passages: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    try:
        from app.rag import experiments as exp_mod
        from app.rag.retriever import retrieve

        # A/B: strategy is chosen by a stable hash of the user id, so a given
        # learner always gets the same arm (see app/rag/experiments.py). When no
        # experiment is running this returns the configured default.
        experiment = await exp_mod.load_experiment(db)
        strategy, experiment_name = exp_mod.assign_arm(str(user.id), experiment)

        # Deliberately NOT filtered to the learner's exact CEFR level. An A2
        # learner benefits from A1 material, and filtering on equality means a C1
        # learner matches nothing in an A1/A2-heavy corpus — which is exactly the
        # empty-sources bug this replaced. Level-appropriateness is handled in the
        # system prompt (the tutor calibrates its answer), not by hiding material.
        found = await retrieve(
            db,
            message,
            strategy=strategy,
            document_id=context.get("document_id"),
            # Ground ONLY in the language being learned. Without this the tutor
            # could cite a German grammar chunk while answering a Spanish
            # question — a confidently wrong answer, the worst failure mode for
            # a teaching product.
            language=getattr(user, "target_language", None),
        )
        passages = [
            {"id": c.id, "title": c.title, "text": c.text, "snippet": c.snippet}
            for c in found.results
        ]
        sources = [c.as_source() for c in found.results]

        await exp_mod.record_event(
            db,
            user_id=user.id,
            experiment=experiment_name,
            arm=strategy,
            strategy=found.strategy,
            query=message,
            n_results=len(found.results),
            top_score=found.results[0].score if found.results else None,
            latency_ms=found.took_ms,
        )
    except Exception as exc:
        # Retrieval is an enhancement, not a precondition — answer ungrounded
        # rather than failing the turn.
        log.warning("retrieval_failed_in_agent", error=str(exc))

    if sources:
        yield _sse("sources", {"sources": sources})

    # ── Prompt ────────────────────────────────────────────────────────────────
    # The learner's own languages are DATA, not an assumption baked into the
    # prompt. Before this, the prompt said "explain in the learner's language"
    # without ever naming it, so every learner got English.
    from app.ai.prompt_registry import resolve as resolve_prompt

    system_prompt = (await resolve_prompt(db, "tutor_system")).format(
        cefr_level=cefr,
        native_language=native_name(getattr(user, "native_language", None)),
        target_language=target_language(getattr(user, "target_language", None)).name,
    )
    if block := build_context_block(passages):
        system_prompt = f"{system_prompt}\n\n{block}"

    tools = await _build_tools(db, user)

    yield _status("thinking", "Thinking…")

    final_text: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tokens_in = tokens_out = 0
    used_model = model
    fallback_used = False
    emitted_any_token = False

    last_error: Exception | None = None

    for idx, candidate in enumerate(chain):
        try:
            llm = make_llm(candidate, streaming=True, **policy.params)
            graph = create_agent(model=llm, tools=tools, system_prompt=system_prompt)

            async for ev in graph.astream_events(
                # Prior turns first: without them every message is answered as
                # if it were the first thing said.
                {"messages": [*history, ("user", message)]},
                version="v2",
                config={"recursion_limit": MAX_ITERATIONS * 2},
            ):
                kind = ev.get("event")

                if kind == "on_chat_model_stream":
                    chunk = ev["data"].get("chunk")
                    if chunk is None:
                        continue

                    # NOTE: we deliberately do NOT emit `tool_call` from here.
                    # While streaming, a chunk's `tool_calls` arrive incrementally
                    # and `args` is usually still empty — emitting now produced
                    # tool chips with `{}` args in the UI. `on_tool_start` below
                    # carries the fully-parsed input, so that's the honest source.

                    text = chunk.content
                    if isinstance(text, list):
                        # Some providers stream content as blocks.
                        text = "".join(
                            b.get("text", "") for b in text if isinstance(b, dict)
                        )
                    if text:
                        final_text.append(str(text))
                        emitted_any_token = True
                        yield _sse("token", {"text": str(text)})

                elif kind == "on_tool_start":
                    name = ev.get("name") or "tool"
                    # `run_id` is stable across this tool's start/end pair, which is
                    # how the UI matches a result back to its chip.
                    call_id = str(ev.get("run_id") or f"call_{len(tool_calls)}")
                    entry = {
                        "id": call_id,
                        "name": name,
                        "args": ev["data"].get("input") or {},
                    }
                    tool_calls.append({**entry, "_started": time.perf_counter()})
                    yield _sse("tool_call", entry)
                    yield _status("calling_tool", f"Calling {name}…")

                elif kind == "on_tool_end":
                    output = ev["data"].get("output")
                    # ToolMessage → take its content; anything else → stringify.
                    result = getattr(output, "content", output)
                    name = ev.get("name") or ""
                    call_id = str(ev.get("run_id") or name)

                    elapsed = 0
                    for entry in tool_calls:
                        if entry["id"] == call_id:
                            entry["result"] = result
                            elapsed = int((time.perf_counter() - entry.pop("_started", 0)) * 1000)
                            break

                    yield _sse(
                        "tool_result",
                        {
                            "id": call_id,
                            "name": name,
                            "ok": True,
                            "result": result,
                            "ms": elapsed,
                        },
                    )
                    yield _status("generating", "Writing the answer…")

                elif kind == "on_chat_model_end":
                    out = ev["data"].get("output")
                    if isinstance(out, AIMessage):
                        um = getattr(out, "usage_metadata", None) or {}
                        tokens_in += int(um.get("input_tokens", 0) or 0)
                        tokens_out += int(um.get("output_tokens", 0) or 0)

            used_model = candidate
            fallback_used = idx > 0
            if idx > 0:
                log.warning(
                    "agent_fallback_used", primary=chain[0], used=candidate, task=str(task)
                )
            break

        except Exception as exc:
            last_error = exc
            log.warning(
                "agent_model_failed",
                model=candidate,
                task=str(task),
                error=str(exc)[:300],
            )
            if emitted_any_token:
                # We've already streamed part of an answer; restarting on another
                # model would duplicate text in the UI. Stop and report.
                break
            continue
    else:
        # Every model failed before producing anything.
        log.error("agent_all_models_failed", task=str(task), chain=chain)

    answer = "".join(final_text).strip()

    if not answer and last_error is not None:
        yield _sse(
            "error",
            {
                "code": "all_models_failed",
                "message": "The tutor is unavailable right now. Please try again in a moment.",
            },
        )
        # Keep the thread clean rather than leaving a blank assistant turn.
        await db.delete(assistant)
        await db.commit()
        return

    latency_ms = int((time.perf_counter() - started) * 1000)
    cost_usd, cost_micro = await estimate_cost(used_model, tokens_in, tokens_out)

    usage = {
        "model": used_model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "from_cache": False,
        "latency_ms": latency_ms,
    }

    assistant.content = answer or "(no answer produced)"
    assistant.model = used_model
    assistant.sources = sources or None
    assistant.tool_calls = tool_calls or None
    assistant.usage = usage
    await db.commit()

    await record_usage(
        db,
        user_id=user.id,
        task_type=str(task),
        result=AIResult(
            text=answer,
            model_used=used_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            cost_micro_usd=cost_micro,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
        ),
    )

    yield _sse("usage", usage)
    yield _sse("done", {"message_id": str(assistant.id), "thread_id": str(thread.id)})
