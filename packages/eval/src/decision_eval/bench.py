"""Banc HTTP de latence (O2) : mesure de bout en bout par l'API.

Pour chaque question : `POST /api/conversations/{id}/messages` (Bearer fourni), lecture du flux SSE
jusqu'à l'événement `final` (ou `error`). Mesure p50, p90 et max ; aucune réponse mise en cache.
Le jeton est lu dans une variable d'environnement (jamais en argument de ligne de commande).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import stats


@dataclass
class BenchObservation:
    question: str
    ok: bool
    latency_ms: int
    ttfb_ms: int | None = None  # premier octet du flux
    first_step_ms: int | None = None
    event: str | None = None
    error: str | None = None


@dataclass
class BenchReport:
    observations: list[BenchObservation] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        lat = [o.latency_ms for o in self.observations if o.ok]
        p50 = stats.percentile(lat, 50)
        p90 = stats.percentile(lat, 90)
        return {
            "n": len(self.observations),
            "ok": len(lat),
            "p50_ms": p50,
            "p90_ms": p90,
            "max_ms": max(lat) if lat else None,
            "o2_median_lt_15s": None if p50 is None else p50 < 15_000,
            "o2_p90_lt_30s": None if p90 is None else p90 < 30_000,
            "note": "p90 indicatif sous 200 observations ; latence « cache froid » à publier à part.",
        }


def parse_sse(buffer: str) -> tuple[list[tuple[str, str]], str]:
    """Découpe un tampon SSE en (événement, données) ; renvoie le reste non terminé."""
    events: list[tuple[str, str]] = []
    buffer = buffer.replace("\r\n", "\n")
    while "\n\n" in buffer:
        block, buffer = buffer.split("\n\n", 1)
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data or name != "message":
            events.append((name, "\n".join(data)))
    return events, buffer


async def ask_once(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    conversation_id: str,
    question: str,
    timeout_s: float = 60.0,
) -> BenchObservation:
    url = f"{base_url.rstrip('/')}/api/conversations/{conversation_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    t0 = time.perf_counter()
    ttfb = first_step = None
    try:
        async with client.stream(
            "POST", url, json={"question": question}, headers=headers, timeout=timeout_s
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:200]
                return BenchObservation(
                    question,
                    False,
                    int((time.perf_counter() - t0) * 1000),
                    error=f"HTTP {resp.status_code}: {body}",
                )
            buf = ""
            async for chunk in resp.aiter_text():
                if ttfb is None:
                    ttfb = int((time.perf_counter() - t0) * 1000)
                events, buf = parse_sse(buf + chunk)
                for name, data in events:
                    if name == "step" and first_step is None:
                        first_step = int((time.perf_counter() - t0) * 1000)
                    if name in {"final", "error"}:
                        ms = int((time.perf_counter() - t0) * 1000)
                        err = None
                        if name == "error":
                            try:
                                err = json.loads(data).get("message")
                            except ValueError:
                                err = data[:200]
                        return BenchObservation(question, name == "final", ms, ttfb, first_step, name, err)
        return BenchObservation(
            question,
            False,
            int((time.perf_counter() - t0) * 1000),
            ttfb,
            first_step,
            error="flux terminé sans événement final",
        )
    except httpx.HTTPError as e:
        return BenchObservation(question, False, int((time.perf_counter() - t0) * 1000), error=str(e))


async def create_conversation(client: httpx.AsyncClient, base_url: str, token: str) -> str:
    resp = await client.post(
        f"{base_url.rstrip('/')}/api/conversations",
        json={"title": "banc O2"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return str(resp.json()["id"])


async def run_bench(
    base_url: str,
    token: str,
    questions: list[str],
    *,
    conversation_id: str | None = None,
    concurrency: int = 1,
    repeat: int = 1,
    timeout_s: float = 60.0,
    client: httpx.AsyncClient | None = None,
) -> BenchReport:
    """Une conversation neuve par question (pas d'historique), sauf si conversation_id est imposé."""
    own = client is None
    client = client or httpx.AsyncClient()
    report = BenchReport()
    sem = asyncio.Semaphore(concurrency)

    async def one(q: str) -> None:
        async with sem:
            cid = conversation_id or await create_conversation(client, base_url, token)
            report.observations.append(await ask_once(client, base_url, token, cid, q, timeout_s))

    try:
        for _ in range(repeat):
            await asyncio.gather(*(one(q) for q in questions))
    finally:
        if own:
            await client.aclose()
    return report
