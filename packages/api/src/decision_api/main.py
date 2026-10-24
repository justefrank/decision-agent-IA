"""Application FastAPI : `create_app()` et `app` (uvicorn decision_api.main:app)."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from decision_core.semantic import SemanticLayer, load_semantic
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from decision_api.auth import JWKSCache, TokenValidator
from decision_api.config import ApiSettings, get_api_settings
from decision_api.db import make_engine, make_sessionmaker
from decision_api.errors import install_error_handlers
from decision_api.logging_setup import configure_logging
from decision_api.routes import admin, conversations, core, dashboard, feedback
from decision_api.runtime import Runtime, default_runtime
from decision_api.services import StreamLimiter

log = logging.getLogger("decision_api")

RuntimeFactory = Callable[[ApiSettings, SemanticLayer], AbstractAsyncContextManager[Runtime]]

_CSP_JSON = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
_DOCS_PATHS = ("/api/docs", "/api/openapi.json")


class SecurityHeadersMiddleware:
    """En-têtes de sécurité et identifiant de requête (ASGI pur : compatible avec le flux SSE)."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        path: str = scope.get("path", "")
        started = time.monotonic()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}

                def add(name: str, value: str) -> None:
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))

                add("x-content-type-options", "nosniff")
                add("referrer-policy", "no-referrer")
                add("x-frame-options", "DENY")
                add("x-request-id", request_id)
                if not path.startswith(_DOCS_PATHS):
                    add("content-security-policy", _CSP_JSON)
                    add("cache-control", "no-store")
                if self.hsts:
                    add("strict-transport-security", "max-age=31536000; includeSubDomains")
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "%s %s",
                scope.get("method"),
                path,
                extra={
                    "request_id": request_id,
                    "path": path,
                    "status": status_holder.get("status"),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )


def create_app(
    settings: ApiSettings | None = None,
    *,
    semantic: SemanticLayer | None = None,
    runtime_factory: RuntimeFactory | None = None,
    token_validator: TokenValidator | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or get_api_settings()
    if configure_logs:
        configure_logging()
    factory: RuntimeFactory = runtime_factory or default_runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sem = semantic or load_semantic(settings.semantic_dir)
        engine = None
        if settings.app_database_url is not None:
            engine = make_engine(settings.app_database_url.get_secret_value())
            app.state.sessionmaker = make_sessionmaker(engine)
        try:
            async with factory(settings, sem) as runtime:
                app.state.runtime = runtime
                log.info("API démarrée", extra={"event": "startup"})
                yield
        finally:
            app.state.runtime = None
            if engine is not None:
                await engine.dispose()

    docs = not settings.is_production
    app = FastAPI(
        title="Decision API",
        version="0.5.0",
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.sessionmaker = None
    app.state.runtime = None
    app.state.stream_limiter = StreamLimiter()
    app.state.token_validator = token_validator or TokenValidator(settings, JWKSCache(settings.jwks_url))

    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (core, conversations, dashboard, feedback, admin):
        api.include_router(module.router)
    app.include_router(api)

    origins = settings.cors_origin_list
    if origins:  # même origine derrière le proxy par défaut : pas de CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["X-Request-Id", "X-Trace-Id"],
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    return app


def __getattr__(name: str) -> Any:
    # `app` créé à la demande : importer le module (tests, outils) ne lit pas l'environnement.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
