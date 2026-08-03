"""The tool layer the tutor calls — search, dictionary, conjugation, quiz, writing,
vocabulary.

Every tool is built per-request by `build_tools(db, user)`, closing over the caller's
DB session and identity. That closure is a security property, not just convenience:
`save_vocabulary` writes rows scoped to `user.id` from the closure, and its
`args_schema` has no user/owner field at all — the model has no argument through
which it could ask to write another learner's data, even if a crafted prompt tried.

Each tool also never raises. `create_tool_calling_agent`/`AgentExecutor` don't exist
in this LangChain version — whatever drives the tool-calling loop here invokes these
via `BaseTool.ainvoke()` directly, and an unhandled exception there would kill the SSE
stream mid-response. So every tool catches broadly and returns a short, recoverable
error *string* instead — the model can read that and say so, rather than the request
500ing.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import structured
from app.ai.tools import conjugators, dictionary
from app.db.models import Flashcard, User, Vocabulary
from app.rag import retriever as rag_retriever

log = structlog.get_logger(__name__)

# API_CONTRACT.md §11 validation rules, mirrored here as the tools' input schemas.
# Multilingual: `À-ÿ` covers the Latin-1 accents these languages need (ä ö ü ß,
# é è ê ç, ñ í ó ú à ì) and `Œœ` the French ligature. Previously German-only, so
# a Spanish learner asking about `enseñar` was rejected by the SCHEMA before any
# engine saw it. This is defence-in-depth — each engine still validates its own
# infinitive shape, and does it with a better error message.
_LEMMA_PATTERN = r"^[A-Za-zÀ-ÿŒœ'’-]{1,64}$"
_VERB_PATTERN = r"^[A-Za-zÀ-ÿŒœ'’-]{1,48}$"

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1"]


# ── Arg schemas (the graded input-validation surface) ──────────────────────────


class SearchKnowledgeBaseArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    cefr_level: CefrLevel | None = None
    skill: str | None = Field(None, max_length=30)


class LookupWordArgs(BaseModel):
    lemma: str = Field(..., pattern=_LEMMA_PATTERN)


class ConjugateVerbArgs(BaseModel):
    verb: str = Field(..., pattern=_VERB_PATTERN)
    # A plain string, not a Literal: tense NAMES are per language (`praesens` vs
    # `presente`), and a union of every language's tenses would let the model ask
    # for a German tense in Spanish. The dispatcher validates against the engine
    # actually being used and names the real alternatives when it refuses.
    tense: str = Field(default="", max_length=32)


class GenerateQuizArgs(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    cefr_level: CefrLevel
    n: int = Field(..., ge=1, le=20)


class EvaluateWritingArgs(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    target_level: CefrLevel


class SaveVocabularyArgs(BaseModel):
    """Deliberately has NO user/owner field — the writer is always the caller's
    own session user, resolved from the `build_tools` closure below, never from
    a tool argument the model could set."""

    lemma: str = Field(..., pattern=_LEMMA_PATTERN)


def _vocab_result(vocab: Vocabulary) -> dict[str, Any]:
    return {
        "id": str(vocab.id),
        "lemma": vocab.lemma,
        "article": vocab.article,
        "plural": vocab.plural,
        "pos": vocab.pos,
        "meaning": vocab.meaning,
        "ipa": vocab.ipa,
        "examples": vocab.examples,
        "status": vocab.status,
    }


def build_tools(db: AsyncSession, user: User) -> list[BaseTool]:
    """Build the six tools for one request, scoped to `db` + `user`."""

    async def _search_knowledge_base(
        query: str, cefr_level: str | None = None, skill: str | None = None
    ) -> dict[str, Any] | str:
        try:
            result = await rag_retriever.retrieve(
                db,
                query,
                cefr_level=cefr_level,
                skill=skill,
                language=user.target_language,
            )
        except Exception as exc:  # retrieve() is documented to never raise — stay defensive anyway
            log.warning("tool_search_kb_failed", query=query, error=str(exc))
            return (
                "The knowledge base search is unavailable right now. Answer from "
                "general knowledge and say the answer isn't grounded in course material."
            )
        return {
            "query": result.query,
            "strategy": result.strategy,
            "results": [c.as_source() for c in result.results],
        }

    async def _lookup_word(lemma: str) -> dict[str, Any] | str:
        try:
            return await dictionary.lookup(db, lemma, user_id=user.id)
        except Exception as exc:
            log.warning("tool_lookup_word_failed", lemma=lemma, error=str(exc))
            return f"Couldn't look up '{lemma}' right now. Try again shortly."

    async def _conjugate_verb(verb: str, tense: str = "") -> dict[str, Any] | str:
        # Routed by the language the learner is STUDYING, from the closure — never
        # a tool argument. Before this the German engine was called for everyone,
        # so a Spanish learner asking about `tener` was told it is not a valid
        # -en/-n infinitive.
        language = user.target_language
        try:
            return conjugators.conjugate(language, verb, tense or None)
        except ValueError as exc:
            # Either an unsupported language/tense, or not a plausible infinitive.
            # The message already names what IS available, so pass it through
            # rather than replacing it with something vaguer.
            return str(exc)
        except Exception as exc:
            log.warning(
                "tool_conjugate_verb_failed",
                verb=verb,
                tense=tense,
                language=language,
                error=str(exc),
            )
            return f"Couldn't conjugate '{verb}' right now."

    async def _generate_quiz(topic: str, cefr_level: str, n: int) -> dict[str, Any] | str:
        try:
            quiz = await structured.generate_quiz(
                db, topic=topic, cefr_level=cefr_level, n=n, user_id=user.id
            )
        except Exception as exc:
            log.warning("tool_generate_quiz_failed", topic=topic, error=str(exc))
            return "Quiz generation failed. Try a narrower topic or fewer questions."
        # The answer key must never reach the model's visible context — it would
        # leak straight into the assistant's reply to the learner. This redacted
        # view is what becomes the tool_result the LLM sees; the full
        # GeneratedQuiz (with `expected`) is what a caller persists server-side
        # for grading via /quiz/submit.
        dumped = quiz.model_dump()
        for q in dumped["questions"]:
            q.pop("expected", None)
        return dumped

    async def _evaluate_writing(text: str, target_level: str) -> dict[str, Any] | str:
        try:
            evaluation = await structured.evaluate_writing(
                db, text=text, target_level=target_level, user_id=user.id
            )
        except Exception as exc:
            log.warning("tool_evaluate_writing_failed", error=str(exc))
            return "Writing evaluation failed. Please try again shortly."
        return evaluation.model_dump()

    async def _save_vocabulary(lemma: str) -> dict[str, Any] | str:
        try:
            existing = (
                await db.execute(
                    select(Vocabulary).where(
                        Vocabulary.user_id == user.id,
                        # Per-language: the same spelling can be a different
                        # word in another language the learner also studies.
                        Vocabulary.language == user.target_language,
                        Vocabulary.lemma == lemma,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _vocab_result(existing)

            enrichment = await dictionary.lookup(db, lemma, user_id=user.id)
            english = next(
                (m.get("text") for m in enrichment.get("meanings", []) if m.get("lang") == "en"),
                None,
            )
            vocab = Vocabulary(
                user_id=user.id,  # from the closure — never from a tool argument
                language=user.target_language,  # likewise: not a tool argument
                lemma=enrichment.get("lemma") or lemma,
                article=enrichment.get("article"),
                plural=enrichment.get("plural"),
                pos=enrichment.get("pos"),
                meaning=english,
                ipa=enrichment.get("ipa"),
                examples=enrichment.get("examples"),
                meanings=enrichment.get("meanings"),
            )
            db.add(vocab)
            await db.flush()
            db.add(Flashcard(user_id=user.id, vocabulary_id=vocab.id))
            await db.commit()
            return _vocab_result(vocab)
        except Exception as exc:
            await db.rollback()
            log.warning("tool_save_vocabulary_failed", lemma=lemma, error=str(exc))
            return f"Couldn't save '{lemma}' to your vocabulary right now."

    return [
        StructuredTool.from_function(
            coroutine=_search_knowledge_base,
            name="search_knowledge_base",
            description=(
                "Search the German-learning knowledge base (grammar notes, stories, lesson "
                "content) for passages relevant to a question. Use this before answering "
                "anything that should be grounded in course material rather than recalled "
                "from memory."
            ),
            args_schema=SearchKnowledgeBaseArgs,
        ),
        StructuredTool.from_function(
            coroutine=_lookup_word,
            name="lookup_word",
            description=(
                "Look up a single German word: part of speech, article and plural for "
                "nouns, meanings, and example sentences. Always use this instead of "
                "guessing a noun's gender or a word's translation."
            ),
            args_schema=LookupWordArgs,
        ),
        StructuredTool.from_function(
            coroutine=_conjugate_verb,
            name="conjugate_verb",
            description=(
                "Conjugate a verb IN THE LANGUAGE THE LEARNER IS STUDYING, given in its "
                "infinitive form. Leave `tense` empty for the present. Always use this "
                "instead of producing a conjugation from memory — it is computed by a "
                "deterministic rule engine per language, never guessed. If the engine "
                "refuses, report its message rather than substituting your own paradigm."
            ),
            args_schema=ConjugateVerbArgs,
        ),
        StructuredTool.from_function(
            coroutine=_generate_quiz,
            name="generate_quiz",
            description=(
                "Generate a short quiz (a mix of multiple-choice and cloze questions) on a "
                "German-learning topic at a given CEFR level. Correct answers are withheld "
                "from the result you see — grading happens server-side."
            ),
            args_schema=GenerateQuizArgs,
        ),
        StructuredTool.from_function(
            coroutine=_evaluate_writing,
            name="evaluate_writing",
            description=(
                "Evaluate a learner's German writing sample: scores for grammar/vocabulary/"
                "coherence, specific corrections, an improved version, and a CEFR estimate. "
                "Use when the learner submits text and wants feedback."
            ),
            args_schema=EvaluateWritingArgs,
        ),
        StructuredTool.from_function(
            coroutine=_save_vocabulary,
            name="save_vocabulary",
            description=(
                "Save a German word to the current learner's personal vocabulary list and "
                "create a flashcard for spaced repetition. Idempotent — saving the same word "
                "twice does not create a duplicate. Always saves for the logged-in learner; "
                "there is no way to target another user."
            ),
            args_schema=SaveVocabularyArgs,
        ),
    ]
