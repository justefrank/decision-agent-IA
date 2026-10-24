"""Démarrage réel (sans faux runtime) : mode dégradé signalé par /health si le MCP ne démarre pas."""

from __future__ import annotations

import asyncio
from pathlib import Path

from decision_api.runtime import default_runtime
from decision_core.semantic import load_semantic

ROOT = Path(__file__).resolve().parents[3]


async def test_default_runtime_degraded_when_mcp_cannot_start(settings_factory):
    settings = settings_factory(
        None, mcp_command="/nonexistent/mcp-binary", anthropic_api_key="sk-test-0000000000"
    )
    async with asyncio.timeout(20):
        async with default_runtime(settings, load_semantic(ROOT / "semantic")) as rt:
            assert not rt.mcp_ready and not rt.agent_ready
            assert any("MCP" in e for e in rt.startup_errors)
            assert rt.llm is not None  # AnthropicClient construit sans appel réseau
