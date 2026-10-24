"""Validateur de sortie déterministe (AGENTIC v5 §3.7).

1. Références : chaque {{f…}}/{{d…}}/{{l:…}} existe, format autorisé.
2. Littéraux numériques résiduels (filet) : extraction FR, appariement à la demi-unité affichée.
   Années de la période, dates, rangs et « N derniers jours » sont tolérés.
3. Résultats tronqués (pas de total) et vides (signalés).
4. Marqueurs causaux interdits hors phrase marquée « hypothèse ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from decision_agent.facts import FactRegistry
from decision_agent.formatting import ALLOWED_FMT, TEMPLATE_RE

MONTHS = (
    "janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
    "septembre|octobre|novembre|décembre|decembre"
)

CAUSAL_FR = (
    "à cause",
    "a cause",
    "en raison",
    "dû à",
    "du a",
    "due à",
    "dus à",
    "dues à",
    "grâce à",
    "grace a",
    "explique",
    "s'explique",
    "porté par",
    "portée par",
    "tiré par",
    "tirée par",
    "lié à",
    "liée à",
    "liés à",
    "suite à",
    "provoqu",
    "entraîn",
    "entrain",
    "résulte de",
    "imputable",
    "parce que",
)
VARIATION_WORDS = re.compile(
    r"(hausse|baisse|recul|progress|diminu|augment|repli|chute|croissance|régress|regress|plus|moins|écart|ecart|"
    r"variation|perd|gagn)",
    re.IGNORECASE,
)

_PRE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("date", re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")),
    ("date", re.compile(rf"\b(?:1er|\d{{1,2}})\s+(?:{MONTHS})\b", re.IGNORECASE)),
    (
        "periode",
        re.compile(
            r"\b\d+\s+(?:derni(?:er|ère|ere)s|prochain(?:e)?s)\s+(?:jours|semaines|mois|années|annees|ans|trimestres)\b",
            re.IGNORECASE,
        ),
    ),
    ("rang", re.compile(r"\btop[\s-]*\d+\b", re.IGNORECASE)),
    ("rang", re.compile(r"\b\d+\s*(?:er|re|ère|e|eme|ème|ième|ieme)\b", re.IGNORECASE)),
    (
        "rang",
        re.compile(
            r"\b\d+\s+(?:premi(?:er|ère|ere)s|derni(?:er|ère|ere)s|meilleur(?:e)?s|plus\s+(?:gros|grand|fort|faible|petit)\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "multiplicatif",
        re.compile(r"\b(?:deux|trois|quatre|cinq|six|dix|\d+(?:,\d+)?)\s+fois\b", re.IGNORECASE),
    ),
    (
        "multiplicatif",
        re.compile(
            r"\b(?:moitié|moitie|double|doublé|triple|triplé|quadruple|un\s+quart|un\s+tiers|trois\s+quarts)\b",
            re.IGNORECASE,
        ),
    ),
]
_YEAR_RE = re.compile(
    r"(?<![\w{.,])(19\d{2}|20\d{2}|2100)(?!\d|,\d)"
    r"(?!\s*(?:%|pts?\b|points?\b|FCFA|F CFA|XOF|francs?|k\b|K\b|mille|milli|M\b|Mds?\b"
    r"|transactions?|clients?|agents?))"
)
_NUM_RE = re.compile(
    r"(?<![\w{.,])"
    r"([+-]?\d{1,3}(?:[ .]\d{3})+(?![\d])|[+-]?\d+\.\d{1,2}(?![\d.])|[+-]?\d+)"
    r"(?:,(\d+))?"
    r"(?:\s*(k|K|mille|milliers?|M|millions?|Mds?|milliards?)\b)?"
    r"(?:\s*(%|pts?\b|points?(?: de pourcentage)?\b|FCFA\b|F CFA\b|XOF\b|francs?\b))?"
)
_SCALES = {
    "k": 1e3,
    "K": 1e3,
    "mille": 1e3,
    "millier": 1e3,
    "milliers": 1e3,
    "M": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "Md": 1e9,
    "Mds": 1e9,
    "milliard": 1e9,
    "milliards": 1e9,
}


@dataclass(frozen=True)
class NumLiteral:
    raw: str
    start: int
    kind: str  # nombre | annee | date | rang | periode | multiplicatif
    value: float | None = None
    precision: float = 1.0
    unit: str | None = None  # pct | pp | xof | None
    signed: bool = False


def normalize_text(text: str) -> str:
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    text = text.replace("−", "-").replace("–", "-")
    for a, b in (("’", "'"), ("‘", "'"), ("«", '"'), ("»", '"'), ("“", '"'), ("”", '"')):
        text = text.replace(a, b)
    return text


def strip_templates(text: str) -> str:
    return TEMPLATE_RE.sub(" § ", text)


def extract_numeric_literals_fr(text: str) -> list[NumLiteral]:
    """Extrait les nombres écrits en chiffres (et les multiplicatifs en lettres) d'un texte français."""
    t = normalize_text(text)
    found: list[NumLiteral] = []
    masked = list(t)

    def mask(a: int, b: int) -> None:
        for i in range(a, b):
            masked[i] = " "

    for kind, pat in _PRE_PATTERNS:
        for m in pat.finditer("".join(masked)):
            found.append(NumLiteral(raw=m.group(0), start=m.start(), kind=kind))
            mask(m.start(), m.end())
    cur = "".join(masked)
    for m in _YEAR_RE.finditer(cur):
        found.append(NumLiteral(raw=m.group(0), start=m.start(), kind="annee", value=float(m.group(1))))
        mask(m.start(), m.end())
    cur = "".join(masked)
    for m in _NUM_RE.finditer(cur):
        int_part, dec, scale_w, unit_w = m.group(1), m.group(2), m.group(3), m.group(4)
        signed = int_part[0] in "+-"
        neg = int_part.startswith("-")
        body = int_part.lstrip("+-")
        if "." in body and re.fullmatch(r"\d+\.\d{1,2}", body):  # « 1.5 » : décimale anglo-saxonne
            ip, dec = body.split(".")
        else:
            ip = re.sub(r"[ .]", "", body)
        decimals = len(dec) if dec else 0
        mant = float(f"{ip}.{dec}") if dec else float(ip)
        scale = _SCALES.get(scale_w, 1.0) if scale_w else 1.0
        value = mant * scale * (-1 if neg else 1)
        unit = None
        if unit_w:
            u = unit_w.lower()
            unit = "pct" if u == "%" else "pp" if u.startswith("pt") or u.startswith("point") else "xof"
        found.append(
            NumLiteral(
                raw=m.group(0).strip(),
                start=m.start(),
                kind="nombre",
                value=value,
                precision=(10**-decimals) * scale,
                unit=unit,
                signed=signed,
            )
        )
    return sorted(found, key=lambda x: x.start)


