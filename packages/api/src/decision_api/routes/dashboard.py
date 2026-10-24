"""Tableau de bord (RF4) et analyse de l'agent (RF17)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from decision_core.models import DashboardAnalysis
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select

from decision_api import models as m
from decision_api.deps import MakerDep, RuntimeDep, SessionDep, SettingsDep, UserDep
from decision_api.errors import ApiError
from decision_api.runtime import Runtime
from decision_api.services import QueryLogWriter, canonical_hash, check_region, month_period, user_ref

router = APIRouter(prefix="/dashboard", tags=["tableau de bord"])
log = logging.getLogger("decision_api.dashboard")


def _regions(runtime: Runtime) -> list[str]:
    return list(runtime.semantic.kpis.get("regions", []))


async def _tiles(runtime: Runtime, period: Any, region: str | None) -> dict[str, Any]:
    if runtime.fetch_dashboard is None or not runtime.mcp_ready:
        raise ApiError(503, "service_unavailable", "Le tableau de bord est momentanément indisponible.")
    try:
        return await runtime.dashboard(period=period, region=region)
    except ApiError:
        raise
    except Exception as exc:
        log.exception("échec du calcul du tableau de bord")
        raise ApiError(
            503, "service_unavailable", "Le tableau de bord est momentanément indisponible."
        ) from exc


@router.get("")
async def get_dashboard(
    user: UserDep,
    runtime: RuntimeDep,
    settings: SettingsDep,
    period: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    p = month_period(period, settings.reference_date)
    reg = check_region(region, _regions(runtime))
    dashboard = await _tiles(runtime, p, reg)
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
    regenerate: bool = False


@router.post("/analysis")
async def dashboard_analysis(
    body: AnalysisIn,
    user: UserDep,
    runtime: RuntimeDep,
    settings: SettingsDep,
    session: SessionDep,
    maker: MakerDep,
) -> dict[str, Any]:
    p = month_period(body.period, settings.reference_date)
    reg = check_region(body.region, _regions(runtime))
    # Empreinte des données : les tuiles courantes. Une analyse n'est réutilisée que pour des données,
    # une couche sémantique et une période/région identiques.
    tiles = await _tiles(runtime, p, reg)
    data_hash = canonical_hash(tiles)
    semantic_version = runtime.semantic.version
    if not body.regenerate:
        row = (
            await session.execute(
                select(m.analysis)
                .where(
                    m.analysis.c.period_start == p.start,
                    m.analysis.c.period_end == p.end,
                    func.coalesce(m.analysis.c.region, "") == (reg or ""),
                    m.analysis.c.semantic_version == semantic_version,
                    m.analysis.c.data_hash == data_hash,
                )
                .order_by(m.analysis.c.ts.desc())
                .limit(1)
            )
        ).first()
        await session.rollback()
        if row is not None:
            return {
                "id": str(row.id),
                "reused": True,
                "generated_at": row.ts.isoformat(),
                "data_hash": data_hash,
                "analysis": row.payload,
            }

    if runtime.run_dashboard_analysis is None or not runtime.agent_ready:
        raise ApiError(503, "service_unavailable", "L'analyse est momentanément indisponible.")
    trace_id = uuid.uuid4().hex
    key = settings.log_pseudonym_key.get_secret_value()
    writer = QueryLogWriter(maker, user_ref=user_ref(key, user.sub), conversation_id=None, question_hash=None)
    try:
        result: DashboardAnalysis = await runtime.analysis(period=p, region=reg, on_log=writer)
    except Exception as exc:
        log.exception("échec de l'analyse du tableau de bord", extra={"trace_id": trace_id})
        raise ApiError(503, "service_unavailable", "L'analyse n'a pas pu être produite.") from exc
    if writer.records:  # l'agent fixe le trace_id de ses appels
        trace_id = writer.records[0].trace_id
    payload = result.model_dump(mode="json")
    aid = uuid.uuid4()
    async with session.begin():
        row = (
            await session.execute(
                insert(m.analysis)
                .values(
                    id=aid,
                    period_start=p.start,
                    period_end=p.end,
                    region=reg,
                    semantic_version=result.semantic_version or semantic_version,
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
        "generated_at": row.ts.isoformat(),
        "data_hash": data_hash,
        "analysis": payload,
    }
