"""Schéma et chargement des jeux d'évaluation (eval/*.yaml).

Un item décrit une question (ou un script multi-tours), l'intention attendue et, pour les réponses,
le SQL de référence. Les valeurs de référence ne sont jamais écrites dans les fichiers : elles sont
recalculées à chaque exécution en lançant `reference_sql` avec le rôle agent_ro.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["answer", "clarification", "refusal"]

CATEGORIES_TEST: dict[str, int] = {
    "kpi_simple": 8,
    "comparaison": 6,
    "classement": 6,
    "clients_agents": 4,
    "ambigu_hors_perimetre": 6,
    "suivi": 4,
    "piege_glossaire": 6,
}

REFERENCE_DATE = date(2026, 9, 30)
INTENT_ONLY_SPLITS = frozenset({"intent"})
DATA_START = date(2025, 4, 1)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedPeriod(_M):
    start: date
    end: date


class ExpectedScope(_M):
    # region_agent | region_client ; None ou "aucune" = non vérifié
    region_kind: Literal["region_agent", "region_client", "aucune"] | None = None
    # dimension -> valeurs (dimensions de query_metric : region_agent, region_client, type, segment, agent)
    filters: dict[str, list[str]] = Field(default_factory=dict)


class ScriptedAnswer(_M):
    """Réponse écrite à l'avance pour un tour d'historique (variante A, et réponse de clarification)."""

    kind: Literal["answer", "clarification", "refusal"] = "answer"
    text: str
    # Les marqueurs {v0}, {v1}… sont remplacés par les valeurs de la 1re ligne de reference_sql.
    reference_sql: str | None = None
    resolved_state: dict[str, Any] = Field(default_factory=dict)
    clarification: dict[str, Any] | None = None


class Injection(_M):
    """Injection indirecte : `nom` est écrit dans analytics.dim_agent pour les agent_id renvoyés par
    `target_sql` (base de test uniquement), puis restauré après le scénario."""

    target_sql: str
    nom: str


class Turn(_M):
    question: str
    answer: ScriptedAnswer | None = None  # présent : tour scripté ; absent : tour joué par l'agent
    expected_kind: Kind | None = None  # pour un tour intermédiaire joué (variantes B et C)


class EvalItem(_M):
    id: str
    category: str
    trap: str | None = None
    variant: Literal["A", "B", "C"] | None = None  # suivi de conversation
    question: str | None = None
    turns: list[Turn] | None = None  # suivi : tours précédents ; le dernier est la question évaluée
    expected_kind: Kind
    accept_kinds: list[Kind] = Field(default_factory=list)  # autres intentions acceptées
    reference_sql: str | None = None
    expected_period: ExpectedPeriod | None = None
    expected_scope: ExpectedScope | None = None
    ordered: bool = False
    order_by: list[str] = Field(default_factory=list)  # colonnes de référence portant le classement
    tie_tolerant: bool = False
    prefix_ok: bool = False  # classement : lignes supplémentaires tolérées après les k premières
    expected_empty: bool = False
    column_groups: list[list[str]] = Field(default_factory=list)  # au moins une colonne par groupe
    must_cite: list[str] | None = None  # colonnes de référence dont la valeur doit être citée
    tolerate_hors_agent_zero: bool = False  # ignore une ligne « Non applicable »/« Hors agent » à zéro
    # Sécurité (injection indirecte)
    inject: Injection | None = None
    canary: str | None = None
    forbidden_in_text: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> EvalItem:
        if (self.question is None) == (self.turns is None):
            raise ValueError(f"{self.id} : exactement un de `question` ou `turns`")
        if self.turns is not None and (not self.turns or self.turns[-1].answer is not None):
            raise ValueError(f"{self.id} : le dernier tour doit être la question évaluée (sans answer)")
        if self.expected_kind != "answer" and self.reference_sql:
            raise ValueError(f"{self.id} : reference_sql inutile hors réponse")
        if self.tie_tolerant and not self.order_by:
            raise ValueError(f"{self.id} : tie_tolerant exige order_by")
        if (self.order_by or self.prefix_ok) and not self.ordered:
            raise ValueError(f"{self.id} : order_by/prefix_ok exigent ordered")
        return self

    def check_gradable(self) -> None:
        """Contrôles d'un item noté en entier (hors jeu d'intention, noté sur l'intention seule)."""
        if self.expected_kind == "answer" and not self.reference_sql:
            raise ValueError(f"{self.id} : reference_sql obligatoire pour expected_kind=answer")
        if self.expected_kind == "answer" and self.expected_period is None and not self.notes:
            raise ValueError(f"{self.id} : expected_period manquant (ou justifier dans notes)")

    @property
    def final_question(self) -> str:
        if self.question is not None:
            return self.question
        assert self.turns is not None
        return self.turns[-1].question

    @property
    def kinds(self) -> set[str]:
        return {self.expected_kind, *self.accept_kinds}


class Dataset(_M):
    split: str
    reference_date: date = REFERENCE_DATE
    description: str | None = None
    items: list[EvalItem]

    @model_validator(mode="after")
    def _unique(self) -> Dataset:
        ids = [i.id for i in self.items]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"identifiants dupliqués : {sorted(dup)}")
        if self.split not in INTENT_ONLY_SPLITS:
            for it in self.items:
                it.check_gradable()
        return self

    @property
    def intent_only(self) -> bool:
        return self.split in INTENT_ONLY_SPLITS


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "semantic" / "kpis.yaml").exists():
            return parent
    return Path.cwd()


def eval_dir() -> Path:
    return repo_root() / "eval"


def load_dataset(path: Path | str) -> Dataset:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Dataset.model_validate(data)


def split_path(split: str, base: Path | None = None) -> Path:
    return (base or eval_dir()) / f"{split}.yaml"


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def category_counts(ds: Dataset) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in ds.items:
        out[it.category] = out.get(it.category, 0) + 1
    return out
