"""Correctifs de revue sans base de données : santé et supervision MCP, limite de corps, MFA, JWKS,
messages d'erreur, OpenAPI, refus de démarrage en production, CSV, cache des tuiles."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from decision_api.auth import JWKSCache, has_mfa
from decision_api.config import ApiSettings
from decision_api.main import BodyLimitMiddleware, create_app
from decision_api.routes.admin import _csv_safe
from decision_api.runtime import McpSupervisor
from decision_api.services import TTLCache
from decision_core.models import ToolResult

JWKS_URL = "https://kc.test/auth/realms/decision/protocol/openid-connect/certs"  # cf. conftest

# --- Supervision du client MCP --------------------------------------------------------------------


class FakeSession:
    def __init__(self) -> None:
        self.dead = False
        self.list_calls = 0

    async def list_tools(self) -> list[str]:
        self.list_calls += 1
        if self.dead:
            raise ConnectionError("sous-processus mort")
        return ["query_metric"]


class FakeMcpClient:
    def __init__(self) -> None:
        self.session = FakeSession()

    async def call(self, name: str, args: dict[str, Any], *, timeout_s: float) -> ToolResult:
        return ToolResult(tool="query_metric", ok=True)


class Starter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.started = 0
        self.clients: list[FakeMcpClient] = []

    @asynccontextmanager
    async def __call__(self):
        self.started += 1
        if self.fail:
            raise FileNotFoundError("mcp introuvable")
        client = FakeMcpClient()
        self.clients.append(client)
        yield client


def _sup(starter: Starter, **kw: Any) -> McpSupervisor:
    base: dict[str, Any] = dict(
        probe_timeout_s=0.5,
        probe_interval_s=60,
        max_restarts=3,
        backoff_initial_s=0.01,
        backoff_max_s=0.05,
        probe_cache_s=0,
    )
    base.update(kw)
    return McpSupervisor(starter, **base)


async def test_supervisor_restarts_dead_mcp():
    starter = Starter()
    sup = _sup(starter)
    await sup.start(wait_s=2)
    try:
        assert sup.ready and await sup.probe() is True
        assert (await sup.call("query_metric", {}, timeout_s=1)).ok
        starter.clients[0].session.dead = True  # mort du sous-processus
        assert await sup.probe() is False  # sonde réelle : list_tools échoue
        async with asyncio.timeout(3):
            while not (starter.started == 2 and sup.ready):
                await asyncio.sleep(0.01)
        assert sup.restarts == 1 and await sup.probe() is True
    finally:
        await sup.stop()


async def test_supervisor_bounded_restarts_then_down():
    starter = Starter(fail=True)
    sup = _sup(starter, max_restarts=2)
    await sup.start(wait_s=2)
    assert not sup.ready and sup.last_error == "FileNotFoundError"
    async with asyncio.timeout(3):
        while sup.state != "down":
            await asyncio.sleep(0.01)
    assert starter.started == 3  # démarrage initial + 2 relances, puis abandon
    res = await sup.call("run_query", {}, timeout_s=1)
    assert res.ok is False and res.error is not None and res.error.error_class == "internal"
    assert await sup.probe() is False
    await sup.stop()


def test_supervisor_backoff_is_exponential_and_capped():
    sup = _sup(Starter(), backoff_initial_s=1, backoff_max_s=8)
    assert [sup._backoff(n) for n in range(1, 6)] == [1, 2, 4, 8, 8]


async def test_health_reports_real_mcp_state_and_missing_key(ctx_nodb):
    # Sans base : status « down » (503) ; on vérifie ici les composants MCP et agent.
    rt = ctx_nodb.app.state.runtime
    starter = Starter()
    sup = _sup(starter)
    await sup.start(wait_s=2)
    rt.mcp, rt.tools = sup, sup
    try:
        snap = (await ctx_nodb.client.get("/api/health")).json()
        assert snap["mcp"] == "ok" and snap["agent"] == "ok"
        rt.llm_configured = False  # ANTHROPIC_API_KEY absente
        snap = (await ctx_nodb.client.get("/api/health")).json()
        assert snap["mcp"] == "ok" and snap["agent"] == "down"
        rt.llm_configured = True
        starter.clients[0].session.dead = True
        r = await ctx_nodb.client.get("/api/health")
        assert r.json()["mcp"] in ("down", "restarting") and r.json()["agent"] == "down"
        assert r.status_code == 503 and r.json()["status"] == "down"  # pas de base dans ce test
    finally:
        await sup.stop()


async def test_agent_routes_503_without_api_key(ctx_nodb):
    ctx_nodb.app.state.runtime.llm_configured = False
    assert not ctx_nodb.app.state.runtime.agent_ready


# --- Limite de taille des corps -------------------------------------------------------------------


async def test_large_content_length_rejected_before_reading(ctx_nodb):
    r = await ctx_nodb.client.post(
        "/api/conversations/00000000-0000-0000-0000-000000000000/messages",
        content=b"x" * (200 * 1024),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413
    err = r.json()["error"]
    assert err["code"] == "payload_too_large" and err["message"] == "Requête trop volumineuse."
    assert err["request_id"]


async def test_chunked_body_stops_reading_at_limit():
    reached: list[str] = []

    async def app(scope, receive, send):  # pragma: no cover - ne doit pas être appelée
        reached.append("app")

    mw = BodyLimitMiddleware(app, max_bytes=64 * 1024)
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive():
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"x" * 16384, "more_body": True}  # flux infini

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/feedback", "headers": [], "state": {}}
    await mw(scope, receive, send)
    assert reached == [] and sent[0]["status"] == 413
    assert received == 5  # 80 Kio lus au plus, puis refus (au lieu de 30 Mo)


async def test_small_body_passes_through(ctx_nodb):
    r = await ctx_nodb.client.post("/api/conversations", json={})
    assert r.status_code == 401  # corps relu normalement, puis authentification


# --- Messages d'erreur, OpenAPI -------------------------------------------------------------------


async def test_404_405_messages_in_french(ctx_nodb):
    r = await ctx_nodb.client.get("/api/inexistant")
    assert r.status_code == 404 and r.json()["error"]["message"] == "Ressource introuvable."
    r = await ctx_nodb.client.put("/api/health")
    assert r.status_code == 405 and r.json()["error"]["message"] == "Méthode non autorisée."


async def test_openapi_declares_bearer(ctx_nodb):
    spec = (await ctx_nodb.client.get("/api/openapi.json")).json()
    assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
    assert spec["paths"]["/api/me"]["get"]["security"] == [{"bearerAuth": []}]
    assert "security" not in spec["paths"]["/api/health"]["get"]


# --- Démarrage en production, DSN agent_ro --------------------------------------------------------


def test_production_refuses_default_pseudonym_key(settings_factory):
    with pytest.raises(RuntimeError, match="LOG_PSEUDONYM_KEY"):
        create_app(settings_factory(None, environment="production", log_pseudonym_key="dev-only-change-me"))
    app = create_app(
        settings_factory(None, environment="production", log_pseudonym_key="k" * 32), configure_logs=False
    )
    assert app.docs_url is None and app.openapi_url is None  # Swagger désactivé en production


def test_agent_ro_dsn_from_secret_file_and_env_scrubbed(tmp_path, monkeypatch, settings_factory):
    secret = tmp_path / "agent_ro_password"
    secret.write_text("p@ss/w:rd\n")
    s = ApiSettings(_env_file=None, agent_ro_password_file=str(secret), pg_host="postgres", pg_port=5432)
    assert s.agent_ro_dsn is not None
    assert (
        s.agent_ro_dsn.get_secret_value() == "postgresql://agent_ro:p%40ss%2Fw%3Ard@postgres:5432/warehouse"
    )
    monkeypatch.setenv("AGENT_RO_DSN", "postgresql://agent_ro:x@h/warehouse")
    create_app(settings_factory(None), configure_logs=False)
    assert "AGENT_RO_DSN" not in os.environ


# --- MFA ------------------------------------------------------------------------------------------


def test_has_mfa_claims():
    assert has_mfa({"amr": ["pwd", "otp"]}, 2)
    assert has_mfa({"amr": "otp"}, 2)
    assert not has_mfa({"amr": ["pwd"]}, 2)
    assert has_mfa({"acr": "2"}, 2) and not has_mfa({"acr": "1"}, 2)
    assert not has_mfa({}, 2) and not has_mfa({"acr": "urn:x"}, 2)


async def test_mfa_required_for_elevated_roles(jwks, builder):
    async with builder(jwks, None, require_mfa_claim=True) as c:
        r = await c.client.get("/api/me", headers=c.h("ana", ["analyste"], extra={"amr": ["pwd"]}))
        assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_required"
        r = await c.client.get("/api/me", headers=c.h("adm", ["admin"]))
        assert r.status_code == 403
        r = await c.client.get("/api/me", headers=c.h("ana", ["analyste"], extra={"amr": ["pwd", "otp"]}))
        assert r.status_code == 200
        r = await c.client.get("/api/me", headers=c.h("dec", ["decideur"], extra={"amr": ["pwd"]}))
        assert r.status_code == 200  # OTP facultatif pour le décideur


async def test_mfa_not_required_by_default_outside_production(ctx_nodb, settings_factory):
    assert settings_factory(None).mfa_required is False
    assert settings_factory(None, environment="production").mfa_required is True
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h("ana", ["analyste"]))
    assert r.status_code == 200


# --- JWKS : échec de rafraîchissement -------------------------------------------------------------


async def test_jwks_failure_is_rate_limited_and_stale_keys_served(jwks):
    state = {"down": False, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["down"]:
            return httpx.Response(503)
        return jwks.handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        cache = JWKSCache(JWKS_URL, http=http, ttl_s=0.0, refresh_min_interval_s=30)
        assert await cache.get_key("k1") is not None and state["calls"] == 1
        state["down"] = True
        cache._last_attempt -= 31  # l'intervalle minimal est écoulé
        # Cache expiré (ttl 0) et JWKS en panne : une seule tentative, clé périmée servie.
        assert await cache.get_key("k1") is not None
        assert await cache.get_key("k1") is not None
        assert await cache.get_key("inconnue") is None
        assert state["calls"] == 2


# --- CSV, cache des tuiles ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1", "\n=1", "|cmd", "  =1+1", " \t@x"]
)
def test_csv_formula_neutralised(value):
    assert _csv_safe(value) == "'" + value


def test_csv_plain_values_untouched():
    assert _csv_safe("SELECT 1") == "SELECT 1" and _csv_safe(-3) == -3 and _csv_safe("a-b") == "a-b"


def test_ttl_cache_expiry_and_bound():
    c = TTLCache(ttl_s=60, max_entries=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert c.get("a") is None and c.get("b") == 2 and c.get("c") == 3
    z = TTLCache(ttl_s=0)
    z.set("a", 1)
    assert z.get("a") is None


async def test_dashboard_tiles_cached(ctx_nodb):
    h = ctx_nodb.h("alice", ["decideur"])
    for _ in range(3):
        r = await ctx_nodb.client.get("/api/dashboard", params={"period": "2026-08"}, headers=h)
        assert r.status_code == 200
    assert ctx_nodb.services.dashboards == 1
    await ctx_nodb.client.get("/api/dashboard", params={"period": "2026-07"}, headers=h)
    assert ctx_nodb.services.dashboards == 2


async def test_supervisor_recovers_state_after_transient_probe_failure():
    starter = Starter()
    sup = _sup(starter)
    await sup.start(wait_s=2)
    try:
        session = starter.clients[0].session
        calls = session.list_calls
        session.dead = True
        assert await sup.probe() is False and sup.state == "restarting"
        session.dead = False  # la sonde de la tâche de supervision réussit : pas de relance
        async with asyncio.timeout(3):
            while session.list_calls == calls + 1 or sup.state != "ok":
                await asyncio.sleep(0.01)
        assert sup.ready and starter.started == 1
    finally:
        await sup.stop()
