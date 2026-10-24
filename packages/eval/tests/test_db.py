"""Tests sur Postgres (marqueur `db`) : références exécutées avec agent_ro sur la fixture analytics,
chaîne complète avec l'agent oracle, injection indirecte, écriture eval_run/eval_result.

Lancer : scripts/dev_pg.sh start 55450 puis
  TEST_PG_DSN=postgresql://postgres@localhost:55450/warehouse uv run pytest packages/eval -m db
"""

from __future__ import annotations

import os
import shutil
from urllib.parse import urlsplit

import pytest
from decision_eval.dataset import eval_dir, load_dataset
from decision_eval.fakes import OracleAgent, oracle_factory
from decision_eval.fixture import fixture_present, load_fixture
from decision_eval.refs import PgReferenceExecutor, PgSetupExecutor
from decision_eval.runner import EvalRunner, QuotaGuard, RunConfig

pytestmark = pytest.mark.db

TEST_PG_DSN = os.environ.get("TEST_PG_DSN")
if not TEST_PG_DSN:
    pytest.skip("TEST_PG_DSN absent", allow_module_level=True)


def role_dsn(role: str) -> str:
    u = urlsplit(TEST_PG_DSN)
    return f"postgresql://{role}:{role}@{u.hostname}:{u.port or 5432}/warehouse"


@pytest.fixture(scope="module")
def agent_ro():
    if not fixture_present(role_dsn("dbt_owner")):
        load_fixture(role_dsn("dbt_owner"))
    return PgReferenceExecutor(role_dsn("agent_ro"))


SPLITS = ["test", "dev", "followup", "security"]


@pytest.mark.parametrize("split", SPLITS)
def test_all_reference_sql_execute_as_agent_ro(agent_ro, split):
    ds = load_dataset(eval_dir() / f"{split}.yaml")
    for it in ds.items:
        sqls = [it.reference_sql] if it.reference_sql else []
        sqls += [t.answer.reference_sql for t in it.turns or [] if t.answer and t.answer.reference_sql]
        if it.inject:
            sqls.append(it.inject.target_sql)
        for s in sqls:
            r = agent_ro.run(s)
            if it.expected_empty and s == it.reference_sql:
                assert r.rows == [], it.id
            else:
                assert r.rows, f"{it.id} : référence vide sur la fixture"


def test_agent_ro_cannot_write(agent_ro):
    import psycopg

    with psycopg.connect(role_dsn("agent_ro")) as conn, pytest.raises(psycopg.Error):
        conn.execute("DELETE FROM analytics.fact_transaction WHERE transaction_id = 1")


def copy_eval(tmp_path, *names):
    d = tmp_path / "eval"
    d.mkdir()
    for n in names:
        shutil.copy(eval_dir() / n, d / n)
    return d


@pytest.mark.parametrize("split", ["test", "dev", "followup"])
async def test_oracle_agent_scores_100(agent_ro, tmp_path, split):
    """Un agent qui renvoie exactement la référence doit tout réussir : valide le correcteur sur les
    formes réelles (Decimal, dates, ex æquo, résultat vide)."""
    files = [f"{split}.yaml"] + (["MANIFEST"] if split == "test" else [])
    d = copy_eval(tmp_path, *files)
    ds = load_dataset(d / f"{split}.yaml")
    runner = EvalRunner(
        # base de développement (fixture ou SCALE réduite) : le garde-fou d'échelle est levé
        RunConfig(split=split, passes=1, eval_dir=d, allow_small_scale=True),
        executor=agent_ro,
        agent_factory=oracle_factory(OracleAgent(ds, agent_ro)),
    )
    rep = await runner.run()
    assert rep["score"]["pass3"]["k"] == rep["n"], rep.get("details") or rep["failures_by_category"]
    assert rep["trace"]["data_hash"]
    assert not rep["reference_errors"]


async def test_security_injection_roundtrip(agent_ro, tmp_path):
    d = copy_eval(tmp_path, "security.yaml")
    ds = load_dataset(d / "security.yaml")
    before = agent_ro.data_hash()
    seen_names: list[str] = []

    def spy(item, msg):
        seen_names.extend(str(r[1]) for r in msg.table.rows)
        return msg

    runner = EvalRunner(
        RunConfig(split="security", passes=1, eval_dir=d),
        executor=agent_ro,
        agent_factory=oracle_factory(OracleAgent(ds, agent_ro, corrupt=spy)),
        setup_executor=PgSetupExecutor(role_dsn("dbt_owner")),
    )
    rep = await runner.run()
    assert rep["score"]["pass3"]["k"] == 5, rep.get("details")
    assert any("PWNED-" in n for n in seen_names)  # l'injection était bien présente pendant le scénario
    assert agent_ro.data_hash() == before  # noms restaurés


APP_DDL = """
CREATE TABLE IF NOT EXISTS app.eval_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
    split text NOT NULL CHECK (split IN ('dev', 'test')), prompt_version text, semantic_version text,
    model_id text, git_sha text, data_hash text, reference_date date, n integer NOT NULL,
    n_correct integer NOT NULL, ci_low double precision, ci_high double precision,
    cache_off boolean NOT NULL DEFAULT false, pass3 double precision, pass1 double precision,
    ablation text, report jsonb);
CREATE TABLE IF NOT EXISTS app.eval_result (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES app.eval_run (id) ON DELETE CASCADE, question_id text NOT NULL,
    category text, trap text, passes integer NOT NULL CHECK (passes BETWEEN 0 AND 3),
    expected jsonb, got jsonb);
GRANT SELECT, INSERT ON app.eval_run, app.eval_result TO app_rw;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO app_rw;
"""


async def test_write_db_and_quota_counter(agent_ro, tmp_path):
    import psycopg

    with psycopg.connect(role_dsn("app_owner"), autocommit=True) as conn:
        conn.execute(APP_DDL)
        conn.execute("DELETE FROM app.eval_run WHERE report->>'milestone' = 'TEST-DB'")
    d = copy_eval(tmp_path, "test.yaml", "MANIFEST")
    ds = load_dataset(d / "test.yaml")
    cfg = RunConfig(
        split="test",
        passes=1,
        eval_dir=d,
        milestone="TEST-DB",
        write_db=role_dsn("app_rw"),
        allow_small_scale=True,
    )
    runner = EvalRunner(cfg, executor=agent_ro, agent_factory=oracle_factory(OracleAgent(ds, agent_ro)))
    rep = await runner.run()
    assert rep["db_run_id"]
    with psycopg.connect(role_dsn("app_rw")) as conn:
        run = conn.execute(
            "SELECT split, n, n_correct, pass3, reference_date::text, cache_off "
            "FROM app.eval_run WHERE id = %s",
            (rep["db_run_id"],),
        ).fetchone()
        assert run == ("test", 40, 40, 1.0, "2026-09-30", True)
        n = conn.execute(
            "SELECT count(*) FROM app.eval_result WHERE run_id = %s", (rep["db_run_id"],)
        ).fetchone()
        assert n == (40,)
    # le compteur lit app.eval_run (le fichier local d'un autre poste n'y figure pas)
    (d / "reports" / "runs.json").unlink()
    assert QuotaGuard(d / "reports", role_dsn("app_rw")).count("TEST-DB", "none") == 1
