"""Faux agents pour tester l'exécuteur sans clé API ni serveur MCP.

- `OracleAgent` : répond à partir des références d'un jeu (résultat, faits, état résolu) ; un mode
  `corrupt` dégrade une partie des réponses pour vérifier que le correcteur les rejette.
- `ScriptedAgent` : renvoie des messages fournis à l'avance, question par question.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from decision_core.models import (
    AssistantMessage,
    ColumnInfo,
    Fact,
    HistoryItem,
    PendingClarification,
    QueryLogRecord,
    ResolvedField,
    ResolvedState,
    StepEvent,
    TableData,
)

from .compare import ResultSet, is_integral, is_number
from .dataset import Dataset, EvalItem
from .refs import ReferenceExecutor
from .runner import AgentHandle


def _col_type(values: list[Any]) -> tuple[str, str]:
    vs = [v for v in values if v is not None]
    if vs and all(is_number(v) for v in vs):
        return ("integer" if all(is_integral(v) for v in vs) else "numeric"), "measure"
    if vs and all(isinstance(v, date) for v in vs):
        return "date", "time"
    return "text", "dimension"


def message_from_reference(item: EvalItem, ref: ResultSet | None) -> AssistantMessage:
    """Réponse « parfaite » construite depuis la référence et les attendus de l'item."""
    if item.expected_kind == "clarification":
        return AssistantMessage(
            kind="clarification",
            text="Précisez votre demande.",
            clarification=PendingClarification(
                original_question=item.final_question,
                missing=["kpi"],
                question="Quel indicateur ?",
                options=[
                    {"label": "Volume", "patch": {"kpi": "volume_transactions"}},
                    {"label": "Valeur", "patch": {"kpi": "valeur_transferee"}},
                ],
            ),
        )
    if item.expected_kind == "refusal":
        return AssistantMessage(kind="refusal", text="Je ne peux pas répondre à cette demande.")
    ref = ref or ResultSet([], [])
    cols = []
    for j, name in enumerate(ref.columns):
        typ, role = _col_type(ref.column(j))
        cols.append(ColumnInfo(name=name, type=typ, role=role))  # type: ignore[arg-type]
    rows = [[_plain(v) for v in r] for r in ref.rows]
    facts: list[Fact] = []
    for r in rows[:5]:
        for v in r:
            if is_number(v):
                unit = "count" if is_integral(v) else "ratio"
                facts.append(
                    Fact(id=f"f{len(facts) + 1}", value=v, unit=unit, label="valeur", rendered=str(v))
                )
    state = ResolvedState(certified=True)
    if item.expected_period:
        state.period = ResolvedField(
            value={
                "start": item.expected_period.start.isoformat(),
                "end": item.expected_period.end.isoformat(),
            },
            source="explicite",
        )
    if item.expected_scope:
        if item.expected_scope.region_kind and item.expected_scope.region_kind != "aucune":
            state.region_kind = ResolvedField(value=item.expected_scope.region_kind, source="explicite")
        state.scope = ResolvedField(
            value={
                "filters": [{"dimension": d, "values": v} for d, v in item.expected_scope.filters.items()]
            },
            source="explicite",
        )
    caveats = ["resultat_vide"] if not rows else []
    return AssistantMessage(
        kind="answer",
        text="Réponse.",
        table=TableData(columns=cols, rows=rows),
        facts=facts,
        resolved_state=state,
        caveats=caveats,
        sql=["SELECT 1"],
        certified=True,
    )


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


class OracleAgent:
    """Agent factice : retrouve l'item par sa question finale et répond depuis la référence."""

    def __init__(
        self,
        dataset: Dataset,
        executor: ReferenceExecutor,
        *,
        corrupt: Callable[[EvalItem, AssistantMessage], AssistantMessage] | None = None,
        cost_usd: float = 0.01,
    ) -> None:
        self.by_question = {it.final_question: it for it in dataset.items}
        self.turn_kinds = {
            t.question: t.expected_kind
            for it in dataset.items
            for t in (it.turns or [])[:-1]
            if t.answer is None and t.expected_kind
        }
        self.executor = executor
        self.corrupt = corrupt
        self.cost_usd = cost_usd
        self.calls: list[dict[str, Any]] = []

    async def answer(
        self,
        question: str,
        *,
        history: list[HistoryItem],
        state: ResolvedState | None,
        role: Any,
        trace_id: str,
        on_event: Callable[[StepEvent], Awaitable[None]] | None = None,
        on_log: Callable[[QueryLogRecord], Awaitable[None]] | None = None,
    ) -> AssistantMessage:
        self.calls.append(
            {"question": question, "history": len(history), "state": state, "trace_id": trace_id}
        )
        if on_log is not None:
            await on_log(
                QueryLogRecord(
                    trace_id=trace_id,
                    step=1,
                    tool="llm",
                    status="ok",
                    duration_ms=5,
                    model_requested="fake",
                    model_served="fake-1",
                    effort="medium",
                    tokens_in=100,
                    tokens_out=10,
                    cost_usd=self.cost_usd,
                    prompt_version="fake-prompt",
                )
            )
        item = self.by_question.get(question)
        if item is None:  # tour intermédiaire joué (variantes B et C)
            if self.turn_kinds.get(question) == "clarification":
                return AssistantMessage(
                    kind="clarification", text="Région du client ou du point de service ?"
                )
            return AssistantMessage(kind="answer", text="Réponse intermédiaire.")
        try:
            ref = self.executor.run(item.reference_sql) if item.reference_sql else None
        except Exception:  # noqa: BLE001 - référence absente : réponse sans résultat
            ref = None
        msg = message_from_reference(item, ref)
        if self.corrupt is not None:
            msg = self.corrupt(item, msg)
        return msg


def oracle_factory(agent: Any) -> Callable[[str], contextlib.AbstractAsyncContextManager[AgentHandle]]:
    @contextlib.asynccontextmanager
    async def factory(ablation: str) -> AsyncIterator[AgentHandle]:
        yield AgentHandle(agent, model_requested="fake", effort="medium", prompt_version="fake-prompt")

    return factory
