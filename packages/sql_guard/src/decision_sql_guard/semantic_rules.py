"""Extraction de portée et règles de cohérence sémantique (revue agentic §3.6).

- `extract_scope` : bornes de période (date_id, txn_ts, dim_date.*), colonnes de région jointes,
  prédicat sur `statut`, usage de `statut_agent`. Sert à l'état résolu de `run_query`.
- `semantic_issues` : avertissements (renvoyés au modèle) et contradictions avec `declared_scope`
  (bloquantes : erreur `semantic_warning`).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from decision_core.semantic import SemanticLayer
from sqlglot import exp

FACT = "fact_transaction"
DATE_TABLE = "dim_date"
REGION_COLUMNS = {"region_agent_id": "region_agent", "region_client_id": "region_client"}
_AGGREGATES = (exp.Count, exp.Sum, exp.Avg)


@dataclass(frozen=True)
class SemanticIssue:
    code: str
    message: str
    blocking: bool = False  # True : contradiction entre declared_scope et l'AST


# --- Résolution des colonnes ---------------------------------------------------------------------


def _alias_map(root: exp.Expression) -> dict[str, str]:
    """alias (ou nom) → nom de table analytics, sur tout l'arbre."""
    mapping: dict[str, str] = {}
    for table in root.find_all(exp.Table):
        name = table.name.lower()
        mapping.setdefault(name, name)
        alias = table.alias
        if alias:
            mapping[alias.lower()] = name
    return mapping


def _column_table(col: exp.Column, aliases: dict[str, str], semantic: SemanticLayer | None) -> str | None:
    if col.table:
        return aliases.get(col.table.lower())
    if semantic is None:
        return None
    owners = [
        t for t, spec in semantic.tables["tables"].items() if col.name.lower() in (spec.get("columns") or {})
    ]
    return owners[0] if len(owners) == 1 else (FACT if FACT in owners else None)


def _literal_value(node: exp.Expression) -> Any:
    """Valeur d'un littéral (éventuellement casté) ; None sinon."""
    while isinstance(node, exp.Cast | exp.Paren):
        node = node.this
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        try:
            return int(node.this)
        except ValueError:
            try:
                return float(node.this)
            except ValueError:
                return None
    return None


def _to_date(column: str, value: Any) -> date | None:
    if value is None:
        return None
    if column == "date_id" and isinstance(value, int):
        try:
            return date(value // 10000, (value // 100) % 100, value % 100)
        except ValueError:
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip()[:19].replace(" ", "T")).date()
        except ValueError:
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError:
                return None
    return None


def _is_statut(node: exp.Expression) -> bool:
    return isinstance(node, exp.Column) and node.name.lower() == "statut"


def statut_values(cond: exp.Expression | None) -> set[str]:
    """Valeurs de `statut` retenues par une condition (statut = 'x', IN, <> 'y')."""
    found: set[str] = set()
    if cond is None:
        return found
    for node in cond.walk():
        if isinstance(node, exp.EQ | exp.NEQ):
            col, lit = (node.left, node.right) if _is_statut(node.left) else (node.right, node.left)
            if _is_statut(col):
                value = _literal_value(lit)
                if isinstance(value, str):
                    if isinstance(node, exp.EQ):
                        found.add(value)
                    else:
                        found |= {"reussie", "echouee"} - {value}
        elif isinstance(node, exp.In) and _is_statut(node.this):
            for item in node.expressions:
                value = _literal_value(item)
                if isinstance(value, str):
                    found.add(value)
    return found


def _conjuncts(cond: exp.Expression | None) -> list[exp.Expression]:
    if cond is None:
        return []
    if isinstance(cond, exp.Where):
        cond = cond.this
    return list(cond.flatten()) if isinstance(cond, exp.And) else [cond]


def _where_statut(select: exp.Select) -> set[str]:
    values: set[str] = set()
    for conj in _conjuncts(select.args.get("where")):
        if isinstance(conj, exp.Or):
            continue
        values |= statut_values(conj)
    for join in select.args.get("joins") or []:
        for conj in _conjuncts(join.args.get("on")):
            values |= statut_values(conj)
    return values


def _reads_fact(select: exp.Select, aliases: dict[str, str]) -> bool:
    sources: list[exp.Expression] = []
    from_ = select.args.get("from_") or select.args.get("from")
    if from_ is not None:
        sources.append(from_.this)
    sources += [j.this for j in select.args.get("joins") or []]
    return any(isinstance(s, exp.Table) and s.name.lower() == FACT for s in sources)


# --- Portée ---------------------------------------------------------------------------------------


