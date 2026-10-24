"""Intégration optionnelle contre l'API Claude réelle (ignorée sans ANTHROPIC_API_KEY).

Vérifie : la requête est acceptée (pas de temperature, outils stricts, cache 1 h), la boucle se termine
par un outil terminal et le préfixe est relu depuis le cache au second appel.
"""

from __future__ import annotations

import os

import pytest
from decision_agent import Agent, AnthropicClient, FakeToolClient
from decision_agent.testing import kpi_result
from pydantic import SecretStr

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY absente")


async def test_real_api_simple_kpi(semantic, settings):
    s = settings.model_copy(update={"anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"])})
    llm = AnthropicClient.from_settings(s)
    tools = FakeToolClient(
        {"query_metric": lambda a: kpi_result({m: 1_234_567 for m in a["metrics"]}, params=a)}
    )
    logs = []

    async def on_log(r):
        logs.append(r)

    agent = Agent(llm, tools, semantic, s)
    for _ in range(2):
        msg = await agent.answer(
            "Quels sont les revenus de frais en août 2026 ?",
            history=[],
            state=None,
            role="analyste",
            trace_id="it-1",
            on_log=on_log,
        )
        assert msg.kind in ("answer", "clarification")
    llm_logs = [r for r in logs if r.tool == "llm" and r.status == "ok"]
    assert llm_logs and all(r.model_served for r in llm_logs)
    assert any((r.tokens_cache_read or 0) > 0 for r in llm_logs[1:]), (
        "le préfixe n'est pas relu depuis le cache"
    )
