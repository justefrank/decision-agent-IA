"""AnthropicClient (SDK simulé : paramètres, relances, échéance), schémas d'outils, client MCP."""

from __future__ import annotations

import os
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from decision_agent import llm as llm_mod
from decision_agent.llm import AnthropicClient, LLMError, LLMRequest, LLMUsage, cost_usd
from decision_agent.prompts import build_system, prompt_version
from decision_agent.tools import CLAUDE_TOOLS, McpToolClient, parse_call_result
from decision_core.models import ToolResult


class FakeStream:
    def __init__(self, outcome):
        self.outcome = outcome
        self.request_id = "req_stream"

    async def __aenter__(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            yield SimpleNamespace(type="message_start")
            yield SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", name="query_metric"),
            )

        return gen()

    async def get_final_message(self):
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=7000,
            cache_creation_input_tokens=0,
            cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=0),
        )
        return SimpleNamespace(
            content=[
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "tool_use", "id": "t1", "name": "query_metric", "input": {}},
            ],
            stop_reason="tool_use",
            usage=usage,
            model="claude-sonnet-5-5",
            _request_id="req_1",
            stop_details=None,
        )


class FakeMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.kwargs = []

    def stream(self, **kw):
        self.kwargs.append(kw)
        return FakeStream(self.outcomes.pop(0))


class FakeSDK:
    def __init__(self, outcomes):
        self.messages = FakeMessages(outcomes)
        self.beta = SimpleNamespace(messages=FakeMessages(outcomes))


def req(deadline=30.0):
    return LLMRequest(
        model="claude-sonnet-5-5",
        system=[{"type": "text", "text": "x"}],
        tools=CLAUDE_TOOLS,
        messages=[{"role": "user", "content": "q"}],
        effort="medium",
        max_tokens=8000,
        deadline_s=deadline,
    )


def api_error(cls, status, body=None, headers=None):
    resp = httpx2.Response(
        status, headers=headers or {}, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return cls("err", response=resp, body=body)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fake_sleep(_):
        return None

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)


async def test_request_parameters():
    sdk = FakeSDK([None])
    client = AnthropicClient(client=sdk)
    events = []

    async def on_event(kind, data):
        events.append((kind, data))

    step = await client.step(req(), on_event=on_event)
    kw = sdk.messages.kwargs[0]
    assert not {"temperature", "top_p", "top_k"} & set(kw)
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["tool_choice"] == {"type": "auto"}
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["timeout"] <= 20
    assert step.content[0]["type"] == "thinking"  # rejoué tel quel
    assert step.usage.cache_read_tokens == 7000 and step.request_id == "req_1"
    assert step.ttft_ms is not None
    assert events == [("tool_use_start", {"name": "query_metric"})]


async def test_fallbacks_use_beta():
    sdk = FakeSDK([None])
    await AnthropicClient(client=sdk, fallbacks=True).step(req())
    kw = sdk.beta.messages.kwargs[0]
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"


async def test_rate_limit_retry_within_deadline():
    sdk = FakeSDK([api_error(anthropic.RateLimitError, 429, headers={"retry-after": "2"}), None])
    step = await AnthropicClient(client=sdk).step(req())
    assert step.stop_reason == "tool_use" and len(sdk.messages.kwargs) == 2


async def test_rate_limit_retry_after_too_long():
    sdk = FakeSDK([api_error(anthropic.RateLimitError, 429, headers={"retry-after": "40"}), None])
    with pytest.raises(LLMError) as e:
        await AnthropicClient(client=sdk).step(req())
    assert e.value.kind == "rate_limited" and len(sdk.messages.kwargs) == 1


async def test_spend_limit_never_retried():
    body = {
        "type": "error",
        "error": {"type": "rate_limit_error", "details": {"error_code": "enforced_spend_limit_reached"}},
    }
    sdk = FakeSDK([api_error(anthropic.RateLimitError, 429, body=body, headers={"retry-after": "1"}), None])
    with pytest.raises(LLMError) as e:
        await AnthropicClient(client=sdk).step(req())
    assert e.value.kind == "spend_limit" and len(sdk.messages.kwargs) == 1


async def test_overloaded_retried_once():
    sdk = FakeSDK(
        [api_error(anthropic.OverloadedError, 529), api_error(anthropic.OverloadedError, 529), None]
    )
    with pytest.raises(LLMError) as e:
        await AnthropicClient(client=sdk).step(req())
    assert e.value.kind == "overloaded" and len(sdk.messages.kwargs) == 2


async def test_overloaded_then_ok():
    sdk = FakeSDK([api_error(anthropic.InternalServerError, 500), None])
    assert (await AnthropicClient(client=sdk).step(req())).stop_reason == "tool_use"


async def test_bad_request_not_retried():
    sdk = FakeSDK([api_error(anthropic.BadRequestError, 400), None])
    with pytest.raises(LLMError) as e:
        await AnthropicClient(client=sdk).step(req())
    assert e.value.kind == "bad_request" and len(sdk.messages.kwargs) == 1


