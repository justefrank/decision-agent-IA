"""Environnement Alembic : connexion app_owner (OWNER_DATABASE_URL), table de version dans le schéma app."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from decision_api.db import to_async_url
from decision_api.models import metadata
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config


def _owner_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("OWNER_DATABASE_URL")
    if not url:
        from decision_core.settings import Settings

        secret = Settings().owner_database_url
        url = secret.get_secret_value() if secret else None
    if not url:
        raise RuntimeError("OWNER_DATABASE_URL (rôle app_owner) non défini.")
    return to_async_url(url)


def _configure(connection: Connection | None = None, **kw: object) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema="app",
        include_schemas=True,
        **kw,  # type: ignore[arg-type]
    )


def run_offline() -> None:
    _configure(url=_owner_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_owner_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
