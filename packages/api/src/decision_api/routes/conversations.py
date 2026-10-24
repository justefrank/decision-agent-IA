"""Conversations et questions en flux SSE (`POST /conversations/{id}/messages`).

Le flux émet `step` (StepEvent) puis un seul `final` (AssistantMessage filtré par rôle) ou `error`.
Rien de non validé n'est envoyé. Une déconnexion du client annule la tâche de l'agent
(l'agent propage l'annulation au MCP, qui annule la requête SQL).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

from decision_core.models import AssistantMessage, HistoryItem, ResolvedState, StepEvent
from fastapi import APIRouter, Response
from fastapi.sse import KEEPALIVE_COMMENT, EventSourceResponse, format_sse_event
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_api import models as m
from decision_api.auth import User
from decision_api.config import cfg
from decision_api.deps import LimiterDep, MakerDep, RuntimeDep, SessionDep, SettingsDep, UserDep
from decision_api.errors import ApiError
from decision_api.runtime import Runtime
from decision_api.services import QueryLogWriter, question_hash, reserve_quota, user_ref

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = logging.getLogger("decision_api.conversations")

PING_INTERVAL_S = 15.0


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    message: AssistantMessage | None = None
    trace_id: str | None = None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=20_000)  # borne dure ; borne métier lue dans config.yaml


async def owned_conversation(session: AsyncSession, conversation_id: uuid.UUID, sub: str) -> Any:
    row = (
        await session.execute(
            select(m.conversation).where(
                m.conversation.c.id == conversation_id, m.conversation.c.user_id == sub
            )
        )
    ).first()
    if row is None:  # 404 même si la conversation existe chez autrui
        raise ApiError(404, "not_found", "Conversation introuvable.")
    return row


def _parse_assistant(data: Any) -> AssistantMessage | None:
    if not data:
        return None
    try:
        return AssistantMessage.model_validate(data)
    except ValidationError:
        return None


@router.post("", status_code=201, response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, user: UserDep, session: SessionDep) -> Any:
    cid = uuid.uuid4()
    async with session.begin():
        row = (
            await session.execute(
                insert(m.conversation)
                .values(id=cid, user_id=user.sub, title=body.title)
                .returning(m.conversation)
            )
        ).one()
    return row._mapping


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: UserDep, session: SessionDep, limit: int = 50, offset: int = 0) -> Any:
    limit = max(1, min(limit, 200))
    rows = (
        await session.execute(
            select(m.conversation)
            .where(m.conversation.c.user_id == user.sub)
            .order_by(m.conversation.c.updated_at.desc(), m.conversation.c.created_at.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
    ).all()
    return [r._mapping for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, user: UserDep, session: SessionDep) -> Any:
    conv = await owned_conversation(session, conversation_id, user.sub)
    rows = (
        await session.execute(
            select(m.message)
            .where(m.message.c.conversation_id == conversation_id)
            .order_by(m.message.c.created_at, m.message.c.role.desc())
        )
    ).all()
    messages = []
    for r in rows:
        msg = _parse_assistant(r.structured_json) if r.role == "assistant" else None
        messages.append(
            MessageOut(
                id=r.id,
                role=r.role,
                content=r.content,
                message=msg.for_role(user.role) if msg else None,  # SQL retiré pour le décideur
                trace_id=r.trace_id,
                created_at=r.created_at,
            )
        )
    return ConversationDetail(**dict(conv._mapping), messages=messages)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, user: UserDep, session: SessionDep) -> Response:
    async with session.begin():
        result = await session.execute(
            delete(m.conversation).where(
                m.conversation.c.id == conversation_id, m.conversation.c.user_id == user.sub
            )
        )
    if result.rowcount == 0:
        raise ApiError(404, "not_found", "Conversation introuvable.")
    return Response(status_code=204)


# --- Question en flux --------------------------------------------------------------------------


async def load_context(
    session: AsyncSession, conversation_id: uuid.UUID, exchanges: int
) -> tuple[list[HistoryItem], ResolvedState | None]:
    """Derniers échanges (question + réponse validée) et état résolu de la dernière réponse."""
    rows = (
        await session.execute(
            select(m.message.c.role, m.message.c.content, m.message.c.structured_json)
            .where(m.message.c.conversation_id == conversation_id)
            .order_by(m.message.c.created_at.desc(), m.message.c.role)
            .limit(exchanges * 2 + 2)
        )
    ).all()
    rows = list(reversed(rows))
    history: list[HistoryItem] = []
    pending_question: str | None = None
    state: ResolvedState | None = None
    for r in rows:
        if r.role == "user":
            pending_question = r.content
        elif r.role == "assistant":
            answer = _parse_assistant(r.structured_json)
            if answer is None:
                pending_question = None
                continue
            state = answer.resolved_state
            if pending_question is not None:
                history.append(HistoryItem(question=pending_question, answer=answer))
            pending_question = None
    return history[-exchanges:], state


def _sse(event: str, payload: BaseModel | dict[str, Any]) -> bytes:
    import json

    data = (
        payload.model_dump_json()
        if isinstance(payload, BaseModel)
        else json.dumps(payload, ensure_ascii=False)
    )
    return format_sse_event(data_str=data, event=event)


_DONE = object()


class AgentEventStream(EventSourceResponse):
    """Ferme explicitement le générateur à la fin du flux, quelle qu'en soit la cause.

    Avec ASGI < 2.4 (uvicorn), Starlette annule le flux à la déconnexion ; avec ASGI ≥ 2.4, l'écriture
    échoue (ClientDisconnect). Dans les deux cas `aclose()` déclenche le `finally` qui annule l'agent.
    """

    on_close: Callable[[], None] | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
            if self.on_close is not None:  # générateur jamais démarré : libère quand même le créneau
                self.on_close()


async def _stream_answer(
    *,
    runtime: Runtime,
    maker: async_sessionmaker[AsyncSession],
    release: Callable[[], None],
    user: User,
    conversation_id: uuid.UUID,
    question: str,
    history: list[HistoryItem],
    state: ResolvedState | None,
    trace_id: str,
    writer: QueryLogWriter,
    set_title: bool,
) -> AsyncIterator[bytes]:
    """Le créneau de flux est acquis par l'appelant AVANT le quota ; `release` le libère (idempotent)."""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    task: asyncio.Task[AssistantMessage] | None = None
    started = time.monotonic()
    try:

        async def on_event(event: StepEvent) -> None:
            await queue.put(event)

        agent = runtime.make_agent()
        task = asyncio.create_task(
            agent.answer(
                question,
                history=history,
                state=state,
                role=user.role,
                trace_id=trace_id,
                on_event=on_event,
                on_log=writer,
            )
        )
        task.add_done_callback(lambda _t: queue.put_nowait(_DONE))
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_S)
            except TimeoutError:
                yield KEEPALIVE_COMMENT
                continue
            if item is _DONE:
                break
            yield _sse("step", item)

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            answer = task.result()
        except Exception:  # noqa: BLE001 - jamais de détail interne au client
            log.exception("échec de l'agent", extra={"trace_id": trace_id})
            await _store_assistant(maker, conversation_id, None, trace_id, latency_ms, question, set_title)
            yield _sse(
                "error",
                {
                    "code": "agent_error",
                    "message": "La réponse n'a pas pu être produite.",
                    "trace_id": trace_id,
                },
            )
            return
        if answer.trace_id is None:
            answer = answer.model_copy(update={"trace_id": trace_id})
        await _store_assistant(maker, conversation_id, answer, trace_id, latency_ms, question, set_title)
        yield _sse("final", answer.for_role(user.role))
    finally:
        # Sous annulation (déconnexion), aucun `await` ici : on annule et on libère, c'est tout.
        if task is not None and not task.done():
            task.cancel()
            log.info("flux interrompu par le client : agent annulé", extra={"trace_id": trace_id})
        release()


