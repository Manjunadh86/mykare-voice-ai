"""Pydantic schemas used by the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    name: Optional[str] = None
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    reason: Optional[str] = None
    slot_start: str
    slot_end: str
    status: str
    created_at: datetime


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    arguments_json: str
    result_json: Optional[str] = None
    success: bool
    duration_ms: Optional[int] = None
    created_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    audio_input_ms: int
    audio_output_ms: int
    text_input_tokens: int
    text_output_tokens: int
    estimated_cost_usd: float
    summary: Optional[str] = None
    extracted_name: Optional[str] = None
    extracted_phone: Optional[str] = None
    extracted_intent: Optional[str] = None
    preferences: Optional[str] = None


class SessionDetail(SessionOut):
    messages: List[MessageOut] = Field(default_factory=list)
    tool_calls: List[ToolCallOut] = Field(default_factory=list)
    appointments: List[AppointmentOut] = Field(default_factory=list)


class SummaryRequest(BaseModel):
    session_id: str


class CostBreakdown(BaseModel):
    audio_input_min: float
    audio_output_min: float
    text_input_tokens: int
    text_output_tokens: int
    audio_input_cost: float
    audio_output_cost: float
    text_input_cost: float
    text_output_cost: float
    total_cost_usd: float
