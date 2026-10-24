"""Signalement d'une réponse (RF10) par le propriétaire du message."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select

from decision_api import models as m
from decision_api.deps import SessionDep, UserDep
from decision_api.errors import ApiError

router = APIRouter(prefix="/feedback", tags=["signalements"])

Category = Literal[
    "chiffre_faux", "mauvaise_comprehension", "periode_ou_perimetre", "refus_injustifie", "autre"
]


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: uuid.UUID
    category: Category
    comment: str | None = Field(default=None, max_length=2000)
    # Consentement explicite : sans lui, le texte de la question n'est jamais joint.
    consent_question: bool = False


@router.post("", status_code=201)
async def create_feedback(body: FeedbackIn, user: UserDep, session: SessionDep) -> dict[str, Any]:
    target = (
        await session.execute(
            select(m.message.c.id, m.message.c.conversation_id, m.message.c.created_at)
            .select_from(m.message.join(m.conversation, m.message.c.conversation_id == m.conversation.c.id))
            .where(
                m.message.c.id == body.message_id,
                m.message.c.role == "assistant",
                m.conversation.c.user_id == user.sub,
            )
        )
    ).first()
    if target is None:
        raise ApiError(404, "not_found", "Message introuvable.")
    question_text = None
    if body.consent_question:
        question_text = (
            await session.execute(
                select(m.message.c.content)
                .where(
                    m.message.c.conversation_id == target.conversation_id,
                    m.message.c.role == "user",
                    m.message.c.created_at <= target.created_at,
                )
                .order_by(m.message.c.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    await session.rollback()
    fid = uuid.uuid4()
    async with session.begin():
        await session.execute(
            insert(m.feedback).values(
                id=fid,
                user_id=user.sub,
                message_id=body.message_id,
                category=body.category,
                comment=body.comment,
                consent_question=body.consent_question,
                question_text=question_text,
            )
        )
    return {"id": str(fid), "status": "nouveau", "question_attached": question_text is not None}
