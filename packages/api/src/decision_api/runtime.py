"""Composants partagés démarrés une fois par processus : client MCP (sous-processus stdio) et client LLM.

`decision_agent` est importé paresseusement : l'API démarre (en mode dégradé, signalé par /health)
même si le paquet agent ou le serveur MCP ne sont pas disponibles. Les tests injectent un `Runtime`.

Le client MCP est tenu par un `McpSupervisor` : une tâche de fond démarre le sous-processus, le sonde
(`list_tools`, délai court) à intervalle régulier et le relance s'il meurt, avec un backoff
exponentiel et un nombre borné de relances consécutives. `/api/health` interroge la même sonde.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from decision_core.models import (
    AssistantMessage,
    DashboardAnalysis,
    HistoryItem,
    Period,
    QueryLogRecord,
    ResolvedState,
    Role,
    StepEvent,
    ToolError,
    ToolResult,
)
from decision_core.semantic import SemanticLayer
from decision_core.settings import Settings

log = logging.getLogger("decision_api.runtime")

OnEvent = Callable[[StepEvent], Awaitable[None]]
OnLog = Callable[[QueryLogRecord], Awaitable[None]]
McpState = Literal["starting", "ok", "restarting", "down"]
ClientStarter = Callable[[], AbstractAsyncContextManager[Any]]


class AgentLike:  # documentation du protocole attendu (brief §3)
    async def answer(
        self,
        question: str,
        *,
        history: list[HistoryItem],
        state: ResolvedState | None,
        role: Role,
        trace_id: str,
        on_event: OnEvent | None = None,
        on_log: OnLog | None = None,
    ) -> AssistantMessage:  # pragma: no cover
        raise NotImplementedError


class _ProbeFailed(Exception):
    pass


class McpSupervisor:
    """Tient le client MCP vivant : démarrage, sonde périodique, relance bornée avec backoff.

    Expose `call()` (même contrat que `ToolClient`) : l'agent et le tableau de bord reçoivent le
    superviseur, qui délègue au client courant ; si le sous-processus est en cours de relance, l'appel
    renvoie une erreur d'outil propre au lieu d'utiliser un client mort.
    """

    def __init__(
        self,
        starter: ClientStarter,
        *,
        probe_timeout_s: float = 2.0,
        probe_interval_s: float = 15.0,
        max_restarts: int = 5,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 30.0,
        probe_cache_s: float = 5.0,
    ) -> None:
        self._starter = starter
        self.probe_timeout_s = probe_timeout_s
        self.probe_interval_s = probe_interval_s
        self.max_restarts = max_restarts
        self.backoff_initial_s = backoff_initial_s
        self.backoff_max_s = backoff_max_s
        self.probe_cache_s = probe_cache_s
        self.client: Any | None = None
        self.state: McpState = "starting"
        self.restarts = 0  # relances effectuées depuis le démarrage
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._first = asyncio.Event()
        self._kick = asyncio.Event()
        self._last_probe: tuple[float, bool] | None = None

    # --- cycle de vie -------------------------------------------------------------------------

    async def start(self, *, wait_s: float = 30.0) -> None:
        """Lance la tâche de supervision et attend le premier démarrage (réussi ou non)."""
        self._task = asyncio.create_task(self._run(), name="mcp-supervisor")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._first.wait(), timeout=wait_s)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self.client = None
        self.state = "down"

    @property
    def ready(self) -> bool:
        return self.state == "ok" and self.client is not None

    def _backoff(self, failures: int) -> float:
        return min(self.backoff_max_s, self.backoff_initial_s * (2 ** max(0, failures - 1)))

    async def _run(self) -> None:
        failures = 0
        while True:
            try:
                async with self._starter() as client:
                    self.client = client
                    self.state = "ok"
                    self._last_probe = (time.monotonic(), True)
                    failures = 0
                    self._first.set()
                    log.info("serveur MCP démarré", extra={"event": "mcp_started"})
                    await self._watch(client)
            except asyncio.CancelledError:
                self.client = None
                raise
            except Exception as exc:  # noqa: BLE001 - mort du sous-processus, échec de démarrage
                self.last_error = type(exc).__name__
                log.error("serveur MCP indisponible : %s", self.last_error)
            self.client = None
            self._last_probe = (time.monotonic(), False)
            failures += 1
            if failures > self.max_restarts:
                self.state = "down"
                self._first.set()
                log.error(
                    "serveur MCP abandonné après %d relances consécutives",
                    self.max_restarts,
                    extra={"event": "mcp_down"},
                )
                return
            self.state = "restarting"
            if failures == 1 and not self._first.is_set():
                self._first.set()  # premier démarrage raté : l'API démarre en mode dégradé
            delay = self._backoff(failures)
            log.warning("relance du serveur MCP dans %.1f s (tentative %d)", delay, failures)
            await asyncio.sleep(delay)
            self.restarts += 1

    async def _watch(self, client: Any) -> None:
        """Sonde le client à intervalle régulier ; lève dès qu'une sonde échoue."""
        while True:
            self._kick.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._kick.wait(), timeout=self.probe_interval_s)
            if not await self._probe_client(client):
                raise _ProbeFailed("sonde MCP en échec")
            self.state = "ok"  # échec passager d'une sonde à la demande : le client répond de nouveau

    async def _probe_client(self, client: Any) -> bool:
        session = getattr(client, "session", None)
        target = getattr(session, "list_tools", None) or getattr(client, "list_tools", None)
        ok = False
        if target is not None:
            try:
                await asyncio.wait_for(target(), timeout=self.probe_timeout_s)
                ok = True
            except Exception as exc:  # noqa: BLE001
                self.last_error = type(exc).__name__
        self._last_probe = (time.monotonic(), ok)
        return ok

    # --- sonde à la demande (/api/health) -------------------------------------------------------

    async def probe(self) -> bool:
        """Sonde réelle (list_tools, délai court), mise en cache quelques secondes contre l'abus."""
        client = self.client
        if self.state != "ok" or client is None:
            return False
        now = time.monotonic()
        if self._last_probe is not None and now - self._last_probe[0] < self.probe_cache_s:
            return self._last_probe[1]
        ok = await self._probe_client(client)
        if not ok:
            self.state = "restarting"  # plus de requêtes vers ce client ; agent en 503 d'ici la relance
            self._kick.set()  # la tâche de supervision relance le sous-processus
        return ok

    # --- ToolClient -----------------------------------------------------------------------------

    async def call(self, name: str, args: dict[str, Any], *, timeout_s: float) -> ToolResult:
        client = self.client
        if client is None or self.state != "ok":
            return _unavailable(name)
        result: ToolResult = await client.call(name, args, timeout_s=timeout_s)
        if not result.ok and result.error is not None and result.error.error_class == "internal":
            self._kick.set()  # erreur de transport possible : sonder sans attendre l'intervalle
        return result