def _compatible(lit_unit: str | None, fact_unit: str) -> tuple[bool, float]:
    """(compatible, facteur appliqué à la valeur du fait)."""
    if lit_unit == "pct":
        return (fact_unit == "pct", 1.0) if fact_unit != "ratio" else (True, 100.0)
    if lit_unit == "pp":
        return fact_unit == "pp", 1.0
    if lit_unit == "xof":
        return fact_unit == "xof", 1.0
    return fact_unit in ("count", "xof"), 1.0


def match_fact(lit: NumLiteral, registry: FactRegistry, *, variation_context: bool = False) -> list[str]:
    """Faits dont la valeur correspond au littéral à la demi-unité affichée près."""
    if lit.value is None:
        return []
    half = lit.precision / 2 + 1e-9
    out = []
    for rec in registry.records():
        v = rec.fact.value
        if not isinstance(v, int | float):
            continue
        ok, factor = _compatible(lit.unit, rec.fact.unit)
        if not ok:
            continue
        fv = v * factor
        if abs(lit.value - fv) <= half or (
            (variation_context or lit.signed is False)
            and rec.signed
            and abs(abs(lit.value) - abs(fv)) <= half
        ):
            out.append(rec.fact.id)
    return out


def _matches_truncated_sum(lit: NumLiteral, registry: FactRegistry) -> bool:
    if lit.value is None or lit.unit in ("pct", "pp"):
        return False
    half = lit.precision / 2 + 1e-9
    return any(abs(lit.value - s) <= half for e in registry.entries() for s in e.truncated_sums)


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def causal_violations(text: str, *, allow_hypothesis: bool = True) -> list[str]:
    """Phrases contenant un marqueur causal sans être marquées « hypothèse »."""
    errs = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", normalize_text(text)):
        folded = _fold(sentence)
        hits = [m for m in CAUSAL_FR if _fold(m) in folded]
        if not hits:
            continue
        if allow_hypothesis and "hypothese" in folded:
            continue
        errs.append(
            f"lien de causalité affirmé sans étiquette « hypothèse » (« {hits[0]} ») : "
            f"retire-le ou écris une phrase commençant par « Hypothèse : »."
        )
    return errs