async def _store_assistant(
    maker: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    answer: AssistantMessage | None,
    trace_id: str,
    latency_ms: int,
    question: str,
    set_title: bool,
) -> None:
    content = answer.text if answer else "La réponse n'a pas pu être produite."
    async with maker() as session, session.begin():
        await session.execute(
            insert(m.message).values(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                structured_json=answer.model_dump(mode="json") if answer else None,
                trace_id=trace_id,
                latency_ms=latency_ms,
            )
        )
        values: dict[str, Any] = {"updated_at": func.now()}
        if set_title:
            values["title"] = question[:80]
        await session.execute(
            update(m.conversation).where(m.conversation.c.id == conversation_id).values(**values)
        )


@router.post(
    "/{conversation_id}/messages",
    responses={200: {"content": {"text/event-stream": {}}, "description": "Flux SSE step… final | error"}},
)
async def ask(
    conversation_id: uuid.UUID,
    body: QuestionIn,
    user: UserDep,
    session: SessionDep,
    maker: MakerDep,
    runtime: RuntimeDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> AgentEventStream:
    semantic = runtime.semantic
    question = body.question.strip()
    max_chars = int(cfg(semantic, "agent.max_question_chars", 1000))
    if not question:
        raise ApiError(422, "invalid_request", "Question vide.")
    if len(question) > max_chars:
        raise ApiError(422, "question_too_long", f"Question trop longue ({max_chars} caractères au plus).")
    conv = await owned_conversation(session, conversation_id, user.sub)
    if not runtime.agent_ready:
        raise ApiError(503, "service_unavailable", "L'agent est momentanément indisponible.")

    exchanges = int(cfg(semantic, "agent.history_exchanges", 6))
    history, state = await load_context(session, conversation_id, exchanges)
    await session.rollback()  # termine la transaction de lecture implicite

    # Créneau de flux d'abord (mémoire, sans attente), puis quota et message sous verrou par
    # utilisateur : jamais de message `user` enregistré sans flux pour y répondre, et jamais deux
    # questions simultanées comptées sur le même solde.
    stream_limit = int(cfg(semantic, "quota.concurrent_streams_per_user", 2))
    release = limiter.slot(user.sub, stream_limit)
    try:
        trace_id = uuid.uuid4().hex
        key = settings.log_pseudonym_key.get_secret_value()
        ref = user_ref(key, user.sub)
        qhash = question_hash(key, question)
        daily = int(cfg(semantic, "quota.questions_per_user_per_day", 200))
        async with session.begin():
            await reserve_quota(
                session,
                ref=ref,
                daily=daily,
                kind="question",
                trace_id=trace_id,
                conversation_id=conversation_id,
                question_hash=qhash,
            )
            await session.execute(
                insert(m.message).values(
                    id=uuid.uuid4(), conversation_id=conversation_id, role="user", content=question
                )
            )
        writer = QueryLogWriter(maker, user_ref=ref, conversation_id=conversation_id, question_hash=qhash)
        stream = _stream_answer(
            runtime=runtime,
            maker=maker,
            release=release,
            user=user,
            conversation_id=conversation_id,
            question=question,
            history=history,
            state=state,
            trace_id=trace_id,
            writer=writer,
            set_title=conv.title is None,
        )
        response = AgentEventStream(
            stream, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Trace-Id": trace_id}
        )
        response.on_close = release
        return response
    except BaseException:
        release()
        raise
