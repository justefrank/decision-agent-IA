"""Services transverses : pseudonymisation, écriture du journal, quotas, périodes."""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import math
import re
import time
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from decision_core.models import Period, QueryLogRecord
from sqlalchemy import func, insert, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_api import models as m
from decision_api.errors import ApiError

# --- Pseudonymisation -------------------------------------------------------------------------


def hmac_hex(key: str, value: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def user_ref(key: str, sub: str) -> str:
    """Pseudonyme stable du sub (HMAC-SHA256) : ce qui est écrit dans query_log."""
    return hmac_hex(key, "sub:" + sub)


def question_hash(key: str, question: str) -> str:
    """Condensat de la question normalisée (HMAC, pour résister au dictionnaire de questions courtes)."""
    norm = " ".join(unicodedata.normalize("NFC", question).casefold().split())
    return hmac_hex(key, "q:" + norm)


def canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:32]


# --- Journal ----------------------------------------------------------------------------------


class QueryLogWriter:
    """Écrit les `QueryLogRecord` reçus par `on_log` dans app.query_log (INSERT seul)."""

    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        *,
        user_ref: str | None,
        conversation_id: uuid.UUID | None,
        question_hash: str | None,
    ) -> None:
        self._maker = maker
        self._base = {
            "user_ref": user_ref,
            "conversation_id": conversation_id,
            "question_hash": question_hash,
        }
        self.records: list[QueryLogRecord] = []

    async def __call__(self, record: QueryLogRecord) -> None:
        self.records.append(record)
        values = record.model_dump()
        values.update(self._base)
        async with self._maker() as session, session.begin():
            await session.execute(insert(m.query_log).values(**values))


# --- Quotas -----------------------------------------------------------------------------------


# Lignes de query_log qui comptent dans le quota quotidien : une par question acceptée, une par analyse
# du tableau de bord générée. Le journal est en ajout seul pour app_rw et survit à la suppression
# des conversations : supprimer une conversation ne rend pas de quota.
QUOTA_TOOLS = ("question", "analysis")
_DAY_START = "(date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')"


STREAMS_RETRY_AFTER_S = 5


def next_quota_reset(now: datetime | None = None) -> tuple[datetime, int]:
    """Prochain minuit UTC (fin du jour de quota) et nombre de secondes à attendre (au moins 1)."""
    now = now or datetime.now(UTC)
    reset = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
    return reset, max(1, math.ceil((reset - now).total_seconds()))


async def usage_today(session: AsyncSession, ref: str) -> int:
    """Questions et analyses imputées depuis minuit UTC (fuseau de Dakar), calculées dans Postgres."""
    ql = m.query_log.c
    stmt = (
        select(func.count())
        .select_from(m.query_log)
        .where(ql.user_ref == ref, ql.tool.in_(QUOTA_TOOLS), ql.ts >= literal_column(_DAY_START))
    )
    return int((await session.execute(stmt)).scalar_one())


async def reserve_quota(
    session: AsyncSession,
    *,
    ref: str,
    daily: int,
    kind: str,
    trace_id: str,
    conversation_id: uuid.UUID | None = None,
    question_hash: str | None = None,
) -> None:
    """Dans la transaction ouverte : verrou consultatif par utilisateur, comptage puis inscription.

    Le verrou (`pg_advisory_xact_lock`, libéré à la fin de la transaction) sérialise les requêtes
    simultanées d'un même utilisateur : deux questions parallèles ne peuvent pas lire le même compte
    puis s'inscrire toutes les deux au-delà de la limite.
    """
    if kind not in QUOTA_TOOLS:
        raise ValueError(kind)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": "quota:" + ref}
    )
    if await usage_today(session, ref) >= daily:
        retry_at, wait_s = next_quota_reset()
        raise ApiError(
            429,
            "quota_exceeded",
            "Quota quotidien de questions atteint.",
            headers={"Retry-After": str(wait_s)},
            retry_at=retry_at,
        )
    await session.execute(
        insert(m.query_log).values(
            trace_id=trace_id,
            step=0,
            tool=kind,
            status="ok",
            duration_ms=0,
            user_ref=ref,
            conversation_id=conversation_id,
            question_hash=question_hash,
        )
    )


class StreamLimiter:
    """Flux simultanés par utilisateur (mémoire du worker ; un seul worker au départ, D3).

    Méthodes synchrones : sans `await`, elles sont atomiques dans la boucle asyncio, et `release`
    reste appelable dans un `finally` exécuté sous annulation (déconnexion du client).
    """

    def __init__(self) -> None:
        self._active: dict[str, int] = defaultdict(int)

    def active(self, sub: str) -> int:
        return self._active.get(sub, 0)

    def acquire(self, sub: str, limit: int) -> None:
        if self._active[sub] >= limit:
            raise ApiError(
                429,
                "too_many_streams",
                "Trop de questions en cours ; attendez la fin d'une réponse.",
                headers={"Retry-After": str(STREAMS_RETRY_AFTER_S)},
            )
        self._active[sub] += 1

    def release(self, sub: str) -> None:
        self._active[sub] = max(0, self._active[sub] - 1)
        if self._active[sub] == 0:
            self._active.pop(sub, None)

    def slot(self, sub: str, limit: int) -> Callable[[], None]:
        """Acquiert un créneau et renvoie une fonction de libération idempotente."""
        self.acquire(sub, limit)
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                self.release(sub)

        return release


class TTLCache:
    """Petit cache mémoire à durée de vie (tuiles du tableau de bord), borné en nombre d'entrées."""

    def __init__(self, ttl_s: float, max_entries: int = 256) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        if time.monotonic() - item[0] > self.ttl_s:
            self._data.pop(key, None)
            return None
        return item[1]

    def set(self, key: Any, value: Any) -> None:
        if self.ttl_s <= 0:
            return
        if len(self._data) >= self.max_entries and key not in self._data:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)
        self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._data.clear()


# --- Périodes du tableau de bord ---------------------------------------------------------------

MOIS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]
_PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def month_period(value: str | None, reference_date: date) -> Period:
    """`YYYY-MM` → Period du mois (défaut : mois de REFERENCE_DATE). Refuse un mois futur."""
    if value is None:
        year, month = reference_date.year, reference_date.month
    else:
        match = _PERIOD_RE.match(value)
        if not match:
            raise ApiError(422, "invalid_period", "Période attendue au format AAAA-MM.")
        year, month = int(match.group(1)), int(match.group(2))
    start = date(year, month, 1)
    if start > reference_date:
        raise ApiError(422, "invalid_period", "Période postérieure à la date de référence.")
    end = min(date(year, month, calendar.monthrange(year, month)[1]), reference_date)
    return Period(start=start, end=end, label=f"{MOIS[month - 1]} {year}")


def check_region(region: str | None, regions: list[str]) -> str | None:
    if region is None or region == "":
        return None
    if region not in regions:
        raise ApiError(422, "invalid_region", "Région inconnue.")
    return region
