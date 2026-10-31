"""Tests de bout en bout avec un vrai Postgres (migration Alembic app_owner, connexion app_rw)."""

from __future__ import annotations

import asyncio
import json
import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.db

DEC = ["decideur"]
ANA = ["analyste"]
ADM = ["admin"]


async def _owner_fetch(ctx, sql: str, *args):
    conn = await asyncpg.connect(ctx.pg["owner"])
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


# --- Santé et conversations ------------------------------------------------------------------


async def test_health(ctx):
    r = await ctx.client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok" and r.json()["mcp"] == "ok"


async def test_conversation_crud_and_cross_access(ctx):
    a, b = ctx.h("alice", DEC), ctx.h("bob", DEC)
    cid = await ctx.new_conv(a)
    await ctx.new_conv(a)
    listed = (await ctx.client.get("/api/conversations", headers=a)).json()
    assert len(listed) == 2 and listed[0]["id"] != cid  # tri : la plus récente d'abord
    assert (await ctx.client.get("/api/conversations", headers=b)).json() == []
    # Accès croisé : 404, jamais 403 (pas de fuite d'existence)
    assert (await ctx.client.get(f"/api/conversations/{cid}", headers=b)).status_code == 404
    assert (await ctx.client.delete(f"/api/conversations/{cid}", headers=b)).status_code == 404
    assert (await ctx.ask(cid, "Volume en septembre ?", b)).status_code == 404
    assert (await ctx.client.get(f"/api/conversations/{cid}", headers=a)).status_code == 200
    assert (await ctx.client.delete(f"/api/conversations/{cid}", headers=a)).status_code == 204
    assert (await ctx.client.get(f"/api/conversations/{cid}", headers=a)).status_code == 404
    bad = await ctx.client.get("/api/conversations/pas-un-uuid", headers=a)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"


# --- Flux SSE --------------------------------------------------------------------------------


