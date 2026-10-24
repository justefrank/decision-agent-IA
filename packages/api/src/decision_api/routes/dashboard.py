"""Tableau de bord (RF4) et analyse de l'agent (RF17)."""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import timedelta
from typing import Any

from decision_core.models import DashboardAnalysis, Period
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select, text

from decision_api import models as m
from decision_api.config import cfg
from decision_api.deps import LimiterDep, MakerDep, RuntimeDep, SessionDep, SettingsDep, UserDep
from decision_api.errors import ApiError
from decision_api.runtime import Runtime
from decision_api.services import (
    QueryLogWriter,
    TTLCache,
    canonical_hash,
    check_region,
    month_period,
    reserve_quota,
    user_ref,
)

router = APIRouter(prefix="/dashboard", tags=["tableau de bord"])
log = logging.getLogger("decision_api.dashboard")


def _regions(runtime: Runtime) -> list[str]:
    return list(runtime.semantic.kpis.get("regions", []))


async def _tiles(request: Request, runtime: Runtime, period: Period, region: str | None) -> dict[str, Any]:
    """Tuiles du tableau de bord, en cache mémoire quelques minutes (clé période, région, version).

    Ce cache porte sur des agrégats déterministes calculés par query_metric, pas sur des réponses de
    l'agent ; il évite qu'un rafraîchissement de page relance toutes les requêtes du tableau de bord.
    """
    if runtime.fetch_dashboard is None or not runtime.mcp_ready:
        raise ApiError(503, "service_unavailable", "Le tableau de bord est momentanément indisponible.")
    cache: TTLCache = request.app.state.tiles_cache
    key = (period.start, period.end, region or "", runtime.semantic.version)
    cached = cache.get(key)
    if cached is not None:
        return copy.deepcopy(cached)
    try:
        tiles = await runtime.dashboard(period=period, region=region)
    except ApiError:
        raise
    except Exception as exc:
        log.exception("échec du calcul du tableau de bord")
        raise ApiError(
            503, "service_unavailable", "Le tableau de bord est momentanément indisponible."
        ) from exc
    if not tiles.get("errors"):  # un calcul partiel n'est pas mis en cache
        cache.set(key, copy.deepcopy(tiles))
    return tiles


@router.get("")
async def get_dashboard(
    request: Request,
    user: UserDep,
    runtime: RuntimeDep,
    settings: SettingsDep,
    period: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    p = month_period(period, settings.reference_date)
    reg = check_region(region, _regions(runtime))
    dashboard = await _tiles(request, runtime, p, reg)
    # fetch_dashboard renvoie déjà period, compare_period, region, tiles, facts, errors
    return {
        "period": p.model_dump(mode="json"),
        "region": reg,
        **dashboard,
        "semantic_version": runtime.semantic.version,
    }


class AnalysisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str | None = Field(default=None, description="AAAA-MM ; défaut : mois de REFERENCE_DATE")
    region: str | None = None
    regenerate: bool = Field(default=False, description="Analyste et admin seulement")


def _latest_analysis(p: Period, reg: str | None, semantic_version: str, data_hash: str) -> Any:
    a = m.analysis.c
    return (
        select(m.analysis)
        .where(
            a.period_start == p.start,
            a.period_end == p.end,
            func.coalesce(a.region, "") == (reg or ""),
            a.semantic_version == semantic_version,
            a.data_hash == data_hash,
        )
        .order_by(a.ts.desc())
        .limit(1)
    )


def _reused(row: Any, data_hash: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "reused": True,
        "generated_at": row.ts.isoformat(),
        "data_hash": data_hash,
        "analysis": row.payload,
    }


@router.post("/analysis")
async def dashboard_analysis(
    request: Request,
    body: AnalysisIn,
    user: UserDep,
    runtime: RuntimeDep,
    settings: SettingsDep,
    session: SessionDep,
    maker: MakerDep,
    limiter: LimiterDep,
) -> dict[str, Any]:
    """Analyse du tableau de bord : réutilisée si période, région, version sémantique et données sont
    identiques. Une génération est imputée au quota quotidien et occupe un créneau de flux ;
    `regenerate=true` est réservé aux analystes et administrateurs, avec un délai minimal.
    """
    if body.regenerate and not (user.roles & {"analyste", "admin"}):
        raise ApiError(403, "forbidden", "La régénération est réservée aux analystes et administrateurs.")
    p = month_period(body.period, settings.reference_date)
    reg = check_region(body.region, _regions(runtime))
    # Empreinte des données : les tuiles courantes. Une analyse n'est réutilisée que pour des données,
    # une couche sémantique et une période/région identiques.
    tiles = await _tiles(request, runtime, p, reg)
    data_hash = canonical_hash(tiles)
    semantic_version = runtime.semantic.version
    lookup = _latest_analysis(p, reg, semantic_version, data_hash)
    if not body.regenerate:
        row = (await session.execute(lookup)).first()
        await session.rollback()
        if row is not None:
            return _reused(row, data_hash)

    if runtime.run_dashboard_analysis is None or not runtime.agent_ready:
        raise ApiError(503, "service_unavailable", "L'analyse est momentanément indisponible.")

    semantic = runtime.semantic
    release = limiter.slot(user.sub, int(cfg(semantic, "quota.concurrent_streams_per_user", 2)))
    try:
        key = settings.log_pseudonym_key.get_secret_value()
        ref = user_ref(key, user.sub)
        lock_key = f"analysis:{p.start}:{p.end}:{reg or ''}:{semantic_version}:{data_hash}"
        min_age = timedelta(seconds=settings.analysis_regenerate_min_interval_s)
        # Verrou consultatif par (période, région, version, données), tenu pendant la génération : deux
        # demandes simultanées ne produisent qu'une analyse ; la seconde reçoit celle de la première.
        async with maker() as gen, gen.begin():
            await gen.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": lock_key})
            row = (await gen.execute(lookup)).first()
            if row is not None:
                now = (await gen.execute(select(func.now()))).scalar_one()
                if not body.regenerate or now - row.ts < min_age:
                    return _reused(row, data_hash)

            trace_id = uuid.uuid4().hex
            async with maker() as qs, qs.begin():  # transaction courte : le verrou utilisateur est relâché
                await reserve_quota(
                    qs,
                    ref=ref,
                    daily=int(cfg(semantic, "quota.questions_per_user_per_day", 200)),
                    kind="analysis",
                    trace_id=trace_id,
                )
            writer = QueryLogWriter(maker, user_ref=ref, conversation_id=None, question_hash=None)
            try:
                result: DashboardAnalysis = await runtime.analysis(period=p, region=reg, on_log=writer)
            except Exception as exc:
                log.exception("échec de l'analyse du tableau de bord", extra={"trace_id": trace_id})
                raise ApiError(503, "service_unavailable", "L'analyse n'a pas pu être produite.") from exc
            if writer.records:  # l'agent fixe le trace_id de ses appels
                trace_id = writer.records[0].trace_id
            payload = result.model_dump(mode="json")
            aid = uuid.uuid4()
            inserted = (
                await gen.execute(
                    insert(m.analysis)
                    .values(
                        id=aid,
                        period_start=p.start,
                        period_end=p.end,
                        region=reg,
                        semantic_version=semantic_version,
                        model_id=result.model_id,
                        payload=payload,
                        data_hash=data_hash,
                        trace_id=trace_id,
                    )
                    .returning(m.analysis.c.ts)
                )
            ).one()
        return {
            "id": str(aid),
            "reused": False,
            "generated_at": inserted.ts.isoformat(),
            "data_hash": data_hash,
            "analysis": payload,
        }
    finally:
        release()
