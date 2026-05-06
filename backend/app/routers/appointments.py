"""REST endpoints for browsing appointments + users (for the UI sidebar)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Appointment, User
from ..schemas import AppointmentOut, UserOut

router = APIRouter(tags=["appointments"])


@router.get("/users", response_model=List[UserOut])
async def list_users(db: AsyncSession = Depends(get_session)) -> List[UserOut]:
    res = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(res.scalars().all())


@router.get("/users/{phone}/appointments", response_model=List[AppointmentOut])
async def get_user_appointments(
    phone: str,
    include_cancelled: bool = Query(False),
    db: AsyncSession = Depends(get_session),
) -> List[AppointmentOut]:
    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")

    q = select(Appointment).where(Appointment.user_id == user.id)
    if not include_cancelled:
        q = q.where(Appointment.status == "confirmed")
    q = q.order_by(Appointment.slot_start)
    res = await db.execute(q)
    return list(res.scalars().all())


@router.get("/appointments", response_model=List[AppointmentOut])
async def list_all_appointments(
    limit: int = 50, db: AsyncSession = Depends(get_session)
) -> List[AppointmentOut]:
    res = await db.execute(
        select(Appointment).order_by(Appointment.slot_start.desc()).limit(limit)
    )
    return list(res.scalars().all())
