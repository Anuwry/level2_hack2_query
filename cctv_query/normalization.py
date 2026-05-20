from __future__ import annotations

import re
from datetime import datetime


DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d %m %Y", "%Y-%m-%d", "%Y/%m/%d", "%Y %m %d")
TIME_PATTERN = re.compile(r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?::(?P<second>\d{1,2}))?\s*$")


def normalize_date(value: str) -> str:
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Expected DD-MM-YYYY or YYYY-MM-DD.")


def normalize_cctv_id(value: str) -> str:
    text = value.strip().replace("O", "0").replace("o", "0")
    match = re.search(r"(?:CCTV\s*)?0*(\d{1,2})\b", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid CCTV_ID '{value}'. Expected CCTV01-CCTV10.")
    number = int(match.group(1))
    return f"CCTV{number:02d}"


def normalize_time(value: str) -> str:
    match = TIME_PATTERN.match(value)
    if not match:
        raise ValueError(f"Invalid time '{value}'. Expected HH:MM[:SS].")

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second") or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Invalid time '{value}'. Time is outside 00:00:00-23:59:59.")
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def time_to_seconds(value: str) -> int:
    hour, minute, second = (int(part) for part in normalize_time(value).split(":"))
    return hour * 3600 + minute * 60 + second
