"""Pure scheduling utilities: time parsing, ICS serialisation, recurrence maths.

All functions here are stateless — they take plain values and return plain values.
RuntimeStore delegates its @staticmethod scheduler helpers to these functions so
the logic lives in one testable place.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_due_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_time_component(raw: str | None) -> tuple[int, int]:
    if not raw:
        return (9, 0)
    text = raw.strip().lower()
    match_ampm = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if match_ampm:
        hour = int(match_ampm.group(1))
        minute = int(match_ampm.group(2) or "0")
        meridiem = match_ampm.group(3)
        hour = hour % 12
        if meridiem == "pm":
            hour += 12
        return (hour, minute)
    match_24 = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
    if match_24:
        hour = int(match_24.group(1))
        minute = int(match_24.group(2) or "0")
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    return (9, 0)


def resolve_timezone(name: str | None) -> tuple[timezone | ZoneInfo, bool]:
    if not name:
        return timezone.utc, False
    tz_name = name.strip()
    if not tz_name:
        return timezone.utc, False
    try:
        return ZoneInfo(tz_name), False
    except Exception:
        pass

    normalized = tz_name.upper()
    fallback_minutes = {
        "UTC": 0,
        "ETC/UTC": 0,
        "GMT": 0,
        "ASIA/MANILA": 8 * 60,
        "ASIA/SINGAPORE": 8 * 60,
        "ASIA/HONG_KONG": 8 * 60,
        "ASIA/TOKYO": 9 * 60,
        "ASIA/SEOUL": 9 * 60,
        "AMERICA/NEW_YORK": -5 * 60,
        "AMERICA/CHICAGO": -6 * 60,
        "AMERICA/DENVER": -7 * 60,
        "AMERICA/LOS_ANGELES": -8 * 60,
        "EUROPE/LONDON": 0,
        "EUROPE/PARIS": 60,
    }.get(normalized)
    if fallback_minutes is not None:
        return timezone(timedelta(minutes=fallback_minutes)), True

    offset_match = re.fullmatch(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", normalized)
    if offset_match:
        sign = 1 if offset_match.group(1) == "+" else -1
        hours = int(offset_match.group(2))
        minutes = int(offset_match.group(3) or "0")
        total_minutes = sign * (hours * 60 + minutes)
        return timezone(timedelta(minutes=total_minutes)), True
    return timezone.utc, True


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_next_run(due: datetime, recurrence: str, now_utc: datetime) -> datetime:
    interval = timedelta(days=1) if recurrence == "daily" else timedelta(days=7)
    next_due = due
    while next_due <= now_utc:
        next_due = next_due + interval
    return next_due


def ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def unfold_ics_lines(raw_text: str) -> list[str]:
    unfolded: list[str] = []
    for line in raw_text.splitlines():
        if (line.startswith(" ") or line.startswith("\t")) and unfolded:
            unfolded[-1] = unfolded[-1] + line[1:]
            continue
        unfolded.append(line)
    return unfolded


def parse_ics_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    key = parts[0].upper().strip()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        name, raw_value = part.split("=", 1)
        params[name.upper().strip()] = raw_value.strip()
    return key, params, value.strip()


def parse_ics_datetime(raw: str, tzid: str | None = None) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    tz, _ = resolve_timezone(tzid or "UTC")
    try:
        if value.endswith("Z"):
            dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if "T" in value:
            dt_local = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            return dt_local.astimezone(timezone.utc)
        dt_local = datetime.strptime(value, "%Y%m%d").replace(tzinfo=tz)
        return dt_local.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_ics_trigger_minutes(raw: str) -> int | None:
    text = raw.strip().upper()
    if not text.startswith("-P"):
        return None
    match = re.fullmatch(
        r"-P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
        text,
    )
    if not match:
        return None
    days = int(match.group(1) or "0")
    hours = int(match.group(2) or "0")
    minutes = int(match.group(3) or "0")
    seconds = int(match.group(4) or "0")
    total_minutes = days * 24 * 60 + hours * 60 + minutes + (1 if seconds > 0 else 0)
    if total_minutes <= 0:
        return None
    return total_minutes
