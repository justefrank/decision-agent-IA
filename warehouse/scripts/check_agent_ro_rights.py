"""Test de droits du rôle agent_ro (SYSTEM_DESIGN §3, S9).

Usage : uv run python warehouse/scripts/check_agent_ro_rights.py --dsn postgresql://agent_ro:…/warehouse
(défaut : variable AGENT_RO_DSN). Code de sortie 0 si tout est conforme, 1 sinon.

Attendu : SELECT sur les 5 tables analytics ; échec de toute écriture (même en forçant une
transaction READ WRITE), de DROP/CREATE, de SELECT sur raw et app, de pg_read_file, pg_ls_dir,
COPY … PROGRAM, lo_import, CREATE EXTENSION, SET ROLE. Lancé avant et après un second
`dbt run` (make rights-test) pour vérifier que les droits survivent à la recréation des tables.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import errors

TABLES = ("fact_transaction", "dim_client", "dim_agent", "dim_region", "dim_date")

# (libellé, SQL, forcer READ WRITE) : chaque instruction doit échouer.
MUST_FAIL: tuple[tuple[str, str, bool], ...] = (
    ("INSERT (transaction lecture seule)", "INSERT INTO analytics.dim_region VALUES (99, 'x', 'y')", False),
    ("INSERT (READ WRITE forcé)", "INSERT INTO analytics.dim_region VALUES (99, 'x', 'y')", True),
    ("UPDATE", "UPDATE analytics.fact_transaction SET frais_xof = 0", True),
    ("DELETE", "DELETE FROM analytics.fact_transaction", True),
    ("TRUNCATE", "TRUNCATE analytics.dim_date", True),
    ("DROP TABLE", "DROP TABLE analytics.dim_date", True),
    ("CREATE TABLE analytics", "CREATE TABLE analytics.pirate (x int)", True),
    ("CREATE TEMP TABLE", "CREATE TEMP TABLE pirate (x int)", True),
    ("CREATE SCHEMA", "CREATE SCHEMA pirate", True),
    ("SELECT raw", "SELECT count(*) FROM raw.raw_transactions", False),
    ("SELECT raw.raw_meta", "SELECT * FROM raw.raw_meta", False),
    ("SELECT app", "SELECT * FROM app.query_log LIMIT 1", False),
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd')", False),
    ("pg_ls_dir", "SELECT pg_ls_dir('.')", False),
    ("COPY TO PROGRAM", "COPY analytics.dim_region TO PROGRAM 'id'", True),
    ("COPY TO fichier", "COPY analytics.dim_region TO '/tmp/pirate.csv'", True),
    ("lo_import", "SELECT lo_import('/etc/passwd')", True),
    ("CREATE EXTENSION dblink", "CREATE EXTENSION dblink", True),
    ("SET ROLE dbt_owner", "SET ROLE dbt_owner", False),
)

SETTINGS = {
    "default_transaction_read_only": "on",
    "statement_timeout": "10s",
    "search_path": "analytics",
}


def run(dsn: str, *, phase: str = "", report: str | None = None, merge: bool = False) -> int:
    failures: list[str] = []
    checks: list[dict[str, object]] = []

    def ok(label: str) -> None:
        print(f"  OK    {label}")
        checks.append({"phase": phase, "label": label, "ok": True})

    def ko(label: str, detail: str) -> None:
        print(f"  ÉCHEC {label} : {detail}")
        failures.append(label)
        checks.append({"phase": phase, "label": label, "ok": False, "detail": detail})

    def check(cond: bool, label: str, detail: str) -> None:
        if cond:
            ok(label)
        else:
            ko(label, detail)

    with psycopg.connect(dsn, autocommit=True) as conn:
        user = conn.execute("SELECT current_user").fetchone()[0]  # type: ignore[index]
        print(f"Connecté en tant que {user}")
        if user != "agent_ro":
            ko("rôle", f"attendu agent_ro, obtenu {user}")

        print("Lectures autorisées :")
        for t in TABLES:
            try:
                n = conn.execute(f"SELECT count(*) FROM analytics.{t}").fetchone()[0]  # type: ignore[index]
                ok(f"SELECT analytics.{t} ({n} lignes)")
            except psycopg.Error as e:
                ko(f"SELECT analytics.{t}", e.diag.message_primary or str(e))

        print("Paramètres du rôle :")
        for name, expected in SETTINGS.items():
            got = conn.execute(f"SHOW {name}").fetchone()[0]  # type: ignore[index]
            check(got == expected, f"{name} = {expected}", f"obtenu {got!r}")

        print("Opérations interdites :")
        for label, sql, read_write in MUST_FAIL:
            try:
                with conn.transaction():
                    if read_write:
                        conn.execute("SET TRANSACTION READ WRITE")
                    conn.execute(sql)
                ko(label, "l'instruction a réussi")
            except (errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction) as e:
                ok(f"{label} → {e.sqlstate} {type(e).__name__}")
            except psycopg.Error as e:
                # Seule l'extension peut échouer pour une autre raison (paquet absent) ;
                # toute autre erreur (syntaxe, objet inexistant) ne prouve rien sur les droits.
                if label.startswith("CREATE EXTENSION"):
                    ok(f"{label} → {e.sqlstate} {type(e).__name__}")
                else:
                    ko(label, f"erreur inattendue {e.sqlstate} {e.diag.message_primary}")

        # GRANT sur une table d'autrui n'échoue pas : Postgres avertit « no privileges were
        # granted ». On vérifie donc que rien n'a été accordé.
        with conn.transaction(force_rollback=True):
            conn.execute("SET TRANSACTION READ WRITE")
            conn.execute("GRANT SELECT ON analytics.dim_region TO PUBLIC")
            leaked = conn.execute(
                "SELECT has_table_privilege('public', 'analytics.dim_region', 'SELECT')"
            ).fetchone()[0]  # type: ignore[index]
        check(not leaked, "GRANT à PUBLIC sans effet", "PUBLIC a reçu SELECT")

        print("Privilèges déclarés :")
        declared = {
            "USAGE raw": "has_schema_privilege('raw', 'USAGE')",
            "USAGE app": "has_schema_privilege('app', 'USAGE')",
            "CREATE analytics": "has_schema_privilege('analytics', 'CREATE')",
            "CREATE public": "has_schema_privilege('public', 'CREATE')",
            "TEMP warehouse": "has_database_privilege(current_database(), 'TEMP')",
        }
        for label, expr in declared.items():
            if conn.execute(f"SELECT {expr}").fetchone()[0]:  # type: ignore[index]
                ko(label, "privilège présent")
            else:
                ok(f"pas de {label}")
        ext = conn.execute(
            "SELECT string_agg(extname, ',') FROM pg_extension "
            "WHERE extname IN ('dblink', 'file_fdw', 'adminpack', 'postgres_fdw')"
        ).fetchone()[0]  # type: ignore[index]
        check(not ext, "aucune extension dblink/file_fdw/adminpack", str(ext))

    print(f"\n{'CONFORME' if not failures else 'NON CONFORME'} ({len(failures)} écart(s))")
    if report:
        write_report(Path(report), checks, merge=merge)
    return 0 if not failures else 1


def write_report(path: Path, checks: list[dict[str, object]], *, merge: bool) -> None:
    """Rapport JSON lu par le back-office (GET /api/admin/security, RIGHTS_TEST_REPORT)."""
    previous: list[dict[str, object]] = []
    if merge and path.is_file():
        try:
            previous = list(json.loads(path.read_text(encoding="utf-8")).get("checks", []))
        except (OSError, ValueError):
            previous = []
    all_checks = previous + checks
    data = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "role": "agent_ro",
        "ok": all(bool(c.get("ok")) for c in all_checks),
        "failed": sum(1 for c in all_checks if not c.get("ok")),
        "phases": sorted({str(c.get("phase", "")) for c in all_checks}),
        "checks": all_checks,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rapport écrit : {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dsn", default=os.environ.get("AGENT_RO_DSN"))
    p.add_argument("--phase", default="", help="libellé de la passe (p. ex. avant / apres_dbt_run)")
    p.add_argument("--report", help="écrit un rapport JSON (défaut : aucun)")
    p.add_argument("--merge", action="store_true", help="ajoute les contrôles au rapport existant")
    args = p.parse_args(argv)
    if not args.dsn:
        print("erreur : --dsn ou AGENT_RO_DSN requis", file=sys.stderr)
        return 2
    return run(args.dsn, phase=args.phase, report=args.report, merge=args.merge)


if __name__ == "__main__":
    sys.exit(main())
