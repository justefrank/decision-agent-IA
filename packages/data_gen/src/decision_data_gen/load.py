"""Chargement dans le schéma `raw` par COPY (rôle dbt_owner), en une seule transaction."""

from __future__ import annotations

import hashlib
import time

import psycopg

from . import reference as ref
from .generate import Dataset
from .serialize import iter_tables

GENERATOR_VERSION = "1"
PRIMARY_KEYS = {
    "raw_clients": "client_id",
    "raw_agents": "agent_id",
    "raw_transactions": "transaction_id",
}


def load(ds: Dataset, dsn: str, *, verbose: bool = True) -> dict[str, object]:
    """Recrée les tables raw, les remplit par COPY et renvoie {data_hash, comptes, durée}."""
    t0 = time.perf_counter()
    h = hashlib.sha256()
    counts: dict[str, int] = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = raw")
            for name, cols, ddl, chunks in iter_tables(ds):
                cur.execute(f"DROP TABLE IF EXISTS raw.{name}")
                cur.execute(f"CREATE TABLE raw.{name} ({ddl})")
                h.update(f"#{name}\n".encode())
                n = 0
                with cur.copy(f"COPY raw.{name} ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
                    for chunk in chunks:
                        h.update(chunk.encode())
                        n += chunk.count("\n")
                        copy.write(chunk)
                if name in PRIMARY_KEYS:
                    cur.execute(f"ALTER TABLE raw.{name} ADD PRIMARY KEY ({PRIMARY_KEYS[name]})")
                counts[name] = n
                if verbose:
                    print(f"  raw.{name:<17} {n:>10,} lignes".replace(",", " "), flush=True)
            digest = h.hexdigest()
            cur.execute("DROP TABLE IF EXISTS raw.raw_meta")
            cur.execute("CREATE TABLE raw.raw_meta (cle text PRIMARY KEY, valeur text NOT NULL)")
            meta = {
                "data_hash": digest,
                "seed": str(ds.seed),
                "scale": repr(ds.scale),
                "start_date": ref.START_DATE.isoformat(),
                "reference_date": ref.REFERENCE_DATE.isoformat(),
                "generator_version": GENERATOR_VERSION,
            }
            cur.executemany("INSERT INTO raw.raw_meta VALUES (%s, %s)", list(meta.items()))
        conn.commit()
        conn.autocommit = True
        conn.execute("ANALYZE raw.raw_transactions")
    return {"data_hash": digest, "counts": counts, "seconds": time.perf_counter() - t0}
