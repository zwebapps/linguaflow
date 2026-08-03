"""V1 router registry.

Owned by the orchestrator — neither build track edits this file. Each track creates
its own module exposing a module-level ``router = APIRouter()``; this file mounts them.
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analysis,
    auth,
    chat,
    flashcards,
    library,
    materials,
    quiz,
    speaking,
    tools,
    topics,
    vocab,
    writing,
)

api_router = APIRouter(prefix="/api/v1")

# Auth + profile
api_router.include_router(auth.router, tags=["auth"])
# AI
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(speaking.router, prefix="/speaking", tags=["speaking"])
# Learning content
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(materials.router, prefix="/materials", tags=["materials"])
api_router.include_router(vocab.router, prefix="/vocab", tags=["vocabulary"])
api_router.include_router(flashcards.router, prefix="/flashcards", tags=["flashcards"])
# Assessment
api_router.include_router(quiz.router, prefix="/quiz", tags=["quiz"])
api_router.include_router(writing.router, prefix="/writing", tags=["writing"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
# Admin
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])

__all__ = ["api_router"]
