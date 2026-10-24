"""Références : contrôle statique des SQL de référence et exécution avec le rôle agent_ro.

Les valeurs attendues ne sont jamais stockées : elles sont recalculées à chaque exécution.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import sqlglot
from sqlglot import exp

from .compare import ResultSet

ALLOWED_TABLES = frozenset(
    {
        "analytics.fact_transaction",
        "analytics.dim_client",
        "analytics.dim_agent",
        "analytics.dim_region",
        "analytics.dim_date",
    }
)
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Merge,
    exp.Into,
)


class ReferenceSQLError(ValueError):
    pass


def check_reference_sql(sql: str, allowed: Iterable[str] = ALLOWED_TABLES) -> list[str]:
    """Vérifie qu'un SQL de référence est un SELECT unique sur analytics.* ; renvoie les tables."""
    allowed_set = set(allowed)
    try:
        stmts = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        raise ReferenceSQLError(f"SQL illisible : {e}") from e
    stmts = [s for s in stmts if s is not None]
    if len(stmts) != 1:
        raise ReferenceSQLError("une seule instruction attendue")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        raise ReferenceSQLError(f"SELECT attendu, obtenu {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise ReferenceSQLError(f"nœud interdit : {type(node).__name__}")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if not t.db and name in ctes:
            continue
        if not name:  # fonctions de table (generate_series…) : interdites ici
            raise ReferenceSQLError("fonction de table non autorisée")
        full = f"{t.db.lower()}.{name}" if t.db else name
        if full not in allowed_set:
            raise ReferenceSQLError(f"table non autorisée : {full} (uniquement analytics.*, qualifiée)")
        tables.add(full)
    if not tables:
        raise ReferenceSQLError("aucune table analytics")
    return sorted(tables)


class ReferenceExecutor(Protocol):
    def run(self, sql: str) -> ResultSet: ...


class PgReferenceExecutor:
    """Exécute les références en lecture seule (rôle agent_ro), sans cache."""

    def __init__(self, dsn: str, *, statement_timeout_s: int = 30) -> None:
        self.dsn = dsn
        self.timeout_ms = statement_timeout_s * 1000

    def run(self, sql: str) -> ResultSet:
        import psycopg

        check_reference_sql(sql)
        with psycopg.connect(self.dsn, autocommit=False) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {int(self.timeout_ms)}")
                cur.execute(sql)  # type: ignore[arg-type]
                cols = [d.name for d in (cur.description or [])]
                rows = [tuple(r) for r in cur.fetchall()]
            conn.rollback()
        return ResultSet(cols, rows)

    def data_hash(self) -> str | None:
        """Empreinte des données analytics (comptes, sommes, noms d'agents), tracée dans chaque run."""
        import psycopg

        try:
            with psycopg.connect(self.dsn) as conn:
                row = conn.execute(DATA_HASH_SQL).fetchone()  # type: ignore[arg-type]
                return str(row[0])[:16] if row and row[0] else None
        except psycopg.Error:
            return None


class PgSetupExecutor:
    """Injection indirecte (split security) : réécrit dim_agent.nom puis restaure. Base de TEST seulement."""

    def __init__(self, owner_dsn: str) -> None:
        self.dsn = owner_dsn

    def inject(self, target_sql: str, nom: str) -> list[tuple[int, str]]:
        import psycopg

        check_reference_sql(target_sql)
        with psycopg.connect(self.dsn) as conn, conn.transaction():
            ids = [r[0] for r in conn.execute(target_sql).fetchall()]  # type: ignore[arg-type]
            saved = [
                (int(r[0]), r[1])
                for r in conn.execute(
                    "SELECT agent_id, nom FROM analytics.dim_agent WHERE agent_id = ANY(%s)", (ids,)
                ).fetchall()
            ]
            conn.execute("UPDATE analytics.dim_agent SET nom = %s WHERE agent_id = ANY(%s)", (nom, ids))
        return saved

    def restore(self, saved: list[tuple[int, str]]) -> None:
        import psycopg

        with psycopg.connect(self.dsn) as conn, conn.transaction():
            for agent_id, nom in saved:
                conn.execute("UPDATE analytics.dim_agent SET nom = %s WHERE agent_id = %s", (nom, agent_id))


DATA_HASH_SQL = (
    "SELECT md5(string_agg(x, '|' ORDER BY x)) FROM ("
    " SELECT 'f:' || count(*) || ':' || coalesce(sum(montant_xof), 0) || ':' || coalesce(sum(frais_xof), 0)"
    "   || ':' || coalesce(max(transaction_id), 0) || ':' || coalesce(min(date_id), 0) || ':'"
    "   || coalesce(max(date_id), 0) AS x FROM analytics.fact_transaction"
    " UNION ALL SELECT 'c:' || count(*) || ':' || coalesce(sum(client_id), 0) FROM analytics.dim_client"
    " UNION ALL SELECT 'a:' || count(*) || ':'"
    "   || md5(coalesce(string_agg(coalesce(nom, '') || statut_agent, ',' ORDER BY agent_id), ''))"
    "   FROM analytics.dim_agent"
    " UNION ALL SELECT 'r:' || count(*) FROM analytics.dim_region"
    " UNION ALL SELECT 'd:' || count(*) || ':' || count(*) FILTER (WHERE jour_ferie) FROM analytics.dim_date"
    ") s"
)


class StaticReferenceExecutor:
    """Exécuteur de test : renvoie des résultats fournis par SQL (après contrôle statique)."""

    def __init__(self, results: dict[str, ResultSet], default: ResultSet | None = None) -> None:
        self.results = {" ".join(k.split()): v for k, v in results.items()}
        self.default = default
        self.calls: list[str] = []

    def run(self, sql: str) -> ResultSet:
        check_reference_sql(sql)
        self.calls.append(sql)
        key = " ".join(sql.split())
        if key in self.results:
            return self.results[key]
        if self.default is not None:
            return self.default
        raise KeyError(f"référence inconnue : {sql[:80]}")
