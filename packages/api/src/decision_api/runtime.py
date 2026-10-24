"""Composants partagés démarrés une fois par processus : client MCP (sous-processus stdio) et client LLM.

`decision_agent` est importé paresseusement : l'API démarre (en mode dégradé, signalé par /health)
même si le paquet agent ou le serveur MCP ne sont pas disponibles. Les tests injectent un `Runtime`.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from decision_core.models import (
    AssistantMessage,
    DashboardAnalysis,
    HistoryItem,
    Period,
    QueryLogRecord,
    ResolvedState,
    Role,
    StepEvent,
)
from decision_core.semantic import SemanticLayer
from decision_core.settings import Settings

log = logging.getLogger("decision_api.runtime")

OnEvent = Callable[[StepEvent], Awaitable[None]]
OnLog = Callable[[QueryLogRecord], Awaitable[None]]


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


@dataclass
class Runtime:
    semantic: SemanticLayer
    settings: Settings
    tools: Any | None = None  # decision_agent.tools.ToolClient
    llm: Any | None = None  # decision_agent.llm.LLMClient
    agent_factory: Callable[[], AgentLike] | None = None
    fetch_dashboard: Callable[..., Awaitable[dict[str, Any]]] | None = None
    run_dashboard_analysis: Callable[..., Awaitable[DashboardAnalysis]] | None = None
    startup_errors: list[str] = field(default_factory=list)

    @property
    def mcp_ready(self) -> bool:
        return self.tools is not None

    @property
    def agent_ready(self) -> bool:
        return self.agent_factory is not None and self.tools is not None and self.llm is not None

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


@asynccontextmanager
async def default_runtime(settings: Settings, semantic: SemanticLayer) -> AsyncIterator[Runtime]:
    """Démarre UN client MCP (`McpToolClient.start`) et l'`AnthropicClient` pour le processus."""
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
        try:
            runtime.tools = await stack.enter_async_context(McpToolClient.start(settings))
        except Exception as exc:  # noqa: BLE001 - mode dégradé signalé par /health
            runtime.startup_errors.append(f"MCP indisponible : {type(exc).__name__}")
            log.error("échec du démarrage du serveur MCP : %s", type(exc).__name__)
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
