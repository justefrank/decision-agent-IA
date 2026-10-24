"""Services transverses : pseudonymisation, écriture du journal, quotas, périodes."""

from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from decision_core.models import Period, QueryLogRecord
from sqlalchemy import func, insert, literal_column, select
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


async def questions_today(session: AsyncSession, sub: str) -> int:
    """Questions posées depuis minuit (UTC, fuseau de Dakar) : calcul dans Postgres, sans cache."""
    stmt = (
        select(func.count())
        .select_from(m.message.join(m.conversation, m.message.c.conversation_id == m.conversation.c.id))
        .where(
            m.conversation.c.user_id == sub,
            m.message.c.role == "user",
            m.message.c.created_at
            >= literal_column("(date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')"),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


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
                429, "too_many_streams", "Trop de questions en cours ; attendez la fin d'une réponse."
            )
        self._active[sub] += 1

    def release(self, sub: str) -> None:
        self._active[sub] = max(0, self._active[sub] - 1)
        if self._active[sub] == 0:
            self._active.pop(sub, None)


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
