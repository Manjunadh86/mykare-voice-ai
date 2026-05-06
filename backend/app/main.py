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

from .config import get_settings
from .database import init_db
from .routers import appointments, sessions, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
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
