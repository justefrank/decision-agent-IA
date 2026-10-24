"""Client LLM mince, au format natif Anthropic (revue LLM v5 §3.3, §4).

- Les blocs de contenu (thinking, text, tool_use) sont conservés bruts et rejoués tels quels.
- L'usage est détaillé (entrée, lecture de cache, écriture 5 min / 1 h, sortie) et chiffré par une table
  de prix versionnée.
- `AnthropicClient` : SDK `anthropic` avec `max_retries=0` ; les relances sont décidées ici, dans la
  limite de l'échéance. Aucun paramètre d'échantillonnage n'est envoyé (400 avec l'API 2026-10-21).
- `ScriptedClient` : réponses scriptées pour les tests, sans clé ni réseau.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# end_turn | tool_use | max_tokens | refusal | pause_turn | stop_sequence | model_context_window_exceeded…
StopReason = str
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

# Table de prix versionnée ($ par million de jetons).
# Source : platform.claude.com/docs/en/about-claude/pricing
# (vérifiée le 2026-10-24) ; lecture de cache = 0,05 × entrée pour Opus et Sonnet 5.5.
# Écriture de cache : 1,25 × entrée (5 min), 2 × entrée (1 h).
PRICING_VERSION = "2026-10-24"
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Modèle servi absent de la table (repli côté serveur, nouvel identifiant) : compté au tarif le plus cher
# connu, par prudence, pour que le plafond de coût par question reste effectif.
PRICING_MAX_MODEL = max(PRICING, key=lambda m: (PRICING[m]["output"], PRICING[m]["input"]))

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0  # non mis en cache
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    output_tokens: int = 0  # réflexion comprise

    @property
    def cache_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens


def cost_usd(usage: LLMUsage, model: str) -> float | None:
    p = PRICING.get(model)
    if p is None:
        return None
    total = (
        usage.input_tokens * p["input"]
        + usage.cache_read_tokens * p["cache_read"]
        + usage.cache_write_5m_tokens * p["input"] * 1.25
        + usage.cache_write_1h_tokens * p["input"] * 2.0
        + usage.output_tokens * p["output"]
    )
    return round(total / 1_000_000, 6)


def cost_usd_prudent(usage: LLMUsage, model: str) -> tuple[float, bool]:
    """(coût, estimé) : un modèle inconnu de `PRICING` est compté au tarif le plus cher connu."""
    c = cost_usd(usage, model)
    if c is not None:
        return c, False
    logger.warning(
        "modèle servi %r absent de PRICING (%s) : coût estimé au tarif de %s",
        model,
        PRICING_VERSION,
        PRICING_MAX_MODEL,
    )
    return cost_usd(usage, PRICING_MAX_MODEL) or 0.0, True


@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    effort: str
    max_tokens: int
    deadline_s: float  # temps restant du budget de la question
    output_format: dict[str, Any] | None = None  # mode analyse : output_config.format


@dataclass(frozen=True)
class LLMStep:
    content: list[dict[str, Any]]  # blocs bruts, à rejouer tels quels
    stop_reason: StopReason
    usage: LLMUsage = field(default_factory=LLMUsage)
    model_served: str = ""
    request_id: str | None = None
    refusal_category: str | None = None
    ttft_ms: int | None = None
    latency_ms: int = 0

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return [
            {"id": b["id"], "name": b["name"], "input": b.get("input") or {}}
            for b in self.content
            if b.get("type") == "tool_use"
        ]

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")


class LLMError(Exception):
    """Échec définitif d'un appel LLM après la politique de relance."""

    def __init__(self, kind: str, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = (
            kind  # rate_limited | spend_limit | overloaded | bad_request | auth | timeout | connection
        )
        self.request_id = request_id


class LLMClient(Protocol):
    async def step(self, req: LLMRequest, on_event: EventCallback | None = None) -> LLMStep: ...


# --- Implémentation Anthropic -------------------------------------------------------------------


def _block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", by_alias=True, exclude_none=True)


def _usage_from(u: Any) -> LLMUsage:
    if u is None:
        return LLMUsage()
    cc = getattr(u, "cache_creation", None)
    w5 = getattr(cc, "ephemeral_5m_input_tokens", None) if cc else None
    w1 = getattr(cc, "ephemeral_1h_input_tokens", None) if cc else None
    total_write = getattr(u, "cache_creation_input_tokens", None) or 0
    if w5 is None and w1 is None:
        w5, w1 = total_write, 0
    return LLMUsage(
        input_tokens=u.input_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
        cache_write_5m_tokens=w5 or 0,
        cache_write_1h_tokens=w1 or 0,
        output_tokens=u.output_tokens or 0,
    )


def _is_spend_limit(err: Any) -> bool:
    body = getattr(err, "body", None)
    blob = json.dumps(body, default=str) if body is not None else str(err)
    return "enforced_spend_limit_reached" in blob or "specified API usage limits" in blob


class AnthropicClient:
    """Appel en flux (`messages.stream`) pour mesurer le TTFT ; relances gouvernées par l'échéance."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        fallbacks: bool = False,
        per_call_timeout_s: float = 20.0,
        client: Any = None,
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=0, timeout=per_call_timeout_s
        )
        self.fallbacks = fallbacks
        self.per_call_timeout_s = per_call_timeout_s

    @classmethod
    def from_settings(cls, settings: Any) -> AnthropicClient:
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return cls(api_key=key, fallbacks=bool(settings.llm_fallbacks))

    def _kwargs(self, req: LLMRequest, timeout: float) -> dict[str, Any]:
        output_config: dict[str, Any] = {"effort": req.effort}
        if req.output_format is not None:
            output_config["format"] = req.output_format
        kw: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": req.messages,
            "output_config": output_config,
            "thinking": {"type": "adaptive"},
            "cache_control": {"type": "ephemeral"},  # cache automatique (5 min) de la boucle en ajout seul
            "timeout": timeout,
        }
        if req.tools:
            kw["tools"] = req.tools
            kw["tool_choice"] = {"type": "auto"}
        return kw

    async def _once(self, req: LLMRequest, timeout: float, on_event: EventCallback | None) -> LLMStep:
        t0 = time.monotonic()
        ttft: float | None = None
        kw = self._kwargs(req, timeout)
        if self.fallbacks:
            manager = self.client.beta.messages.stream(**kw, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            manager = self.client.messages.stream(**kw)
        stream: Any
        async with manager as stream:
            async for ev in stream:
                if ev.type == "content_block_start":
                    block = ev.content_block
                    # TTFT au premier bloc visible (texte ou appel d'outil), pas au bloc de réflexion
                    if ttft is None and getattr(block, "type", None) in ("text", "tool_use"):
                        ttft = time.monotonic() - t0
                    if on_event is not None and getattr(block, "type", None) == "tool_use":
                        await on_event("tool_use_start", {"name": block.name})
            msg = await stream.get_final_message()
        stop_details = getattr(msg, "stop_details", None)
        return LLMStep(
            content=[_block_to_dict(b) for b in msg.content],
            stop_reason=msg.stop_reason or "end_turn",
            usage=_usage_from(msg.usage),
            model_served=msg.model,
            request_id=getattr(msg, "_request_id", None) or getattr(stream, "request_id", None),
            refusal_category=getattr(stop_details, "category", None) if stop_details else None,
            ttft_ms=int(ttft * 1000) if ttft is not None else None,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def step(self, req: LLMRequest, on_event: EventCallback | None = None) -> LLMStep:
        a = self._anthropic
        start = time.monotonic()
        retried = False

        def remaining() -> float:
            return req.deadline_s - (time.monotonic() - start)

        while True:
            timeout = max(1.0, min(self.per_call_timeout_s, remaining()))
            budget = remaining()
            if budget <= 0:
                raise LLMError("timeout", "Échéance de la question atteinte.")
            try:
                # Le délai httpx porte sur chaque lecture : un flux lent mais continu le contournerait.
                # L'échéance globale est donc imposée sur l'appel entier.
                async with asyncio.timeout(budget):
                    return await self._once(req, timeout, on_event)
            except TimeoutError as e:
                raise LLMError("timeout", "Échéance de la question atteinte pendant l'appel.") from e
            except a.APIStatusError as e:
                etype = _error_type(e)
                if isinstance(e, a.RateLimitError) or etype == "rate_limit_error":
                    if _is_spend_limit(e):
                        raise LLMError(
                            "spend_limit", "Plafond de dépenses atteint.", request_id=e.request_id
                        ) from e
                    retry_after = _retry_after(e)
                    if not retried and retry_after is not None and retry_after < remaining() - 5:
                        retried = True
                        await asyncio.sleep(retry_after)
                        continue
                    raise LLMError("rate_limited", "Service saturé.", request_id=e.request_id) from e
                if isinstance(e, a.BadRequestError):
                    kind = "spend_limit" if _is_spend_limit(e) else "bad_request"
                    raise LLMError(kind, str(e), request_id=e.request_id) from e
                if isinstance(e, a.AuthenticationError | a.PermissionDeniedError):
                    raise LLMError("auth", "Clé API refusée.", request_id=e.request_id) from e
                # Erreur reçue dans le flux SSE après un HTTP 200 : le type est dans le corps.
                overloaded = e.status_code >= 500 or etype in ("overloaded_error", "api_error")
                if overloaded and not retried:
                    jitter = random.uniform(0.5, 1.5)  # noqa: S311 - gigue, pas de cryptographie
                    if remaining() > jitter + 3:
                        retried = True
                        await asyncio.sleep(jitter)
                        continue
                kind = "overloaded" if overloaded else "bad_request"
                raise LLMError(kind, str(e), request_id=e.request_id) from e
            except a.APIConnectionError as e:  # inclut APITimeoutError et les erreurs en cours de flux
                jitter = random.uniform(0.5, 1.5)  # noqa: S311
                if not retried and remaining() > jitter + 3:
                    retried = True
                    await asyncio.sleep(jitter)
                    continue
                kind = "timeout" if isinstance(e, a.APITimeoutError) else "connection"
                raise LLMError(kind, str(e)) from e


def _error_type(e: Any) -> str | None:
    """Type d'erreur Anthropic du corps (`{"type": "error", "error": {"type": ...}}`)."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("type"), str):
            return err["type"]
    return None


def _retry_after(e: Any) -> float | None:
    try:
        v = e.response.headers.get("retry-after")
        return float(v) if v is not None else None
    except (AttributeError, ValueError):
        return None


# --- Client scripté (tests) ---------------------------------------------------------------------

Script = LLMStep | Callable[[LLMRequest], LLMStep] | Exception


class ScriptedClient:
    """Rejoue une liste de réponses (ou de fonctions de la requête) ; mémorise les requêtes reçues."""

    def __init__(self, steps: Sequence[Script], *, model: str = "claude-sonnet-5-5") -> None:
        self._steps = list(steps)
        self.requests: list[LLMRequest] = []
        self.model = model

    async def step(self, req: LLMRequest, on_event: EventCallback | None = None) -> LLMStep:
        self.requests.append(req)
        if not self._steps:
            raise AssertionError("ScriptedClient : plus de réponse scriptée")
        s = self._steps.pop(0)
        if isinstance(s, Exception):
            raise s
        step = s(req) if callable(s) else s
        if on_event is not None:
            for c in step.tool_calls:
                await on_event("tool_use_start", {"name": c["name"]})
        return step


ReplayClient = ScriptedClient

_counter = 0


def _tool_id() -> str:
    global _counter
    _counter += 1
    return f"toolu_test_{_counter:04d}"


def tool_step(
    *calls: tuple[str, dict[str, Any]],
    text: str | None = None,
    usage: LLMUsage | None = None,
    model: str = "claude-sonnet-5-5",
) -> LLMStep:
    """Fabrique une réponse scriptée avec un ou plusieurs appels d'outils (et un bloc thinking)."""
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "", "signature": "sig-test"}]
    if text:
        content.append({"type": "text", "text": text})
    for name, inp in calls:
        content.append({"type": "tool_use", "id": _tool_id(), "name": name, "input": inp})
    return LLMStep(
        content=content,
        stop_reason="tool_use",
        usage=usage or LLMUsage(input_tokens=500, cache_read_tokens=6000, output_tokens=200),
        model_served=model,
        request_id="req_test",
        ttft_ms=100,
        latency_ms=900,
    )


def text_step(
    text: str,
    *,
    stop_reason: StopReason = "end_turn",
    refusal_category: str | None = None,
    usage: LLMUsage | None = None,
    model: str = "claude-sonnet-5-5",
) -> LLMStep:
    return LLMStep(
        content=[{"type": "text", "text": text}],
        stop_reason=stop_reason,
        usage=usage or LLMUsage(input_tokens=500, output_tokens=100),
        model_served=model,
        request_id="req_test",
        refusal_category=refusal_category,
        ttft_ms=100,
        latency_ms=500,
    )