async def test_no_retry_when_deadline_too_short():
    sdk = FakeSDK([api_error(anthropic.OverloadedError, 529), None])
    with pytest.raises(LLMError):
        await AnthropicClient(client=sdk).step(req(deadline=2.0))
    assert len(sdk.messages.kwargs) == 1


def test_cost_table():
    u = LLMUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_1h_tokens=1_000_000,
    )
    assert cost_usd(u, "claude-sonnet-5-5") == pytest.approx(2 + 10 + 0.1 + 4)
    assert cost_usd(u, "modele-inconnu") is None


def _walk(schema, path="$"):
    yield path, schema
    if isinstance(schema, dict):
        for k, v in schema.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            yield from _walk(v, f"{path}[{i}]")


def test_tool_schemas_are_strict():
    assert [t["name"] for t in CLAUDE_TOOLS] == [
        "query_metric",
        "run_query",
        "describe_schema",
        "submit_answer",
        "ask_clarification",
        "refuse",
    ]
    for tool in CLAUDE_TOOLS:
        assert tool["strict"] is True
        for path, node in _walk(tool["input_schema"]):
            if isinstance(node, dict) and node.get("type") == "object":
                assert node["additionalProperties"] is False, path
                assert set(node["required"]) == set(node["properties"]), path
            if isinstance(node, dict):
                assert not {"minimum", "maximum", "maxLength", "minLength", "maxItems", "pattern"} & set(
                    node
                ), path
                if "minItems" in node:
                    assert node["minItems"] in (0, 1), path
    submit = next(t for t in CLAUDE_TOOLS if t["name"] == "submit_answer")
    assert set(submit["input_schema"]["properties"]) == {"text", "result_ids", "caveats", "follow_up"}


def test_prompt_is_stable(semantic):
    assert build_system(semantic) == build_system(semantic)
    assert prompt_version() == prompt_version()
    text = build_system(semantic)[0]["text"]
    assert "N'invente jamais" in text and "DONNÉES NON FIABLES" in text


def test_parse_call_result():
    data = ToolResult(tool="query_metric", ok=True, row_count=0).model_dump(mode="json")
    res = parse_call_result(
        "query_metric", SimpleNamespace(structured_content=data, content=[], is_error=False)
    )
    assert res.ok
    import json

    res2 = parse_call_result(
        "run_query",
        SimpleNamespace(
            structured_content=None,
            is_error=True,
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "tool": "run_query",
                            "ok": False,
                            "error": {"error_class": "sql_error", "message": "x"},
                        }
                    )
                )
            ],
        ),
    )
    assert not res2.ok and res2.error.error_class == "sql_error"
    res3 = parse_call_result("run_query", SimpleNamespace(structured_content=None, content=[], is_error=True))
    assert res3.error.error_class == "internal"


def test_mcp_env_is_restricted(settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    env = McpToolClient.server_env(settings.model_copy(update={"agent_ro_dsn": None}))
    assert set(env) <= set(McpToolClient.ENV_KEYS)
    assert "ANTHROPIC_API_KEY" not in env and env["REFERENCE_DATE"] == "2026-09-30"


def _mcp_server_importable() -> bool:
    try:
        import decision_mcp_server.server  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _mcp_server_importable(), reason="paquet decision_mcp_server absent")
async def test_mcp_tool_client_protocol(settings):
    """Sous-processus stdio réel, sans base : describe_schema répond, query_metric renvoie un ToolResult."""
    s = settings.model_copy(update={"agent_ro_dsn": None})
    async with McpToolClient.start(s) as client:
        res = await client.call("describe_schema", {"table": "dim_region"}, timeout_s=10)
        assert res.ok and res.tool == "describe_schema" and res.payload
        res = await client.call(
            "query_metric",
            {
                "metrics": ["volume_transactions"],
                "period": {"start": "2026-09-01", "end": "2026-09-30", "label": None},
                "compare_to": "none",
                "group_by": [],
                "grain": "none",
                "filters": [],
                "order": "none",
                "limit": None,
            },
            timeout_s=10,
        )
        assert res.tool == "query_metric" and res.certified
        assert res.sql and "LIMIT 1001" in res.sql


@pytest.mark.db
@pytest.mark.skipif(
    not (_mcp_server_importable() and os.environ.get("AGENT_RO_DSN")),
    reason="Intégration MCP + Postgres : définir AGENT_RO_DSN (base seedée, ex. scripts/dev_pg.sh "
    "start 55430 puis le générateur de données).",
)
async def test_mcp_tool_client_with_db(settings):
    from pydantic import SecretStr

    s = settings.model_copy(update={"agent_ro_dsn": SecretStr(os.environ["AGENT_RO_DSN"])})
    async with McpToolClient.start(s) as client:
        res = await client.call(
            "query_metric",
            {
                "metrics": ["volume_transactions"],
                "period": {"start": "2026-09-01", "end": "2026-09-30", "label": None},
                "compare_to": "previous_period",
                "group_by": [],
                "grain": "none",
                "filters": [],
                "order": "none",
                "limit": None,
            },
            timeout_s=10,
        )
        assert res.ok, res.error
        assert any(c.role == "period" for c in res.columns)
