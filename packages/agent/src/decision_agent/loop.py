"""Boucle de l'agent (AGENTIC v5 §3.2) : un seul agent, outils contraints, garde-fous déterministes.

Bornes : 6 appels LLM, 8 appels d'outils, 2 corrections SQL par requête, 1 nouvel essai du validateur,
30 s (délai propagé aux outils), plafond de coût par question. Le message « réponds maintenant » réserve
le dernier tour à la rédaction. L'historique de la boucle est en ajout seul (cache, réflexion préservée).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from decision_core.models import (
    AssistantMessage,
    HistoryItem,
    MetricFilter,
    Period,
    QueryLogRecord,
    QueryMetricParams,
    ResolvedState,
    Role,
    StepEvent,
    ToolError,
    ToolResult,
)

from decision_agent import periods
from decision_agent.facts import FactRegistry, ResultEntry, is_ranking
from decision_agent.formatting import (
    choose_chart,
    default_notes,
    evidence_chain,
    render_text,
    scope_label,
    table_from_entry,
    template_answer,
)
from decision_agent.llm import LLMClient, LLMError, LLMRequest, LLMStep, cost_usd_prudent
from decision_agent.prompts import (
    ABLATIONS,
    ANSWER_NOW,
    USE_TERMINAL,
    build_system,
    build_turn_message,
    claude_tools,
    prompt_version,
)
from decision_agent.state import (
    apply_patch,
    make_pending,
    normalize,
    period_from_scope,
    region_kind_needs_clarification,
    resolve_clarification_reply,
    state_from_query_metric,
    state_from_run_query,
)
from decision_agent.tools import CAVEATS, DATA_TOOLS, TERMINAL_TOOLS, ToolClient
from decision_agent.validator import (
    NUMBER_KINDS,
    extract_numeric_literals_fr,
    literals_to_refs,
    validate_answer,
)

EventCb = Callable[[StepEvent], Awaitable[None]] | None
LogCb = Callable[[QueryLogRecord], Awaitable[None]] | None

SQL_FIXABLE = {"sql_error", "guard_blocked", "semantic_warning"}
COST_ESTIMATED = "cout_estime_tarif_max"  # modèle servi absent de PRICING
REFUSAL_MODEL_TEXT = "Je ne peux pas répondre à cette demande."
NO_ANSWER_TEXT = (
    "Je n'ai pas pu produire de réponse vérifiée à cette question. "
    "Reformulez-la en précisant l'indicateur et la période."
)
LLM_ERROR_TEXT = {
    "spend_limit": "Le service d'analyse est temporairement indisponible (plafond de dépenses atteint).",
    "rate_limited": "Le service d'analyse est saturé ; réessayez dans un instant.",
}
REFUSE_DEFAULT = {
    "hors_modele": "Cette question sort du périmètre des données disponibles.",
    "modification_demandee": "Je ne peux que lire les données : aucune modification n'est possible.",
    "contournement": "Je ne peux pas donner suite à cette demande.",
    "donnee_personnelle": "Je ne communique pas d'informations personnelles.",
    "autre": "Je ne peux pas donner suite à cette demande.",
}
TOOL_LABELS = {
    "query_metric": "Calcul d'indicateurs certifiés",
    "run_query": "Calcul ad hoc (SQL)",
    "describe_schema": "Lecture du schéma",
}


@dataclass(frozen=True)
class Limits:
    llm_calls: int = 6
    tool_calls: int = 8
    sql_fixes_per_query: int = 2
    validator_retries: int = 1
    wall_s: float = 30.0
    rows_to_llm: int = 50
    history_exchanges: int = 6
    max_question_chars: int = 1000
    cost_cap_usd: float = 0.10
    max_tokens: int = 8000
    tool_timeout_cap_s: float = 10.0
    max_sql_chars: int = 5000

    @classmethod
    def from_semantic(cls, semantic: Any) -> Limits:
        cfg = semantic.config or {}
        a = cfg.get("agent", {})
        return cls(
            llm_calls=a.get("max_llm_calls", 6),
            tool_calls=a.get("max_tool_calls", 8),
            sql_fixes_per_query=a.get("max_sql_fixes_per_query", 2),
            validator_retries=a.get("validator_retries", 1),
            wall_s=float(a.get("wall_seconds", 30)),
            rows_to_llm=a.get("rows_to_llm", 50),
            history_exchanges=a.get("history_exchanges", 6),
            max_question_chars=a.get("max_question_chars", 1000),
            cost_cap_usd=float(a.get("cost_cap_usd", 0.10)),
            max_tokens=cfg.get("llm", {}).get("max_tokens_per_call", 8000),
            tool_timeout_cap_s=float(cfg.get("sql", {}).get("statement_timeout_s", 10)),
            max_sql_chars=cfg.get("sql", {}).get("max_sql_chars", 5000),
        )


# --- Compilation des paramètres de query_metric (côté agent) -------------------------------------


class CompileError(Exception):
    pass


def _norm_value(v: str, allowed: list[str]) -> str | None:
    n = normalize(v)
    return next((a for a in allowed if normalize(a) == n), None)


def compile_metric_args(
    inp: dict[str, Any], *, reference_date: date, semantic: Any
) -> tuple[QueryMetricParams, Period, Period | None, bool]:
    """Entrée du modèle → QueryMetricParams (période résolue par le code). Lève CompileError."""
    metrics = list(dict.fromkeys(inp.get("metrics") or []))
    if not metrics or len(metrics) > 3:
        raise CompileError("metrics : 1 à 3 KPI distincts.")
    unknown = [m for m in metrics if m not in semantic.metrics]
    if unknown:
        raise CompileError(f"KPI inconnu(s) : {unknown}. Valeurs valides : {sorted(semantic.metrics)}")
    p = inp.get("period") or {}
    kind = p.get("kind", "defaut")
    is_default = False
    try:
        if kind == "absolute":
            if not p.get("start") or not p.get("end"):
                raise CompileError(
                    "period.start et period.end sont requis (AAAA-MM-JJ) quand kind = absolute."
                )
            start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
            if start > end:
                raise CompileError("period.start est postérieur à period.end.")
            period = periods.make_period(start, end)
        elif kind == "relative":
            if not p.get("relative"):
                raise CompileError("period.relative est requis quand kind = relative.")
            period = periods.resolve_relative(p["relative"], reference_date)
        else:
            period = periods.default_period_for(metrics, semantic.metrics, reference_date)
            is_default = True
    except ValueError as e:
        raise CompileError(f"période invalide : {e}") from e
    compare_to = inp.get("compare_to") or "none"
    group_by = list(dict.fromkeys(inp.get("group_by") or []))
    if len(group_by) > 2:
        raise CompileError("group_by : 2 dimensions au plus.")
    filters_in = inp.get("filters") or []
    if len(filters_in) > 4:
        raise CompileError("filters : 4 filtres au plus.")
    filters: list[MetricFilter] = []
    for f in filters_in:
        dim = f.get("dimension")
        values = [str(v) for v in f.get("values") or []]
        if not values or len(values) > 20:
            raise CompileError(f"filtre {dim} : 1 à 20 valeurs.")
        if dim in ("region_agent", "region_client"):
            allowed = list(semantic.kpis.get("regions") or [])
        else:
            allowed = list(semantic.dimensions.get(dim, {}).get("values") or [])
        if allowed:
            fixed = []
            for v in values:
                ok = _norm_value(v, allowed)
                if ok is None:
                    raise CompileError(f"valeur « {v} » inconnue pour {dim}. Valeurs valides : {allowed}")
                fixed.append(ok)
            values = fixed
        filters.append(MetricFilter(dimension=dim, values=values))
    limit = inp.get("limit")
    if limit is not None and not (1 <= int(limit) <= 50):
        raise CompileError("limit : entre 1 et 50.")
    order = inp.get("order") or "none"
    if limit is not None and order == "none":
        order = "desc"
    params = QueryMetricParams(
        metrics=metrics,
        period=period,
        compare_to=compare_to,
        group_by=group_by,
        grain=inp.get("grain") or "none",
        filters=filters,
        order=order,
        limit=limit,
    )
    return params, period, periods.compare_period(period, compare_to), is_default


# --- Agent ----------------------------------------------------------------------------------------


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolClient,
        semantic: Any,
        settings: Any,
        *,
        limits: Limits | None = None,
        ablation: str = "none",
    ) -> None:
        if ablation not in ABLATIONS:
            raise ValueError(f"ablation inconnue : {ablation}")
        self.llm = llm
        self.tools = tools
        self.semantic = semantic
        self.settings = settings
        self.limits = limits or Limits.from_semantic(semantic)
        self.ablation = ablation
        self.system = build_system(semantic, ablation)
        self.claude_tools = claude_tools(ablation)
        self.prompt_version = prompt_version(ablation)

    async def answer(
        self,
        question: str,
        *,
        history: list[HistoryItem],
        state: ResolvedState | None,
        role: Role,
        trace_id: str,
        on_event: EventCb = None,
        on_log: LogCb = None,
    ) -> AssistantMessage:
        run = _Run(
            self,
            question,
            history=history,
            state=state,
            role=role,
            trace_id=trace_id,
            on_event=on_event,
            on_log=on_log,
        )
        return await run.execute()


class _Run:
    """État d'une question (un registre de faits, des compteurs, une échéance)."""

    def __init__(
        self,
        agent: Agent,
        question: str,
        *,
        history: list[HistoryItem],
        state: ResolvedState | None,
        role: Role,
        trace_id: str,
        on_event: EventCb,
        on_log: LogCb,
    ) -> None:
        self.a = agent
        self.lim = agent.limits
        self.question = question
        self.history = history
        self.prev_state = state
        self.role = role
        self.trace_id = trace_id
        self.on_event = on_event
        self.on_log = on_log
        self.ref: date = agent.settings.reference_date
        self.registry = FactRegistry(rows_to_llm=self.lim.rows_to_llm, metric_defs=agent.semantic.metrics)
        self.states: dict[str, ResolvedState] = {}
        self.period_defaults: dict[str, bool] = {}
        self.t0 = time.monotonic()
        self.event_n = 0
        self.llm_calls = 0
        self.tool_calls = 0
        # Corrections SQL comptées par question (pas par `purpose`, contournable en reformulant) :
        # tout run_query qui suit une erreur corrigeable est une correction, comptée avant l'exécution.
        self.sql_errors = 0
        self.sql_fixes = 0
        self.v_retry = 0
        self.cost = 0.0
        self.answer_now_sent = False
        self.clarified: dict[str, Any] = {}
        self.base_state: ResolvedState | None = state

    # --- utilitaires ---------------------------------------------------------------------
    def remaining(self) -> float:
        return self.lim.wall_s - (time.monotonic() - self.t0)

    async def emit(self, kind: str, label: str, tool: str | None = None) -> None:
        self.event_n += 1
        if self.on_event is not None:
            await self.on_event(StepEvent(step=self.event_n, kind=kind, label=label, tool=tool))  # type: ignore[arg-type]

    async def log(self, rec: QueryLogRecord) -> None:
        if self.on_log is not None:
            await self.on_log(rec)

    # --- déroulé -------------------------------------------------------------------------
    async def execute(self) -> AssistantMessage:
        await self.emit("intent", "Analyse de la question")
        q = self.question.strip()
        if not q:
            return self._error("Votre message est vide.")
        if len(q) > self.lim.max_question_chars:
            return self._error(f"Question trop longue (maximum {self.lim.max_question_chars} caractères).")
        pending = self.prev_state.pending_clarification if self.prev_state else None
        if pending is not None:
            patch = resolve_clarification_reply(q, pending)
            if patch is not None:
                q = pending.original_question
                self.base_state = apply_patch(self.prev_state, patch)
                self.clarified = patch
                pending = None
        self.question = q
        user_text = build_turn_message(
            q,
            reference_date=self.ref,
            role=self.role,
            state=self.base_state,
            history=self.history,
            history_n=self.lim.history_exchanges,
            pending=pending,
            clarified=self.clarified or None,
        )
        msgs: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        return await self._loop(msgs)

    async def _loop(self, msgs: list[dict[str, Any]]) -> AssistantMessage:
        while True:
            if self.remaining() <= 1.0 or self.cost >= self.lim.cost_cap_usd:
                return self._template_or(NO_ANSWER_TEXT, reason="budget")
            if not self.answer_now_sent and (
                self.remaining() < 6
                or self.llm_calls >= self.lim.llm_calls - 1
                or self.cost >= 0.8 * self.lim.cost_cap_usd
            ):
                msgs.append({"role": "system", "content": ANSWER_NOW})
                self.answer_now_sent = True
            try:
                step = await self._call_llm(msgs)
            except LLMError as e:
                return self._template_or(
                    LLM_ERROR_TEXT.get(e.kind, "Le service d'analyse est indisponible."), reason="llm_error"
                )
            if step.stop_reason == "refusal":
                return self._message("refusal", REFUSAL_MODEL_TEXT, caveats=["refus_modele"])
            if step.stop_reason in ("max_tokens", "model_context_window_exceeded"):
                return self._template_or(NO_ANSWER_TEXT, reason="max_tokens")
            calls = step.tool_calls
            terminals = [c for c in calls if c["name"] in TERMINAL_TOOLS]
            assistant = {"role": "assistant", "content": step.content}
            if terminals:
                if len(calls) > 1:
                    errors = ["Un outil terminal doit être appelé seul, sans autre outil dans le même tour."]
                    out: AssistantMessage | None = None
                else:
                    await self.emit("validation", "Vérification des chiffres")
                    out, errors = await self._handle_terminal(terminals[0])
                if out is not None:
                    await self.emit("formatting", "Mise en forme de la réponse")
                    return out
                if self.v_retry < self.lim.validator_retries and self.llm_calls < self.lim.llm_calls:
                    self.v_retry += 1
                    msgs.append(assistant)
                    msgs.append(
                        {
                            "role": "user",
                            "content": [
                                _tool_result(
                                    c["id"],
                                    {"errors": errors}
                                    if c in terminals
                                    else {"error": "non exécuté : outil terminal dans le même tour"},
                                    is_error=True,
                                )
                                for c in calls
                            ],
                        }
                    )
                    continue
                return self._template_or(NO_ANSWER_TEXT, reason="validation")
            if not calls:  # texte libre : violation de protocole
                if self.llm_calls >= self.lim.llm_calls:
                    return self._template_or(NO_ANSWER_TEXT, reason="protocol")
                msgs.append(assistant)
                msgs.append({"role": "user", "content": USE_TERMINAL})
                continue
            results = await self._run_data_calls(calls)
            msgs.append(assistant)
            msgs.append({"role": "user", "content": results})  # tous les tool_result dans UN message
            if self.llm_calls >= self.lim.llm_calls:
                return self._template_or(NO_ANSWER_TEXT, reason="budget")

    async def _call_llm(self, msgs: list[dict[str, Any]]) -> LLMStep:
        settings = self.a.settings
        req = LLMRequest(
            model=settings.llm_model,
            system=self.a.system,
            tools=self.a.claude_tools,
            messages=list(msgs),
            effort=settings.llm_effort,
            max_tokens=self.lim.max_tokens,
            deadline_s=max(1.0, self.remaining()),
        )
        self.llm_calls += 1
        step_n = self.llm_calls
        t = time.monotonic()

        async def relay(kind: str, data: dict[str, Any]) -> None:
            if kind == "tool_use_start" and data.get("name") in DATA_TOOLS:
                await self.emit("tool", TOOL_LABELS.get(data["name"], data["name"]), tool=data["name"])

        try:
            step = await self.a.llm.step(req, on_event=relay)
        except LLMError as e:
            await self.log(
                QueryLogRecord(
                    trace_id=self.trace_id,
                    step=step_n,
                    tool="llm",
                    status="error",
                    error_class=f"llm_{e.kind}",
                    duration_ms=int((time.monotonic() - t) * 1000),
                    model_requested=settings.llm_model,
                    effort=settings.llm_effort,
                    request_id=e.request_id,
                    prompt_version=self.a.prompt_version,
                    semantic_version=self.a.semantic.version,
                )
            )
            raise
        # modèle servi inconnu de la table : tarif le plus cher connu (le plafond de coût reste effectif)
        c, estimated = cost_usd_prudent(step.usage, step.model_served or settings.llm_model)
        self.cost += c
        await self.log(
            QueryLogRecord(
                trace_id=self.trace_id,
                step=step_n,
                tool="llm",
                status="ok",
                error_class=COST_ESTIMATED if estimated else None,
                duration_ms=step.latency_ms or int((time.monotonic() - t) * 1000),
                model_requested=settings.llm_model,
                model_served=step.model_served or None,
                effort=settings.llm_effort,
                stop_reason=step.stop_reason,
                request_id=step.request_id,
                ttft_ms=step.ttft_ms,
                tokens_in=step.usage.input_tokens,
                tokens_out=step.usage.output_tokens,
                tokens_cache_read=step.usage.cache_read_tokens,
                tokens_cache_write=step.usage.cache_write_tokens,
                cost_usd=c,
                prompt_version=self.a.prompt_version,
                semantic_version=self.a.semantic.version,
            )
        )
        return step

    # --- outils de données ---------------------------------------------------------------
    async def _run_data_calls(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        plans: list[tuple[dict[str, Any], ToolResult | dict[str, Any]]] = []
        for call in calls:
            plans.append((call, await self._plan(call)))
        # exécution parallèle des appels réellement envoyés au serveur MCP ; enregistrement dans l'ordre
        done = await asyncio.gather(*[p["coro"] for _, p in plans if isinstance(p, dict)])
        it = iter(done)
        out = []
        for call, plan in plans:
            if isinstance(plan, dict):
                res, duration = next(it)
                entry = await self._after_call(call, res, duration, plan)
            else:
                res = plan
                entry = self.registry.register(res)
                await self.log(
                    QueryLogRecord(
                        trace_id=self.trace_id,
                        step=self.llm_calls,
                        attempt=0,
                        tool=call["name"],
                        status="error",
                        error_class=res.error.error_class if res.error else None,
                        duration_ms=0,
                    )
                )
            out.append(_tool_result(call["id"], self.registry.llm_view(entry), is_error=not res.ok))
        return out

    async def _plan(self, call: dict[str, Any]) -> ToolResult | dict[str, Any]:
        name, inp = call["name"], call["input"]
        if name not in DATA_TOOLS:
            return _err(name, "invalid_params", f"Outil inconnu : {name}.")
        self.tool_calls += 1
        if self.answer_now_sent:
            return _err(
                name,
                "invalid_params",
                "Budget atteint : plus d'appel d'outil, réponds avec les faits disponibles.",
            )
        if self.tool_calls > self.lim.tool_calls:
            return _err(
                name, "invalid_params", "Budget d'outils épuisé : réponds avec les faits disponibles."
            )
        timeout = min(self.lim.tool_timeout_cap_s, self.remaining() - 4)
        if timeout < 1:
            return _err(name, "timeout", "Plus assez de temps pour un appel d'outil : réponds maintenant.")
        meta: dict[str, Any] = {"attempt": 0, "period": None, "compare": None, "default": False}
        if name == "query_metric":
            try:
                params, period, cmp, is_default = compile_metric_args(
                    inp, reference_date=self.ref, semantic=self.a.semantic
                )
            except (CompileError, ValueError) as e:
                return _err(name, "invalid_params", str(e))
            enforced = self._enforce_clarified(params)
            if isinstance(enforced, ToolResult):
                return enforced
            args = params.model_dump(mode="json")
            meta.update(period=period, compare=cmp, default=is_default)
        elif name == "run_query":
            sql = str(inp.get("sql") or "")
            if not sql.strip():
                return _err(name, "invalid_params", "sql vide.")
            if len(sql) > self.lim.max_sql_chars:
                return _err(
                    name, "invalid_params", f"SQL trop long (maximum {self.lim.max_sql_chars} caractères)."
                )
            declared = inp.get("declared_scope") or {"statut": "reussie", "region_kind": "aucune"}
            chosen_rk = self._clarified_value("region_kind")
            declared_rk = declared.get("region_kind")
            if chosen_rk and declared_rk in ("region_agent", "region_client") and declared_rk != chosen_rk:
                return _err(
                    name,
                    "invalid_params",
                    f"L'utilisateur a choisi le sens de « région » {chosen_rk} : joins la colonne "
                    f"{chosen_rk} et déclare region_kind = {chosen_rk}.",
                )
            if self.sql_errors > 0:  # correction d'une erreur corrigeable précédente
                self.sql_fixes += 1
                if self.sql_fixes > self.lim.sql_fixes_per_query:
                    return _err(
                        name, "invalid_params", "Trop de corrections ; simplifie ou utilise query_metric."
                    )
                meta["attempt"] = self.sql_fixes
            args = {
                "sql": sql,
                "purpose": str(inp.get("purpose") or "")[:200],
                "declared_scope": declared,
            }
        else:
            args = {"table": inp.get("table")}
        meta["args"] = args

        async def run() -> tuple[ToolResult, int]:
            t = time.monotonic()
            res = await self.a.tools.call(name, args, timeout_s=timeout)
            return res, int((time.monotonic() - t) * 1000)

        meta["coro"] = run()
        return meta

    async def _after_call(
        self, call: dict[str, Any], res: ToolResult, duration: int, meta: dict[str, Any]
    ) -> ResultEntry:
        name = call["name"]
        attempt = meta.get("attempt", 0)
        chosen_rk = self._clarified_value("region_kind")
        if name == "run_query" and res.ok and chosen_rk:
            used_rk = (res.params or {}).get("region_kind")
            if used_rk in ("region_agent", "region_client") and used_rk != chosen_rk:
                # la portée extraite de l'AST contredit le choix de l'utilisateur : résultat écarté
                res = _err(
                    name,
                    "semantic_warning",
                    f"La requête utilise {used_rk} alors que l'utilisateur a choisi {chosen_rk} : "
                    f"corrige la jointure de région.",
                )
        status = (
            "ok"
            if res.ok
            else ("blocked" if res.error and res.error.error_class == "guard_blocked" else "error")
        )
        await self.log(
            QueryLogRecord(
                trace_id=self.trace_id,
                step=self.llm_calls,
                attempt=attempt,
                tool=name,
                status=status,
                error_class=res.error.error_class if res.error else None,
                sql=res.sql,
                row_count=res.row_count if res.ok else None,
                truncated=res.truncated if res.ok else None,
                duration_ms=res.duration_ms or duration,
                semantic_version=self.a.semantic.version,
            )
        )
        if name == "run_query" and not res.ok and res.error and res.error.error_class in SQL_FIXABLE:
            self.sql_errors += 1
        period, cmp = meta.get("period"), meta.get("compare")
        if name == "run_query":
            period = period_from_scope(res.params) if res.ok else None
        # le `purpose` du modèle n'est pas conservé : il ne doit jamais être montré au décideur
        entry = self.registry.register(res, period=period, compare_period=cmp)
        if res.ok and name == "query_metric":
            params = meta["args"]
            self.states[entry.result_id] = state_from_query_metric(
                params,
                period=period,
                compare_period=cmp,
                period_is_default=meta["default"],
                prev=self.base_state,
                question=self.question,
                metric_defs=self.a.semantic.metrics,
                clarified_fields={_field_key(k) for k in self.clarified},
                clarified_values={_field_key(k): v for k, v in self.clarified.items()},
            )
            self.period_defaults[entry.result_id] = meta["default"]
        elif res.ok and name == "run_query":
            self.states[entry.result_id] = state_from_run_query(
                res.params, meta["args"].get("declared_scope"), prev=self.base_state
            )
        return entry

    def _clarified_value(self, field: str) -> Any:
        """Valeur choisie par l'utilisateur pour un champ (après une clarification), sinon None."""
        for k, v in self.clarified.items():
            if _field_key(k) == field:
                return v
        return None

    def _enforce_clarified(self, params: QueryMetricParams) -> ToolResult | None:
        """Aligne les paramètres compilés sur le choix de l'utilisateur (sens de la région, KPI).

        Le sens de la région est corrigé d'office ; un KPI choisi absent rend une erreur actionnable.
        """
        chosen_rk = self._clarified_value("region_kind")
        if chosen_rk in ("region_agent", "region_client"):
            other = "region_client" if chosen_rk == "region_agent" else "region_agent"
            params.group_by = list(dict.fromkeys(chosen_rk if g == other else g for g in params.group_by))
            for f in params.filters:
                if f.dimension == other:
                    f.dimension = chosen_rk  # type: ignore[assignment]
        chosen_kpi = self._clarified_value("metrics")
        if (
            isinstance(chosen_kpi, str)
            and chosen_kpi in self.a.semantic.metrics
            and chosen_kpi not in params.metrics
        ):
            return _err(
                "query_metric",
                "invalid_params",
                f"L'utilisateur a choisi le KPI {chosen_kpi} : inclus-le dans metrics.",
            )
        return None

    def _needs_region_clarification(self, state: ResolvedState) -> bool:
        return bool(
            state.metrics
            and not self.clarified
            and state.region_kind is not None
            and region_kind_needs_clarification(
                state.metrics.value, self.a.semantic.metrics, state.region_kind.source
            )
        )

    def _region_clarification(self) -> AssistantMessage:
        """Clarification du sens de « région » produite par le code (repli, au lieu d'un gabarit)."""
        options = [
            {
                "label": "Région du point de service",
                "patch": {"field": "sens_region", "value": "region_agent"},
            },
            {"label": "Région du client", "patch": {"field": "sens_region", "value": "region_client"}},
        ]
        pending = make_pending(
            self.question, "sens_region", "Quel sens de « région » souhaitez-vous ?", options
        )
        return self._pending_message(pending)

    def _pending_message(self, pending: Any) -> AssistantMessage:
        st = (self.base_state or ResolvedState()).model_copy(deep=True)
        st.pending_clarification = pending
        text = (
            pending.question + "\n" + "\n".join(f"{i}. {o.label}" for i, o in enumerate(pending.options, 1))
        )
        return AssistantMessage(
            kind="clarification", text=text, clarification=pending, resolved_state=st, trace_id=self.trace_id
        )

    # --- outils terminaux ----------------------------------------------------------------
    async def _handle_terminal(self, call: dict[str, Any]) -> tuple[AssistantMessage | None, list[str]]:
        name, inp = call["name"], call["input"]
        if name == "refuse":
            cat = inp.get("category") or "autre"
            reason = str(inp.get("reason") or "").strip()[:300]
            if not reason or any(lit.kind in NUMBER_KINDS for lit in extract_numeric_literals_fr(reason)):
                reason = REFUSE_DEFAULT.get(cat, REFUSE_DEFAULT["autre"])
            return self._message("refusal", reason, caveats=[f"refus_{cat}"]), []
        if name == "ask_clarification":
            return self._clarification(inp)
        return self._submit(inp)

    def _clarification(self, inp: dict[str, Any]) -> tuple[AssistantMessage | None, list[str]]:
        if self.clarified:
            return None, [
                "Une précision vient d'être donnée : applique-la (et le défaut annoncé pour le reste) "
                "et réponds avec submit_answer."
            ]
        options = inp.get("options") or []
        question = str(inp.get("question") or "").strip()
        errs = []
        if not (2 <= len(options) <= 3):
            errs.append("ask_clarification : 2 ou 3 options.")
        if not question or len(question) > 200:
            errs.append("ask_clarification : question requise (≤ 200 caractères).")
        if any(not str(o.get("label") or "").strip() or len(str(o.get("label"))) > 60 for o in options):
            errs.append("ask_clarification : chaque option a un libellé de 60 caractères au plus.")
        if errs:
            return None, errs
        pending = make_pending(self.question, inp.get("missing") or "autre", question, options)
        return self._pending_message(pending), []

    def _primary(self, result_ids: list[str]) -> ResultEntry | None:
        for rid in result_ids:
            e = self.registry.entry(rid)
            if e is not None and e.result.ok and e.result.tool in ("query_metric", "run_query"):
                return e
        return self.registry.last_data_entry()

    def _submit(self, inp: dict[str, Any]) -> tuple[AssistantMessage | None, list[str]]:
        text = str(inp.get("text") or "").strip()
        result_ids = [str(r) for r in inp.get("result_ids") or []]
        model_caveats = [c for c in inp.get("caveats") or [] if c in CAVEATS]
        errs: list[str] = []
        if not text:
            errs.append("text vide.")
        if len(text) > 1200:
            errs.append("text trop long (1 200 caractères au plus).")
        primary = self._primary(result_ids)
        state = self.states.get(primary.result_id) if primary else None
        state = state or (self.base_state or ResolvedState()).model_copy(
            update={"pending_clarification": None}
        )
        years = {self.ref.year, self.ref.year - 1}
        for e in self.registry.data_entries():
            for p in (e.period, e.compare_period):
                if p is not None:
                    years.update({p.start.year, p.end.year})
        smalls = {
            int(e.result.params.get("limit"))
            for e in self.registry.data_entries()
            if e.result.params and e.result.params.get("limit")
        }
        smalls |= {
            len(e.result.rows)
            for e in self.registry.data_entries()
            if e.result.params and e.result.params.get("limit")
        }
        counts, numbers = self._allowed_counts_and_numbers()
        errs += validate_answer(
            text,
            registry=self.registry,
            result_ids=result_ids,
            caveats=model_caveats,
            allowed_years=years,
            allowed_small_ints=smalls,
            accept_matched_literals=self.a.ablation == "e",
            allowed_counts=counts,
            allowed_numbers=numbers,
            role=self.role,
        )
        if self.a.ablation == "d":  # sans validateur : seules les erreurs qui empêchent le rendu restent
            errs = [
                e
                for e in errs
                if e.startswith(("référence inconnue", "étiquette inconnue", "résultat inconnu"))
            ]
        if self.a.ablation == "e" and not errs:
            text = literals_to_refs(text, self.registry)
        # Politique par champ : sens de « région » non précisé pour un KPI sans défaut
        if self._needs_region_clarification(state):
            errs.append(
                "Sens de « région » non précisé pour un KPI sans défaut : utilise ask_clarification "
                "(missing = sens_region, options region_agent / region_client)."
            )
        if errs:
            return None, errs
        return self._finalize(text, result_ids, model_caveats, inp.get("follow_up") or [], primary, state), []

    def _allowed_counts_and_numbers(self) -> tuple[set[int], set[int]]:
        """Comptages (lignes, catégories, régions du référentiel, jours de la période) et numéros de
        semaine ou de mois (données et périodes) que le texte peut citer en clair."""
        counts: set[int] = set()
        regions = self.a.semantic.kpis.get("regions") or []
        if regions:
            counts.add(len(regions))
        numbers: set[int] = set()
        for e in self.registry.data_entries():
            res = e.result
            counts.update({len(res.rows), res.row_count})
            for j, col in enumerate(res.columns):
                vals = [r[j] for r in res.rows if j < len(r)]
                if col.role == "dimension":
                    counts.add(len({str(v) for v in vals}))
                if col.role == "time" or col.name in ("semaine", "week", "mois", "month"):
                    for v in vals:
                        numbers.update(_period_numbers(v, col.name))
            for p in (e.period, e.compare_period):
                if p is None:
                    continue
                n_days = (p.end - p.start).days + 1
                counts.add(n_days)
                for i in range(min(n_days, 400)):
                    d = p.start + timedelta(days=i)
                    numbers.update({d.isocalendar()[1], d.month})
        counts.discard(0)
        return counts, numbers

    def _finalize(
        self,
        text: str,
        result_ids: list[str],
        model_caveats: list[str],
        follow_up: list[str],
        primary: ResultEntry | None,
        state: ResolvedState,
    ) -> AssistantMessage:
        used = [self.registry.entry(r) for r in result_ids if self.registry.entry(r) is not None]
        used = [e for e in used if e and e.result.ok and e.result.tool != "describe_schema"] or (
            [primary] if primary else []
        )
        caveats = list(dict.fromkeys(model_caveats))
        notes = []
        if any(e.result.truncated for e in used):
            caveats.append("resultat_tronque")
        if any(not e.result.certified for e in used):
            caveats.append("calcul_ad_hoc")
        d_caveats, d_notes = default_notes(state)
        caveats += d_caveats
        notes += d_notes
        rendered = render_text(self.registry.deopaque(text), self.registry)
        if notes:
            rendered += "\n" + " ".join(notes)
        follow = []
        for f in follow_up[:3]:
            f = str(f).strip()
            if (
                f
                and len(f) <= 150
                and not any(lit.kind in NUMBER_KINDS for lit in extract_numeric_literals_fr(f))
            ):
                follow.append(f)
        msg = AssistantMessage(
            kind="answer",
            text=rendered,
            follow_up=follow,
            caveats=list(dict.fromkeys(caveats)),
            resolved_state=state,
            trace_id=self.trace_id,
        )
        if primary is not None:
            res = primary.result
            metrics = (res.params or {}).get("metrics") or []
            additive = bool(metrics) and all(
                self.a.semantic.metrics.get(m, {}).get("additive") for m in metrics
            )
            msg.period = primary.period
            msg.table = table_from_entry(primary)
            msg.truncated = res.truncated
            msg.chart = choose_chart(
                res.columns, res.rows, additive=additive, truncated=res.truncated, ranking=is_ranking(res)
            )
            msg.evidence = evidence_chain(primary, self.a.semantic)
        data = self.registry.data_entries()
        msg.tables = sorted({t for e in data for t in e.result.tables})
        sqls = [e.result.sql for e in data if e.result.sql]
        msg.sql = sqls or None
        msg.certified = bool(used) and all(e.result.certified for e in used)
        msg.scope = scope_label(state)
        msg.facts = self.registry.public_facts()
        return msg

    # --- sorties de repli ----------------------------------------------------------------
    def _final_state(self) -> ResolvedState:
        entry = self.registry.last_data_entry()
        st = self.states.get(entry.result_id) if entry else None
        return st or (self.base_state or ResolvedState()).model_copy(update={"pending_clarification": None})

    def _template_or(self, text: str, *, reason: str) -> AssistantMessage:
        state = self._final_state()
        if self._needs_region_clarification(state):
            # pas de gabarit sur un sens de « région » choisi sans fondement : on le demande
            return self._region_clarification()
        msg = template_answer(self.registry, state, self.a.semantic, trace_id=self.trace_id, reason=reason)
        if msg is not None:
            msg.facts = self.registry.public_facts()
            return msg
        return self._error(text)

    def _message(self, kind: str, text: str, *, caveats: list[str] | None = None) -> AssistantMessage:
        return AssistantMessage(
            kind=kind,
            text=text,
            caveats=caveats or [],
            resolved_state=self._final_state(),  # type: ignore[arg-type]
            trace_id=self.trace_id,
        )

    def _error(self, text: str) -> AssistantMessage:
        return self._message("error", text)


def _period_numbers(v: Any, col_name: str) -> set[int]:
    """Numéros de semaine / mois d'une valeur de colonne temporelle (entier, date ou texte ISO)."""
    if isinstance(v, bool) or v is None:
        return set()
    if isinstance(v, int):
        return {v} if 1 <= v <= 53 else set()
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        m = re.search(r"(?:W|S|-)(\d{1,2})$", str(v))
        return {int(m.group(1))} if m else set()
    if col_name in ("mois", "month"):
        return {d.month}
    return {d.isocalendar()[1], d.month}


def _field_key(k: str) -> str:
    return {"periode": "period", "kpi": "metrics", "perimetre": "scope", "sens_region": "region_kind"}.get(
        k, k
    )


def _err(tool: str, error_class: str, message: str) -> ToolResult:
    t = tool if tool in DATA_TOOLS else "describe_schema"
    return ToolResult(tool=t, ok=False, error=ToolError(error_class=error_class, message=message))  # type: ignore[arg-type]


def _tool_result(tool_use_id: str, payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }
    if is_error:
        block["is_error"] = True
    return block
