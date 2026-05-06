"""Tool catalog + executors.

This module is the bridge between the LLM and our database. Each tool:

1. Has a JSON schema that the LLM sees (used in `session.update`).
2. Has an `execute_*` function with the same name (minus the prefix).

The tools deliberately return small, well-structured JSON the model can read
out loud naturally. We never leak DB ids unless the model needs them
internally (we wrap them in `_id` so the model knows not to verbalize them).
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Appointment, ToolCallLog, User
from .utils.time_utils import (
    SLOT_DURATION_MIN,
    generate_slots_for_date,
    normalize_phone,
    normalize_slot,
    now_in_clinic,
    parse_target_date,
)

settings = get_settings()


# ---------------------------------------------------------------------------
# Tool schemas (what the OpenAI Realtime model sees)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "identify_user",
        "description": (
            "Identify (or create) the user by their phone number. "
            "Always call this BEFORE booking, modifying, cancelling or fetching "
            "appointments. The phone number is the unique identifier."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "User's phone number. Digits only or with leading +.",
                },
                "name": {
                    "type": "string",
                    "description": "User's full name if they provided one.",
                },
            },
            "required": ["phone"],
        },
    },
    {
        "type": "function",
        "name": "fetch_slots",
        "description": (
            "Fetch available appointment slots for a given date and (optional) "
            "provider. Returns a small list of slot strings the user can pick from."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Target date in any human form ('tomorrow', 'May 12', "
                        "'2026-05-12'). Required."
                    ),
                },
                "provider": {
                    "type": "string",
                    "description": "Specific doctor name. Omit for any provider.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": (
            "Book a confirmed appointment. Requires identify_user to have been "
            "called first. Returns an error if the slot is already taken."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "User phone (must already be identified)."},
                "slot_start": {
                    "type": "string",
                    "description": "ISO 8601 start time as returned by fetch_slots.",
                },
                "provider": {"type": "string", "description": "Doctor name."},
                "reason": {
                    "type": "string",
                    "description": "Short reason for the visit (e.g. 'follow-up', 'fever').",
                },
            },
            "required": ["phone", "slot_start", "provider"],
        },
    },
    {
        "type": "function",
        "name": "retrieve_appointments",
        "description": "List the user's upcoming and past appointments.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "include_cancelled": {"type": "boolean", "default": False},
            },
            "required": ["phone"],
        },
    },
    {
        "type": "function",
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment. Use the appointment_id from retrieve_appointments.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "appointment_id": {"type": "integer"},
            },
            "required": ["phone", "appointment_id"],
        },
    },
    {
        "type": "function",
        "name": "modify_appointment",
        "description": (
            "Reschedule an existing appointment to a new slot. The old slot is "
            "freed and the new slot is reserved atomically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "appointment_id": {"type": "integer"},
                "new_slot_start": {
                    "type": "string",
                    "description": "New ISO 8601 start time.",
                },
                "new_provider": {
                    "type": "string",
                    "description": "Optionally change the provider.",
                },
            },
            "required": ["phone", "appointment_id", "new_slot_start"],
        },
    },
    {
        "type": "function",
        "name": "end_conversation",
        "description": (
            "Politely end the call when the user says goodbye or has no more "
            "needs. The frontend will play the farewell, then disconnect."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "farewell": {
                    "type": "string",
                    "description": "Short final message, e.g. 'Take care!'",
                }
            },
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt() -> str:
    providers = ", ".join(settings.providers)
    today = now_in_clinic().strftime("%A, %B %d, %Y at %I:%M %p %Z")
    return f"""You are Aria, the warm, professional voice receptionist for {settings.clinic_name}.

Today is {today}. The clinic timezone is {settings.clinic_timezone}.
Available providers: {providers}.
Standard slot length: {SLOT_DURATION_MIN} minutes. Working hours: 9:00 AM - 6:00 PM.

PERSONALITY
- Warm, calm, concise. Sound like a real human, not a script.
- Speak in short sentences. One question at a time.
- Confirm important details (date, time, provider, name, phone) clearly.

