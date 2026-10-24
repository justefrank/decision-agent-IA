"""Dépendances FastAPI communes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_api.auth import User, current_user, require_roles
from decision_api.config import ApiSettings
from decision_api.db import get_session
from decision_api.errors import ApiError
from decision_api.runtime import Runtime
from decision_api.services import StreamLimiter


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise ApiError(503, "service_unavailable", "Service en cours de démarrage.")
    return runtime


def get_settings_dep(request: Request) -> ApiSettings:
    return request.app.state.settings


def get_maker(request: Request) -> async_sessionmaker[AsyncSession]:
    maker = request.app.state.sessionmaker
    if maker is None:
        raise ApiError(503, "service_unavailable", "Base de données non configurée.")
    return maker


def get_limiter(request: Request) -> StreamLimiter:
    return request.app.state.stream_limiter


SessionDep = Annotated[AsyncSession, Depends(get_session)]
MakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_maker)]
RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
SettingsDep = Annotated[ApiSettings, Depends(get_settings_dep)]
UserDep = Annotated[User, Depends(current_user)]
LimiterDep = Annotated[StreamLimiter, Depends(get_limiter)]
AnalystDep = Annotated[User, Depends(require_roles("analyste", "admin"))]
AdminDep = Annotated[User, Depends(require_roles("admin"))]
