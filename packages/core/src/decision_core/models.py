"""Contrats partagés entre le serveur MCP, l'agent, l'API et l'évaluation.

Ces modèles sont la seule définition des échanges ; les types TypeScript de l'interface en seront générés.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["decideur", "analyste", "admin"]
Unit = Literal["count", "xof", "ratio", "pct", "pp", "text", "date", "id"]
ColumnRole = Literal["dimension", "measure", "time", "period"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Paramètres de `query_metric` -------------------------------------------------------------


class Period(_Model):
    start: date
    end: date
    label: str | None = None  # libellé français calculé par le code (« mars 2026 »)


class MetricFilter(_Model):
    dimension: Literal["region_agent", "region_client", "type", "segment", "agent"]
    values: list[str] = Field(min_length=1, max_length=20)


class QueryMetricParams(_Model):
    """Entrée de l'outil `query_metric` (chemin certifié, compilé depuis semantic/kpis.yaml)."""

    metrics: list[str] = Field(min_length=1, max_length=6)
    period: Period
    compare_to: Literal["none", "previous_period", "previous_year"] = "none"
    group_by: list[Literal["region_agent", "region_client", "type", "segment", "agent"]] = Field(
        default_factory=list, max_length=2
    )
    grain: Literal["none", "day", "week", "month", "quarter"] = "none"
    filters: list[MetricFilter] = Field(default_factory=list)
    order: Literal["none", "desc", "asc"] = "none"
    limit: int | None = Field(default=None, ge=1, le=50)


# --- Résultat d'un outil de données (structuredContent MCP) ----------------------------------


class ColumnInfo(_Model):
    name: str
    type: str  # type Postgres normalisé : integer, numeric, text, date, boolean, timestamptz
    role: ColumnRole
    unit: Unit | None = None
    label: str | None = None
    # Projection dérivée d'une colonne `free_text: true` de tables.yaml (nom, ville), même sous un alias ou
    # une fonction : calculé par le serveur MCP depuis l'AST ; l'agent opacifie d'après ce drapeau.
    free_text: bool = False


class ToolError(_Model):
    error_class: Literal[
        "guard_blocked",  # refus du garde SQL (status = blocked dans query_log)
        "semantic_warning",  # règle de cohérence sémantique non respectée
        "invalid_params",  # paramètres hors énumération, dimension non supportée…
        "sql_error",  # erreur Postgres normalisée (corrigeable)
        "timeout",
        "internal",
    ]
    message: str  # actionnable par le modèle, sans secret
    hint: str | None = None  # ex. définition canonique du KPI


class ToolResult(_Model):
    """Retour de `query_metric`, `run_query`, `describe_schema` (contrat unique, SRS v5 §8)."""

    tool: Literal["query_metric", "run_query", "describe_schema"]
    ok: bool
    sql: str | None = None  # SQL réécrit depuis l'AST validé : la seule version exécutée
    columns: list[ColumnInfo] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)  # au plus sql.row_limit lignes
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    certified: bool = False  # True pour query_metric
    params: dict[str, Any] | None = None  # paramètres compilés (query_metric) ou portée extraite (run_query)
    tables: list[str] = Field(default_factory=list)  # tables analytics utilisées
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None
    payload: dict[str, Any] | None = None  # describe_schema : métadonnées normalisées


# --- État résolu et message de l'assistant ---------------------------------------------------

FieldSource = Literal["explicite", "herite", "defaut"]


class ResolvedField(_Model):
    value: Any
    source: FieldSource


class ClarificationOption(_Model):
    label: str
    patch: dict[str, Any]  # champ(s) de l'état résolu fixés par ce choix


class PendingClarification(_Model):
    original_question: str
    missing: list[str]
    question: str
    options: list[ClarificationOption] = Field(min_length=2, max_length=3)