CONVERSATION FLOW
1. Greet the caller in ONE short sentence ("Mykare Health, this is Aria — how can I help?"). DO NOT call any tool in this opening turn.
2. WAIT for the caller to actually speak. Only respond once you've heard a clear user message.
3. As soon as the caller gives a phone number, call `identify_user`. The phone number is their unique ID.
4. For any booking-related action, ALWAYS call the relevant tool — never invent appointment data.
5. When fetching slots, list 3-4 options succinctly ("I have 10 AM, 11:30 AM, or 2 PM. Which works?"). Don't read every slot.
6. After booking/cancelling/modifying, repeat the confirmation back ("Booked: tomorrow at 11:30 AM with Dr. Khan. Anything else?").
7. If the caller asks something out of scope (e.g. medical advice), politely redirect.

ECHO / NOISE HANDLING (very important)
- If the input audio sounds like your OWN previous words coming back (echo from speakers), or is muffled, fragmented, or just background noise — DO NOT respond and DO NOT call any tool. Stay silent and wait for a clear user turn.
- If you only catch one or two unclear words, ask "Sorry, could you repeat that?" — do NOT guess and do NOT call tools on guesses.
- NEVER call a tool unless the user has clearly and unambiguously asked for that action in their LATEST turn.

TOOL USAGE RULES
- ALWAYS call `identify_user` before any other appointment tool, even if the user just gave their name.
- Phone numbers spoken naturally ("nine eight seven six...") should be passed as the digits-only string.
- Pass slot_start values exactly as returned by fetch_slots — do not reformat them.
- Use `end_conversation` when the user says bye, "that's all", "thanks, that's it", etc.
- If a tool returns an error, apologize briefly and offer an alternative.

EXTRACTION
Throughout the call, you are also extracting: caller's full name, phone number,
desired date/time, and the visit intent (e.g. "fever follow-up", "annual check-up").
The summary tool will use these later — speak naturally, but make sure they get captured.

Begin by greeting the caller warmly.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_user(
    db: AsyncSession, phone: str, name: Optional[str] = None
) -> User:
    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(phone=phone, name=name)
        db.add(user)
        await db.flush()
    elif name and not user.name:
        user.name = name
    return user


