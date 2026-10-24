"""Compilateur déterministe de `query_metric` (chemin certifié, semantic/kpis.yaml).

métriques × dimensions × filtres × comparaison × grain → un SELECT paramétré (``%(nom)s``, liés
par psycopg, jamais interpolés). Le SQL produit repasse ensuite par le garde (défense en profondeur).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from decision_core.models import ColumnInfo, Period, QueryMetricParams, ToolError
from decision_core.semantic import SemanticLayer
from pydantic import ValidationError

FACT_FROM = "analytics.fact_transaction f\nJOIN analytics.dim_date d ON d.date_id = f.date_id"
GRAIN_COLUMNS = {
    "day": ("jour", "Jour"),
    "week": ("semaine", "Semaine"),
    "month": ("mois", "Mois"),
    "quarter": ("trimestre", "Trimestre"),
}
UNIT_TYPES = {"count": "integer", "xof": "numeric", "ratio": "numeric", "pct": "numeric", "pp": "numeric"}


GENERAL_HINT = (
    "Schéma : metrics, period{start,end}, compare_to ∈ {none, previous_period, previous_year}, "
    "group_by ⊂ {region_agent, region_client, type, segment, agent} (≤ 2, distinctes), "
    "grain ∈ {none, day, week, month, quarter}, filters[{dimension, values}] (un filtre par dimension), "
    "order ∈ {none, desc, asc}, limit ≤ 50 avec group_by."
)


class CompileError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.error = ToolError(error_class="invalid_params", message=message, hint=hint or GENERAL_HINT)


@dataclass
class CompiledQuery:
    sql: str
    bind: dict[str, Any]
    columns: list[ColumnInfo]
    params: dict[str, Any]  # description des paramètres compilés (ToolResult.params)
    warnings: list[str] = field(default_factory=list)
    rank_limit: int | None = None  # LIMIT demandé (le SQL lit une ligne de plus pour les ex æquo)
    order_column: str | None = None


# --- Périodes ------------------------------------------------------------------------------------


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 février
        return d.replace(year=d.year + years, day=28)


def _shift_year_end(d: date, years: int) -> date:
    """Fin de période décalée : le dernier jour de février reste le dernier jour de février."""
    if d.month == 2 and d == _month_end(d):
        return _month_end(date(d.year + years, 2, 1))
    return _shift_year(d, years)


def comparison_period(period: Period, compare_to: str) -> Period | None:
    """Période de comparaison.

    - previous_period : même durée juste avant ; si la période couvre des mois calendaires entiers,
      le même nombre de mois calendaires juste avant (mars → février, T1 → T4 précédent) ;
    - previous_year : décalage d'un an (29 février → 28 février ; une fin au dernier jour de février
      recule au dernier jour de février de l'année précédente, 28/02/2025 → 29/02/2024).
    """
    start, end = period.start, period.end
    if compare_to == "previous_year":
        return Period(start=_shift_year(start, -1), end=_shift_year_end(end, -1))
    if compare_to == "previous_period":
        if start.day == 1 and end == _month_end(end):
            months = (end.year - start.year) * 12 + end.month - start.month + 1
            prev_start = _add_months(start, -months)
            return Period(start=prev_start, end=start - timedelta(days=1))
        length = (end - start).days
        prev_end = start - timedelta(days=1)
        return Period(start=prev_end - timedelta(days=length), end=prev_end)
    return None


def date_id(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def date_from_id(value: int) -> date:
    return date(value // 10000, (value // 100) % 100, value % 100)


def _covered_days(start: date, end: date, bounds: tuple[date, date]) -> int:
    lo, hi = max(start, bounds[0]), min(end, bounds[1])
    return max(0, (hi - lo).days + 1)


def _coverage(
    period: Period, compare: Period | None, bounds: tuple[date, date] | None
) -> tuple[dict[str, Any] | None, list[str]]:
    """Couverture des périodes par les données (bornes min/max de f.date_id).

    Période de comparaison entièrement hors données → CompileError (variation trompeuse) ; période
    courante hors données avec comparaison → CompileError ; sans comparaison → avertissement explicite ;
    couverture partielle → avertissement précis.
    """
    if bounds is None:
        return None, []
    span = f"données du {bounds[0].isoformat()} au {bounds[1].isoformat()}"
    hint = (
        f"Les données couvrent du {bounds[0].isoformat()} au {bounds[1].isoformat()} : choisir une période "
        "couverte, ou retirer compare_to."
    )
    warnings: list[str] = []
    coverage: dict[str, Any] = {"data_start": bounds[0].isoformat(), "data_end": bounds[1].isoformat()}
    parts = [("current", period)] + ([("comparison", compare)] if compare is not None else [])
    for key, per in parts:
        assert per is not None
        days = (per.end - per.start).days + 1
        covered = _covered_days(per.start, per.end, bounds)
        coverage[key] = {"days": days, "covered_days": covered, "complete": covered == days}
        if key == "comparison":
            if covered == 0:
                raise CompileError(f"Période de comparaison hors des données ({span}).", hint)
            if covered < days:
                warnings.append(
                    f"comparaison partielle : {covered} jours sur {days} couverts ({span}) ; "
                    "la variation n'est pas comparable à période égale."
                )
        elif covered == 0:
            if compare is not None:
                raise CompileError(f"Période courante hors des données ({span}).", hint)
            warnings.append(
                f"période hors des données ({span}) : aucune transaction n'existe sur cette période, "
                "les valeurs nulles ou vides ne sont pas une mesure."
            )
        elif covered < days:
            warnings.append(f"période partielle : {covered} jours sur {days} couverts ({span}).")
    return coverage, warnings


# --- Validation ----------------------------------------------------------------------------------


def parse_params(args: dict[str, Any]) -> QueryMetricParams:
    """Valide l'entrée brute ; toute erreur devient un ToolError(invalid_params) lisible."""
    try:
        return QueryMetricParams.model_validate(args)
    except ValidationError as exc:
        details = []
        for err in exc.errors()[:6]:
            loc = ".".join(str(p) for p in err["loc"]) or "(racine)"
            details.append(f"{loc} : {err['msg']}")
        raise CompileError(
            "Paramètres query_metric invalides : " + " ; ".join(details),
        ) from exc


