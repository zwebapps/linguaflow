"""Alembic environment.

Two things this does that the generated template does not:

* **Reads the URL from `app.core.config`**, not `alembic.ini`. The connection
  string is a bootstrap secret injected via the environment in every deployed
  environment; duplicating it in a checked-in ini file would be a second source
  of truth and a place to leak a password.
* **Creates the `vector` extension before running migrations.** `chunks.embedding`
  is a pgvector column, so a migration against a fresh database fails at
  `CREATE TABLE` unless the extension already exists.

`target_metadata` points at the real models, which is what lets `alembic check`
detect model/schema drift — the exact failure that motivated wiring this up: two
columns were added to a model, `create_all()` silently skipped them because the
table already existed, and the app 500'd on
`column users.native_language does not exist`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models registers every table on Base.metadata.
from app.core.config import settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Env wins over the ini file. `%` is escaped because ConfigParser interpolates it,
# and percent-encoded characters in a password are a real thing.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep alembic's own bookkeeping table out of autogenerate."""
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB — useful for reviewing a migration."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # pgvector must exist before any table carrying a Vector column is created.
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Both default to False, and both matter: without them a changed column
        # type or server default is silently ignored by autogenerate — the same
        # class of silent no-op that caused the original bug.
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()

    # Explicit commit is REQUIRED here, and its absence is silent.
    #
    # The `CREATE EXTENSION` above opens a transaction on the connection before
    # Alembic configures itself. Alembic then sees an already-begun transaction,
    # treats it as externally managed, and does not commit — so `upgrade head`
    # logged "Running upgrade -> …" and applied nothing, leaving an empty database
    # with no `alembic_version` row. Exactly the class of silent no-op this whole
    # migration setup exists to eliminate.
    connection.commit()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
