"""Fabriques de résultats d'outils pour les tests (agent, évaluation) : aucune clé API, aucun Postgres."""

from __future__ import annotations

from typing import Any

from decision_core.models import ColumnInfo, ToolError, ToolResult

UNITS = {
    "volume_transactions": "count",
    "valeur_transferee": "xof",
    "revenus_frais": "xof",
    "clients_actifs": "count",
    "agents_actifs": "count",
    "taux_echec": "ratio",
}


def measure(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, type="numeric", role="measure", unit=UNITS.get(name, "count"))


def kpi_result(values: dict[str, Any], params: dict | None = None) -> ToolResult:
    cols = [measure(m) for m in values]
    return ToolResult(
        tool="query_metric",
        ok=True,
        sql="SELECT /* kpi */ 1",
        columns=cols,
        rows=[list(values.values())],
        row_count=1,
        certified=True,
        tables=["analytics.fact_transaction", "analytics.dim_date"],
        params=params or {"metrics": list(values)},
    )


def compare_result(cur: dict[str, Any], prev: dict[str, Any], params: dict | None = None) -> ToolResult:
    cols = [ColumnInfo(name="periode", type="text", role="period")] + [measure(m) for m in cur]
    return ToolResult(
        tool="query_metric",
        ok=True,
        sql="SELECT /* cmp */ 1",
        columns=cols,
        rows=[["courante", *cur.values()], ["comparaison", *prev.values()]],
        row_count=2,
        certified=True,
        tables=["analytics.fact_transaction"],
        params=params or {"metrics": list(cur), "compare_to": "previous_period"},
    )


def group_result(
    dim: str,
    metric: str,
    values: dict[str, Any],
    *,
    truncated: bool = False,
    tool: str = "query_metric",
    params: dict | None = None,
) -> ToolResult:
    cols = [ColumnInfo(name=dim, type="text", role="dimension"), measure(metric)]
    rows = [[k, v] for k, v in values.items()]
    return ToolResult(
        tool=tool,
        ok=True,
        sql=f"SELECT /* {dim} */ 1",
        columns=cols,
        rows=rows,
        row_count=1001 if truncated else len(rows),
        truncated=truncated,
        certified=tool == "query_metric",
        tables=["analytics.fact_transaction", "analytics.dim_region"],
        params=params or {"metrics": [metric], "group_by": [dim]},
    )


def error_result(tool: str, error_class: str, message: str) -> ToolResult:
    return ToolResult(tool=tool, ok=False, error=ToolError(error_class=error_class, message=message))  # type: ignore[arg-type]


def qm_input(
    metrics: list[str],
    *,
    kind: str = "relative",
    relative: str | None = "mois_courant",
    start: str | None = None,
    end: str | None = None,
    compare_to: str = "none",
    group_by: list[str] | None = None,
    filters: list | None = None,
    order: str = "none",
    limit: int | None = None,
    grain: str = "none",
) -> dict[str, Any]:
    return {
        "metrics": metrics,
        "period": {
            "kind": kind,
            "start": start,
            "end": end,
            "relative": relative if kind == "relative" else None,
        },
        "compare_to": compare_to,
        "group_by": group_by or [],
        "grain": grain,
        "filters": filters or [],
        "order": order,
        "limit": limit,
    }


def submit(
    text: str,
    result_ids: list[str] | None = None,
    caveats: list[str] | None = None,
    follow_up: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    return (
        "submit_answer",
        {
            "text": text,
            "result_ids": result_ids or [],
            "caveats": caveats or [],
            "follow_up": follow_up or [],
        },
    )
