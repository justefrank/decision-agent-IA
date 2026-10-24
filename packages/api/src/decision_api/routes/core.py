"""`GET /health` (public, sans détail sensible) et `GET /me`."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from decision_api.auth import User, authenticated_user

router = APIRouter(tags=["système"])
log = logging.getLogger("decision_api.health")


async def check_db(request: Request) -> bool:
    maker = request.app.state.sessionmaker
    if maker is None:
        return False
    try:
        async with maker() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=3)
        return True
    except Exception:  # noqa: BLE001
        log.warning("base de données injoignable")
        return False


async def health_snapshot(request: Request) -> dict[str, Any]:
    """État réel : requête SQL, sonde MCP (list_tools, délai court), agent configuré.

    `status` : `ok` si tout fonctionne, `down` si la base est injoignable (l'API ne sert plus rien),
    `degraded` sinon (base joignable mais MCP ou agent indisponible : questions refusées en 503).
    """
    runtime = getattr(request.app.state, "runtime", None)
    db_ok = await check_db(request)
    mcp_ok = False
    if runtime is not None:
        try:
            mcp_ok = await runtime.probe_mcp()
        except Exception:  # noqa: BLE001
            log.warning("sonde MCP en échec")
    agent_ok = bool(runtime and runtime.agent_ready and mcp_ok)
    if not db_ok:
        status = "down"
    elif mcp_ok and agent_ok:
        status = "ok"
    else:
        status = "degraded"
    if mcp_ok:
        mcp = "ok"
    elif runtime is not None and runtime.mcp_state in ("starting", "restarting"):
        mcp = "restarting"
    else:
        mcp = "down"
    return {
        "status": status,
        "db": "ok" if db_ok else "down",
        "mcp": mcp,
        "agent": "ok" if agent_ok else "down",
        "semantic_version": runtime.semantic.version if runtime else None,
    }


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    snap = await health_snapshot(request)
    return JSONResponse(snap, status_code=503 if snap["status"] == "down" else 200)


@router.get("/me")
async def me(user: Annotated[User, Depends(authenticated_user)]) -> dict[str, Any]:
    return {
        "sub": user.sub,
        "name": user.name,
        "email": user.email,
        "roles": sorted(user.roles),
        "role": user.role if user.roles else None,
        "sees_sql": bool(user.roles) and user.sees_sql,
    }