def canonical_definition(semantic: SemanticLayer, metric: str) -> str:
    spec = semantic.metrics[metric]
    allowed = spec.get("dimensions") or list(semantic.dimensions)
    return (
        f"Définition canonique de {metric} ({spec.get('label')}) : "
        f"{' '.join(str(spec.get('description', '')).split())} "
        f"SQL : {spec['sql']} ; FROM {FACT_FROM.replace(chr(10), ' ')} ; filtre de période sur f.date_id "
        f"(AAAAMMJJ). Dimensions supportées : {', '.join(allowed)}. Si la question l'exige, utiliser "
        "run_query en partant de cette définition (réponse étiquetée « calcul ad hoc »)."
    )


def _filter_values(semantic: SemanticLayer, dimension: str, values: list[str]) -> list[Any]:
    spec = semantic.dimensions[dimension]
    if dimension in ("region_agent", "region_client"):
        allowed = list(semantic.kpis.get("regions") or [])
    elif dimension == "agent":
        out: list[Any] = []
        for v in values:
            try:
                agent_id = int(str(v).strip())
            except ValueError:
                raise CompileError(
                    f"Filtre agent : identifiant invalide {v!r} (entier agent_id attendu).",
                    "Obtenir les identifiants par un classement query_metric group_by=[agent].",
                ) from None
            if agent_id == -1:
                raise CompileError("Filtre agent : -1 (« Hors agent ») n'est pas un point de service.")
            out.append(agent_id)
        return out
    else:
        allowed = list(spec.get("values") or [])
    if allowed:
        unknown = [v for v in values if v not in allowed]
        if unknown:
            raise CompileError(
                f"Valeur(s) inconnue(s) pour le filtre {dimension} : {', '.join(map(str, unknown))}.",
                f"Valeurs autorisées : {', '.join(allowed)}.",
            )
    return list(dict.fromkeys(values))


