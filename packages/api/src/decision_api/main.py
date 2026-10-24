"""Application FastAPI : `create_app()` et `app` (uvicorn decision_api.main:app)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from decision_core.semantic import SemanticLayer, load_semantic
from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from decision_api.auth import JWKSCache, TokenValidator
from decision_api.config import ApiSettings, get_api_settings, scrub_agent_ro_env
from decision_api.db import make_engine, make_sessionmaker
from decision_api.errors import install_error_handlers
from decision_api.logging_setup import configure_logging
from decision_api.routes import admin, conversations, core, dashboard, feedback
from decision_api.runtime import Runtime, default_runtime
from decision_api.services import StreamLimiter, TTLCache

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


class BodyLimitMiddleware:
    """Borne la taille des corps de requête /api/* AVANT que l'application ne les lise (413 uniforme).

    `Content-Length` trop grand : refus immédiat, sans rien lire. Sinon (ou en transfert par
    morceaux) le corps est lu en mémoire jusqu'à la limite au plus, puis rejoué à l'application ;
    au-delà, refus sans lire la suite. L'authentification se faisant après la lecture du corps
    (FastAPI lit le corps avant de résoudre les dépendances), un client anonyme ne peut ainsi pas
    faire lire plus de `max_bytes` octets.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int, prefix: str = "/api") -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.prefix = prefix

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        err: dict[str, Any] = {"code": "payload_too_large", "message": "Requête trop volumineuse."}
        if request_id:
            err["request_id"] = request_id
        body = json.dumps({"error": err}, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.max_bytes + 1
                if declared > self.max_bytes:
                    await self._reject(scope, send)
                    return
        if scope.get("method") in ("GET", "HEAD", "OPTIONS", "DELETE"):
            has_body = any(n in (b"content-length", b"transfer-encoding") for n, _ in scope["headers"])
            if not has_body:
                await self.app(scope, receive, send)
                return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._reject(scope, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()  # ensuite : détection de la déconnexion (flux SSE)

        await self.app(scope, replay, send)


def _install_openapi_security(app: FastAPI) -> None:
    """Déclare le schéma Bearer (JWT Keycloak) dans OpenAPI ; /api/health reste public."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        for path, ops in schema.get("paths", {}).items():
            if path == "/api/health":
                continue
            for op in ops.values():
                if isinstance(op, dict):
                    op["security"] = [{"bearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def create_app(
    settings: ApiSettings | None = None,
    *,
    semantic: SemanticLayer | None = None,
    runtime_factory: RuntimeFactory | None = None,
    token_validator: TokenValidator | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or get_api_settings()
    settings.check_production()  # clé de pseudonymisation par défaut refusée en production
    scrub_agent_ro_env()  # le DSN agent_ro ne reste que dans settings (transmis au seul MCP)
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
    app.state.tiles_cache = TTLCache(settings.dashboard_cache_ttl_s)
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
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)  # le plus externe
    if docs:
        _install_openapi_security(app)
    return app


def __getattr__(name: str) -> Any:
    # `app` créé à la demande : importer le module (tests, outils) ne lit pas l'environnement.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