class ResolvedState(_Model):
    """Produit par le code à partir des appels exécutés (jamais par le LLM)."""

    metrics: ResolvedField | None = None
    period: ResolvedField | None = None
    compare_to: ResolvedField | None = None
    region_kind: ResolvedField | None = None
    scope: ResolvedField | None = None  # périmètre géographique et filtres
    group_by: ResolvedField | None = None
    certified: bool = False
    pending_clarification: PendingClarification | None = None


class Fact(_Model):
    """Valeur citable : cellule d'un résultat (f…) ou dérivé calculé par le code (d…)."""

    id: str
    value: float | int | str | None
    unit: Unit
    label: str
    result_index: int | None = None
    rendered: str | None = None  # libellé exact affiché


class EvidenceStep(_Model):
    """Maillon de la chaîne de preuve (ENF6), visible par le décideur sans SQL."""

    kind: Literal["table", "filtre", "periode", "operation"]
    label: str


class Chart(_Model):
    type: Literal["line", "bar", "donut", "kpi", "table"]
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None


class TableData(_Model):
    columns: list[ColumnInfo]
    rows: list[list[Any]]


class AssistantMessage(_Model):
    """Message final validé (SYSTEM_DESIGN v5 §5). `sql` est retiré côté serveur pour le décideur."""

    kind: Literal["answer", "clarification", "refusal", "error"]
    text: str  # texte rendu par le code (gabarits {{f}} remplacés)
    period: Period | None = None
    scope: str | None = None
    table: TableData | None = None
    truncated: bool = False
    chart: Chart | None = None
    tables: list[str] = Field(default_factory=list)
    sql: list[str] | None = None
    evidence: list[EvidenceStep] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    certified: bool = False
    simplified: bool = False  # True si repli par réponse gabarit
    clarification: PendingClarification | None = None
    follow_up: list[str] = Field(default_factory=list)
    resolved_state: ResolvedState = Field(default_factory=ResolvedState)
    trace_id: str | None = None

    def for_role(self, role: Role) -> AssistantMessage:
        """Filtrage côté serveur (S5) : le décideur ne reçoit jamais le SQL."""
        if role == "decideur":
            return self.model_copy(update={"sql": None})
        return self


class StepEvent(_Model):
    """Événement d'étape émis pendant le calcul (SSE `step`)."""

    step: int
    kind: Literal["intent", "tool", "validation", "formatting"]
    label: str  # texte affiché et annoncé aux lecteurs d'écran
    tool: str | None = None


# --- Analyse du tableau de bord (RF17) ------------------------------------------------------


class AnalysisFinding(_Model):
    tag: Literal["Hausse", "Baisse", "À surveiller", "Écart", "Écart favorable"]
    text: str
    confidence: Literal["elevee", "moyenne", "hypothese"]
    sources: list[str]  # identifiants de faits
    hypothesis: str | None = None  # toujours étiquetée « hypothèse » à l'affichage


class DashboardAnalysis(_Model):
    period: Period
    region: str | None
    lead: str
    findings: list[AnalysisFinding] = Field(max_length=3)
    follow_up: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    semantic_version: str
    model_id: str | None = None
    available: bool = True


# --- Journalisation (écrite par l'API seule dans app.query_log, ENF5) -----------------------


class QueryLogRecord(_Model):
    """Une ligne de app.query_log : un appel d'outil (tool = query_metric…) ou un appel LLM (tool = llm)."""

    trace_id: str
    step: int
    attempt: int = 0
    tool: str
    status: Literal["ok", "error", "blocked"]
    error_class: str | None = None
    sql: str | None = None
    row_count: int | None = None
    truncated: bool | None = None
    duration_ms: int
    # Champs propres aux appels LLM
    model_requested: str | None = None
    model_served: str | None = None
    effort: str | None = None
    stop_reason: str | None = None
    request_id: str | None = None
    ttft_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cache_read: int | None = None
    tokens_cache_write: int | None = None
    cost_usd: float | None = None
    prompt_version: str | None = None
    semantic_version: str | None = None


class HistoryItem(_Model):
    """Un échange passé, rejoué à l'agent (6 derniers) : question et réponse validée."""

    question: str
    answer: AssistantMessage
