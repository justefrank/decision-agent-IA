"""Sérialisation CSV (format COPY de Postgres) et empreinte `data_hash`.

Le `data_hash` est le SHA-256 des octets exacts envoyés à `COPY`, table par table, dans
l'ordre de `TABLES` : deux chargements de même empreinte ont un contenu identique.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import timedelta

import numpy as np

from . import reference as ref
from .generate import EPOCH, Dataset

CHUNK = 200_000


def _iso_days(values: np.ndarray) -> list[str]:
    cache: dict[int, str] = {}
    out = []
    for v in values.tolist():
        s = cache.get(v)
        if s is None:
            s = cache[v] = (EPOCH + timedelta(days=v)).isoformat()
        out.append(s)
    return out


def _csv_text(value: str) -> str:
    if any(c in value for c in ',"\n\r') or value != value.strip() or value == "":
        return '"' + value.replace('"', '""') + '"'
    return value


def regions_rows(_ds: Dataset) -> Iterator[str]:
    yield "".join(f"{r.region_id},{_csv_text(r.nom)},{_csv_text(ref.PAYS)}\n" for r in ref.REGIONS)


def holidays_rows(_ds: Dataset) -> Iterator[str]:
    yield "".join(
        f"{d.isoformat()},{_csv_text(nom)},{cat}\n" for d, nom, cat in ref.JOURS_FERIES
    )


def clients_rows(ds: Dataset) -> Iterator[str]:
    insc = _iso_days(ds.client_inscription)
    seg = [ref.SEGMENTS[i] for i in ds.client_segment.tolist()]
    yield "".join(
        f"{cid},{d},{r},{s}\n"
        for cid, d, r, s in zip(ds.client_id.tolist(), insc, ds.client_region.tolist(), seg, strict=True)
    )


def agents_rows(ds: Dataset) -> Iterator[str]:
    act = _iso_days(ds.agent_activation)
    ferm = [
        "" if f < 0 else (EPOCH + timedelta(days=f)).isoformat() for f in ds.agent_fermeture.tolist()
    ]
    yield "".join(
        f"{aid},{_csv_text(nom)},{_csv_text(ville)},{r},{a},{'ferme' if f else 'ouvert'},{f}\n"
        for aid, nom, ville, r, a, f in zip(
            ds.agent_id.tolist(), ds.agent_nom, ds.agent_ville, ds.agent_region.tolist(), act, ferm,
            strict=True,
        )
    )


def transactions_rows(ds: Dataset) -> Iterator[str]:
    types = ref.TYPES
    n = len(ds.txn_id)
    day_str: dict[int, str] = {}
    for lo in range(0, n, CHUNK):
        hi = min(lo + CHUNK, n)
        sec = ds.txn_seconds[lo:hi]
        day = (sec // 86_400).tolist()
        tod = (sec % 86_400).tolist()
        parts = []
        for tid, cid, aid, d, t, ty, m, f, e in zip(
            ds.txn_id[lo:hi].tolist(),
            ds.txn_client[lo:hi].tolist(),
            ds.txn_agent[lo:hi].tolist(),
            day,
            tod,
            ds.txn_type[lo:hi].tolist(),
            ds.txn_montant[lo:hi].tolist(),
            ds.txn_frais[lo:hi].tolist(),
            ds.txn_echec[lo:hi].tolist(),
            strict=True,
        ):
            ds_ = day_str.get(d)
            if ds_ is None:
                ds_ = day_str[d] = (EPOCH + timedelta(days=d)).isoformat()
            parts.append(
                f"{tid},{cid},{'' if aid < 0 else aid},"
                f"{ds_} {t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}+00,"
                f"{types[ty]},{m},{f},{'echouee' if e else 'reussie'}\n"
            )
        yield "".join(parts)


# (table, colonnes, DDL, producteur de lignes CSV)
TABLES: tuple[tuple[str, str, str, object], ...] = (
    (
        "raw_regions",
        "region_id, region, pays",
        "region_id integer PRIMARY KEY, region text NOT NULL, pays text NOT NULL",
        regions_rows,
    ),
    (
        "raw_holidays",
        "date, nom, categorie",
        "date date PRIMARY KEY, nom text NOT NULL, categorie text NOT NULL",
        holidays_rows,
    ),
    (
        "raw_clients",
        "client_id, date_inscription, region_id, segment",
        "client_id integer, date_inscription date, region_id integer, segment text",
        clients_rows,
    ),
    (
        "raw_agents",
        "agent_id, nom, ville, region_id, date_activation, statut, date_fermeture",
        "agent_id integer, nom text, ville text, region_id integer, date_activation date, "
        "statut text, date_fermeture date",
        agents_rows,
    ),
    (
        "raw_transactions",
        "transaction_id, client_id, agent_id, txn_ts, type, montant, frais, statut",
        "transaction_id bigint, client_id integer, agent_id integer, txn_ts timestamptz, "
        "type text, montant numeric(14,0), frais numeric(12,0), statut text",
        transactions_rows,
    ),
)


def iter_tables(ds: Dataset) -> Iterator[tuple[str, str, str, Iterator[str]]]:
    for name, cols, ddl, producer in TABLES:
        yield name, cols, ddl, producer(ds)  # type: ignore[operator]


def data_hash(ds: Dataset) -> str:
    """Empreinte calculée sans base de données (même valeur que celle du chargement)."""
    h = hashlib.sha256()
    for name, _cols, _ddl, chunks in iter_tables(ds):
        h.update(f"#{name}\n".encode())
        for chunk in chunks:
            h.update(chunk.encode())
    return h.hexdigest()
