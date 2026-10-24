"""Ligne de commande : `python -m decision_eval <commande>`.

  run       --split test|dev|intent|followup|security --passes 3 --ablation none|a|b|c|d|e
            --max-concurrency 4 [--milestone P1] [--write-db DSN] [--baseline rapport.json]
  antileak  contrôle exemples ↔ test (et dev ↔ test) + MANIFEST
  manifest  --freeze [--force] | --verify
  refs      exécute toutes les reference_sql d'un split (contrôle des références)
  compare-runs BASE.json ABLATION.json   comparaison appariée (McNemar exact)
  bench     --base-url URL --questions-from dev [--repeat N]  (jeton dans EVAL_BENCH_TOKEN)

DSN (variables d'environnement, jamais en clair dans le code) : AGENT_RO_DSN (références, rôle agent_ro),
EVAL_SETUP_DSN (propriétaire analytics d'une base de TEST, split security), EVAL_DB_DSN (app_rw, --write-db).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .dataset import REFERENCE_DATE, eval_dir, load_dataset, split_path


def _agent_ro_dsn() -> str:
    dsn = os.environ.get("AGENT_RO_DSN")
    if not dsn:
        try:
            from decision_core.settings import get_settings

            s = get_settings().agent_ro_dsn
            dsn = s.get_secret_value() if s else None
        except Exception:  # noqa: BLE001
            dsn = None
    if not dsn:
        sys.exit("AGENT_RO_DSN manquant : les références sont recalculées avec le rôle agent_ro.")
    return dsn


def cmd_run(a: argparse.Namespace) -> int:
    from .refs import PgReferenceExecutor, PgSetupExecutor
    from .runner import EvalRunner, RunConfig

    ref_date = REFERENCE_DATE
    env_ref = os.environ.get("REFERENCE_DATE")
    if env_ref and env_ref != REFERENCE_DATE.isoformat():
        sys.exit(
            f"REFERENCE_DATE={env_ref} ≠ {REFERENCE_DATE} : "
            "l'agent et les références doivent partager la date."
        )
    write_db = a.write_db or (os.environ.get("EVAL_DB_DSN") if a.write_db_env else None)
    cfg = RunConfig(
        split=a.split,
        passes=a.passes,
        ablation=a.ablation,
        max_concurrency=a.max_concurrency,
        milestone=a.milestone,
        reference_date=ref_date,
        write_db=write_db,
        baseline=Path(a.baseline) if a.baseline else None,
        allow_small_scale=a.allow_small_scale,
    )
    setup = os.environ.get("EVAL_SETUP_DSN")
    meta_dsn = os.environ.get("EVAL_META_DSN") or setup
    runner = EvalRunner(
        cfg,
        executor=PgReferenceExecutor(_agent_ro_dsn(), meta_dsn=meta_dsn),
        setup_executor=PgSetupExecutor(setup) if setup else None,
    )
    report = asyncio.run(runner.run())
    print(report["score"]["honest_sentence"])
    for f in report.get("files", []):
        print(f"rapport : {f}")
    return 0


def cmd_antileak(a: argparse.Namespace) -> int:
    from .antileak import ManifestError, run_antileak, verify_manifest

    rep = run_antileak()
    print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
    try:
        print(f"MANIFEST : test.yaml {verify_manifest()[:16]}… conforme")
        manifest_ok = True
    except ManifestError as e:
        print(f"MANIFEST : {e}")
        manifest_ok = False
    return 0 if rep.ok and manifest_ok else 1


def cmd_manifest(a: argparse.Namespace) -> int:
    from .antileak import freeze_manifest, verify_manifest

    if a.freeze:
        print(freeze_manifest(force=a.force))
    else:
        print(verify_manifest())
    return 0


def cmd_refs(a: argparse.Namespace) -> int:
    from .refs import PgReferenceExecutor

    ex = PgReferenceExecutor(_agent_ro_dsn())
    ds = load_dataset(split_path(a.split))
    bad = 0
    for it in ds.items:
        sqls = [it.reference_sql] if it.reference_sql else []
        sqls += [t.answer.reference_sql for t in it.turns or [] if t.answer and t.answer.reference_sql]
        for s in sqls:
            try:
                r = ex.run(s)
                flag = " (vide attendu)" if it.expected_empty else ""
                if it.expected_empty and r.rows:
                    flag, bad = " ERREUR : vide attendu mais lignes renvoyées", bad + 1
                print(f"{it.id:6} ok  {len(r.rows):4} lignes{flag}")
            except Exception as e:  # noqa: BLE001
                bad += 1
                print(f"{it.id:6} ERREUR {type(e).__name__}: {e}")
    return 1 if bad else 0


def cmd_compare_runs(a: argparse.Namespace) -> int:
    from .runner import compare_reports

    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    arm = json.loads(Path(a.arm).read_text(encoding="utf-8"))
    print(json.dumps(compare_reports(base, arm), indent=2, ensure_ascii=False))
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from .bench import run_bench

    token = os.environ.get("EVAL_BENCH_TOKEN")
    if not token:
        sys.exit("EVAL_BENCH_TOKEN manquant (jeton Keycloak d'un compte technique).")
    if a.questions_file:
        questions = [
            q.strip() for q in Path(a.questions_file).read_text(encoding="utf-8").splitlines() if q.strip()
        ]
    else:
        ds = load_dataset(split_path(a.questions_from))
        questions = [it.question for it in ds.items if it.question and it.expected_kind == "answer"]
    rep = asyncio.run(
        run_bench(
            a.base_url,
            token,
            questions,
            conversation_id=a.conversation_id,
            concurrency=a.concurrency,
            repeat=a.repeat,
            timeout_s=a.timeout,
        )
    )
    out = {"summary": rep.summary(), "observations": [o.__dict__ for o in rep.observations]}
    path = eval_dir() / "reports" / "bench_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="decision_eval", description="Évaluation de l'agent (SRS §11).")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="exécute un split")
    r.add_argument("--split", choices=["test", "dev", "intent", "followup", "security"], default="dev")
    r.add_argument("--passes", type=int, default=3)
    r.add_argument("--ablation", choices=["none", "a", "b", "c", "d", "e"], default="none")
    r.add_argument("--max-concurrency", type=int, default=4)
    r.add_argument("--milestone", default=os.environ.get("EVAL_MILESTONE", "P1"))
    r.add_argument("--write-db", default=None, metavar="DSN", help="DSN app_rw (préférer --write-db-env)")
    r.add_argument("--write-db-env", action="store_true", help="lit le DSN dans EVAL_DB_DSN")
    r.add_argument("--baseline", default=None, help="rapport JSON du bras de base (ablations)")
    r.add_argument(
        "--allow-small-scale",
        action="store_true",
        help="autorise le split test sous SCALE=1.0 ou avec des références dégénérées (marqué)",
    )
    r.set_defaults(func=cmd_run)
    al = sub.add_parser("antileak")
    al.set_defaults(func=cmd_antileak)
    m = sub.add_parser("manifest")
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--verify", action="store_true")
    m.add_argument("--force", action="store_true")
    m.set_defaults(func=cmd_manifest)
    rf = sub.add_parser("refs")
    rf.add_argument("--split", default="test")
    rf.set_defaults(func=cmd_refs)
    c = sub.add_parser("compare-runs")
    c.add_argument("base")
    c.add_argument("arm")
    c.set_defaults(func=cmd_compare_runs)
    b = sub.add_parser("bench")
    b.add_argument("--base-url", required=True)
    b.add_argument("--questions-from", default="dev")
    b.add_argument("--questions-file", default=None)
    b.add_argument("--conversation-id", default=None)
    b.add_argument("--concurrency", type=int, default=1)
    b.add_argument("--repeat", type=int, default=1)
    b.add_argument("--timeout", type=float, default=60.0)
    b.set_defaults(func=cmd_bench)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
