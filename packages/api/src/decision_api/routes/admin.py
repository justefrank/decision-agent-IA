"""Back-office en lecture (MVP v5). Les rôles sont vérifiés ici, côté serveur.

- analyste et admin : vue d'ensemble, journal d'audit (RF13), évaluation, signalements, catalogue ;
- admin seul : sécurité (RF20) et paramètres.

Le journal n'expose jamais le texte des questions (`question_hash` seulement). Le détail d'un appel
et l'export CSV écrivent `app.audit_access_log` AVANT de renvoyer les données.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, and_, case, func, insert, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api import models as m
from decision_api.auth import User
from decision_api.deps import AdminDep, AnalystDep, RuntimeDep, SessionDep, SettingsDep
from decision_api.errors import ApiError
from decision_api.routes.core import health_snapshot

router = APIRouter(prefix="/admin", tags=["back-office"])
log = logging.getLogger("decision_api.admin")

RANGES = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
RangeParam = Literal["24h", "7d", "30d", "90d"]
DATA_TOOLS = ("query_metric", "run_query", "describe_schema")

# Matrice de droits appliquée par l'API (documentation affichée dans la vue sécurité).
ROLE_MATRIX = {
    "decideur": ["questions", "tableau de bord", "analyse", "historique personnel", "signalement"],
    "analyste": [
        "decideur + SQL",
        "vue d'ensemble",
        "journal d'audit",
        "évaluation",
        "signalements",
        "catalogue et couche sémantique",
    ],
    "admin": ["analyste", "sécurité", "paramètres (lecture)"],
}


def _since(range_: str) -> datetime:
    return datetime.now(UTC) - RANGES[range_]


async def audit_access(
    session: AsyncSession,
    user: User,
    action: str,
    *,
    target_trace_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Écrit une ligne d'audit dans sa propre transaction (validée avant la réponse)."""
    if session.in_transaction():
        await session.rollback()
    async with session.begin():
        await session.execute(
            insert(m.audit_access_log).values(
                actor_sub=user.sub,
                actor_role=user.role,
                action=action,
                target_trace_id=target_trace_id,
                details=details,
            )
        )


# --- Vue d'ensemble --------------------------------------------------------------------------


@router.get("/overview")
async def overview(
    request: Request, user: AnalystDep, session: SessionDep, range: RangeParam = "7d"
) -> dict[str, Any]:  # noqa: A002
    since = _since(range)
    ql = m.query_log.c
    agg = (
        await session.execute(
            select(
                func.count(func.distinct(ql.trace_id)).label("traces"),
                func.count().filter(ql.tool.in_(DATA_TOOLS)).label("tool_calls"),
                func.count().filter(and_(ql.tool.in_(DATA_TOOLS), ql.status == "blocked")).label("blocked"),
                func.count().filter(ql.status == "error").label("errors"),
                func.count().filter(ql.tool == "llm").label("llm_calls"),
                func.coalesce(func.sum(ql.cost_usd), 0).label("cost_usd"),
                func.coalesce(func.sum(ql.tokens_in), 0).label("tokens_in"),
                func.coalesce(func.sum(ql.tokens_out), 0).label("tokens_out"),
                func.coalesce(func.sum(ql.tokens_cache_read), 0).label("cache_read"),
                func.coalesce(func.sum(ql.tokens_cache_write), 0).label("cache_write"),
            ).where(ql.ts >= since)
        )
    ).one()
    mc = m.message.c
    lat = (
        await session.execute(
            select(
                func.count().label("answers"),
                func.percentile_cont(0.5).within_group(mc.latency_ms).label("p50"),
                func.percentile_cont(0.9).within_group(mc.latency_ms).label("p90"),
            ).where(mc.role == "assistant", mc.created_at >= since, mc.latency_ms.is_not(None))
        )
    ).one()
    questions = (
        await session.execute(select(func.count()).where(mc.role == "user", mc.created_at >= since))
    ).scalar_one()
    await session.rollback()
    cache_den = int(agg.cache_read) + int(agg.cache_write) + int(agg.tokens_in)
    cost = float(agg.cost_usd)
    return {
        "range": range,
        "since": since.isoformat(),
        "questions": int(questions),
        "traces": int(agg.traces),
        "answers": int(lat.answers),
        "latency_ms": {"p50": _num(lat.p50), "p90": _num(lat.p90)},
        "cost_usd": {
            "total": round(cost, 6),
            "per_trace": round(cost / agg.traces, 6) if agg.traces else None,
        },
        "tokens": {
            "in": int(agg.tokens_in),
            "out": int(agg.tokens_out),
            "cache_read": int(agg.cache_read),
            "cache_write": int(agg.cache_write),
            "cache_read_rate": round(int(agg.cache_read) / cache_den, 4) if cache_den else None,
        },
        "tool_calls": int(agg.tool_calls),
        "llm_calls": int(agg.llm_calls),
        "errors": int(agg.errors),
        "guard": {
            "blocked": int(agg.blocked),
            "block_rate": round(agg.blocked / agg.tool_calls, 4) if agg.tool_calls else None,
        },
        "health": await health_snapshot(request),
    }


