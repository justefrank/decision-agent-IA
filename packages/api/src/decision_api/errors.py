"""Contrat d'erreurs uniforme : `{"error": {"code", "message", "request_id"}}`.

Aucune exception Postgres ni trace Python n'est renvoyée au client : elles sont journalisées
(masquées) et remplacées par un message neutre.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("decision_api.errors")

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}

_DEFAULT_MESSAGES = {
    401: "Authentification requise.",
    403: "Accès refusé.",
    404: "Ressource introuvable.",
    405: "Méthode non autorisée.",
    413: "Requête trop volumineuse.",
    429: "Trop de requêtes.",
    500: "Erreur interne.",
    503: "Service momentanément indisponible.",
}


def _phrase(status: int) -> str | None:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return None


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str | None = None,
        message: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.message = message or _DEFAULT_MESSAGES.get(status, "Requête refusée.")
        self.headers = headers
        super().__init__(self.message)


def error_body(code: str, message: str, request: Request | None = None, **extra: Any) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    rid = getattr(request.state, "request_id", None) if request is not None else None
    if rid:
        err["request_id"] = rid
    err.update(extra)
    return {"error": err}


def _resp(
    request: Request,
    status: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    return JSONResponse(error_body(code, message, request, **extra), status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _resp(request, exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status = exc.status_code
        message = exc.detail if isinstance(exc.detail, str) and status < 500 else None
        if message is not None and message == _phrase(status):
            message = None  # « Not Found », « Method Not Allowed »… : message français par défaut
        return _resp(
            request,
            status,
            _DEFAULT_CODES.get(status, "error"),
            message or _DEFAULT_MESSAGES.get(status, "Requête refusée."),
            getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # On ne renvoie ni la valeur reçue (`input`) ni le contexte : seulement l'emplacement et le type.
        fields = [
            {"loc": [str(p) for p in e.get("loc", ())], "type": e.get("type"), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return _resp(request, 422, "invalid_request", "Requête invalide.", fields=fields)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error(
            "erreur base de données : %s",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        if isinstance(exc, DBAPIError) and exc.connection_invalidated:
            return _resp(request, 503, "service_unavailable", _DEFAULT_MESSAGES[503])
        return _resp(request, 500, "internal_error", _DEFAULT_MESSAGES[500])

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("erreur inattendue", extra={"request_id": getattr(request.state, "request_id", None)})
        return _resp(request, 500, "internal_error", _DEFAULT_MESSAGES[500])
