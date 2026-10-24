"""Chargement réel par COPY (opt-in) : DATA_GEN_TEST_DSN=postgresql://dbt_owner:…/warehouse.

Attention : le test RECRÉE les tables raw de la base visée (échelle 0.01).
"""

from __future__ import annotations

import os

import pytest
from decision_data_gen import data_hash, generate

DSN = os.environ.get("DATA_GEN_TEST_DSN")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="DATA_GEN_TEST_DSN absent")]


def test_load_copy_et_hash():
    import psycopg
    from decision_data_gen.load import load

    ds = generate(0.01, 42)
    res = load(ds, DSN, verbose=False)  # type: ignore[arg-type]
    assert res["data_hash"] == data_hash(ds)
    with psycopg.connect(DSN) as conn:  # type: ignore[arg-type]
        n, hors_agent, montant = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE agent_id IS NULL), sum(montant) "
            "FROM raw.raw_transactions"
        ).fetchone()  # type: ignore[misc]
        meta = dict(conn.execute("SELECT cle, valeur FROM raw.raw_meta").fetchall())
    assert n == len(ds.txn_id)
    assert hors_agent == int((ds.txn_agent < 0).sum())
    assert int(montant) == int(ds.txn_montant.sum())
    assert meta["data_hash"] == res["data_hash"]
    assert meta["reference_date"] == "2026-09-30"