def extract_scope(root: exp.Expression, semantic: SemanticLayer | None = None) -> dict[str, Any]:
    aliases = _alias_map(root)
    date_predicates: list[str] = []
    lowers: list[date] = []
    uppers: list[date] = []
    year: int | None = None
    month: int | None = None

    def date_column(node: exp.Expression) -> str | None:
        if not isinstance(node, exp.Column):
            return None
        table = _column_table(node, aliases, semantic)
        name = node.name.lower()
        if table == FACT and name in ("date_id", "txn_ts"):
            return name
        if table == DATE_TABLE and name in ("date_id", "date", "debut_mois", "fin_mois", "annee", "mois"):
            return name
        return None

    conditions: list[exp.Expression] = []
    for sel in root.find_all(exp.Select):
        conditions += _conjuncts(sel.args.get("where"))
        for join in sel.args.get("joins") or []:
            conditions += _conjuncts(join.args.get("on"))

    for cond in conditions:
        if isinstance(cond, exp.Between) and (col := date_column(cond.this)):
            low, high = (
                _to_date(col, _literal_value(cond.args["low"])),
                _to_date(col, _literal_value(cond.args["high"])),
            )
            if low:
                lowers.append(low)
            if high:
                uppers.append(high)
            date_predicates.append(cond.sql(dialect="postgres"))
        elif isinstance(cond, exp.GT | exp.GTE | exp.LT | exp.LTE | exp.EQ):
            left, right = cond.left, cond.right
            flipped = False
            col = date_column(left)
            if col is None and (col := date_column(right)):
                left, right, flipped = right, left, True
            if col is None or isinstance(right, exp.Column):
                continue
            raw = _literal_value(right)
            date_predicates.append(cond.sql(dialect="postgres"))
            if col == "annee" and isinstance(raw, int) and isinstance(cond, exp.EQ):
                year = raw
                continue
            if col == "mois" and isinstance(raw, int) and isinstance(cond, exp.EQ):
                month = raw
                continue
            value = _to_date(col, raw)
            if value is None:
                continue
            kind = type(cond)
            if flipped:
                kind = {exp.GT: exp.LT, exp.GTE: exp.LTE, exp.LT: exp.GT, exp.LTE: exp.GTE}.get(kind, kind)
            if kind in (exp.GT, exp.GTE, exp.EQ):
                lowers.append(value + timedelta(days=1) if kind is exp.GT and col != "txn_ts" else value)
            if kind in (exp.LT, exp.LTE, exp.EQ):
                uppers.append(value - timedelta(days=1) if kind is exp.LT else value)
    if year is not None:
        m1, m2 = (month, month) if month else (1, 12)
        lowers.append(date(year, m1, 1))
        uppers.append(date(year, m2, calendar.monthrange(year, m2)[1]))

    region_cols = sorted(
        {c.name.lower() for c in root.find_all(exp.Column) if c.name.lower() in REGION_COLUMNS}
    )
    kinds = sorted({REGION_COLUMNS[c] for c in region_cols})
    region_kind = "aucune" if not kinds else kinds[0] if len(kinds) == 1 else "mixte"

    where_statut: set[str] = set()
    filter_statut: set[str] = set()
    for sel in root.find_all(exp.Select):
        if _reads_fact(sel, aliases):
            where_statut |= _where_statut(sel)
    for flt in root.find_all(exp.Filter):
        filter_statut |= statut_values(flt.expression)
    if len(where_statut) == 1:
        statut = next(iter(where_statut))
    elif where_statut:
        statut = "toutes"
    elif filter_statut == {"reussie"}:
        statut = "reussie"
    else:
        statut = "toutes"

    return {
        "period": {
            "start": max(lowers).isoformat() if lowers else None,
            "end": min(uppers).isoformat() if uppers else None,
        },
        "date_predicates": date_predicates,
        "region_columns": region_cols,
        "region_kind": region_kind,
        "statut": statut,
        "statut_where": sorted(where_statut),
        "statut_filters": sorted(filter_statut),
        "uses_statut_agent": any(c.name.lower() == "statut_agent" for c in root.find_all(exp.Column)),
    }


# --- Règles de cohérence --------------------------------------------------------------------------


def _aggregate_statut(agg: exp.Expression, select: exp.Select) -> set[str] | None:
    """Statuts couverts par un agrégat ; None s'il n'y a aucune restriction."""
    values: set[str] = set()
    parent = agg.parent
    if isinstance(parent, exp.Filter):
        values |= statut_values(parent.expression)
    for case in agg.find_all(exp.Case):
        values |= statut_values(case)
    values |= _where_statut(select)
    return values or None


def _enclosing_select(node: exp.Expression) -> exp.Select | None:
    cur = node.parent
    while cur is not None and not isinstance(cur, exp.Select):
        cur = cur.parent
    return cur


