from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cctv_query.csv_store import load_records
from cctv_query.mock_data import FIELDNAMES
from cctv_query.normalization import normalize_cctv_id, normalize_date, normalize_event, normalize_time, time_to_seconds


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "all_required_output.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "cctv_vehicle_log_ready.csv"
OUTPUT_FIELDNAMES = tuple(column for column in FIELDNAMES if column != "Event")

ALIASES = {
    "date": ("Date", "date", "day"),
    "cctv_id": (
        "CCTV_ID",
        "CCTV ID",
        "cctv_id",
        "camera_id",
        "camera",
        "source_id",
        "source_uri",
        "stream_uri",
        "rtsp",
        "video",
        "video_name",
        "video_path",
        "filename",
        "Image_Path",
        "image_path",
    ),
    "timestamp": ("Timestamp", "timestamp", "time", "First_Timestamp", "first_timestamp"),
    "track_id": ("Track_ID", "track_id", "uuid", "object_id", "track_uuid"),
    "first_seen": ("First_Seen", "FirstSeen", "first_seen", "first_seen_iso", "first_seen_ts", "Timestamp", "timestamp"),
    "last_seen": (
        "Last_Seen",
        "LastSeen",
        "last_seen",
        "last_seen_iso",
        "last_seen_ts",
        "Tracking_Lost",
        "Lost_At",
        "Timestamp",
        "timestamp",
    ),
    "brand": ("Brand", "brand", "car_brand", "make"),
    "color": ("Color", "color", "car_color"),
    "type": ("Type", "type", "vehicle_type", "class", "label"),
    "event": ("Event", "event", "line_event"),
}

TYPE_ALIASES = {
    "car": "Car",
    "cars": "Car",
    "motorbike": "Motorcycle",
    "motorbikes": "Motorcycle",
    "motorcycle": "Motorcycle",
    "motorcycles": "Motorcycle",
    "bike": "Motorcycle",
    "truck": "Truck",
    "trucks": "Truck",
    "bus": "Bus",
    "buses": "Bus",
}

UNKNOWN_VALUES = {"", "unknown", "none", "null", "nan", "n/a", "-"}


@dataclass(frozen=True)
class ConversionReport:
    input_rows: int
    output_rows: int
    skipped_rows: int
    warnings: tuple[str, ...] = ()


@dataclass
class _PreparedRow:
    date: str
    cctv_id: str
    first_seen: str
    last_seen: str
    brand: str
    color: str
    vehicle_type: str
    event: str
    row_number: int
    track_id: str = ""