def _check_metrics_and_dimensions(p: QueryMetricParams, semantic: SemanticLayer) -> None:
    limits = semantic.kpis.get("limits") or {}
    known = list(semantic.metrics)
    unknown = [m for m in p.metrics if m not in semantic.metrics]
    if unknown:
        raise CompileError(
            f"Métrique(s) inconnue(s) : {', '.join(unknown)}.",
            f"Métriques certifiées : {', '.join(known)}. Pour un autre calcul, utiliser run_query.",
        )
    if len(set(p.metrics)) != len(p.metrics):
        raise CompileError("Métrique répétée dans metrics.")
    if len(p.metrics) > int(limits.get("max_metrics", 6)):
        raise CompileError(f"Au plus {limits.get('max_metrics', 6)} métriques par appel.")
    if len(p.group_by) > int(limits.get("max_group_by", 2)) or len(set(p.group_by)) != len(p.group_by):
        raise CompileError(f"group_by : au plus {limits.get('max_group_by', 2)} dimensions distinctes.")
    if p.limit is not None and p.limit > int(limits.get("max_rank_limit", 50)):
        raise CompileError(f"limit doit être ≤ {limits.get('max_rank_limit', 50)}.")
    dims_used = list(p.group_by) + [f.dimension for f in p.filters]
    for dim in dims_used:
        if dim not in semantic.dimensions:
            raise CompileError(
                f"Dimension inconnue : {dim}.", f"Dimensions : {', '.join(semantic.dimensions)}."
            )
    for metric in p.metrics:
        allowed = semantic.metrics[metric].get("dimensions")
        if allowed is None:
            continue
        bad = [d for d in dims_used if d not in allowed]
        if bad:
            raise CompileError(
                f"Dimension non supportée pour {metric} : {', '.join(bad)}.",
                canonical_definition(semantic, metric),
            )
    if len({f.dimension for f in p.filters}) != len(p.filters):
        raise CompileError("Un seul filtre par dimension : regrouper les valeurs dans `values`.")
    if p.compare_to != "none" and p.limit is not None:
        raise CompileError(
            "Combinaison non supportée : classement (limit) avec comparaison de périodes.",
            "Faire d'abord le classement sans comparaison, puis rappeler query_metric avec compare_to et "
            "un filtre sur les éléments obtenus (ex. filters=[{dimension: agent, values: [...]}]).",
        )
    if p.period.start > p.period.end:
        raise CompileError("Période invalide : start est postérieur à end.")
    if p.limit is not None and not p.group_by:
        raise CompileError(
            "limit n'a de sens qu'avec un regroupement (group_by).",
            "Ajouter group_by (ex. [agent] ou [region_agent]) ou retirer limit.",
        )


# --- Compilation ---------------------------------------------------------------------------------


