"""End-of-call summary generation.

Produces a structured JSON summary including:
  - one-paragraph plain-English summary
  - extracted name / phone / intent / preferences
  - timestamp
The full appointment list is attached separately by the route layer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Message, Session, ToolCallLog

settings = get_settings()


SUMMARY_SCHEMA_PROMPT = """You are summarizing a phone call between a healthcare front-desk
AI agent ("Aria") and a caller. Produce STRICT JSON with these keys:

{
  "summary": "1-2 sentence neutral summary of the call",
  "name": "caller's full name, or null",
  "phone": "caller's phone (digits, with optional leading +), or null",
  "intent": "primary reason for calling (book/cancel/reschedule/inquire) - 2-6 words",
  "preferences": ["short, high-signal preferences caller mentioned"],
  "actions_taken": ["bulleted list of what the agent actually DID, e.g. 'Booked Dr. Khan for May 12 at 11:30 AM'"],
  "follow_ups": ["any pending items the caller still needs to do, or empty"]
}

Rules:
- Output ONLY the JSON object, no prose.
- Empty arrays are fine. Use null for missing string fields.
- Do not invent facts not present in the transcript or tool log.
"""


def _format_transcript(messages: List[Message]) -> str:
    lines = []
    for m in messages:
        role = "Caller" if m.role == "user" else "Aria"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines) if lines else "(no transcript)"


def _format_tools(tools: List[ToolCallLog]) -> str:
    lines = []
    for t in tools:
        try:
            args = json.loads(t.arguments_json or "{}")
            res = json.loads(t.result_json or "{}")
        except json.JSONDecodeError:
            args, res = {}, {}
        ok = "OK" if t.success else "FAIL"
        lines.append(f"- [{ok}] {t.name}({json.dumps(args)}) → {json.dumps(res)}")
    return "\n".join(lines) if lines else "(no tools called)"


async def generate_summary_for_session(
    session_id: str, db: AsyncSession
) -> Dict[str, Any]:
    """Generates a summary, persists it on the session row, returns the dict."""

    sess = await db.get(Session, session_id)
    if sess is None:
        return {"error": "session not found"}

    msgs_res = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    )
    messages = msgs_res.scalars().all()
    tools_res = await db.execute(
        select(ToolCallLog).where(ToolCallLog.session_id == session_id).order_by(
            ToolCallLog.id
        )
    )
    tools = tools_res.scalars().all()

    if not settings.openai_api_key:
        # Graceful fallback: build a tiny rule-based summary so the UI still works
        return _fallback_summary(sess, messages, tools)

    transcript = _format_transcript(messages)
    tool_log = _format_tools(tools)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_summary_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SUMMARY_SCHEMA_PROMPT},
            {
                "role": "user",
                "content": (
                    f"TRANSCRIPT:\n{transcript}\n\n"
                    f"TOOL CALLS:\n{tool_log}\n\n"
                    "Return the JSON now."
                ),
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"summary": content}

    # Persist on the session
    sess.summary = data.get("summary")
    sess.extracted_name = data.get("name")
    sess.extracted_phone = data.get("phone")
    sess.extracted_intent = data.get("intent")
    sess.preferences = json.dumps(
        {
            "preferences": data.get("preferences", []),
            "actions_taken": data.get("actions_taken", []),
            "follow_ups": data.get("follow_ups", []),
        }
    )
    await db.commit()

    return data


def _fallback_summary(
    sess: Session, messages: List[Message], tools: List[ToolCallLog]
) -> Dict[str, Any]:
    actions = []
    phone = None
    for t in tools:
        try:
            args = json.loads(t.arguments_json or "{}")
            res = json.loads(t.result_json or "{}")
        except json.JSONDecodeError:
            continue
        if t.name == "identify_user":
            phone = res.get("phone") or args.get("phone")
        if t.name == "book_appointment" and res.get("ok"):
            actions.append(
                f"Booked {res.get('provider')} at {res.get('slot_start')}"
            )
        if t.name == "cancel_appointment" and res.get("ok"):
            actions.append(f"Cancelled appointment #{res.get('appointment_id')}")
        if t.name == "modify_appointment" and res.get("ok"):
            actions.append(
                f"Rescheduled to {res.get('provider')} at {res.get('slot_start')}"
            )

    summary_text = (
        f"Call with {len(messages)} exchanges. "
        f"{len(actions)} action(s) taken."
        if messages
        else "Empty call."
    )
    return {
        "summary": summary_text,
        "name": None,
        "phone": phone,
        "intent": None,
        "preferences": [],
        "actions_taken": actions,
        "follow_ups": [],
    }
