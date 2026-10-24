"""Tests du banc HTTP (O2) avec un transport httpx simulé."""

from __future__ import annotations

import json

import httpx
from decision_eval.bench import parse_sse, run_bench


def test_parse_sse():
    events, rest = parse_sse(': ping\n\nevent: step\ndata: {"step": 1}\n\nevent: final\ndata: {"kind"')
    assert events == [("step", '{"step": 1}')]
    assert rest.startswith("event: final")
    events, rest = parse_sse(rest + ': "answer"}\n\n')
    assert events == [("final", '{"kind": "answer"}')] and rest == ""


def make_transport(fail_on: str | None = None):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/api/conversations":
            return httpx.Response(201, json={"id": "c1"})
        q = json.loads(request.content)["question"]
        if q == fail_on:
            body = 'event: error\ndata: {"code": "x", "message": "LLM indisponible"}\n\n'
        else:
            body = 'event: step\ndata: {"step": 1}\n\n: ping\n\nevent: final\ndata: {"kind": "answer"}\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler), seen


async def test_run_bench_measures_until_final():
    transport, seen = make_transport(fail_on="Q2")
    async with httpx.AsyncClient(transport=transport) as client:
        rep = await run_bench("http://api", "jeton", ["Q1", "Q2", "Q3"], client=client, concurrency=2)
    s = rep.summary()
    assert s["n"] == 3 and s["ok"] == 2
    assert s["p50_ms"] is not None and s["o2_median_lt_15s"] is True
    err = [o for o in rep.observations if not o.ok][0]
    assert err.event == "error" and err.error == "LLM indisponible"
    assert all(h == "Bearer jeton" for _, _, h in seen)
    assert sum(1 for _, p, _ in seen if p == "/api/conversations/c1/messages") == 3


async def test_run_bench_http_error():
    def handler(request):
        return httpx.Response(401, text="non autorisé")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rep = await run_bench("http://api", "t", ["Q"], conversation_id="c9", client=client)
    assert rep.observations[0].ok is False and "401" in rep.observations[0].error
