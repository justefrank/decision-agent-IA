"""Périodes : résolution par rapport à REFERENCE_DATE et libellés français.

Tout calcul de date se fait à partir de REFERENCE_DATE (glossaire « aujourd'hui »), jamais de la date
système. Les libellés produits ici sont les seuls affichés : le modèle ne les écrit pas.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from decision_core.models import Period

MOIS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

# Périodes relatives acceptées par l'outil `query_metric` côté modèle.
RELATIVE_PERIODS = (
    "mois_courant",
    "mois_precedent",
    "trimestre_courant",
    "trimestre_precedent",
    "annee_courante",
    "7_derniers_jours",
    "30_derniers_jours",
    "12_derniers_mois",
)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, _last_day(year, month))


def _add_months(d: date, months: int) -> date:
    """Décale au même jour du mois (borné au dernier jour du mois cible)."""
    idx = d.year * 12 + (d.month - 1) + months
    year, month = divmod(idx, 12)
    month += 1
    return date(year, month, min(d.day, _last_day(year, month)))


def _day_fr(d: date) -> str:
    return "1er" if d.day == 1 else str(d.day)


def _is_month_start(d: date) -> bool:
    return d.day == 1


def _is_month_end(d: date) -> bool:
    return d.day == _last_day(d.year, d.month)


def _months_between(start: date, end: date) -> int:
    """Nombre de mois calendaires entiers couverts (start = 1er, end = fin de mois)."""
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def period_label(start: date, end: date) -> str:
    """Libellé français : « mars 2026 », « T2 2026 », « année 2025 », « du 1er au 15 mars 2026 »."""
    if start > end:
        raise ValueError("début de période postérieur à la fin")
    full_months = _is_month_start(start) and _is_month_end(end)
    if full_months:
        n = _months_between(start, end)
        if n == 1:
            return f"{MOIS_FR[start.month - 1]} {start.year}"
        if n == 3 and start.month in (1, 4, 7, 10):
            return f"T{(start.month - 1) // 3 + 1} {start.year}"
        if n == 12 and start.month == 1:
            return f"année {start.year}"
        if start.year == end.year:
            return f"de {MOIS_FR[start.month - 1]} à {MOIS_FR[end.month - 1]} {start.year}"
        return f"de {MOIS_FR[start.month - 1]} {start.year} à {MOIS_FR[end.month - 1]} {end.year}"
    if start == end:
        return f"le {_day_fr(start)} {MOIS_FR[start.month - 1]} {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"du {_day_fr(start)} au {_day_fr(end)} {MOIS_FR[start.month - 1]} {start.year}"
    if start.year == end.year:
        return (
            f"du {_day_fr(start)} {MOIS_FR[start.month - 1]} au "
            f"{_day_fr(end)} {MOIS_FR[end.month - 1]} {start.year}"
        )
    return (
        f"du {_day_fr(start)} {MOIS_FR[start.month - 1]} {start.year} au "
        f"{_day_fr(end)} {MOIS_FR[end.month - 1]} {end.year}"
    )


def make_period(start: date, end: date) -> Period:
    return Period(start=start, end=end, label=period_label(start, end))


def _ytd_label(end: date) -> str:
    """« 2026, au 30 septembre » : cumul depuis le début de l'année."""
    return f"{end.year}, au {_day_fr(end)} {MOIS_FR[end.month - 1]}"


def _mtd_label(end: date) -> str:
    """« octobre 2026, au 15 octobre » : cumul depuis le début du mois."""
    m = MOIS_FR[end.month - 1]
    return f"{m} {end.year}, au {_day_fr(end)} {m}"


def year_to_date(end: date) -> Period:
    """Année civile bornée à `end` (REFERENCE_DATE) : l'année entière si `end` est le 31 décembre."""
    start = date(end.year, 1, 1)
    if end.month == 12 and end.day == 31:
        return make_period(start, end)
    return Period(start=start, end=end, label=_ytd_label(end))


def month_to_date(end: date) -> Period:
    """Mois de `end` borné à `end` : le mois entier si `end` est une fin de mois."""
    start = date(end.year, end.month, 1)
    if _is_month_end(end):
        return make_period(start, end)
    return Period(start=start, end=end, label=_mtd_label(end))