def validate_text(
    text: str,
    registry: FactRegistry,
    *,
    allowed_years: Iterable[int] = (),
    allowed_small_ints: Iterable[int] = (),
    allow_hypothesis: bool = True,
    restrict_to: set[str] | None = None,
    accept_matched_literals: bool = False,
) -> list[str]:
    """Contrôles communs au chat et à l'analyse : références, littéraux, causalité.

    `accept_matched_literals` (ablation e) : un nombre écrit en clair qui correspond à un fait est accepté ;
    il est ensuite remplacé par sa référence (`literals_to_refs`).
    """
    errs: list[str] = []
    years = set(allowed_years)
    smalls = set(allowed_small_ints)
    # 1. Références
    for m in TEMPLATE_RE.finditer(text):
        if m.group(1) == "l":
            if not registry.has_label(m.group(2)):
                errs.append(f"étiquette inconnue {m.group(2)}")
            continue
        fid, fmt = m.group(3), m.group(4)
        if not registry.exists(fid):
            errs.append(f"référence inconnue {fid}")
        elif restrict_to is not None and fid not in restrict_to:
            errs.append(f"référence {fid} hors des faits du constat")
        if fmt and fmt not in ALLOWED_FMT:
            errs.append(
                f"format « {fmt} » non autorisé pour {fid} (autorisés : {', '.join(sorted(ALLOWED_FMT))})"
            )
    if re.search(r"\}\}\s*(%|FCFA|F CFA|XOF|pts?\b|points?\b)", text):
        errs.append("n'ajoute pas d'unité après une référence : le code rend l'unité (%, FCFA, pts).")
    # 2. Littéraux résiduels
    stripped = strip_templates(text)
    norm = normalize_text(stripped)
    for lit in extract_numeric_literals_fr(stripped):
        if lit.kind in ("date", "rang", "periode"):
            continue
        if lit.kind == "annee":
            if lit.value is not None and int(lit.value) in years:
                continue
            errs.append(f"année « {lit.raw} » sans rapport avec la période interrogée")
            continue
        if lit.kind == "multiplicatif":
            errs.append(f"« {lit.raw} » est un calcul : cite un dérivé {{{{d…}}}} (écart, variation, part).")
            continue
        if (
            lit.value is not None
            and lit.unit is None
            and float(lit.value).is_integer()
            and int(lit.value) in smalls
        ):
            continue
        if _matches_truncated_sum(lit, registry):
            errs.append(f"« {lit.raw} » est un total sur un résultat tronqué : interdit.")
            continue
        context = norm[max(0, lit.start - 60) : lit.start]
        ids = match_fact(lit, registry, variation_context=bool(VARIATION_WORDS.search(context)))
        if not ids:
            errs.append(f"nombre non sourcé : « {lit.raw} »")
        elif not accept_matched_literals:
            errs.append(f"écris {{{{{ids[0]}}}}} au lieu de « {lit.raw} »")
    # 4. Causalité
    errs.extend(causal_violations(text, allow_hypothesis=allow_hypothesis))
    return errs


def validate_answer(
    text: str,
    *,
    registry: FactRegistry,
    result_ids: list[str],
    caveats: list[str],
    allowed_years: Iterable[int] = (),
    allowed_small_ints: Iterable[int] = (),
    accept_matched_literals: bool = False,
) -> list[str]:
    """Validation de `submit_answer` ; renvoie la liste des erreurs (vide si valide)."""
    errs = validate_text(
        text,
        registry,
        allowed_years=allowed_years,
        allowed_small_ints=allowed_small_ints,
        accept_matched_literals=accept_matched_literals,
    )
    for rid in result_ids:
        if registry.entry(rid) is None:
            errs.append(f"résultat inconnu {rid}")
    used = [registry.entry(r) for r in result_ids if registry.entry(r) is not None]
    if not used:
        used = registry.data_entries()
    # 3. Tronqués et vides
    for m in TEMPLATE_RE.finditer(text):
        fid = m.group(3)
        if not fid:
            continue
        rec = registry.get(fid)
        entry = registry.entry_of_fact(fid)
        if rec and entry and rec.is_row_sum and entry.result.truncated:
            errs.append(f"{fid} est un total sur un résultat tronqué : interdit.")
    if (
        any(e is not None and e.result.ok and e.result.row_count == 0 for e in used)
        and "resultat_vide" not in caveats
    ):
        errs.append(
            "résultat vide non signalé : ajoute le caveat resultat_vide "
            "et dis qu'aucune donnée ne correspond."
        )
    return errs


def literals_to_refs(text: str, registry: FactRegistry) -> str:
    """Remplace chaque nombre en clair apparié à un fait par sa référence (ablation e).

    Les gabarits existants sont masqués à longueur constante pour garder les positions.
    """
    masked = TEMPLATE_RE.sub(lambda m: "§" * len(m.group(0)), text)
    norm = normalize_text(masked)
    out, last = [], 0
    for lit in extract_numeric_literals_fr(masked):
        if lit.kind not in ("nombre",) or lit.value is None:
            continue
        context = norm[max(0, lit.start - 60) : lit.start]
        ids = match_fact(lit, registry, variation_context=bool(VARIATION_WORDS.search(context)))
        if not ids:
            continue
        out.append(text[last : lit.start])
        out.append("{{" + ids[0] + "}}")
        last = lit.start + len(lit.raw)
    out.append(text[last:])
    return "".join(out)