def semantic_issues(
    root: exp.Expression, declared_scope: dict[str, Any] | None, semantic: SemanticLayer | None = None
) -> list[SemanticIssue]:
    declared = declared_scope or {}
    declared_statut = declared.get("statut", "reussie")
    declared_region = declared.get("region_kind")
    aliases = _alias_map(root)
    scope = extract_scope(root, semantic)
    issues: list[SemanticIssue] = []

    # 1. Agrégat de montant ou de volume sans statut = 'reussie'.
    if declared_statut == "reussie":
        for agg in root.find_all(*_AGGREGATES):
            sel = _enclosing_select(agg)
            if sel is None or not _reads_fact(sel, aliases):
                continue
            covered = _aggregate_statut(agg, sel)
            if covered is None or "reussie" not in covered:
                expr_sql = (agg.parent if isinstance(agg.parent, exp.Filter) else agg).sql(dialect="postgres")
                issues.append(
                    SemanticIssue(
                        "statut_manquant",
                        f"L'agrégat {expr_sql} ne filtre pas statut = 'reussie' alors que "
                        "declared_scope.statut = "
                        "reussie : un volume ou un montant porte sur les transactions réussies. Ajouter "
                        "FILTER (WHERE f.statut = 'reussie') ou WHERE f.statut = 'reussie', ou "
                        "déclarer statut = toutes.",
                    )
                )
                break

    # 2. « Agent actif » via statut_agent.
    if scope["uses_statut_agent"]:
        issues.append(
            SemanticIssue(
                "agent_actif_statut_agent",
                "statut_agent (ouvert/ferme) est un statut administratif. Si la question porte sur "
                "les agents "
                "actifs, utiliser COUNT(DISTINCT f.agent_id) FILTER (WHERE f.statut = 'reussie' AND "
                "f.agent_id <> -1) sur la période.",
            )
        )

    # 3. Jointure de région incohérente avec region_kind.
    actual = scope["region_kind"]
    if declared_region in ("region_agent", "region_client"):
        other = "region_client" if declared_region == "region_agent" else "region_agent"
        if actual == other:
            issues.append(
                SemanticIssue(
                    "region_incoherente",
                    f"declared_scope.region_kind = {declared_region} mais la requête utilise {other}_id. "
                    f"Joindre analytics.dim_region sur f.{declared_region}_id, ou corriger declared_scope.",
                    blocking=True,
                )
            )
        elif actual == "mixte":
            issues.append(
                SemanticIssue(
                    "region_mixte",
                    f"La requête utilise region_agent_id et region_client_id ; vérifier que le sens retenu "
                    f"({declared_region}) est bien celui des filtres et regroupements.",
                )
            )
    elif declared_region == "aucune" and actual != "aucune":
        issues.append(
            SemanticIssue(
                "region_non_declaree",
                "declared_scope.region_kind = aucune mais la requête utilise "
                f"{', '.join(scope['region_columns'])}. "
                "Déclarer region_agent ou region_client.",
                blocking=True,
            )
        )

    # 4. Dénominateur du taux d'échec filtré sur « reussie ».
    for div in root.find_all(exp.Div):
        num_statuts = set()
        for flt in div.left.find_all(exp.Filter):
            num_statuts |= statut_values(flt.expression)
        for case in div.left.find_all(exp.Case):
            num_statuts |= statut_values(case)
        if "echouee" not in num_statuts:
            continue
        den_statuts: set[str] = set()
        for flt in div.right.find_all(exp.Filter):
            den_statuts |= statut_values(flt.expression)
        sel = _enclosing_select(div)
        if sel is not None:
            den_statuts |= _where_statut(sel)
        if den_statuts == {"reussie"}:
            issues.append(
                SemanticIssue(
                    "taux_echec_denominateur",
                    "Taux d'échec : le dénominateur doit compter toutes les transactions (réussies "
                    "+ échouées), "
                    "pas seulement les réussies : COUNT(*) FILTER (WHERE f.statut = 'echouee')::numeric / "
                    "NULLIF(COUNT(*), 0).",
                )
            )
            break

    # 5. Statut global contredisant declared_scope.statut.
    where = set(scope["statut_where"])
    if where:
        if declared_statut == "toutes":
            issues.append(
                SemanticIssue(
                    "statut_contradictoire",
                    "declared_scope.statut = toutes mais la requête filtre statut = "
                    f"{', '.join(sorted(where))} "
                    "dans WHERE. Retirer le filtre ou corriger declared_scope.",
                    blocking=True,
                )
            )
        elif declared_statut in ("reussie", "echouee") and declared_statut not in where:
            issues.append(
                SemanticIssue(
                    "statut_contradictoire",
                    f"declared_scope.statut = {declared_statut} mais la requête filtre statut = "
                    f"{', '.join(sorted(where))}.",
                    blocking=True,
                )
            )
    return issues


def semantic_warnings(sql_ast: exp.Expression | str, declared_scope: dict[str, Any] | None) -> list[str]:
    """Contrat du brief : messages des règles de cohérence (bloquantes comprises)."""
    if isinstance(sql_ast, str):
        import sqlglot

        sql_ast = sqlglot.parse_one(sql_ast, read="postgres")
    return [issue.message for issue in semantic_issues(sql_ast, declared_scope)]
