"""Smoke tests for the tool layer.

Run with:
    cd backend && .venv/bin/python -m pytest -q
or directly:
    cd backend && .venv/bin/python tests/test_tools.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile

# Use an in-memory-ish temp DB so tests are isolated
_tmp = tempfile.mkstemp(suffix=".db")[1]
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}"

from app.database import init_db, session_scope  # noqa: E402
from app.tools import dispatch_tool  # noqa: E402


async def main() -> None:
    await init_db()

    async with session_scope() as db:
        # Identify a new user
        r = await dispatch_tool(
            "identify_user",
            {"phone": "(555) 123-9876", "name": "Alex Doe"},
            db,
            session_id="test-session",
        )
        assert r["ok"], r
        assert r["phone"] == "5551239876"
        print("identify_user OK")

        # Fetch slots for tomorrow
        r = await dispatch_tool(
            "fetch_slots",
            {"date": "tomorrow", "provider": "Dr. Aisha Khan"},
            db,
            session_id="test-session",
        )
        assert r["ok"], r
        assert len(r["slots"]) > 0
        slot_iso = r["slots"][0]["start"]
        print(f"fetch_slots OK ({len(r['slots'])} slots)")

        # Book a slot
        r = await dispatch_tool(
            "book_appointment",
            {
                "phone": "5551239876",
                "slot_start": slot_iso,
                "provider": "Dr. Aisha Khan",
                "reason": "annual checkup",
            },
            db,
            session_id="test-session",
        )
        assert r["ok"], r
        appt_id = r["appointment_id"]
        print(f"book_appointment OK (id={appt_id})")

        # Try to book the SAME slot again — must fail
        r = await dispatch_tool(
            "book_appointment",
            {
                "phone": "5551239876",
                "slot_start": slot_iso,
                "provider": "Dr. Aisha Khan",
            },
            db,
            session_id="test-session",
        )
        assert not r["ok"], "Double booking should have been prevented!"
        print("double-booking prevention OK")

        # Retrieve
        r = await dispatch_tool(
            "retrieve_appointments",
            {"phone": "5551239876"},
            db,
            session_id="test-session",
        )
        assert r["ok"] and r["count"] == 1
        print("retrieve_appointments OK")

        # Modify
        r2 = await dispatch_tool(
            "fetch_slots",
            {"date": "tomorrow", "provider": "Dr. Rohan Mehta"},
            db,
            session_id="test-session",
        )
        new_slot = r2["slots"][2]["start"]
        r = await dispatch_tool(
            "modify_appointment",
            {
                "phone": "5551239876",
                "appointment_id": appt_id,
                "new_slot_start": new_slot,
                "new_provider": "Dr. Rohan Mehta",
            },
            db,
            session_id="test-session",
        )
        assert r["ok"], r
        print("modify_appointment OK")

        # Cancel
        r = await dispatch_tool(
            "cancel_appointment",
            {"phone": "5551239876", "appointment_id": appt_id},
            db,
            session_id="test-session",
        )
        assert r["ok"]
        print("cancel_appointment OK")

        # End
        r = await dispatch_tool(
            "end_conversation",
            {"farewell": "Bye"},
            db,
            session_id="test-session",
        )
        assert r["ok"] and r.get("end_call")
        print("end_conversation OK")

    print("\nAll tool tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
