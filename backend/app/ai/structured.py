"""JSON-schema'd calls through the AI Router — quiz generation and writing evaluation.

Neither task uses provider-native JSON mode / function calling: OpenRouter fans out to
many providers and not all of them implement structured-output modes consistently, so
we instruct-and-parse instead — strict "JSON only" in the prompt, tolerant extraction
on the way back, and exactly one repair retry (feeding the validation error back to
the model) before giving up. This is the same trade the router already makes at the
model layer (try, fail over, then give up) applied one level up at the payload layer.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import router as ai_router
from app.ai.prompts import (
    QUIZ_GENERATE_SYSTEM_PROMPT,
    WRITING_EVALUATE_SYSTEM_PROMPT,
    build_context_block,
)
from app.ai.tasks import TaskType
from app.core.errors import UpstreamError

log = structlog.get_logger(__name__)


# ── Tolerant JSON extraction ─────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a model response that may still wrap it in
    markdown fences or a stray sentence despite being told "JSON only".

    Strips ``` fences, then takes the substring between the first ``{`` and the
    last ``}``. Raises ``ValueError`` (never a raw ``json.JSONDecodeError``) so
    callers have one exception type to catch.
    """
    text = _CODE_FENCE_RE.sub("", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


# ── Quiz ──────────────────────────────────────────────────────────────────────


class QuizQuestion(BaseModel):
    id: str
    type: Literal["mcq", "cloze"]
    prompt: str
    options: list[str] | None = None
    # Kept on this internal model so the caller can persist it for server-side
    # grading. NEVER let it reach a client response or an LLM's visible context —
    # see the registry tool wrapper (app/ai/tools/registry.py), which strips this
    # field before the quiz becomes a tool_result the chat model can see/repeat.
    expected: str
    explanation: str


class GeneratedQuiz(BaseModel):
    topic: str
    cefr_level: str
    questions: list[QuizQuestion]
    sources: list[dict[str, Any]] | None = None


# ── Writing evaluation ────────────────────────────────────────────────────────


class WritingScores(BaseModel):
    grammar: float
    vocabulary: float
    coherence: float
    overall: float


class Correction(BaseModel):
    original: str
    suggestion: str
    explanation: str
    severity: Literal["error", "warning", "style"]
    offset: int
    length: int


class WritingEvaluation(BaseModel):
    scores: WritingScores
    cefr_estimate: str
    corrections: list[Correction] = Field(default_factory=list)
    improved_version: str
    suggestions: list[str] = Field(default_factory=list)


# ── Shared instruct-parse-repair loop ─────────────────────────────────────────


async def _complete_structured(
    db: AsyncSession,
    *,
    task_type: TaskType,
    system_prompt: str,
    user_prompt: str,
    model_cls: type[BaseModel],
    user_id: Any | None,
    extra_check: Any = None,
) -> Any:
    """Run one completion, validate as JSON against `model_cls`, and — if that
    fails — retry exactly once with the validation error fed back to the model.

    `extra_check(obj)` may raise `ValueError` for validity rules Pydantic can't
    express (e.g. "exactly n questions"); that also triggers the repair retry.
    """

    def _validate(text: str) -> Any:
        obj = model_cls.model_validate(parse_json_object(text))
        if extra_check is not None:
            extra_check(obj)
        return obj

    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    result = await ai_router.complete(db, task_type=task_type, messages=messages, user_id=user_id)
    try:
        return _validate(result.text)
    except (ValueError, ValidationError) as exc:
        log.warning("structured_json_invalid", task=str(task_type), error=str(exc))
        messages.append(AIMessage(content=result.text))
        messages.append(
            HumanMessage(
                content=(
                    "Your previous response was not valid JSON matching the requested "
                    f"schema. Validation error: {exc}\n"
                    "Return ONLY the corrected JSON object — no prose, no markdown fences."
                )
            )
        )
        retry = await ai_router.complete(
            db, task_type=task_type, messages=messages, user_id=user_id
        )
        try:
            return _validate(retry.text)
        except (ValueError, ValidationError) as exc2:
            log.warning("structured_json_repair_failed", task=str(task_type), error=str(exc2))
            raise UpstreamError(
                "The AI model returned malformed JSON even after a repair attempt."
            ) from exc2


async def generate_quiz(
    db: AsyncSession,
    *,
    topic: str,
    cefr_level: str,
    n: int,
    user_id: Any | None,
    passages: list[dict[str, Any]] | None = None,
    # Defaults to German so every existing caller is unaffected; the tutor passes
    # the learner's actual target language through.
    target_language: str = "German",
) -> GeneratedQuiz:
    system_prompt = QUIZ_GENERATE_SYSTEM_PROMPT.format(
        n=n, topic=topic, cefr_level=cefr_level, target_language=target_language
    )
    context_block = build_context_block(passages or [])
    schema_hint = (
        "Return ONLY a JSON object with exactly this shape (no markdown fences, no prose):\n"
        '{"topic": "...", "cefr_level": "A2", "questions": ['
        '{"id": "q1", "type": "mcq", "prompt": "...", '
        '"options": ["...", "...", "...", "..."], "expected": "...", "explanation": "..."}'
        '], "sources": null}\n'
        'For "cloze" questions, set "options" to null. Produce exactly '
        f"{n} question(s)."
    )
    user_prompt = f"{context_block}\n\n{schema_hint}" if context_block else schema_hint

    def _check_count(quiz: GeneratedQuiz) -> None:
        if len(quiz.questions) != n:
            raise ValueError(f"expected {n} questions, got {len(quiz.questions)}")

    quiz = await _complete_structured(
        db,
        task_type=TaskType.QUIZ_GENERATE,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_cls=GeneratedQuiz,
        user_id=user_id,
        extra_check=_check_count,
    )
    return quiz


async def evaluate_writing(
    db: AsyncSession,
    *,
    text: str,
    target_level: str,
    prompt: str | None = None,
    user_id: Any | None,
    target_language: str = "German",
) -> WritingEvaluation:
    system_prompt = WRITING_EVALUATE_SYSTEM_PROMPT.format(
        target_level=target_level, target_language=target_language
    )
    schema_hint = (
        "Return ONLY a JSON object with exactly this shape (no markdown fences, no prose):\n"
        '{"scores": {"grammar": 0.0, "vocabulary": 0.0, "coherence": 0.0, "overall": 0.0}, '
        '"cefr_estimate": "A2", "corrections": [{"original": "...", "suggestion": "...", '
        '"explanation": "...", "severity": "error", "offset": 0, "length": 0}], '
        '"improved_version": "...", "suggestions": ["..."]}'
    )
    parts = []
    if prompt:
        parts.append(f"Writing prompt: {prompt}")
    parts.append(f"Learner's text:\n{text}")
    parts.append(schema_hint)
    user_prompt = "\n\n".join(parts)

    evaluation = await _complete_structured(
        db,
        task_type=TaskType.WRITING_EVALUATE,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_cls=WritingEvaluation,
        user_id=user_id,
    )
    return evaluation
