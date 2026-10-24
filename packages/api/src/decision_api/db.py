"""Accès Postgres (SQLAlchemy async + asyncpg) avec le rôle app_rw."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def to_async_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


def make_engine(url: str, **kwargs: object) -> AsyncEngine:
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(
        to_async_url(url),
        connect_args={"server_settings": {"application_name": "decision-api"}},
        **kwargs,  # type: ignore[arg-type]
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] | None = request.app.state.sessionmaker
    if maker is None:
        from decision_api.errors import ApiError

        raise ApiError(503, "service_unavailable", "Base de données non configurée.")
    async with maker() as session:
        yield session
