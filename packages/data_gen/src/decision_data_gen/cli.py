"""CLI : python -m decision_data_gen --scale 1.0 --seed 42 --dsn postgresql://dbt_owner@…/warehouse"""

from __future__ import annotations

import argparse
import os
import sys
import time

from .generate import generate
from .serialize import data_hash


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decision_data_gen", description=__doc__)
    p.add_argument("--scale", type=float, default=1.0, help="1.0 = 50 000 clients, ~2,2 M transactions")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--dsn",
        default=os.environ.get("DBT_OWNER_DSN"),
        help="DSN du rôle dbt_owner (défaut : variable DBT_OWNER_DSN)",
    )
    p.add_argument("--dry-run", action="store_true", help="génère et imprime data_hash sans charger")
    args = p.parse_args(argv)

    t0 = time.perf_counter()
    ds = generate(scale=args.scale, seed=args.seed)
    t_gen = time.perf_counter() - t0
    print(
        f"généré en {t_gen:.1f} s : {len(ds.client_id)} clients, {len(ds.agent_id)} agents, "
        f"{len(ds.txn_id)} transactions (scale={args.scale}, seed={args.seed})",
        flush=True,
    )
    if args.dry_run:
        print(f"data_hash={data_hash(ds)}")
        return 0
    if not args.dsn:
        print("erreur : --dsn ou DBT_OWNER_DSN requis (ou --dry-run)", file=sys.stderr)
        return 2
    from .load import load

    res = load(ds, args.dsn)
    print(f"chargé en {res['seconds']:.1f} s (total {time.perf_counter() - t0:.1f} s)")
    print(f"data_hash={res['data_hash']}")
    return 0
