"""Fixtures : clé RSA et JWKS simulé, Postgres jetable (port 55440), faux Agent et faux runtime."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from decision_api.auth import JWKSCache, TokenValidator
from decision_api.config import ApiSettings
from decision_api.main import create_app
from decision_api.runtime import Runtime
from decision_core.models import (
    AssistantMessage,
    DashboardAnalysis,
    EvidenceStep,
    HistoryItem,
    Period,
    QueryLogRecord,
    ResolvedField,
    ResolvedState,
    StepEvent,
)
from decision_core.semantic import load_semantic

ROOT = Path(__file__).resolve().parents[3]
API_DIR = ROOT / "packages" / "api"
PG_PORT = int(os.environ.get("DECISION_API_TEST_PG_PORT", "55440"))
PG_DIR = f"/tmp/decision-pg/{PG_PORT}"  # noqa: S108 - dossier de scripts/dev_pg.sh
ISSUER = "https://kc.test/auth/realms/decision"
JWKS_URL = "https://kc.test/auth/realms/decision/protocol/openid-connect/certs"
CLIENT_ID = "decision-web"
AUDIENCE = "decision-api"


# --- Clés et JWKS simulé ----------------------------------------------------------------------


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    data.update(kid=kid, use="sig", alg="RS256")
    return data


class FakeJWKS:
    """Serveur JWKS simulé (httpx.MockTransport) : compte les téléchargements, permet la rotation."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPrivateKey] = {"k1": _new_key()}
        self.published: list[str] = ["k1"]
        self.fetches = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == JWKS_URL
        self.fetches += 1
        return httpx.Response(200, json={"keys": [_jwk(self.keys[k], k) for k in self.published]})

    def rotate(self, kid: str) -> None:
        self.keys[kid] = _new_key()
        self.published = [kid]

    def token(
        self,
        sub: str = "user-1",
        roles: list[str] | None = None,
        *,
        kid: str = "k1",
        client: str = CLIENT_ID,
        aud: str | list[str] = AUDIENCE,
        iss: str = ISSUER,
        exp_in: int = 300,
        nbf_in: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": sub,
            "iss": iss,
            "aud": aud,
            "iat": now,
            "exp": now + exp_in,
            "resource_access": {client: {"roles": roles if roles is not None else ["decideur"]}},
            "preferred_username": sub,
        }
        if nbf_in is not None:
            claims["nbf"] = now + nbf_in
        claims.update(extra or {})
        key = self.keys.get(kid) or self.keys["k1"]
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def jwks() -> FakeJWKS:
    return FakeJWKS()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Faux agent et faux runtime ---------------------------------------------------------------


@dataclass
class FakeAgentScript:
    steps: int = 2
    fail: bool = False
    hang: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    sleeping: asyncio.Event = field(default_factory=asyncio.Event)


class FakeAgent:
    def __init__(self, script: FakeAgentScript) -> None:
        self.script = script

    async def answer(
        self,
        question: str,
        *,
        history: list[HistoryItem],
        state: ResolvedState | None,
        role: str,
        trace_id: str,
        on_event: Any = None,
        on_log: Any = None,
    ) -> AssistantMessage:
        self.script.calls.append(
            {"question": question, "history": history, "state": state, "role": role, "trace_id": trace_id}
        )
        self.script.started.set()
        for i in range(1, self.script.steps + 1):
            if on_event:
                await on_event(StepEvent(step=i, kind="tool", label=f"Étape {i}", tool="query_metric"))
            if on_log:
                await on_log(
                    QueryLogRecord(
                        trace_id=trace_id,
                        step=i,
                        tool="query_metric",
                        status="ok",
                        sql="SELECT 1",
                        row_count=1,
                        truncated=False,
                        duration_ms=12,
                        semantic_version="test",
                    )
                )
        if on_log:
            await on_log(
                QueryLogRecord(
                    trace_id=trace_id,
                    step=self.script.steps + 1,
                    tool="llm",
                    status="ok",
                    duration_ms=800,
                    model_requested="claude-sonnet-5-5",
                    model_served="claude-sonnet-5-5",
                    tokens_in=100,
                    tokens_out=50,
                    tokens_cache_read=900,
                    tokens_cache_write=0,
                    cost_usd=0.0021,
                )
            )
        if self.script.hang:
            self.script.sleeping.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.script.cancelled.set()
                raise
        if self.script.fail:
            raise RuntimeError("password=secret relation analytics.fact_transaction does not exist")
        return AssistantMessage(
            kind="answer",
            text=f"Réponse à : {question}",
            period=Period(start="2026-09-01", end="2026-09-30", label="septembre 2026"),
            tables=["analytics.fact_transaction"],
            sql=["SELECT count(*) FROM analytics.fact_transaction"],
            evidence=[EvidenceStep(kind="table", label="Transactions")],
            certified=True,
            resolved_state=ResolvedState(
                metrics=ResolvedField(value=["volume_transactions"], source="explicite"), certified=True
            ),
        )


def tiles_for(period: Period, region: str | None) -> dict[str, Any]:
    # même forme que decision_agent.dashboard.fetch_dashboard
    return {
        "period": period.model_dump(mode="json"),
        "compare_period": None,
        "region": region,
        "tiles": [{"metric": "volume_transactions", "value": 1000, "previous": 900, "available": True}],
        "facts": [],
        "errors": [],
    }


@dataclass
class FakeServices:
    script: FakeAgentScript = field(default_factory=FakeAgentScript)
    analyses: int = 0
    dashboards: int = 0