def _num(value: Any) -> float | None:
    return None if value is None else round(float(value), 1)


# --- Journal d'audit (RF13) ------------------------------------------------------------------


def _filters(
    date_from: datetime | None = Query(default=None, alias="from"),  # noqa: B008
    date_to: datetime | None = Query(default=None, alias="to"),  # noqa: B008
    status: Literal["ok", "error", "blocked"] | None = None,
    tool: str | None = Query(default=None, max_length=64),  # noqa: B008
    trace_id: str | None = Query(default=None, max_length=64),  # noqa: B008
    user_ref: str | None = Query(default=None, max_length=128),  # noqa: B008
    error_class: str | None = Query(default=None, max_length=64),  # noqa: B008
) -> list[Any]:
    ql = m.query_log.c
    conds: list[Any] = []
    if date_from:
        conds.append(ql.ts >= date_from)
    if date_to:
        conds.append(ql.ts < date_to)
    if tool:
        conds.append(ql.tool == tool)
    if trace_id:
        conds.append(ql.trace_id == trace_id)
    if user_ref:
        conds.append(ql.user_ref == user_ref)
    if error_class:
        conds.append(ql.error_class == error_class)
    if status:
        # Filtre au niveau de la trace : au moins un appel avec ce statut.
        sub = select(m.query_log.c.trace_id).where(m.query_log.c.status == status)
        conds.append(ql.trace_id.in_(sub))
    return conds


FiltersDep = Depends(_filters)


def _trace_summary(conds: list[Any]) -> Select[Any]:
    ql = m.query_log.c
    return (
        select(
            ql.trace_id,
            func.min(ql.ts).label("ts"),
            func.max(ql.user_ref).label("user_ref"),
            func.max(ql.question_hash).label("question_hash"),
            func.max(literal_column("conversation_id::text")).label("conversation_id"),
            func.count().label("calls"),
            func.count().filter(ql.tool.in_(DATA_TOOLS)).label("tool_calls"),
            func.count().filter(ql.tool == "llm").label("llm_calls"),
            func.coalesce(func.sum(ql.duration_ms), 0).label("duration_ms"),
            func.sum(ql.cost_usd).label("cost_usd"),
            func.bool_or(ql.status == "blocked").label("blocked"),
            func.bool_or(ql.status == "error").label("has_error"),
            func.array_agg(func.distinct(ql.tool)).label("tools"),
            func.max(ql.semantic_version).label("semantic_version"),
            func.max(ql.prompt_version).label("prompt_version"),
            func.max(ql.model_served).label("model_served"),
        )
        .where(*conds)
        .group_by(ql.trace_id)
    )


