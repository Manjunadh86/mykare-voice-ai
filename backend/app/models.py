"""SQLAlchemy ORM models.

Schema overview
---------------
- User           : one row per phone number (the unique identity in our system).
- Session       : one voice call. Tracks costs, transcript, summary.
- Appointment    : booked slots. Soft-cancel via `status`. Hard uniqueness on
                  (provider, slot_start) when status='confirmed' to prevent
                  double-booking at the DB layer.
- ToolCallLog   : every tool invocation (great for debugging & audit).
- Message       : a single utterance (user or assistant) within a session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # No two CONFIRMED appointments for the same provider at the same start.
        # SQLite supports partial indexes via Index(..., sqlite_where=...).
        Index(
            "uq_provider_slot_confirmed",
            "provider",
            "slot_start",
            unique=True,
            sqlite_where=text("status = 'confirmed'"),
        ),
        Index("ix_appt_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Stored as ISO 8601 in the clinic timezone for human readability + easy querying.
    slot_start: Mapped[str] = mapped_column(String(32), nullable=False)  # "2026-05-12T10:30:00+05:30"
    slot_end: Mapped[str] = mapped_column(String(32), nullable=False)

    # 'confirmed' | 'cancelled'
    status: Mapped[str] = mapped_column(String(16), default="confirmed", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="appointments")


class Session(Base):
    """A single voice conversation."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Aggregated cost / usage (updated as the session runs)
    audio_input_ms: Mapped[int] = mapped_column(Integer, default=0)
    audio_output_ms: Mapped[int] = mapped_column(Integer, default=0)
    text_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    text_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # End-of-call artifacts
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    extracted_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    extracted_intent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string

    user: Mapped[Optional[User]] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.id"
    )
    tool_calls: Mapped[list["ToolCallLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ToolCallLog.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[Session] = relationship(back_populates="messages")


class ToolCallLog(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    arguments_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(default=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[Session] = relationship(back_populates="tool_calls")