def compile_query_metric(
    p: QueryMetricParams, semantic: SemanticLayer, bounds: tuple[date, date] | None = None
) -> CompiledQuery:
    """`bounds` : premier et dernier jour des données (min/max de f.date_id), mis en cache par le serveur."""
    _check_metrics_and_dimensions(p, semantic)
    dims = semantic.dimensions
    bind: dict[str, Any] = {"debut": date_id(p.period.start), "fin": date_id(p.period.end)}
    select: list[str] = []
    group: list[str] = []
    columns: list[ColumnInfo] = []
    joins: list[str] = []
    where: list[str] = []
    warnings: list[str] = []

    compare = comparison_period(p.period, p.compare_to)
    if compare is not None and compare.start <= p.period.end and compare.end >= p.period.start:
        raise CompileError(
            f"Période de comparaison ({compare.start.isoformat()} – {compare.end.isoformat()}) chevauchant "
            "la période courante : comparaison impossible sans double compte.",
            "Réduire la période à un an au plus pour previous_year, ou comparer deux appels distincts.",
        )
    coverage, coverage_warnings = _coverage(p.period, compare, bounds)
    warnings.extend(coverage_warnings)
    if compare is not None:
        bind["debut_comparaison"] = date_id(compare.start)
        bind["fin_comparaison"] = date_id(compare.end)
        select.append(
            "CASE WHEN f.date_id BETWEEN %(debut)s AND %(fin)s THEN 'courante' ELSE 'comparaison' "
            "END AS periode"
        )
        group.append("periode")
        columns.append(ColumnInfo(name="periode", type="text", role="period", unit="text", label="Période"))
        where.append(
            "(f.date_id BETWEEN %(debut)s AND %(fin)s OR f.date_id BETWEEN %(debut_comparaison)s AND "
            "%(fin_comparaison)s)"
        )
    else:
        where.append("f.date_id BETWEEN %(debut)s AND %(fin)s")

    if p.grain != "none":
        grain_sql = semantic.kpis["grains"][p.grain]
        name, label = GRAIN_COLUMNS[p.grain]
        select.append(f"{grain_sql} AS {name}")
        group.append(name)
        columns.append(ColumnInfo(name=name, type="date", role="time", unit="date", label=label))

    def add_joins(dim: str) -> None:
        for j in dims[dim].get("joins") or []:
            if j not in joins:
                joins.append(j)
        extra = dims[dim].get("where")
        if extra and extra not in where:
            where.append(extra)

    for dim in p.group_by:
        spec = dims[dim]
        add_joins(dim)
        if dim == "agent":
            select.append(f"{spec['column']} AS agent_id")
            group.append("agent_id")
            columns.append(
                ColumnInfo(
                    name="agent_id", type="integer", role="dimension", unit="id", label=spec.get("label")
                )
            )
            if spec.get("label_column"):
                select.append(f"{spec['label_column']} AS nom")
                group.append("nom")
                columns.append(
                    ColumnInfo(
                        name="nom",
                        type="text",
                        role="dimension",
                        unit="text",
                        label="Nom du point de service",
                        free_text=True,  # dim_agent.nom : texte libre (tables.yaml)
                    )
                )
        else:
            select.append(f"{spec['column']} AS {dim}")
            group.append(dim)
            columns.append(
                ColumnInfo(name=dim, type="text", role="dimension", unit="text", label=spec.get("label"))
            )
        if dim == "region_agent":
            warnings.append(
                "Découpage par région du point de service : les transactions hors agent "
                "(transferts et paiements) sont exclues."
            )

    compiled_filters = []
    for i, flt in enumerate(p.filters):
        values = _filter_values(semantic, flt.dimension, flt.values)
        add_joins(flt.dimension)
        names = []
        for j, v in enumerate(values):
            key = f"f{i}_{j}"
            bind[key] = v
            names.append(f"%({key})s")
        where.append(f"{dims[flt.dimension]['filter_column']} IN ({', '.join(names)})")
        compiled_filters.append({"dimension": flt.dimension, "values": values})

    for metric in p.metrics:
        spec = semantic.metrics[metric]
        select.append(f"{spec['sql']} AS {metric}")
        unit = spec.get("unit", "count")
        columns.append(
            ColumnInfo(
                name=metric,
                type=UNIT_TYPES.get(unit, "numeric"),
                role="measure",
                unit=unit,
                label=spec.get("label"),
            )
        )

    # GROUP BY / ORDER BY par position : un alias comme `mois` ou `agent_id` serait résolu par
    # Postgres comme colonne d'entrée (d.mois, f.agent_id ambigu) dans GROUP BY.
    names = [c.name for c in columns]
    group = [str(names.index(g) + 1) for g in group]
    order: list[str] = []
    order_column: str | None = None
    if compare is not None:
        order.append(f"{names.index('periode') + 1} DESC")  # « courante » avant « comparaison »
    if p.order != "none" or (p.limit is not None):
        direction = "ASC" if p.order == "asc" else "DESC"
        order_column = p.metrics[0]
        order.append(f"{names.index(order_column) + 1} {direction} NULLS LAST")
    order += [g for g in group if not (compare is not None and g == str(names.index("periode") + 1))]

    sql = "SELECT " + ",\n  ".join(select) + "\nFROM " + FACT_FROM
    for join_sql in joins:
        sql += "\n" + join_sql
    sql += "\nWHERE " + "\n  AND ".join(where)
    if group:
        sql += "\nGROUP BY " + ", ".join(group)
    if order:
        sql += "\nORDER BY " + ", ".join(order)
    if p.limit is not None:
        sql += f"\nLIMIT {int(p.limit) + 1}"  # une ligne de plus pour signaler les ex æquo

    params: dict[str, Any] = {
        "metrics": list(p.metrics),
        "period": p.period.model_dump(mode="json"),
        "compare_to": p.compare_to,
        "compare_period": compare.model_dump(mode="json") if compare else None,
        "group_by": list(p.group_by),
        "grain": p.grain,
        "filters": compiled_filters,
        "order": p.order if p.order != "none" or p.limit is None else "desc",
        "limit": p.limit,
        "region_kind": next(
            (
                d
                for d in p.group_by + [f.dimension for f in p.filters]
                if d in ("region_agent", "region_client")
            ),
            None,
        ),
        "bind": dict(bind),
        "semantic_version": semantic.version,
    }
    if coverage is not None:
        params["coverage"] = coverage
    return CompiledQuery(
        sql=sql,
        bind=bind,
        columns=columns,
        params=params,
        warnings=warnings,
        rank_limit=p.limit,
        order_column=order_column,
    )
