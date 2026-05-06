"""Seed the DB with a couple of demo users + appointments so the UI has
something to show on first load. Idempotent — safe to run multiple times.

Run from repo root:
    backend/.venv/bin/python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)
# Match uvicorn's cwd so the relative SQLite path lands in the same file.
os.chdir(BACKEND)

from app.database import init_db, session_scope  # noqa: E402
from app.tools import dispatch_tool  # noqa: E402
from app.utils.time_utils import now_in_clinic  # noqa: E402


async def main() -> None:
    await init_db()

    seeds = [
        {"phone": "5550101010", "name": "Demo Patient One",
         "delta_days": 1, "hour": 10, "provider": "Dr. Aisha Khan",
         "reason": "annual checkup"},
        {"phone": "5550202020", "name": "Demo Patient Two",
         "delta_days": 2, "hour": 14, "provider": "Dr. Rohan Mehta",
         "reason": "fever follow-up"},
        {"phone": "5550303030", "name": "Demo Patient Three",
         "delta_days": 3, "hour": 11, "provider": "Dr. Priya Sharma",
         "reason": "consultation"},
    ]

    async with session_scope() as db:
        for s in seeds:
            await dispatch_tool(
                "identify_user",
                {"phone": s["phone"], "name": s["name"]},
                db,
                "seed-session",
            )
            target = (now_in_clinic() + timedelta(days=s["delta_days"])).replace(
                hour=s["hour"], minute=0, second=0, microsecond=0
            )
            await dispatch_tool(
                "book_appointment",
                {
                    "phone": s["phone"],
                    "slot_start": target.isoformat(timespec="seconds"),
                    "provider": s["provider"],
                    "reason": s["reason"],
                },
                db,
                "seed-session",
            )
            print(f"  seeded: {s['name']} ({s['phone']}) → {s['provider']} on {target.strftime('%a %b %d %I:%M %p')}")

    print("Seed done.")


if __name__ == "__main__":
    asyncio.run(main())
