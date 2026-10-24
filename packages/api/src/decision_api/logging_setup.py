"""Journaux JSON avec filtre de masquage (jetons, clés d'API, en-têtes Authorization, mots de passe)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # En-tête Authorization (quel que soit le schéma) et jetons Bearer isolés
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)([^'\",\s]+(\s+[^'\",\s]+)?)"), r"\1[MASQUÉ]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [MASQUÉ]"),
    # JWT (trois segments base64url, en-tête commençant par eyJ)
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[JWT MASQUÉ]"),
    # Clés Anthropic et assimilées
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[CLÉ MASQUÉE]"),
    # Mots de passe dans un DSN : scheme://user:motdepasse@hôte
    (re.compile(r"([a-z][a-z0-9+.-]*://[^:/@\s]+:)([^@\s]+)(@)"), r"\1[MASQUÉ]\3"),
    # Paires clé=valeur sensibles
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|password|passwd|secret|token|x-api-key)['\"]?\s*[:=]\s*['\"]?)([^'\",\s}]+)"
        ),
        r"\1[MASQUÉ]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Masque les secrets dans le message formaté (arguments compris) avant toute sortie."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - un journal ne doit jamais faire échouer la requête
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    _EXTRA = ("trace_id", "request_id", "path", "status", "duration_ms", "event")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self._EXTRA:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_decision_api", False):
            root.removeHandler(existing)
    handler._decision_api = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
