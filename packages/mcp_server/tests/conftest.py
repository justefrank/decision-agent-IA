"""Fixtures : Postgres jetable (port 55420 par défaut) et jeu analytics de fixture."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mcp_fixture_data import Fixture, build_fixture, load_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PORT = int(os.environ.get("MCP_TEST_PG_PORT", "55420"))


def _dsn(role: str) -> str:
    base = os.environ.get("TEST_PG_HOST", "localhost")
    return f"postgresql://{role}:{role}@{base}:{PORT}/warehouse"


def _reachable() -> bool:
    import psycopg

    try:
        with psycopg.connect(_dsn("postgres"), connect_timeout=2):
            return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def pg_server() -> Iterator[int]:
    started = False
    if not _reachable():
        script = ROOT / "scripts" / "dev_pg.sh"
        if not script.exists() or not (
            shutil.which("pg_ctl") or list(Path("/usr/lib/postgresql").glob("*/bin"))
        ):
            pytest.skip("Postgres indisponible (binaires absents)")
        subprocess.run([str(script), "start", str(PORT)], check=True, capture_output=True)  # noqa: S603
        started = True
        if not _reachable():
            pytest.skip("Postgres indisponible")
    yield PORT
    if started and not os.environ.get("MCP_TEST_PG_KEEP"):
        pgdir = f"/tmp/decision-pg/{PORT}"  # noqa: S108 - dossier par défaut de dev_pg.sh
        subprocess.run(  # noqa: S603
            [str(ROOT / "scripts" / "dev_pg.sh"), "stop", pgdir],
            check=False,
            capture_output=True,
        )


@pytest.fixture(scope="session")
def fixture_data(pg_server: int) -> Fixture:
    import psycopg

    fx = build_fixture()
    with psycopg.connect(_dsn("dbt_owner")) as conn:
        load_fixture(conn, fx)
    return fx


@pytest.fixture(scope="session")
def agent_ro_dsn(fixture_data: Fixture) -> str:
    return _dsn("agent_ro")
