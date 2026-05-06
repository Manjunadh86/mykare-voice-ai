"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Endpoints
---------
GET    /health                                    - liveness probe
GET    /config                                    - public clinic info (UI bootstrap)
WS     /ws/voice                                  - bidirectional voice channel
GET    /sessions                                  - list recent sessions
GET    /sessions/{id}                             - full session detail
POST   /sessions/{id}/summary                     - generate / regenerate summary
GET    /users                                     - list users
GET    /users/{phone}/appointments                - list a user's appointments
GET    /appointments                              - list all appointments (admin view)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select

from .config import get_settings
from .database import init_db, session_scope
from .models import Appointment
from .routers import appointments, sessions, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

settings = get_settings()


async def _seed_demo_data_if_empty() -> None:
    """On a fresh deploy (Render's free tier wipes SQLite on every cold
    start), populate 3 demo appointments so the UI's 'Recent appointments'
    panel isn't empty when an evaluator first opens the app. Idempotent —
    only seeds when the table has zero rows.
    """
    from datetime import timedelta

    from .tools import dispatch_tool
    from .utils.time_utils import now_in_clinic

    async with session_scope() as db:
        existing = (await db.execute(select(Appointment))).first()
        if existing is not None:
            return

        seeds = [
            ("5550101010", "Demo Patient One", 1, 10, "Dr. Aisha Khan", "annual checkup"),
            ("5550202020", "Demo Patient Two", 2, 14, "Dr. Rohan Mehta", "fever follow-up"),
            ("5550303030", "Demo Patient Three", 3, 11, "Dr. Priya Sharma", "consultation"),
        ]
        for phone, name, dd, hh, prov, reason in seeds:
            await dispatch_tool(
                "identify_user", {"phone": phone, "name": name}, db, "auto-seed",
            )
            slot = (now_in_clinic() + timedelta(days=dd)).replace(
                hour=hh, minute=0, second=0, microsecond=0
            )
            await dispatch_tool(
                "book_appointment",
                {
                    "phone": phone,
                    "slot_start": slot.isoformat(timespec="seconds"),
                    "provider": prov,
                    "reason": reason,
                },
                db,
                "auto-seed",
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    try:
        await _seed_demo_data_if_empty()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("seed").warning("auto-seed skipped: %s", exc)
    yield


app = FastAPI(
    title="Mykare Voice AI",
    version="1.0.0",
    description=(
        "Production voice AI receptionist for healthcare appointment booking. "
        "Powered by OpenAI Realtime API + FastAPI + SQLite."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {
        "status": "ok",
        "version": "1.0.0",
        "openai_configured": bool(settings.openai_api_key),
    }


@app.get("/config", tags=["meta"])
async def public_config() -> dict:
    """Public-safe config used by the frontend at boot."""
    return {
        "clinic_name": settings.clinic_name,
        "clinic_timezone": settings.clinic_timezone,
        "providers": settings.providers,
        "voice": settings.openai_realtime_voice,
        "model": settings.openai_realtime_model,
        "openai_configured": bool(settings.openai_api_key),
    }


app.include_router(voice.router, prefix="/ws", tags=["voice"])
app.include_router(sessions.router)
app.include_router(appointments.router)