def make_runtime_factory(services: FakeServices, *, ready: bool = True):
    async def fetch_dashboard(
        tools: Any, semantic: Any, *, period: Period, region: str | None
    ) -> dict[str, Any]:
        services.dashboards += 1
        return tiles_for(period, region)

    async def run_dashboard_analysis(
        llm: Any,
        tools: Any,
        semantic: Any,
        settings: Any,
        *,
        period: Period,
        region: str | None,
        on_log: Any = None,
    ) -> DashboardAnalysis:
        services.analyses += 1
        if on_log:
            await on_log(
                QueryLogRecord(
                    trace_id="analysis-" + uuid.uuid4().hex[:8],
                    step=1,
                    tool="llm",
                    status="ok",
                    duration_ms=500,
                    cost_usd=0.001,
                )
            )
        return DashboardAnalysis(
            period=period,
            region=region,
            lead="Hausse du volume.",
            findings=[],
            semantic_version=semantic.version,
            model_id="claude-sonnet-5-5",
        )

    @asynccontextmanager
    async def factory(settings: Any, semantic: Any) -> AsyncIterator[Runtime]:
        yield Runtime(
            semantic=semantic,
            settings=settings,
            tools=object() if ready else None,
            llm=object() if ready else None,
            agent_factory=lambda: FakeAgent(services.script),
            fetch_dashboard=fetch_dashboard,
            run_dashboard_analysis=run_dashboard_analysis,
        )

    return factory


# --- Postgres ---------------------------------------------------------------------------------


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("localhost", port)) == 0


def dsn(role: str) -> str:
    return f"postgresql://{role}:{role}@localhost:{PG_PORT}/warehouse"


@pytest.fixture(scope="session")
def pg() -> Iterator[dict[str, str]]:
    started = False
    if not _port_open(PG_PORT):
        if not list(Path("/usr/lib/postgresql").glob("*/bin/initdb")) and not shutil.which("initdb"):
            pytest.skip("binaires Postgres absents")
        subprocess.run(  # noqa: S603 - script du dépôt
            [str(ROOT / "scripts" / "dev_pg.sh"), "start", str(PG_PORT)], check=True, capture_output=True
        )
        started = True
    env = {**os.environ, "OWNER_DATABASE_URL": dsn("app_owner")}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    try:
        yield {"app": dsn("app_rw"), "owner": dsn("app_owner")}
    finally:
        if started and os.environ.get("DECISION_API_TEST_KEEP_PG") != "1":
            subprocess.run(  # noqa: S603 - script du dépôt
                [str(ROOT / "scripts" / "dev_pg.sh"), "stop", PG_DIR], check=False, capture_output=True
            )


async def _truncate(owner_dsn: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(owner_dsn)
    try:
        await conn.execute(
            "TRUNCATE app.audit_access_log, app.query_log, app.feedback, app.message, app.conversation, "
            "app.analysis, app.eval_result, app.eval_run RESTART IDENTITY CASCADE"
        )
    finally:
        await conn.close()


# --- Application ------------------------------------------------------------------------------


@dataclass
class Ctx:
    client: httpx.AsyncClient
    jwks: FakeJWKS
    services: FakeServices
    app: Any
    settings: ApiSettings
    pg: dict[str, str] | None

    def h(self, sub: str = "user-1", roles: list[str] | None = None, **kw: Any) -> dict[str, str]:
        return auth(self.jwks.token(sub, roles, **kw))

    async def ask(self, cid: str, question: str, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(
            f"/api/conversations/{cid}/messages", json={"question": question}, headers=headers
        )

    async def new_conv(self, headers: dict[str, str]) -> str:
        r = await self.client.post("/api/conversations", json={}, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()["id"]


def make_settings(app_dsn: str | None, **overrides: Any) -> ApiSettings:
    base: dict[str, Any] = dict(
        environment="test",
        keycloak_issuer=ISSUER,
        keycloak_jwks_url=JWKS_URL,
        keycloak_audience=AUDIENCE,
        keycloak_client_id=CLIENT_ID,
        cors_origins="",
        log_pseudonym_key="test-pseudonym-key",
        app_database_url=app_dsn,
        rights_test_report="/nonexistent/rights-test.json",
    )
    base.update(overrides)
    return ApiSettings(_env_file=None, **base)


@asynccontextmanager
async def build_ctx(
    jwks: FakeJWKS, pg_dsns: dict[str, str] | None, *, ready: bool = True, **overrides: Any
) -> AsyncIterator[Ctx]:
    settings = make_settings(pg_dsns["app"] if pg_dsns else None, **overrides)
    services = FakeServices()
    http = httpx.AsyncClient(transport=httpx.MockTransport(jwks.handler))
    validator = TokenValidator(settings, JWKSCache(JWKS_URL, http=http, refresh_min_interval_s=30))
    app = create_app(
        settings,
        semantic=load_semantic(ROOT / "semantic"),
        runtime_factory=make_runtime_factory(services, ready=ready),
        token_validator=validator,
        configure_logs=False,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Ctx(client=client, jwks=jwks, services=services, app=app, settings=settings, pg=pg_dsns)
    await http.aclose()


@pytest.fixture
def settings_factory():
    return make_settings


@pytest.fixture
def builder():
    return build_ctx


@pytest.fixture
def sse():
    return parse_sse


@pytest.fixture
async def ctx_nodb(jwks: FakeJWKS) -> AsyncIterator[Ctx]:
    async with build_ctx(jwks, None) as c:
        yield c


@pytest.fixture
async def ctx(jwks: FakeJWKS, pg: dict[str, str]) -> AsyncIterator[Ctx]:
    await _truncate(pg["owner"])
    async with build_ctx(jwks, pg) as c:
        yield c


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    for block in body.split("\n\n"):
        name, data = None, []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if name:
            events.append((name, json.loads("\n".join(data)) if data else None))
    return events
