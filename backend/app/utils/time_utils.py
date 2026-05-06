"""Time / slot helpers for the appointment system.

The Realtime model already does great natural-language → ISO conversion when we
ask it to (we instruct it via the system prompt). This module is the
defensive last-mile parser/normalizer.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from dateutil import parser as date_parser
from dateutil.tz import gettz

from ..config import get_settings


# Standard clinic working window (configurable in a real system)
WORK_START_HOUR = 9
WORK_END_HOUR = 18
SLOT_DURATION_MIN = 30


def get_clinic_tz():
    return gettz(get_settings().clinic_timezone) or timezone.utc


def now_in_clinic() -> datetime:
    return datetime.now(tz=get_clinic_tz())


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _resolve_relative(value: str, now: datetime) -> Optional[datetime]:
    """Handle the relative date phrases dateutil doesn't grok: 'today',
    'tomorrow', 'next monday', 'in 3 days', '3 days from now', etc."""
    v = value.strip().lower()
    if v in {"today", "now"}:
        return now
    if v == "tomorrow":
        return now + timedelta(days=1)
    if v in {"day after tomorrow", "the day after tomorrow"}:
        return now + timedelta(days=2)

    # "next <weekday>"
    m = re.match(r"^(?:next|coming)\s+([a-z]+)$", v)
    if m and m.group(1) in _WEEKDAYS:
        target = _WEEKDAYS[m.group(1)]
        delta = (target - now.weekday()) % 7
        delta = delta or 7  # always next, not today
        return now + timedelta(days=delta)

    # bare "<weekday>" → next occurrence (today if today)
    if v in _WEEKDAYS:
        target = _WEEKDAYS[v]
        delta = (target - now.weekday()) % 7
        return now + timedelta(days=delta)

    # "in N day(s)" or "N days from now"
    m = re.match(r"^(?:in\s+)?(\d+)\s+days?(?:\s+from\s+now)?$", v)
    if m:
        return now + timedelta(days=int(m.group(1)))

    return None


def parse_to_iso(value: str) -> Optional[str]:
    """Parse a flexible date/time string into a clinic-tz ISO 8601 string.

    Returns None if the string can't be parsed. Always anchors to today
    if only a time is provided (and rolls to tomorrow if already past).
    """
    if not value:
        return None
    tz = get_clinic_tz()
    now = now_in_clinic()

    # Try relative phrases first (dateutil can't handle "tomorrow", weekdays etc.)
    rel = _resolve_relative(value, now)
    if rel is not None:
        # If the input had no explicit time, default to noon
        return rel.replace(hour=12, minute=0, second=0, microsecond=0).isoformat(
            timespec="seconds"
        )

    try:
        dt = date_parser.parse(value, fuzzy=True, default=now)
    except (ValueError, OverflowError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)

    return dt.isoformat(timespec="seconds")


def round_to_slot(dt: datetime) -> datetime:
    """Round down to the nearest SLOT_DURATION_MIN boundary."""
    minute = (dt.minute // SLOT_DURATION_MIN) * SLOT_DURATION_MIN
    return dt.replace(minute=minute, second=0, microsecond=0)


def normalize_slot(iso_str: str) -> Optional[Tuple[str, str]]:
    """Given an ISO start time, return (slot_start_iso, slot_end_iso) snapped
    to the slot grid. Returns None if invalid.
    """
    parsed = parse_to_iso(iso_str)
    if not parsed:
        return None
    dt = date_parser.isoparse(parsed)
    snapped = round_to_slot(dt)
    end = snapped + timedelta(minutes=SLOT_DURATION_MIN)
    return snapped.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def generate_slots_for_date(target: datetime, taken_starts: set[str]) -> List[dict]:
    """Generate the standard slot grid for a given date, marking which are
    taken. Returns slots as: {start, end, available, label}.
    """
    tz = get_clinic_tz()
    base = target.astimezone(tz).replace(
        hour=WORK_START_HOUR, minute=0, second=0, microsecond=0
    )
    end_of_day = base.replace(hour=WORK_END_HOUR)
    slots: List[dict] = []
    cur = base
    now = now_in_clinic()
    while cur < end_of_day:
        nxt = cur + timedelta(minutes=SLOT_DURATION_MIN)
        # Skip slots in the past (only relevant for today)
        if cur > now:
            iso = cur.isoformat(timespec="seconds")
            slots.append(
                {
                    "start": iso,
                    "end": nxt.isoformat(timespec="seconds"),
                    "available": iso not in taken_starts,
                    "label": cur.strftime("%a, %b %d at %I:%M %p"),
                }
            )
        cur = nxt
    return slots


_PHONE_DIGITS = re.compile(r"\D+")


def normalize_phone(raw: str) -> Optional[str]:
    """Strip everything except digits and a leading '+'.

    Returns None if there are fewer than 7 digits (likely a mis-transcription).
    """
    if not raw:
        return None
    raw = raw.strip()
    plus = "+" if raw.startswith("+") else ""
    digits = _PHONE_DIGITS.sub("", raw)
    if len(digits) < 7:
        return None
    return f"{plus}{digits}"


def parse_target_date(value: str) -> Optional[datetime]:
    """Parse loose date input into a tz-aware datetime at midnight clinic-tz."""
    iso = parse_to_iso(value)
    if not iso:
        return None
    dt = date_parser.isoparse(iso)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