@router.get("/audit/queries")
async def audit_queries(
    user: AnalystDep,
    session: SessionDep,
    conds: list[Any] = FiltersDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    summary = _trace_summary(conds).subquery()
    total = (await session.execute(select(func.count()).select_from(summary))).scalar_one()
    rows = (
        await session.execute(
            select(summary)
            .order_by(summary.c.ts.desc(), summary.c.trace_id.desc())  # départage stable entre pages
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    await session.rollback()
    items = []
    for r in rows:
        d = dict(r._mapping)
        d["ts"] = d["ts"].isoformat()
        d["cost_usd"] = float(d["cost_usd"]) if d["cost_usd"] is not None else None
        d["tools"] = sorted(t for t in d["tools"] if t)
        items.append(d)
    return {"total": int(total), "page": page, "page_size": page_size, "items": items}


_DETAIL_COLUMNS = [c for c in m.query_log.c if c.name not in ("conversation_id",)]


def _row_out(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif k == "cost_usd" and v is not None:
            d[k] = float(v)
    return d


@router.get("/audit/queries/export.csv")
async def audit_export(
    user: AnalystDep,
    session: SessionDep,
    conds: list[Any] = FiltersDep,
    limit: int = Query(default=10_000, ge=1, le=50_000),
) -> Response:
    rows = (
        await session.execute(
            select(*_DETAIL_COLUMNS)
            .where(*conds)
            .order_by(m.query_log.c.ts.desc(), m.query_log.c.id)
            .limit(limit)
        )
    ).all()
    await audit_access(session, user, "audit_export_csv", details={"rows": len(rows), "limit": limit})
    buf = io.StringIO()
    writer = csv.writer(buf)
    names = [c.name for c in _DETAIL_COLUMNS]
    writer.writerow(names)
    for r in rows:
        out = _row_out(r)
        writer.writerow(["" if out[n] is None else _csv_safe(out[n]) for n in names])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="query_log.csv"'},
    )


_CSV_CONTROL = ("\t", "\r", "\n")
_CSV_FORMULA = ("=", "+", "-", "@", "|")


def _csv_safe(value: Any) -> Any:
    """Neutralise l'injection de formules dans un tableur (y compris derrière des espaces initiaux)."""
    if isinstance(value, str) and (value.startswith(_CSV_CONTROL) or value.lstrip().startswith(_CSV_FORMULA)):
        return "'" + value
    return value


@router.get("/audit/queries/{trace_id}")
async def audit_query_detail(trace_id: str, user: AnalystDep, session: SessionDep) -> dict[str, Any]:
    if len(trace_id) > 64:
        raise ApiError(404, "not_found", "Trace introuvable.")
    rows = (
        await session.execute(
            select(*m.query_log.c)
            .where(m.query_log.c.trace_id == trace_id)
            .order_by(m.query_log.c.step, m.query_log.c.attempt, m.query_log.c.id)
        )
    ).all()
    if not rows:
        raise ApiError(404, "not_found", "Trace introuvable.")
    await audit_access(session, user, "audit_detail", target_trace_id=trace_id)
    steps = [_row_out(r) for r in rows]
    for s in steps:
        s["conversation_id"] = str(s["conversation_id"]) if s["conversation_id"] else None
    first = steps[0]
    return {
        "trace_id": trace_id,
        "user_ref": first["user_ref"],
        "question_hash": first["question_hash"],
        "steps": steps,
        "total_duration_ms": sum(s["duration_ms"] or 0 for s in steps),
        "total_cost_usd": round(sum(s["cost_usd"] or 0 for s in steps), 6),
    }


# --- Sécurité (RF20, admin) -------------------------------------------------------------------


def _read_rights_report(path: str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("rapport de test de droits illisible")
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("generated_at", datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat())
    return data


_RIGHTS_HOWTO = (
    "Le test de droits de agent_ro s'exécute hors de l'API (qui ne détient pas ce DSN) : "
    "`make rights-test` écrit le rapport lu ici."
)


@router.get("/security")
async def security(
    request: Request, user: AdminDep, session: SessionDep, settings: SettingsDep, range: RangeParam = "7d"
) -> dict[str, Any]:  # noqa: A002
    since = _since(range)
    ql = m.query_log.c
    blocked = (
        await session.execute(
            select(func.coalesce(ql.error_class, "inconnu").label("error_class"), func.count().label("n"))
            .where(ql.ts >= since, ql.status == "blocked")
            .group_by(literal_column("1"))
            .order_by(func.count().desc())
        )
    ).all()
    by_day = (
        await session.execute(
            select(
                func.date_trunc("day", ql.ts).label("day"),
                func.count().filter(ql.status == "blocked").label("blocked"),
                func.count().filter(ql.tool.in_(DATA_TOOLS)).label("tool_calls"),
            )
            .where(ql.ts >= since)
            .group_by(literal_column("1"))
            .order_by(literal_column("1"))
        )
    ).all()
    aal = m.audit_access_log.c
    recent = (
        await session.execute(
            select(aal.ts, aal.actor_role, aal.action, aal.target_trace_id).order_by(aal.ts.desc()).limit(20)
        )
    ).all()
    await session.rollback()
    report = _read_rights_report(settings.rights_test_report)
    return {
        "range": range,
        "guard_blocks": [{"error_class": r.error_class, "count": int(r.n)} for r in blocked],
        "guard_blocks_by_day": [
            {"day": r.day.date().isoformat(), "blocked": int(r.blocked), "tool_calls": int(r.tool_calls)}
            for r in by_day
        ],
        "role_matrix": ROLE_MATRIX,
        "rights_test": {"available": report is not None, "report": report, "how": _RIGHTS_HOWTO},
        "recent_audit_access": [
            {
                "ts": r.ts.isoformat(),
                "actor_role": r.actor_role,
                "action": r.action,
                "target_trace_id": r.target_trace_id,
            }
            for r in recent
        ],
        "sessions": "Console Keycloak (MVP : pas de proxy d'administration).",
        "health": await health_snapshot(request),
    }


@router.post("/security/rights-test")
async def rights_test(user: AdminDep, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """Relit le dernier rapport de `make rights-test` (l'API n'a pas le DSN agent_ro : choix documenté)."""
    report = _read_rights_report(settings.rights_test_report)
    await audit_access(session, user, "rights_test_read", details={"available": report is not None})
    if report is None:
        return {"available": False, "how": _RIGHTS_HOWTO}
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    failed = [c for c in checks if isinstance(c, dict) and not c.get("ok")]
    return {
        "available": True,
        "ok": bool(report.get("ok", not failed)),
        "failed": len(failed),
        "report": report,
        "how": _RIGHTS_HOWTO,
    }


# --- Évaluation -------------------------------------------------------------------------------


def _jsonable(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


@router.get("/eval/runs")
async def eval_runs(
    user: AnalystDep,
    session: SessionDep,
    split: Literal["dev", "test"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    er = m.eval_run.c
    stmt = select(*[c for c in m.eval_run.c if c.name != "report"]).order_by(er.ts.desc()).limit(limit)
    if split:
        stmt = stmt.where(er.split == split)
    rows = (await session.execute(stmt)).all()
    return {"items": [_jsonable(r) for r in rows]}


@router.get("/eval/runs/{run_id}")
async def eval_run_detail(run_id: int, user: AnalystDep, session: SessionDep) -> dict[str, Any]:
    run = (await session.execute(select(m.eval_run).where(m.eval_run.c.id == run_id))).first()
    if run is None:
        raise ApiError(404, "not_found", "Exécution introuvable.")
    results = (
        await session.execute(
            select(m.eval_result)
            .where(m.eval_result.c.run_id == run_id)
            .order_by(m.eval_result.c.question_id)
        )
    ).all()
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        c = by_cat.setdefault(r.category or "autre", {"n": 0, "pass3": 0})
        c["n"] += 1
        c["pass3"] += int(r.passes == 3)
    return {"run": _jsonable(run), "by_category": by_cat, "results": [_jsonable(r) for r in results]}


# --- Signalements -----------------------------------------------------------------------------


@router.get("/feedback")
async def list_feedback(
    user: AnalystDep,
    session: SessionDep,
    status: Literal["nouveau", "traite", "rejete"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    fb = m.feedback.c
    conds = [fb.status == status] if status else []
    total = (await session.execute(select(func.count()).select_from(m.feedback).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(
                fb.id,
                fb.ts,
                fb.category,
                fb.comment,
                fb.consent_question,
                fb.question_text,
                fb.status,
                fb.reject_reason,
                fb.promoted_to_dev,
                fb.handled_at,
                fb.message_id,
                m.message.c.trace_id,
            )
            .select_from(m.feedback.join(m.message, m.message.c.id == fb.message_id))
            .where(*conds)
            .order_by(case((fb.status == "nouveau", 0), else_=1), fb.ts.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    items = []
    for r in rows:
        d = _jsonable(r)
        d["id"], d["message_id"] = str(r.id), str(r.message_id)
        items.append(d)
    return {"total": int(total), "page": page, "page_size": page_size, "items": items}


class FeedbackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["traiter", "rejeter", "promouvoir"]
    reason: str | None = Field(default=None, max_length=1000)


@router.patch("/feedback/{feedback_id}")
async def patch_feedback(
    feedback_id: str, body: FeedbackPatch, user: AnalystDep, session: SessionDep
) -> dict[str, Any]:
    try:
        fid = uuid.UUID(feedback_id)
    except ValueError as exc:
        raise ApiError(404, "not_found", "Signalement introuvable.") from exc
    row = (await session.execute(select(m.feedback).where(m.feedback.c.id == fid).with_for_update())).first()
    if row is None:
        raise ApiError(404, "not_found", "Signalement introuvable.")
    values: dict[str, Any] = {"handled_by": user.sub, "handled_at": func.now()}
    if body.action == "rejeter":
        if not body.reason or not body.reason.strip():
            raise ApiError(422, "reason_required", "Le motif de rejet est obligatoire.")
        if row.status != "nouveau":
            raise ApiError(409, "conflict", "Seul un signalement nouveau peut être rejeté.")
        values.update(status="rejete", reject_reason=body.reason.strip())
    elif body.action == "traiter":
        if row.status != "nouveau":
            raise ApiError(409, "conflict", "Seul un signalement nouveau peut être traité.")
        values.update(status="traite")
    else:  # promouvoir vers le jeu de DEV (jamais le test : le test est figé par hash)
        if row.status == "rejete":
            raise ApiError(409, "conflict", "Un signalement rejeté ne peut pas être promu.")
        if not row.consent_question or not row.question_text:
            raise ApiError(
                409, "consent_required", "Promotion impossible sans consentement à joindre la question."
            )
        values.update(status="traite", promoted_to_dev=True)
    await session.execute(update(m.feedback).where(m.feedback.c.id == fid).values(**values))
    await session.commit()
    updated = (await session.execute(select(m.feedback).where(m.feedback.c.id == fid))).one()
    await session.rollback()
    d = _jsonable(updated)
    d["id"], d["message_id"] = str(updated.id), str(updated.message_id)
    d["target_split"] = "dev" if updated.promoted_to_dev else None
    return d


# --- Catalogue, couche sémantique, paramètres --------------------------------------------------


@router.get("/kpis")
async def kpis(user: AnalystDep, runtime: RuntimeDep) -> dict[str, Any]:
    k = runtime.semantic.kpis
    return {
        "semantic_version": runtime.semantic.version,
        "metrics": k.get("metrics", {}),
        "dimensions": k.get("dimensions", {}),
        "grains": k.get("grains"),
        "regions": k.get("regions", []),
        "limits": k.get("limits", {}),
    }


@router.get("/semantic/{name}")
async def semantic_file(
    name: Literal["tables", "glossary", "examples"], user: AnalystDep, runtime: RuntimeDep
) -> dict[str, Any]:
    sem = runtime.semantic
    return {
        "semantic_version": sem.version,
        "name": name,
        "content": getattr(sem, name),
        "source": f"semantic/{name}.yaml",
    }


@router.get("/settings")
async def settings_view(user: AdminDep, runtime: RuntimeDep, settings: SettingsDep) -> dict[str, Any]:
    return {
        "semantic_version": runtime.semantic.version,
        "config": runtime.semantic.config,
        "runtime": {
            "environment": settings.environment,
            "reference_date": settings.reference_date.isoformat(),
            "llm_model": settings.llm_model,
            "llm_effort": settings.llm_effort,
            "llm_fallbacks": settings.llm_fallbacks,
            "keycloak_issuer": settings.keycloak_issuer,
            "keycloak_audience": settings.keycloak_audience,
            "keycloak_client_id": settings.keycloak_client_id,
            "cors_origins": settings.cors_origin_list,
        },
        "change_procedure": {
            "how": "Lecture seule : toute modification passe par une pull request Git sur semantic/*.yaml, "
            "relue par une autre personne (protection de branche), puis redéploiement.",
            "url": settings.settings_procedure_url,
        },
    }