def _is_ytd(p: Period) -> bool:
    return p.start == date(p.end.year, 1, 1) and p.label == _ytd_label(p.end)


def _is_mtd(p: Period) -> bool:
    return p.start == date(p.end.year, p.end.month, 1) and p.label == _mtd_label(p.end)


def month_of_reference(ref: date) -> Period:
    """Défaut annoncé de la politique par champ : le mois de REFERENCE_DATE, borné à REFERENCE_DATE."""
    return month_to_date(ref)


def last_n_days(ref: date, n: int) -> Period:
    """N derniers jours se terminant à REFERENCE_DATE (inclus)."""
    return make_period(ref - timedelta(days=n - 1), ref)


def last_30_days(ref: date) -> Period:
    return last_n_days(ref, 30)


def resolve_relative(name: str, ref: date) -> Period:
    if name == "mois_courant":
        return month_of_reference(ref)
    if name == "mois_precedent":
        prev = _add_months(date(ref.year, ref.month, 1), -1)
        return make_period(*month_bounds(prev.year, prev.month))
    if name in ("trimestre_courant", "trimestre_precedent"):
        q_start = date(ref.year, 3 * ((ref.month - 1) // 3) + 1, 1)
        if name == "trimestre_precedent":
            q_start = _add_months(q_start, -3)
        q_end_month = _add_months(q_start, 2)
        return make_period(q_start, month_bounds(q_end_month.year, q_end_month.month)[1])
    if name == "annee_courante":
        return year_to_date(ref)
    if name == "7_derniers_jours":
        return last_n_days(ref, 7)
    if name == "30_derniers_jours":
        return last_n_days(ref, 30)
    if name == "12_derniers_mois":
        start = _add_months(date(ref.year, ref.month, 1), -11)
        return make_period(start, month_bounds(ref.year, ref.month)[1])
    raise ValueError(f"période relative inconnue : {name}")


def default_period_for(metric_names: list[str], semantic_metrics: dict, ref: date) -> Period:
    """Défaut de période : 30 derniers jours si tous les KPI le déclarent (clients/agents actifs),
    sinon le mois de REFERENCE_DATE."""
    defaults = {semantic_metrics.get(m, {}).get("default_period") for m in metric_names}
    if defaults == {"last_30_days"}:
        return last_30_days(ref)
    return month_of_reference(ref)


def _shift_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 février
        return d.replace(year=d.year - 1, day=28)


def previous_period(p: Period) -> Period:
    """Période précédente de même longueur ; en mois entiers si la période est en mois entiers.

    Cumul annuel (« 2026, au 30 septembre ») : même cumul l'année précédente. Cumul mensuel : mêmes jours
    du mois précédent (bornés à sa fin).
    """
    if _is_ytd(p):
        return previous_year(p)
    if _is_mtd(p):
        prev = _add_months(p.start, -1)
        end = date(prev.year, prev.month, min(p.end.day, _last_day(prev.year, prev.month)))
        return Period(start=prev, end=end, label=_mtd_label(end))
    if _is_month_start(p.start) and _is_month_end(p.end):
        n = _months_between(p.start, p.end)
        start = _add_months(p.start, -n)
        end_month = _add_months(p.start, -1)
        return make_period(start, month_bounds(end_month.year, end_month.month)[1])
    length = (p.end - p.start).days + 1
    end = p.start - timedelta(days=1)
    return make_period(end - timedelta(days=length - 1), end)


def previous_year(p: Period) -> Period:
    """Même période un an plus tôt (le 29 février devient le 28)."""

    start, end = _shift_year(p.start), _shift_year(p.end)
    if _is_ytd(p):
        return Period(start=start, end=end, label=_ytd_label(end))
    if _is_mtd(p):
        return Period(start=start, end=end, label=_mtd_label(end))
    if _is_month_end(p.end):
        end = date(end.year, end.month, _last_day(end.year, end.month))
    return make_period(start, end)


def compare_period(p: Period, compare_to: str) -> Period | None:
    if compare_to == "previous_period":
        return previous_period(p)
    if compare_to == "previous_year":
        return previous_year(p)
    return None


def ensure_label(p: Period) -> Period:
    if p.label:
        return p
    return make_period(p.start, p.end)