def _err(message: str, **extra) -> Dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _ok(**fields) -> Dict[str, Any]:
    return {"ok": True, **fields}


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def execute_identify_user(args: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    phone = normalize_phone(args.get("phone", ""))
    if not phone:
        return _err("Invalid phone number. Please ask the user to repeat it.")
    name = (args.get("name") or "").strip() or None

    user = await _get_or_create_user(db, phone, name)
    await db.commit()

    res = await db.execute(
        select(Appointment)
        .where(Appointment.user_id == user.id, Appointment.status == "confirmed")
        .order_by(Appointment.slot_start)
    )
    upcoming = res.scalars().all()

    return _ok(
        user_id=user.id,
        phone=user.phone,
        name=user.name,
        is_returning=len(upcoming) > 0,
        upcoming_count=len(upcoming),
        message=(
            f"Identified {user.name or 'the caller'} ({user.phone}). "
            f"They have {len(upcoming)} upcoming appointment(s)."
        ),
    )


async def execute_fetch_slots(args: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    target = parse_target_date(args.get("date", ""))
    if not target:
        return _err("Couldn't understand that date. Please ask the user to clarify.")

    provider = (args.get("provider") or "").strip()
    if provider and provider not in settings.providers:
        # Try a fuzzy match
        provider_norm = next(
            (p for p in settings.providers if provider.lower() in p.lower()),
            None,
        )
        if provider_norm:
            provider = provider_norm
        else:
            return _err(
                f"Unknown provider '{provider}'. Available: {', '.join(settings.providers)}"
            )

    # Find the day window
    day_start = target.isoformat()
    day_end = (target + timedelta(days=1)).isoformat()

    q = select(Appointment).where(
        Appointment.status == "confirmed",
        Appointment.slot_start >= day_start,
        Appointment.slot_start < day_end,
    )
    if provider:
        q = q.where(Appointment.provider == provider)

    res = await db.execute(q)
    taken_starts = {a.slot_start for a in res.scalars().all()}

    slots = generate_slots_for_date(target, taken_starts)
    available = [s for s in slots if s["available"]][:6]  # top 6

    return _ok(
        date=target.strftime("%A, %B %d, %Y"),
        provider=provider or "any provider",
        slots=available,
        total_available=len(available),
        message=(
            f"Found {len(available)} open slots on {target.strftime('%a %b %d')}."
            if available
            else f"No openings on {target.strftime('%a %b %d')}. Try another day."
        ),
    )


async def execute_book_appointment(args: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    phone = normalize_phone(args.get("phone", ""))
    if not phone:
        return _err("Missing or invalid phone number.")

    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        return _err("User not identified. Call identify_user first.")

    slot = normalize_slot(args.get("slot_start", ""))
    if not slot:
        return _err("Invalid slot_start. Please ask the user to pick another time.")
    slot_start, slot_end = slot

    provider = (args.get("provider") or "").strip()
    if not provider:
        return _err("Provider is required.")
    if provider not in settings.providers:
        provider_norm = next(
            (p for p in settings.providers if provider.lower() in p.lower()),
            None,
        )
        if not provider_norm:
            return _err(f"Unknown provider. Choose one of: {', '.join(settings.providers)}")
        provider = provider_norm

    # Conflict check (defensive — also guarded by partial unique index)
    res = await db.execute(
        select(Appointment).where(
            Appointment.provider == provider,
            Appointment.slot_start == slot_start,
            Appointment.status == "confirmed",
        )
    )
    if res.scalar_one_or_none():
        return _err(
            "That slot was just taken. Please offer the user another time.",
            slot_start=slot_start,
            provider=provider,
        )

    appt = Appointment(
        user_id=user.id,
        provider=provider,
        slot_start=slot_start,
        slot_end=slot_end,
        reason=(args.get("reason") or "").strip() or None,
        status="confirmed",
    )
    db.add(appt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _err("That slot is no longer available — please offer another.")

    return _ok(
        appointment_id=appt.id,
        provider=appt.provider,
        slot_start=appt.slot_start,
        slot_end=appt.slot_end,
        reason=appt.reason,
        message=(
            f"Booked {appt.provider} for {appt.slot_start}. "
            "Confirm clearly with the caller."
        ),
    )


async def execute_retrieve_appointments(
    args: Dict[str, Any], db: AsyncSession
) -> Dict[str, Any]:
    phone = normalize_phone(args.get("phone", ""))
    if not phone:
        return _err("Missing or invalid phone number.")
    include_cancelled = bool(args.get("include_cancelled", False))

    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        return _ok(appointments=[], message="No user found with that phone.")

    q = select(Appointment).where(Appointment.user_id == user.id)
    if not include_cancelled:
        q = q.where(Appointment.status == "confirmed")
    q = q.order_by(Appointment.slot_start)
    res = await db.execute(q)
    rows = res.scalars().all()

    return _ok(
        appointments=[
            {
                "appointment_id": a.id,
                "provider": a.provider,
                "slot_start": a.slot_start,
                "slot_end": a.slot_end,
                "status": a.status,
                "reason": a.reason,
            }
            for a in rows
        ],
        count=len(rows),
        message=f"User has {len(rows)} appointment(s).",
    )


async def execute_cancel_appointment(
    args: Dict[str, Any], db: AsyncSession
) -> Dict[str, Any]:
    phone = normalize_phone(args.get("phone", ""))
    appt_id = args.get("appointment_id")
    if not phone or not appt_id:
        return _err("phone and appointment_id are required.")

    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        return _err("User not found.")

    res = await db.execute(
        select(Appointment).where(
            Appointment.id == appt_id, Appointment.user_id == user.id
        )
    )
    appt = res.scalar_one_or_none()
    if appt is None:
        return _err("That appointment doesn't belong to this user.")
    if appt.status == "cancelled":
        return _ok(message="Already cancelled.", appointment_id=appt.id)

    appt.status = "cancelled"
    await db.commit()

    return _ok(
        appointment_id=appt.id,
        provider=appt.provider,
        slot_start=appt.slot_start,
        message=f"Cancelled appointment with {appt.provider} on {appt.slot_start}.",
    )


async def execute_modify_appointment(
    args: Dict[str, Any], db: AsyncSession
) -> Dict[str, Any]:
    phone = normalize_phone(args.get("phone", ""))
    appt_id = args.get("appointment_id")
    new_start = args.get("new_slot_start")
    new_provider = (args.get("new_provider") or "").strip()
    if not (phone and appt_id and new_start):
        return _err("phone, appointment_id and new_slot_start are required.")

    res = await db.execute(select(User).where(User.phone == phone))
    user = res.scalar_one_or_none()
    if user is None:
        return _err("User not found.")

    res = await db.execute(
        select(Appointment).where(
            Appointment.id == appt_id, Appointment.user_id == user.id
        )
    )
    appt = res.scalar_one_or_none()
    if appt is None:
        return _err("That appointment doesn't belong to this user.")
    if appt.status != "confirmed":
        return _err("Cannot modify a non-confirmed appointment.")

    slot = normalize_slot(new_start)
    if not slot:
        return _err("Invalid new_slot_start.")
    s, e = slot

    provider = new_provider or appt.provider
    if provider not in settings.providers:
        provider_norm = next(
            (p for p in settings.providers if provider.lower() in p.lower()),
            None,
        )
        if not provider_norm:
            return _err(f"Unknown provider. Choose one of: {', '.join(settings.providers)}")
        provider = provider_norm

    # Conflict check (excluding this appointment)
    res = await db.execute(
        select(Appointment).where(
            Appointment.provider == provider,
            Appointment.slot_start == s,
            Appointment.status == "confirmed",
            Appointment.id != appt.id,
        )
    )
    if res.scalar_one_or_none():
        return _err("That new slot is taken — offer another time.")

    appt.slot_start = s
    appt.slot_end = e
    appt.provider = provider
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _err("Conflict — that slot is no longer free.")

    return _ok(
        appointment_id=appt.id,
        provider=appt.provider,
        slot_start=appt.slot_start,
        message=f"Rescheduled to {appt.provider} at {appt.slot_start}.",
    )


async def execute_end_conversation(
    args: Dict[str, Any], db: AsyncSession
) -> Dict[str, Any]:
    farewell = (args.get("farewell") or "Take care!").strip()
    return _ok(message=farewell, end_call=True)


# ---------------------------------------------------------------------------
# Dispatcher (called by the realtime proxy)
# ---------------------------------------------------------------------------

EXECUTORS = {
    "identify_user": execute_identify_user,
    "fetch_slots": execute_fetch_slots,
    "book_appointment": execute_book_appointment,
    "retrieve_appointments": execute_retrieve_appointments,
    "cancel_appointment": execute_cancel_appointment,
    "modify_appointment": execute_modify_appointment,
    "end_conversation": execute_end_conversation,
}


async def dispatch_tool(
    name: str,
    args: Dict[str, Any],
    db: AsyncSession,
    session_id: str,
) -> Dict[str, Any]:
    """Run a tool by name and log the call. Always returns a dict."""
    started = time.time()
    fn = EXECUTORS.get(name)
    if fn is None:
        result = _err(f"Unknown tool: {name}")
        success = False
    else:
        try:
            result = await fn(args, db)
            success = bool(result.get("ok", False))
        except Exception as exc:  # noqa: BLE001
            result = _err(f"Tool crashed: {exc}")
            success = False

    duration_ms = int((time.time() - started) * 1000)

    log = ToolCallLog(
        session_id=session_id,
        name=name,
        arguments_json=json.dumps(args, default=str),
        result_json=json.dumps(result, default=str),
        success=success,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.commit()

    return result