async def test_sse_order_and_decideur_without_sql(ctx, sse):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    r = await ctx.ask(cid, "Volume en septembre ?", h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    names = [n for n, _ in events]
    assert names == ["step", "step", "final"]
    assert [d["step"] for n, d in events if n == "step"] == [1, 2]
    final = events[-1][1]
    assert final["kind"] == "answer" and final["sql"] is None
    assert final["trace_id"] == r.headers["x-trace-id"]
    # Relecture : SQL toujours retiré pour le décideur, titre fixé par la première question.
    conv = (await ctx.client.get(f"/api/conversations/{cid}", headers=h)).json()
    assert conv["title"] == "Volume en septembre ?"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["message"]["sql"] is None


async def test_sse_analyste_gets_sql(ctx, sse):
    h = ctx.h("ana", ANA)
    cid = await ctx.new_conv(h)
    final = sse((await ctx.ask(cid, "Volume ?", h)).text)[-1][1]
    assert final["sql"] == ["SELECT count(*) FROM analytics.fact_transaction"]
    conv = (await ctx.client.get(f"/api/conversations/{cid}", headers=h)).json()
    assert conv["messages"][1]["message"]["sql"]
    assert ctx.services.script.calls[-1]["role"] == "analyste"


async def test_history_and_state_passed_to_agent(ctx, sse):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    for i in range(8):
        sse((await ctx.ask(cid, f"Question {i}", h)).text)
    last = ctx.services.script.calls[-1]
    assert len(last["history"]) == 6
    assert [x.question for x in last["history"]] == [f"Question {i}" for i in range(1, 7)]
    assert last["state"] is not None and last["state"].certified is True
    assert ctx.services.script.calls[0]["history"] == [] and ctx.services.script.calls[0]["state"] is None


async def test_agent_failure_emits_error_without_leak(ctx, sse):
    ctx.services.script.fail = True
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    r = await ctx.ask(cid, "Volume ?", h)
    events = sse(r.text)
    assert [n for n, _ in events] == ["step", "step", "error"]
    err = events[-1][1]
    assert err["code"] == "agent_error" and "password" not in r.text and "analytics" not in err["message"]


async def test_question_length_and_empty(ctx):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    r = await ctx.ask(cid, "x" * 1001, h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "question_too_long"
    assert (await ctx.ask(cid, "   ", h)).status_code == 422


# --- Journal ---------------------------------------------------------------------------------


async def test_query_log_written_and_append_only(ctx, sse):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    r = await ctx.ask(cid, "Volume en septembre ?", h)
    trace = r.headers["x-trace-id"]
    rows = await _owner_fetch(ctx, "SELECT * FROM app.query_log WHERE trace_id = $1 ORDER BY step", trace)
    # step 0 : inscription de la question (quota), puis les appels de l'agent
    assert [x["tool"] for x in rows] == ["question", "query_metric", "query_metric", "llm"]
    assert all(x["user_ref"] and x["user_ref"] != "alice" and len(x["user_ref"]) == 64 for x in rows)
    assert rows[0]["question_hash"] and "Volume" not in json.dumps([dict(x) for x in rows], default=str)
    assert rows[0]["question_hash"] == rows[1]["question_hash"]
    assert str(rows[0]["conversation_id"]) == cid
    assert float(rows[3]["cost_usd"]) == pytest.approx(0.0021)

    conn = await asyncpg.connect(ctx.pg["app"])  # rôle de l'API
    try:
        for stmt in (
            "UPDATE app.query_log SET status = 'ok'",
            "DELETE FROM app.query_log",
            "TRUNCATE app.query_log",
            "UPDATE app.audit_access_log SET action = 'x'",
            "DELETE FROM app.audit_access_log",
            "DELETE FROM app.eval_run",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(stmt)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE TABLE app.intrus (id int)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM app.alembic_version")
        with pytest.raises(asyncpg.PostgresError):  # CHECK status
            await conn.execute(
                "INSERT INTO app.query_log (trace_id, step, tool, status, duration_ms) "
                "VALUES ('t', 1, 'x', 'bizarre', 1)"
            )
    finally:
        await conn.close()


# --- Quotas ----------------------------------------------------------------------------------


async def test_daily_quota(ctx, sse, monkeypatch):
    sem = ctx.app.state.runtime.semantic
    monkeypatch.setitem(sem.config["quota"], "questions_per_user_per_day", 2)
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    for _ in range(2):
        assert (await ctx.ask(cid, "Volume ?", h)).status_code == 200
    r = await ctx.ask(cid, "Volume ?", h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    # Le quota est par utilisateur
    hb = ctx.h("bob", DEC)
    assert (await ctx.ask(await ctx.new_conv(hb), "Volume ?", hb)).status_code == 200


async def test_concurrent_stream_limit(ctx):
    limiter = ctx.app.state.stream_limiter
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    limiter.acquire("alice", 10)
    limiter.acquire("alice", 10)
    r = await ctx.ask(cid, "Volume ?", h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_streams"
    # Refus du limiteur AVANT le quota : ni message `user` orphelin, ni question imputée.
    conv = (await ctx.client.get(f"/api/conversations/{cid}", headers=h)).json()
    assert conv["messages"] == []
    assert (await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.query_log"))[0]["n"] == 0
    limiter.release("alice")
    limiter.release("alice")
    assert (await ctx.ask(cid, "Volume ?", h)).status_code == 200
    assert limiter.active("alice") == 0


async def test_client_disconnect_cancels_agent(ctx):
    """La fermeture du flux (déconnexion) annule la tâche de l'agent et libère le créneau."""
    from decision_api.routes.conversations import _stream_answer
    from decision_api.services import QueryLogWriter

    ctx.services.script.hang = True
    runtime = ctx.app.state.runtime
    maker = ctx.app.state.sessionmaker
    limiter = ctx.app.state.stream_limiter
    h = ctx.h("alice", DEC)
    cid = uuid.UUID(await ctx.new_conv(h))
    from decision_api.auth import User

    user = User(sub="alice", roles=frozenset(DEC))
    release = limiter.slot("alice", 2)
    gen = _stream_answer(
        runtime=runtime,
        maker=maker,
        release=release,
        user=user,
        conversation_id=cid,
        question="q",
        history=[],
        state=None,
        trace_id="t-cancel",
        writer=QueryLogWriter(maker, user_ref="r", conversation_id=cid, question_hash="h"),
        set_title=False,
    )
    first = await gen.__anext__()
    assert first.startswith(b"event: step")
    assert limiter.active("alice") == 1
    await gen.__anext__()
    await asyncio.wait_for(ctx.services.script.sleeping.wait(), 2)
    await gen.aclose()  # ce que fait Starlette à la déconnexion
    await asyncio.wait_for(ctx.services.script.cancelled.wait(), 2)
    assert limiter.active("alice") == 0


# --- Tableau de bord ------------------------------------------------------------------------


async def test_dashboard_and_analysis_reuse(ctx):
    h = ctx.h("alice", DEC)
    r = await ctx.client.get("/api/dashboard", params={"period": "2026-08", "region": "Dakar"}, headers=h)
    assert r.status_code == 200
    assert r.json()["period"]["label"] == "août 2026" and r.json()["region"] == "Dakar"
    assert isinstance(r.json()["tiles"], list)  # réponse à plat, sans double enveloppe
    assert (
        await ctx.client.get("/api/dashboard", params={"period": "2026-13"}, headers=h)
    ).status_code == 422
    assert (
        await ctx.client.get("/api/dashboard", params={"period": "2026-11"}, headers=h)
    ).status_code == 422
    assert (await ctx.client.get("/api/dashboard", params={"region": "Paris"}, headers=h)).status_code == 422
    default = (await ctx.client.get("/api/dashboard", headers=h)).json()
    assert default["period"]["start"] == "2026-09-01"

    body = {"period": "2026-08", "region": "Dakar"}
    a1 = (await ctx.client.post("/api/dashboard/analysis", json=body, headers=h)).json()
    assert a1["reused"] is False and a1["analysis"]["lead"]
    a2 = (await ctx.client.post("/api/dashboard/analysis", json=body, headers=h)).json()
    assert a2["reused"] is True and a2["id"] == a1["id"]
    # Régénération : refusée au décideur, réservée à l'analyste et à l'admin
    r = await ctx.client.post("/api/dashboard/analysis", json={**body, "regenerate": True}, headers=h)
    assert r.status_code == 403
    an = ctx.h("ana", ANA)
    ctx.app.state.settings.analysis_regenerate_min_interval_s = 0
    a3 = (
        await ctx.client.post("/api/dashboard/analysis", json={**body, "regenerate": True}, headers=an)
    ).json()
    assert a3["reused"] is False and a3["id"] != a1["id"]
    assert ctx.services.analyses == 2
    rows = await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.analysis")
    assert rows[0]["n"] == 2
    logs = await _owner_fetch(
        ctx, "SELECT trace_id FROM app.query_log WHERE conversation_id IS NULL AND tool = 'llm'"
    )
    assert len(logs) == 2
    marks = await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.query_log WHERE tool = 'analysis'")
    assert marks[0]["n"] == 2  # chaque génération est imputée au quota
    stored = await _owner_fetch(ctx, "SELECT trace_id FROM app.analysis ORDER BY ts")
    assert {x["trace_id"] for x in stored} == {x["trace_id"] for x in logs}


# --- Signalements ----------------------------------------------------------------------------


async def _answer_message_id(ctx, h) -> str:
    cid = await ctx.new_conv(h)
    await ctx.ask(cid, "Combien de transactions en août ?", h)
    conv = (await ctx.client.get(f"/api/conversations/{cid}", headers=h)).json()
    return conv["messages"][1]["id"]


async def test_feedback_owner_consent_and_admin_flow(ctx):
    a, b = ctx.h("alice", DEC), ctx.h("bob", DEC)
    mid = await _answer_message_id(ctx, a)
    # Pas le propriétaire : 404
    r = await ctx.client.post(
        "/api/feedback", json={"message_id": mid, "category": "chiffre_faux"}, headers=b
    )
    assert r.status_code == 404
    # Sans consentement : pas de texte joint
    f1 = await ctx.client.post(
        "/api/feedback", json={"message_id": mid, "category": "chiffre_faux"}, headers=a
    )
    assert f1.status_code == 201 and f1.json()["question_attached"] is False
    f2 = await ctx.client.post(
        "/api/feedback",
        json={"message_id": mid, "category": "autre", "consent_question": True, "comment": "faux"},
        headers=a,
    )
    assert f2.json()["question_attached"] is True

    an = ctx.h("ana", ANA)
    assert (await ctx.client.get("/api/admin/feedback", headers=a)).status_code == 403
    items = (await ctx.client.get("/api/admin/feedback", headers=an)).json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[f1.json()["id"]]["question_text"] is None
    assert by_id[f2.json()["id"]]["question_text"] == "Combien de transactions en août ?"

    url1 = f"/api/admin/feedback/{f1.json()['id']}"
    r = await ctx.client.patch(url1, json={"action": "rejeter"}, headers=an)
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = await ctx.client.patch(url1, json={"action": "promouvoir"}, headers=an)
    assert r.status_code == 409 and r.json()["error"]["code"] == "consent_required"
    r = await ctx.client.patch(url1, json={"action": "rejeter", "reason": "Chiffre exact"}, headers=an)
    assert r.status_code == 200 and r.json()["status"] == "rejete"
    url2 = f"/api/admin/feedback/{f2.json()['id']}"
    r = await ctx.client.patch(url2, json={"action": "promouvoir"}, headers=an)
    assert r.status_code == 200 and r.json()["promoted_to_dev"] is True and r.json()["target_split"] == "dev"
    assert (
        await ctx.client.patch(f"/api/admin/feedback/{uuid.uuid4()}", json={"action": "traiter"}, headers=an)
    ).status_code == 404


async def test_feedback_detail_rights_consent_and_audit(ctx):
    a = ctx.h("alice", DEC)
    mid = await _answer_message_id(ctx, a)
    f1 = (
        await ctx.client.post("/api/feedback", json={"message_id": mid, "category": "autre"}, headers=a)
    ).json()
    f2 = (
        await ctx.client.post(
            "/api/feedback",
            json={"message_id": mid, "category": "autre", "consent_question": True},
            headers=a,
        )
    ).json()
    an, adm = ctx.h("ana", ANA), ctx.h("root", ADM)
    # Droits : décideur 403 (même le propriétaire), analyste et admin 200
    assert (await ctx.client.get(f"/api/admin/feedback/{f1['id']}", headers=a)).status_code == 403
    r1 = await ctx.client.get(f"/api/admin/feedback/{f1['id']}", headers=an)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["question"] is None and "question_text" not in d1  # pas de consentement
    assert d1["answer"]["kind"] == "answer" and d1["answer"]["evidence"] is not None
    assert d1["answer"]["sql"] is not None  # analyste et admin voient le SQL
    assert "user_id" not in d1
    r2 = await ctx.client.get(f"/api/admin/feedback/{f2['id']}", headers=adm)
    assert r2.status_code == 200
    assert r2.json()["question"] == "Combien de transactions en août ?"
    # 404 : inconnu ou identifiant mal formé
    assert (await ctx.client.get(f"/api/admin/feedback/{uuid.uuid4()}", headers=an)).status_code == 404
    assert (await ctx.client.get("/api/admin/feedback/pas-un-uuid", headers=an)).status_code == 404
    # Audit : une ligne par lecture, identifiant du signalement, jamais de texte
    rows = await _owner_fetch(
        ctx,
        "SELECT actor_role, details FROM app.audit_access_log WHERE action = 'feedback.detail' ORDER BY id",
    )
    assert [r["actor_role"] for r in rows] == ["analyste", "admin"]
    details = [json.loads(r["details"]) for r in rows]
    assert details == [{"feedback_id": f1["id"]}, {"feedback_id": f2["id"]}]


async def test_quota_429_has_retry_after_and_retry_at(ctx, monkeypatch):
    from datetime import UTC, datetime

    sem = ctx.app.state.runtime.semantic
    monkeypatch.setitem(sem.config["quota"], "questions_per_user_per_day", 1)
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    assert (await ctx.ask(cid, "Volume ?", h)).status_code == 200
    r = await ctx.ask(cid, "Volume ?", h)
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "quota_exceeded" and "request_id" in err
    wait = int(r.headers["Retry-After"])
    assert 1 <= wait <= 86_400
    retry_at = datetime.fromisoformat(err["retry_at"].replace("Z", "+00:00"))
    assert retry_at.tzinfo is not None and (retry_at.hour, retry_at.minute, retry_at.second) == (0, 0, 0)
    assert retry_at > datetime.now(UTC)


async def test_too_many_streams_retry_after_without_retry_at(ctx):
    limiter = ctx.app.state.stream_limiter
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    limiter.acquire("alice", 10)
    limiter.acquire("alice", 10)
    r = await ctx.ask(cid, "Volume ?", h)
    assert r.status_code == 429 and r.headers["Retry-After"] == "5"
    assert "retry_at" not in r.json()["error"]


# --- Back-office ----------------------------------------------------------------------------


async def test_admin_routes_refused_to_decideur(ctx):
    h = ctx.h("alice", DEC)
    for path in (
        "/api/admin/overview",
        "/api/admin/audit/queries",
        "/api/admin/audit/queries/x",
        "/api/admin/audit/queries/export.csv",
        "/api/admin/security",
        "/api/admin/eval/runs",
        "/api/admin/eval/runs/1",
        "/api/admin/feedback",
        f"/api/admin/feedback/{uuid.uuid4()}",
        "/api/admin/kpis",
        "/api/admin/semantic/tables",
        "/api/admin/settings",
    ):
        r = await ctx.client.get(path, headers=h)
        assert r.status_code == 403, path
        assert r.json()["error"]["code"] == "forbidden"
    assert (await ctx.client.post("/api/admin/security/rights-test", headers=h)).status_code == 403
    an = ctx.h("ana", ANA)
    assert (await ctx.client.get("/api/admin/security", headers=an)).status_code == 403
    assert (await ctx.client.post("/api/admin/security/rights-test", headers=an)).status_code == 403
    rows = await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.audit_access_log")
    assert rows[0]["n"] == 0


async def test_audit_list_detail_and_access_log(ctx, sse):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    trace = (await ctx.ask(cid, "Question confidentielle sur Dakar", h)).headers["x-trace-id"]
    an = ctx.h("ana", ANA)
    lst = await ctx.client.get("/api/admin/audit/queries", headers=an)
    assert lst.status_code == 200
    body = lst.json()
    assert body["total"] == 1 and body["items"][0]["trace_id"] == trace
    assert "confidentielle" not in lst.text and body["items"][0]["question_hash"]
    assert (await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.audit_access_log"))[0]["n"] == 0

    detail = await ctx.client.get(f"/api/admin/audit/queries/{trace}", headers=an)
    assert detail.status_code == 200
    assert [s["step"] for s in detail.json()["steps"]] == [0, 1, 2, 3]
    assert detail.json()["steps"][0]["tool"] == "question"
    assert "confidentielle" not in detail.text
    logs = await _owner_fetch(ctx, "SELECT * FROM app.audit_access_log")
    assert len(logs) == 1 and logs[0]["action"] == "audit_detail" and logs[0]["target_trace_id"] == trace
    assert logs[0]["actor_sub"] == "ana" and logs[0]["actor_role"] == "analyste"
    assert (await ctx.client.get("/api/admin/audit/queries/inconnue", headers=an)).status_code == 404

    filt = await ctx.client.get("/api/admin/audit/queries", params={"status": "blocked"}, headers=an)
    assert filt.json()["total"] == 0
    csv = await ctx.client.get("/api/admin/audit/queries/export.csv", headers=an)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert len(csv.text.strip().splitlines()) == 5 and "question_hash" in csv.text.splitlines()[0]
    actions = [
        x["action"] for x in await _owner_fetch(ctx, "SELECT action FROM app.audit_access_log ORDER BY id")
    ]
    assert actions == ["audit_detail", "audit_export_csv"]


async def test_overview_metrics(ctx, sse):
    h = ctx.h("alice", DEC)
    cid = await ctx.new_conv(h)
    for _ in range(3):
        await ctx.ask(cid, "Volume ?", h)
    conn = await asyncpg.connect(ctx.pg["app"])
    try:
        await conn.execute(
            "INSERT INTO app.query_log (trace_id, step, tool, status, error_class, duration_ms) "
            "VALUES ('tb', 1, 'run_query', 'blocked', 'guard_blocked', 3)"
        )
    finally:
        await conn.close()
    r = await ctx.client.get("/api/admin/overview", params={"range": "24h"}, headers=ctx.h("adm", ADM))
    assert r.status_code == 200
    o = r.json()
    assert o["questions"] == 3 and o["traces"] == 4 and o["answers"] == 3
    assert o["latency_ms"]["p50"] is not None and o["latency_ms"]["p90"] >= o["latency_ms"]["p50"]
    assert o["cost_usd"]["total"] == pytest.approx(0.0063)
    assert o["guard"]["blocked"] == 1 and o["guard"]["block_rate"] == pytest.approx(1 / 7, abs=1e-3)
    assert o["health"]["db"] == "ok"
    assert (
        await ctx.client.get("/api/admin/overview", params={"range": "1y"}, headers=ctx.h("adm", ADM))
    ).status_code == 422


async def test_security_and_rights_test(ctx, tmp_path):
    adm = ctx.h("adm", ADM)
    r = await ctx.client.get("/api/admin/security", headers=adm)
    assert r.status_code == 200 and r.json()["rights_test"]["available"] is False
    report = tmp_path / "rights.json"
    report.write_text(json.dumps({"ok": True, "checks": [{"name": "insert_raw", "ok": True}]}))
    ctx.app.state.settings.rights_test_report = str(report)
    t = await ctx.client.post("/api/admin/security/rights-test", headers=adm)
    assert t.status_code == 200 and t.json()["available"] is True and t.json()["ok"] is True
    actions = [x["action"] for x in await _owner_fetch(ctx, "SELECT action FROM app.audit_access_log")]
    assert actions == ["rights_test_read"]


async def test_eval_runs(ctx):
    conn = await asyncpg.connect(ctx.pg["app"])  # l'évaluation écrit avec app_rw (INSERT seul)
    try:
        run_id = await conn.fetchval(
            "INSERT INTO app.eval_run (split, n, n_correct, pass1, pass3, ci_low, ci_high, model_id, report) "
            "VALUES ('test', 40, 34, 0.85, 0.8, 0.71, 0.93, 'claude-sonnet-5-5', '{}'::jsonb) RETURNING id"
        )
        await conn.execute(
            "INSERT INTO app.eval_result (run_id, question_id, category, passes, expected, got) VALUES "
            "($1, 'q1', 'kpi', 3, '{}'::jsonb, '{}'::jsonb), ($1, 'q2', 'kpi', 1, '{}'::jsonb, '{}'::jsonb)",
            run_id,
        )
    finally:
        await conn.close()
    an = ctx.h("ana", ANA)
    runs = (await ctx.client.get("/api/admin/eval/runs", headers=an)).json()["items"]
    assert len(runs) == 1 and runs[0]["n_correct"] == 34
    d = (await ctx.client.get(f"/api/admin/eval/runs/{run_id}", headers=an)).json()
    assert d["by_category"]["kpi"] == {"n": 2, "pass3": 1} and len(d["results"]) == 2
    assert (await ctx.client.get("/api/admin/eval/runs/999", headers=an)).status_code == 404


async def test_db_errors_do_not_leak(ctx, monkeypatch):
    from decision_api.routes import conversations
    from sqlalchemy.exc import ProgrammingError

    async def boom(*a, **k):
        raise ProgrammingError("SELECT secret FROM app.conversation", {}, Exception("relation app.x"))

    monkeypatch.setattr(conversations, "owned_conversation", boom)
    h = ctx.h("alice", DEC)
    r = await ctx.client.get(f"/api/conversations/{uuid.uuid4()}", headers=h)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error" and "app." not in r.text and "SELECT" not in r.text


# --- Correctifs de revue : quota, analyse, pagination, purge ----------------------------------


async def test_quota_survives_conversation_deletion(ctx, monkeypatch):
    sem = ctx.app.state.runtime.semantic
    monkeypatch.setitem(sem.config["quota"], "questions_per_user_per_day", 2)
    h = ctx.h("alice", DEC)
    for _ in range(2):
        cid = await ctx.new_conv(h)
        assert (await ctx.ask(cid, "Volume ?", h)).status_code == 200
        assert (await ctx.client.delete(f"/api/conversations/{cid}", headers=h)).status_code == 204
    # Supprimer les conversations ne rend pas de quota : le compte vit dans query_log (ajout seul).
    cid = await ctx.new_conv(h)
    r = await ctx.ask(cid, "Volume ?", h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    conv = (await ctx.client.get(f"/api/conversations/{cid}", headers=h)).json()
    assert conv["messages"] == []  # refus : aucun message user enregistré


async def test_quota_concurrent_requests_serialised(ctx, monkeypatch):
    sem = ctx.app.state.runtime.semantic
    monkeypatch.setitem(sem.config["quota"], "questions_per_user_per_day", 3)
    monkeypatch.setitem(sem.config["quota"], "concurrent_streams_per_user", 50)
    h = ctx.h("alice", DEC)
    cids = [await ctx.new_conv(h) for _ in range(10)]
    results = await asyncio.gather(*(ctx.ask(cid, "Volume ?", h) for cid in cids))
    codes = sorted(r.status_code for r in results)
    assert codes == [200] * 3 + [429] * 7  # verrou consultatif : ni dépassement ni course
    rows = await _owner_fetch(ctx, "SELECT count(*) AS n FROM app.message WHERE role = 'user'")
    assert rows[0]["n"] == 3
    assert ctx.app.state.stream_limiter.active("alice") == 0


async def test_analysis_counts_in_quota_and_uses_stream_limiter(ctx, monkeypatch):
    sem = ctx.app.state.runtime.semantic
    monkeypatch.setitem(sem.config["quota"], "questions_per_user_per_day", 1)
    h = ctx.h("alice", DEC)
    r = await ctx.client.post("/api/dashboard/analysis", json={"period": "2026-08"}, headers=h)
    assert r.status_code == 200 and r.json()["reused"] is False
    # Analyse réutilisée : gratuite.
    r = await ctx.client.post("/api/dashboard/analysis", json={"period": "2026-08"}, headers=h)
    assert r.status_code == 200 and r.json()["reused"] is True
    r = await ctx.client.post("/api/dashboard/analysis", json={"period": "2026-07"}, headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    r = await ctx.ask(await ctx.new_conv(h), "Volume ?", h)
    assert r.status_code == 429
    # Limiteur de flux : plein, la génération est refusée avant toute imputation.
    limiter = ctx.app.state.stream_limiter
    hb = ctx.h("bob", ANA)
    limiter.acquire("bob", 10)
    limiter.acquire("bob", 10)
    r = await ctx.client.post("/api/dashboard/analysis", json={"period": "2026-06"}, headers=hb)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_streams"
    limiter.release("bob")
    limiter.release("bob")


async def test_analysis_regenerate_min_interval_and_dedup(ctx):
    an = ctx.h("ana", ANA)
    body = {"period": "2026-08", "region": "Dakar"}
    a1 = (await ctx.client.post("/api/dashboard/analysis", json=body, headers=an)).json()
    # Régénération dans le délai minimal (60 s) : l'analyse existante est renvoyée, sans génération.
    a2 = (
        await ctx.client.post("/api/dashboard/analysis", json={**body, "regenerate": True}, headers=an)
    ).json()
    assert a2["reused"] is True and a2["id"] == a1["id"] and ctx.services.analyses == 1
    # Générations concurrentes pour la même clé : une seule (verrou consultatif).
    body2 = {"period": "2026-07", "region": "Dakar"}
    rs = await asyncio.gather(
        *(
            ctx.client.post("/api/dashboard/analysis", json=body2, headers=ctx.h(f"u{i}", DEC))
            for i in range(4)
        )
    )
    assert all(r.status_code == 200 for r in rs)
    assert len({r.json()["id"] for r in rs}) == 1 and ctx.services.analyses == 2


async def test_audit_pagination_stable_tiebreak(ctx):
    conn = await asyncpg.connect(ctx.pg["app"])
    try:
        await conn.executemany(
            "INSERT INTO app.query_log (ts, trace_id, step, tool, status, duration_ms) "
            "VALUES ('2026-09-01T00:00:00Z', $1, 1, 'run_query', 'ok', 1)",
            [(f"t{i:02d}",) for i in range(25)],
        )
    finally:
        await conn.close()
    an = ctx.h("ana", ANA)
    seen: list[str] = []
    for page in (1, 2, 3):
        r = await ctx.client.get(
            "/api/admin/audit/queries", params={"page": page, "page_size": 10}, headers=an
        )
        seen += [i["trace_id"] for i in r.json()["items"]]
    assert len(seen) == 25 and len(set(seen)) == 25  # ts identiques : départage par trace_id


async def test_purge_logs_owner_only(ctx, monkeypatch, capsys):
    from decision_api import cli

    conn = await asyncpg.connect(ctx.pg["app"])
    try:
        await conn.execute(
            "INSERT INTO app.query_log (ts, trace_id, step, tool, status, duration_ms) VALUES "
            "(now() - interval '91 days', 'vieux', 1, 'llm', 'ok', 1), (now(), 'recent', 1, 'llm', 'ok', 1)"
        )
    finally:
        await conn.close()
    # app_rw (rôle de l'API) : DELETE refusé.
    monkeypatch.setenv("OWNER_DATABASE_URL", ctx.pg["app"])
    assert await asyncio.to_thread(cli.main, ["purge-logs"]) == 2
    assert "app_owner" in capsys.readouterr().err
    monkeypatch.setenv("OWNER_DATABASE_URL", ctx.pg["owner"])
    assert await asyncio.to_thread(cli.main, ["purge-logs", "--days", "90"]) == 0
    assert "1 ligne" in capsys.readouterr().out
    rows = await _owner_fetch(ctx, "SELECT trace_id FROM app.query_log")
    assert [r["trace_id"] for r in rows] == ["recent"]


async def test_health_degraded_when_mcp_down(ctx):
    r = await ctx.client.get("/api/health")
    assert r.json()["status"] == "ok"
    rt = ctx.app.state.runtime
    rt.tools = None  # MCP indisponible
    r = await ctx.client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {**r.json(), "status": "degraded", "db": "ok", "mcp": "down", "agent": "down"}
