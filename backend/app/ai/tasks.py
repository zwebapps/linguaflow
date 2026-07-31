"""Task taxonomy + the default routing policy (ARCHITECTURE.md §5.1–5.2).

The app never hardcodes a model. Every AI call declares a *task*; the AI Router
resolves task → model policy at request time, reading the ``ai_routes`` table
(seeded from DEFAULT_ROUTES below) so an admin can re-point a task at a different
model with no redeploy.

Model ids are OpenRouter slugs. They are *defaults* — verify availability in the
live catalog (`GET /api/v1/admin/models`) and re-point from the admin UI.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TaskType(StrEnum):
    GRAMMAR_EXPLAIN = "grammar_explain"
    TRANSLATE = "translate"
    VOCAB_EXAMPLE = "vocab_example"
    CONTENT_GENERATE = "content_generate"
    WRITING_EVALUATE = "writing_evaluate"
    CONVERSATION = "conversation"
    QUIZ_GENERATE = "quiz_generate"
    EMBEDDING = "embedding"
    # Voice — OpenRouter serves STT + TTS alongside chat, so the same routing,
    # fallback and cost-accounting machinery covers the speaking module.
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    PRONUNCIATION_SCORE = "pronunciation_score"


# Cheap, capable defaults. Tuned per task rather than one model for everything.
DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    TaskType.GRAMMAR_EXPLAIN: {
        "primary_model": "anthropic/claude-sonnet-5",
        "fallbacks": ["openai/gpt-4o", "google/gemini-2.5-flash"],
        "params": {"temperature": 0.3, "max_tokens": 1400},
    },
    TaskType.CONVERSATION: {
        "primary_model": "openai/gpt-4o",
        "fallbacks": ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash"],
        "params": {"temperature": 0.6, "max_tokens": 1200},
    },
    TaskType.TRANSLATE: {
        # Word lookups are the highest-volume call in the product and are cached,
        # so the cheapest capable model wins here.
        "primary_model": "google/gemini-2.5-flash-lite",
        "fallbacks": ["openai/gpt-4o-mini", "google/gemini-2.5-flash"],
        "params": {"temperature": 0.2, "max_tokens": 500},
        "cacheable": True,
        "cache_ttl": 60 * 60 * 24 * 30,
    },
    TaskType.VOCAB_EXAMPLE: {
        "primary_model": "openai/gpt-4o-mini",
        "fallbacks": ["google/gemini-2.5-flash-lite"],
        "params": {"temperature": 0.5, "max_tokens": 600},
        "cacheable": True,
        "cache_ttl": 60 * 60 * 24 * 30,
    },
    TaskType.QUIZ_GENERATE: {
        "primary_model": "openai/gpt-4o-mini",
        "fallbacks": ["google/gemini-2.5-flash", "anthropic/claude-sonnet-5"],
        "params": {"temperature": 0.4, "max_tokens": 2000},
    },
    TaskType.WRITING_EVALUATE: {
        "primary_model": "anthropic/claude-sonnet-5",
        "fallbacks": ["openai/gpt-4o"],
        "params": {"temperature": 0.2, "max_tokens": 2500},
    },
    TaskType.CONTENT_GENERATE: {
        "primary_model": "google/gemini-2.5-flash",
        "fallbacks": ["anthropic/claude-sonnet-5"],
        "params": {"temperature": 0.7, "max_tokens": 4000},
    },
    # Scoring a spoken turn is a structured judgement, not a chat — low temperature.
    TaskType.PRONUNCIATION_SCORE: {
        "primary_model": "anthropic/claude-sonnet-5",
        "fallbacks": ["openai/gpt-4o"],
        "params": {"temperature": 0.2, "max_tokens": 1200},
    },
    # ── Non-chat modalities ───────────────────────────────────────────────────
    # These do NOT go through `router.complete()` (which speaks chat-completions).
    # They are resolved by the same `load_policy()` and then dispatched by
    # `app.ai.audio` / `app.ai.embeddings` to OpenRouter's dedicated endpoints,
    # so a model swap and cost tracking still work identically.
    TaskType.EMBEDDING: {
        "primary_model": "openai/text-embedding-3-small",
        "fallbacks": ["qwen/qwen3-embedding-0.6b"],
        "params": {"dimensions": 1536},
    },
    # Audio model ids are NOT listed by GET /models (that endpoint returns chat
    # models only) — they come from OpenRouter's speech-to-text / text-to-speech
    # collections. Verified live 2026-07-30.
    # Multimodal chat FIRST, not a dedicated transcription model: the /audio/*
    # endpoints are guardrail-blocked on many org accounts, while an ordinary chat
    # call with an input_audio part works anywhere chat works. Verified 2026-07-30.
    TaskType.SPEECH_TO_TEXT: {
        "primary_model": "google/gemini-2.5-flash",
        "fallbacks": ["openai/gpt-4o-mini-transcribe", "openai/whisper-large-v3-turbo"],
        "params": {"language": "de"},
    },
    TaskType.TEXT_TO_SPEECH: {
        "primary_model": "deepgram/aura-2",
        "fallbacks": ["hexgrad/kokoro-82m", "microsoft/mai-voice-2-flash"],
        "params": {"voice": "alloy", "response_format": "mp3"},
    },
}

# Tasks that are NOT chat completions — `router.complete()` refuses these so a
# caller can't accidentally send audio bytes to a chat endpoint.
NON_CHAT_TASKS = frozenset(
    {TaskType.EMBEDDING, TaskType.SPEECH_TO_TEXT, TaskType.TEXT_TO_SPEECH}
)


class RoutePolicy:
    """Resolved policy for one task: which models to try, in order, with what params."""

    __slots__ = ("task_type", "primary_model", "fallbacks", "params", "cacheable", "cache_ttl")

    def __init__(
        self,
        task_type: str,
        primary_model: str,
        fallbacks: list[str] | None = None,
        params: dict[str, Any] | None = None,
        cacheable: bool = False,
        cache_ttl: int = 3600,
    ) -> None:
        self.task_type = task_type
        self.primary_model = primary_model
        self.fallbacks = fallbacks or []
        self.params = params or {}
        self.cacheable = cacheable
        self.cache_ttl = cache_ttl

    @property
    def chain(self) -> list[str]:
        """Models to attempt in order. Deduplicated, primary first."""
        seen, out = set(), []
        for m in [self.primary_model, *self.fallbacks]:
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        return out

    @classmethod
    def default_for(cls, task_type: str) -> RoutePolicy:
        cfg = DEFAULT_ROUTES.get(task_type)
        if not cfg:
            # Unknown task → safe general-purpose default rather than a hard failure.
            cfg = DEFAULT_ROUTES[TaskType.CONVERSATION]
        return cls(
            task_type=task_type,
            primary_model=cfg["primary_model"],
            fallbacks=list(cfg.get("fallbacks", [])),
            params=dict(cfg.get("params", {})),
            cacheable=bool(cfg.get("cacheable", False)),
            cache_ttl=int(cfg.get("cache_ttl", 3600)),
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RoutePolicy {self.task_type} → {self.chain}>"