def convert_csv(
    input_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_OUTPUT,
    *,
    camera_id_map: dict[str, str] | None = None,
) -> ConversionReport:
    source = Path(input_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"Input CSV not found: {source}")

    prepared_rows: list[_PreparedRow] = []
    warnings: list[str] = []
    with source.open("r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError(f"Input CSV has no header: {source}")
        for row_number, row in enumerate(reader, start=2):
            try:
                prepared_rows.append(_prepare_row(row, row_number, camera_id_map=camera_id_map))
            except ValueError as exc:
                warnings.append(f"row {row_number}: skipped: {exc}")

    output_rows = _aggregate_rows(prepared_rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(OUTPUT_FIELDNAMES), lineterminator="\n")
        writer.writeheader()
        writer.writerows(_without_event(row) for row in output_rows)

    try:
        load_records(target)
    except Exception as exc:
        raise ValueError(f"Converted CSV is not loadable by the site: {exc}") from exc

    return ConversionReport(
        input_rows=len(prepared_rows) + len(warnings),
        output_rows=len(output_rows),
        skipped_rows=len(warnings),
        warnings=tuple(warnings),
    )


def _prepare_row(
    row: dict[str, str],
    row_number: int,
    *,
    camera_id_map: dict[str, str] | None = None,
) -> _PreparedRow:
    first_raw = _first_value(row, ALIASES["first_seen"]) or _first_value(row, ALIASES["timestamp"])
    last_raw = _first_value(row, ALIASES["last_seen"]) or first_raw
    date_raw = _first_value(row, ALIASES["date"])

    first_seen = _parse_time(first_raw)
    last_seen = _parse_time(last_raw or first_raw)
    date = _parse_date(date_raw, fallback_datetime=first_raw)
    cctv_id = _normalize_camera_id(_required_value(row, ALIASES["cctv_id"], "CCTV_ID"), camera_id_map=camera_id_map)
    color = _clean_label(_first_value(row, ALIASES["color"]), default="Unknown")
    vehicle_type = _normalize_type(_first_value(row, ALIASES["type"]))
    brand = _normalize_brand(_first_value(row, ALIASES["brand"]), vehicle_type)
    event_raw = _first_value(row, ALIASES["event"])
    event = normalize_event(event_raw) if event_raw else ""
    track_id = _first_value(row, ALIASES["track_id"])

    return _PreparedRow(
        date=date,
        cctv_id=cctv_id,
        first_seen=first_seen,
        last_seen=last_seen,
        brand=brand,
        color=color,
        vehicle_type=vehicle_type,
        event=event,
        row_number=row_number,
        track_id=track_id.strip(),
    )


def _aggregate_rows(rows: list[_PreparedRow]) -> list[dict[str, str]]:
    groups: dict[tuple[Any, ...], list[_PreparedRow]] = defaultdict(list)
    for row in rows:
        if row.track_id:
            key = (row.date, row.cctv_id, row.track_id, row.first_seen, row.last_seen)
        else:
            key = ("row", row.row_number)
        groups[key].append(row)

    output_rows: list[dict[str, str]] = []
    for group_rows in groups.values():
        first_seconds = min(time_to_seconds(row.first_seen) for row in group_rows)
        last_seconds = max(time_to_seconds(row.last_seen) for row in group_rows)
        output_rows.append(
            {
                "Date": group_rows[0].date,
                "CCTV_ID": group_rows[0].cctv_id,
                "First_Seen": _format_seconds(first_seconds),
                "Last_Seen": _format_seconds(last_seconds),
                "Brand": _most_common(row.brand for row in group_rows),
                "Color": _most_common(row.color for row in group_rows),
                "Type": _most_common(row.vehicle_type for row in group_rows),
                "Event": _most_common_event(row.event for row in group_rows),
            }
        )

    return sorted(output_rows, key=_sort_key)


def _first_value(row: dict[str, str], names: tuple[str, ...]) -> str:
    normalized = {_normalize_header(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(_normalize_header(name))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _required_value(row: dict[str, str], names: tuple[str, ...], label: str) -> str:
    value = _first_value(row, names)
    if not value:
        raise ValueError(f"missing {label}")
    return value


def _parse_date(value: str, *, fallback_datetime: str) -> str:
    if value:
        return normalize_date(value)
    parsed = _parse_datetime(fallback_datetime)
    if parsed:
        return parsed.strftime("%d-%m-%Y")
    raise ValueError("missing Date and no parseable timestamp")


def _parse_time(value: str) -> str:
    if not value:
        raise ValueError("missing time")
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.strftime("%H:%M:%S")
    return normalize_time(value)


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text))
        except (OverflowError, OSError, ValueError):
            return None
    candidates = (text, text.replace("Z", "+00:00"), text.replace(" ", "T"))
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _clean_label(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return default if text.casefold() in UNKNOWN_VALUES else text


def _normalize_type(value: str) -> str:
    text = _clean_label(value, default="Unknown")
    return TYPE_ALIASES.get(text.casefold(), text[:1].upper() + text[1:] if text else "Unknown")


def _normalize_brand(value: str, vehicle_type: str) -> str:
    type_key = vehicle_type.casefold()
    if type_key == "motorcycle":
        return "Motorcycle"
    if type_key == "truck":
        return "Hino"
    brand = _clean_label(value, default="Unknown")
    brand_key = brand.casefold()
    if brand_key in {"motorcycle", "motorbike", "motorcycles", "motorbikes", "bike"}:
        return "Motorcycle"
    if brand_key in {"truck", "trucks"}:
        return "Hino"
    return brand


def _normalize_camera_id(value: str, *, camera_id_map: dict[str, str] | None = None) -> str:
    text = str(value or "").strip()
    if camera_id_map:
        mapped = _mapped_camera_id(text, camera_id_map)
        if mapped:
            return mapped
    normalized_text = text.replace("O", "0").replace("o", "0")
    match = re.search(r"\b(?:CCTV|camera|cam)\s*0*(\d{1,2})\b", normalized_text, flags=re.IGNORECASE)
    if match:
        return normalize_cctv_id(match.group(1))
    if re.fullmatch(r"\s*0*\d{1,2}\s*", normalized_text):
        return normalize_cctv_id(normalized_text)
    raise ValueError(f"Invalid CCTV_ID '{value}'. Expected CCTV01-CCTV10.")


def _mapped_camera_id(value: str, camera_id_map: dict[str, str]) -> str:
    text = str(value or "").casefold().replace("\\", "/")
    normalized_map = {key.casefold(): mapped for key, mapped in camera_id_map.items()}
    for key, mapped in sorted(normalized_map.items(), key=lambda item: len(item[0]), reverse=True):
        if _contains_token(text, key):
            return mapped
    return ""


def _contains_token(text: str, token: str) -> bool:
    separators = "/\\:_-. "
    start = 0
    while True:
        index = text.find(token, start)
        if index < 0:
            return False
        before = text[index - 1] if index > 0 else ""
        after_index = index + len(token)
        after = text[after_index] if after_index < len(text) else ""
        if (not before or before in separators) and (not after or after in separators):
            return True
        start = index + 1


def _most_common(values: Any) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    known = [value for value in cleaned if value.casefold() not in UNKNOWN_VALUES]
    candidates = known or cleaned or ["Unknown"]
    counts = Counter(candidates)
    return max(counts, key=lambda value: (counts[value], -candidates.index(value)))


def _most_common_event(values: Any) -> str:
    cleaned = [str(value).strip() for value in values]
    candidates = [value for value in cleaned if value]
    if not candidates:
        return ""
    counts = Counter(candidates)
    return max(counts, key=lambda value: (counts[value], -candidates.index(value)))


def _format_seconds(seconds: int) -> str:
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _normalize_header(value: str) -> str:
    return str(value).strip().casefold().replace(" ", "_").replace("-", "_")


def _sort_key(row: dict[str, str]) -> tuple[Any, ...]:
    parsed_date = datetime.strptime(row["Date"], "%d-%m-%Y")
    return (parsed_date, row["First_Seen"], row["CCTV_ID"], row["Brand"].casefold(), row["Color"].casefold(), row["Type"].casefold())


def _without_event(row: dict[str, str]) -> dict[str, str]:
    return {column: row[column] for column in OUTPUT_FIELDNAMES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert CCTV detection CSVs into the web app CSV contract.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input CSV. Defaults to all_required_output.csv.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output CSV. Defaults to cctv_vehicle_log_ready.csv.")
    parser.add_argument("--strict", action="store_true", help="Fail if any rows are skipped.")
    parser.add_argument("--show-warnings", action="store_true", help="Print skipped-row warnings.")
    args = parser.parse_args(argv)

    report = convert_csv(args.input, args.output)
    print(f"input_rows={report.input_rows}")
    print(f"output_rows={report.output_rows}")
    print(f"skipped_rows={report.skipped_rows}")
    print(f"output={Path(args.output).resolve()}")
    if args.show_warnings:
        for warning in report.warnings:
            print(warning)
    if args.strict and report.skipped_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