def _unavailable(name: str) -> ToolResult:
    tool = name if name in ("query_metric", "run_query", "describe_schema") else "describe_schema"
    return ToolResult(
        tool=tool,  # type: ignore[arg-type]
        ok=False,
        error=ToolError(error_class="internal", message="Serveur d'outils momentanément indisponible."),
    )


@dataclass
class Runtime:
    semantic: SemanticLayer
    settings: Settings
    tools: Any | None = None  # decision_agent.tools.ToolClient (ou McpSupervisor)
    llm: Any | None = None  # decision_agent.llm.LLMClient
    agent_factory: Callable[[], AgentLike] | None = None
    fetch_dashboard: Callable[..., Awaitable[dict[str, Any]]] | None = None
    run_dashboard_analysis: Callable[..., Awaitable[DashboardAnalysis]] | None = None
    startup_errors: list[str] = field(default_factory=list)
    mcp: McpSupervisor | None = None
    llm_configured: bool = True  # clé API présente

    @property
    def mcp_ready(self) -> bool:
        if self.mcp is not None:
            return self.mcp.ready
        return self.tools is not None

    @property
    def mcp_state(self) -> str:
        if self.mcp is not None:
            return self.mcp.state
        return "ok" if self.tools is not None else "down"

    async def probe_mcp(self) -> bool:
        if self.mcp is not None:
            return await self.mcp.probe()
        return self.tools is not None

    @property
    def agent_ready(self) -> bool:
        return (
            self.agent_factory is not None and self.mcp_ready and self.llm is not None and self.llm_configured
        )

    def make_agent(self) -> AgentLike:
        assert self.agent_factory is not None
        return self.agent_factory()

    async def dashboard(self, *, period: Period, region: str | None) -> dict[str, Any]:
        assert self.fetch_dashboard is not None
        result = self.fetch_dashboard(self.tools, self.semantic, period=period, region=region)
        return await result if inspect.isawaitable(result) else result

    async def analysis(
        self, *, period: Period, region: str | None, on_log: OnLog | None
    ) -> DashboardAnalysis:
        assert self.run_dashboard_analysis is not None
        return await self.run_dashboard_analysis(
            self.llm, self.tools, self.semantic, self.settings, period=period, region=region, on_log=on_log
        )


