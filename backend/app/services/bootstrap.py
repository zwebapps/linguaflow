"""First-run bootstrap: create tables, seed AI routes, ensure a bootstrap admin.

Idempotent — safe to run on every startup.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.router import heal_stale_routes, seed_routes
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import User

log = structlog.get_logger(__name__)


async def create_schema() -> None:
    """Bring the database schema up to date by running Alembic migrations.

    This used to call `Base.metadata.create_all`, which is subtly dangerous:
    create_all creates **missing tables** but never alters existing ones. Adding
    two columns to `User` therefore did nothing at all — the app started happily
    and then 500'd on `column users.native_language does not exist`. A schema
    change that silently no-ops is worse than one that fails loudly.

    `alembic upgrade head` applies real ALTERs and records what ran, so the same
    mistake now either applies or errors. Alembic is run in a worker thread
    because its `command` API is synchronous and drives its own event loop, which
    cannot be nested inside the running one.
    """
    import asyncio

    await asyncio.to_thread(_upgrade_to_head)


def _upgrade_to_head() -> None:
    """Synchronous `alembic upgrade head`, config resolved from the repo root."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")
    log.info("schema_migrated", revision="head")


async def ensure_admin(db: AsyncSession) -> None:
    email = settings.ADMIN_EMAIL.strip().lower()
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        User(
            email=email,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            display_name="Administrator",
            role="admin",
            cefr_level="C1",
        )
    )
    await db.commit()
    log.info("bootstrap_admin_created", email=email)


async def ensure_demo_learner(db: AsyncSession) -> None:
    """Local dev account — matches frontend login defaults."""
    if not settings.is_local:
        return
    email = settings.DEMO_LEARNER_EMAIL.strip().lower()
    demo_password = settings.DEMO_LEARNER_PASSWORD
    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        changed = False
        if not verify_password(demo_password, existing.password_hash):
            existing.password_hash = hash_password(demo_password)
            changed = True
        if existing.role != "student":
            existing.role = "student"
            changed = True
        if existing.onboarded_at is None:
            existing.onboarded_at = datetime.now(UTC)
            changed = True
        if changed:
            await db.commit()
            log.info("bootstrap_demo_learner_synced", email=email)
        return
    db.add(
        User(
            email=email,
            password_hash=hash_password(demo_password),
            display_name="Demo Learner",
            role="student",
            cefr_level="A2",
            goal="travel",
            learning_style="balanced",
            daily_goal_minutes=20,
            onboarded_at=datetime.now(UTC),
        )
    )
    await db.commit()
    log.info("bootstrap_demo_learner_created", email=email)


async def bootstrap(db: AsyncSession) -> None:
    await create_schema()
    added = await seed_routes(db)
    if added:
        log.info("ai_routes_seeded", count=added)
    # Best-effort: a dead primary model shouldn't cost a 404 on every request.
    if healed := await heal_stale_routes(db):
        log.info("ai_routes_healed", tasks=healed)
    await ensure_admin(db)
    await ensure_demo_learner(db)
