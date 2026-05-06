"""REST endpoints for sessions, summaries and cost."""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Appointment, Message, Session, ToolCallLog, User
from ..schemas import (
    AppointmentOut,
    MessageOut,
    SessionDetail,
    SessionOut,
    ToolCallOut,
)
from ..services.summary import generate_summary_for_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=List[SessionOut])
async def list_sessions(
    limit: int = 20, db: AsyncSession = Depends(get_session)
) -> List[SessionOut]:
    res = await db.execute(
        select(Session).order_by(Session.started_at.desc()).limit(limit)
    )
    return list(res.scalars().all())


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> SessionDetail:
    sess = await db.get(Session, session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")

    msgs = (
        await db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.id)
        )
    ).scalars().all()
    tools = (
        await db.execute(
            select(ToolCallLog)
            .where(ToolCallLog.session_id == session_id)
            .order_by(ToolCallLog.id)
        )
    ).scalars().all()

    appts: List[Appointment] = []
    if sess.user_id:
        appts = (
            await db.execute(
                select(Appointment)
                .where(Appointment.user_id == sess.user_id)
                .order_by(Appointment.slot_start)
            )
        ).scalars().all()
    elif sess.extracted_phone:
        user_res = await db.execute(
            select(User).where(User.phone == sess.extracted_phone)
        )
        user = user_res.scalar_one_or_none()
        if user:
            appts = (
                await db.execute(
                    select(Appointment)
                    .where(Appointment.user_id == user.id)
                    .order_by(Appointment.slot_start)
                )
            ).scalars().all()

    return SessionDetail(
        id=sess.id,
        user_id=sess.user_id,
        started_at=sess.started_at,
        ended_at=sess.ended_at,
        audio_input_ms=sess.audio_input_ms,
        audio_output_ms=sess.audio_output_ms,
        text_input_tokens=sess.text_input_tokens,
        text_output_tokens=sess.text_output_tokens,
        estimated_cost_usd=sess.estimated_cost_usd,
        summary=sess.summary,
        extracted_name=sess.extracted_name,
        extracted_phone=sess.extracted_phone,
        extracted_intent=sess.extracted_intent,
        preferences=sess.preferences,
        messages=[MessageOut.model_validate(m) for m in msgs],
        tool_calls=[ToolCallOut.model_validate(t) for t in tools],
        appointments=[AppointmentOut.model_validate(a) for a in appts],
    )


@router.post("/{session_id}/summary")
async def create_summary(
    session_id: str, db: AsyncSession = Depends(get_session)
) -> dict:
    """Generate (and persist) the summary for a finished session."""
    sess = await db.get(Session, session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")

    summary = await generate_summary_for_session(session_id, db)

    # Link the session to a user if the model extracted a phone
    extracted_phone = summary.get("phone") or sess.extracted_phone
    if extracted_phone and not sess.user_id:
        user_res = await db.execute(select(User).where(User.phone == extracted_phone))
        user = user_res.scalar_one_or_none()
        if user:
            sess.user_id = user.id
            await db.commit()

    # Attach appointment list
    appointments: List[dict] = []
    if sess.user_id:
        appts_res = await db.execute(
            select(Appointment)
            .where(Appointment.user_id == sess.user_id)
            .order_by(Appointment.slot_start)
        )
        for a in appts_res.scalars().all():
            appointments.append(
                {
                    "id": a.id,
                    "provider": a.provider,
                    "slot_start": a.slot_start,
                    "slot_end": a.slot_end,
                    "status": a.status,
                    "reason": a.reason,
                }
            )

    return {
        "session_id": session_id,
        "generated_at": (sess.ended_at or sess.started_at).isoformat(),
        **summary,
        "appointments": appointments,
        "cost_usd": sess.estimated_cost_usd,
    }