def _build_llm(settings: Settings) -> Any:
    from decision_agent.llm import AnthropicClient  # import paresseux

    if hasattr(AnthropicClient, "from_settings"):
        return AnthropicClient.from_settings(settings)
    return AnthropicClient(settings)


def _has_api_key(settings: Settings) -> bool:
    key = settings.anthropic_api_key
    return key is not None and bool(key.get_secret_value().strip())


def make_supervisor(settings: Settings, starter: ClientStarter) -> McpSupervisor:
    return McpSupervisor(
        starter,
        probe_timeout_s=float(getattr(settings, "mcp_probe_timeout_s", 2.0)),
        probe_interval_s=float(getattr(settings, "mcp_probe_interval_s", 15.0)),
        max_restarts=int(getattr(settings, "mcp_max_restarts", 5)),
        backoff_initial_s=float(getattr(settings, "mcp_backoff_initial_s", 1.0)),
        backoff_max_s=float(getattr(settings, "mcp_backoff_max_s", 30.0)),
    )


@asynccontextmanager
async def default_runtime(settings: Settings, semantic: SemanticLayer) -> AsyncIterator[Runtime]:
    """Démarre UN client MCP supervisé (`McpToolClient.start`) et l'`AnthropicClient` du processus."""
    runtime = Runtime(semantic=semantic, settings=settings)
    async with AsyncExitStack() as stack:
        try:
            import decision_agent
            from decision_agent.tools import McpToolClient
        except ImportError as exc:
            runtime.startup_errors.append(f"agent indisponible : {type(exc).__name__}")
            log.error("paquet decision_agent indisponible")
            yield runtime
            return
        try:  # le tableau de bord est facultatif : les questions restent servies sans lui
            from decision_agent.dashboard import fetch_dashboard, run_dashboard_analysis

            runtime.fetch_dashboard = fetch_dashboard
            runtime.run_dashboard_analysis = run_dashboard_analysis
        except ImportError as exc:
            runtime.startup_errors.append(f"tableau de bord indisponible : {type(exc).__name__}")
            log.error("module decision_agent.dashboard indisponible")

        supervisor = make_supervisor(settings, lambda: McpToolClient.start(settings))
        stack.push_async_callback(supervisor.stop)
        await supervisor.start()
        runtime.mcp = supervisor
        runtime.tools = supervisor
        if not supervisor.ready:
            runtime.startup_errors.append(f"MCP indisponible : {supervisor.last_error or 'démarrage'}")
            log.error("échec du démarrage du serveur MCP : %s", supervisor.last_error)

        runtime.llm_configured = _has_api_key(settings)
        if not runtime.llm_configured:
            runtime.startup_errors.append("LLM indisponible : ANTHROPIC_API_KEY absente")
            log.error("ANTHROPIC_API_KEY absente : agent désactivé")
        else:
            try:
                runtime.llm = _build_llm(settings)
                aclose = getattr(runtime.llm, "aclose", None)
                if aclose is not None:
                    stack.push_async_callback(aclose)
            except Exception as exc:  # noqa: BLE001
                runtime.startup_errors.append(f"LLM indisponible : {type(exc).__name__}")
                log.error("échec de l'initialisation du client LLM : %s", type(exc).__name__)

        def _factory() -> AgentLike:
            return decision_agent.Agent(runtime.llm, runtime.tools, runtime.semantic, runtime.settings)

        runtime.agent_factory = _factory
        yield runtime
