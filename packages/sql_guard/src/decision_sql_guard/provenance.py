"""Provenance des projections : colonnes `free_text: true` de tables.yaml (sécurité E1).

Une projection dérivée d'une colonne de texte libre (dim_agent.nom, dim_agent.ville) doit être marquée
`free_text`, quel que soit son alias, même sous une fonction (lower, upper, coalesce, cast, ||,
substring, CASE…), à travers les CTE, sous-requêtes et UNION. Le lignage est calculé par sqlglot sur
l'AST **validé** par le garde (copie : l'AST d'origine n'est pas modifié).
"""

from __future__ import annotations

from decision_core.semantic import SemanticLayer
from sqlglot import exp
from sqlglot.lineage import lineage
from sqlglot.optimizer.qualify import qualify

DIALECT = "postgres"


def free_text_columns(semantic: SemanticLayer) -> set[tuple[str, str]]:
    """Couples (table, colonne) marqués `free_text: true` dans tables.yaml."""
    out: set[tuple[str, str]] = set()
    for tname, spec in semantic.tables["tables"].items():
        for cname, cspec in (spec.get("columns") or {}).items():
            if (cspec or {}).get("free_text"):
                out.add((tname, cname))
    return out


def _schema(semantic: SemanticLayer) -> dict[str, dict[str, dict[str, str]]]:
    tables = semantic.tables["tables"]
    return {
        semantic.tables["schema"]: {
            t: dict.fromkeys(spec.get("columns") or {}, "text") for t, spec in tables.items()
        }
    }


def _leftmost_select(node: exp.Expression) -> exp.Select | None:
    while isinstance(node, exp.Union | exp.Intersect | exp.Except):
        node = node.this
    if isinstance(node, exp.Subquery):
        return _leftmost_select(node.this)
    return node if isinstance(node, exp.Select) else None


def free_text_projections(ast: exp.Expression, semantic: SemanticLayer) -> list[bool] | None:
    """Drapeau par position de projection du résultat ; None si le lignage est incalculable.

    En cas de None, l'appelant doit échouer « fermé » (marquer les colonnes texte comme libres).
    """
    sensitive = free_text_columns(semantic)
    if not sensitive:
        return None
    schema = _schema(semantic)
    try:
        qualified = qualify(
            ast.copy(),
            schema=schema,
            dialect=DIALECT,
            validate_qualify_columns=False,
            identify=False,
        )
        first = _leftmost_select(qualified)
        if first is None:
            return None
        # Alias uniques par position : deux projections de même nom ne se confondent pas.
        names = []
        for i, proj in enumerate(first.expressions):
            name = f"__p{i}"
            inner = proj.this if isinstance(proj, exp.Alias) else proj
            proj.replace(exp.alias_(inner.copy(), name))
            names.append(name)
        nodes = lineage(None, qualified, schema=schema, dialect=DIALECT)
    except Exception:  # lignage impossible : l'appelant échoue fermé
        return None
    if not isinstance(nodes, dict):
        return None
    flags: list[bool] = []
    for name in names:
        node = nodes.get(name)
        if node is None:
            return None
        hit = False
        for leaf in node.walk():
            if leaf.downstream or not isinstance(leaf.source, exp.Table):
                continue
            table = leaf.source.name.lower()
            column = leaf.name.rsplit(".", 1)[-1].strip('"').lower()
            if (table, column) in sensitive:
                hit = True
                break
        flags.append(hit)
    return flags
