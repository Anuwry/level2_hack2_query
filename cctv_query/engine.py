from __future__ import annotations

from collections import Counter
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.models import CCTVRecord, QueryResult, QuerySpec, QuerySummary, VehicleRoute
from cctv_query.parser import parse_question


UNIQUE_VEHICLE_GAP_SECONDS = 30 * 60

THAI_TYPE_LABELS = {
    "Car": "รถยนต์",
    "Motorcycle": "มอเตอร์ไซค์",
    "Bus": "รถบัส",
    "Truck": "รถบรรทุก",
}


class CCTVQueryEngine:
    def __init__(self, records: list[CCTVRecord]):
        self.records = records
        self.known_brands = sorted({record.brand for record in records})
        self.known_colors = sorted({record.color for record in records})
        self.known_dates = sorted({record.date for record in records})

    @classmethod
    def from_csv(cls, path: str | Path) -> "CCTVQueryEngine":
        return cls(load_records(path))

    def ask(self, question: str) -> QueryResult:
        spec = parse_question(
            question,
            known_brands=self.known_brands,
            known_colors=self.known_colors,
            known_dates=self.known_dates,
        )
        matches = self.filter_records(spec)
        if spec.wants_route:
            routes = self.find_routes(spec)
            route_matches = [record for route in routes for record in route.detections]
            summary = summarize_routes(routes)
            answer = format_answer(spec, summary, routes=routes)
            return QueryResult(spec=spec, matches=route_matches, routes=routes, summary=summary, answer=answer)

        routes = build_vehicle_routes(matches)
        summary = summarize_routes(routes)
        answer = format_answer(spec, summary, routes=routes)
        return QueryResult(spec=spec, matches=matches, routes=routes, summary=summary, answer=answer)

    def filter_records(self, spec: QuerySpec) -> list[CCTVRecord]:
        return [record for record in self.records if _matches(record, spec)]

    def find_routes(self, spec: QuerySpec) -> list[VehicleRoute]:
        return [
            route
            for route in build_vehicle_routes(self.records)
            if any(_matches(record, spec) for record in route.detections)
        ]


def summarize(records: list[CCTVRecord], event_count: int | None = None) -> QuerySummary:
    return QuerySummary(
        brand_color_counts=Counter((record.brand, record.color) for record in records),
        brand_counts=Counter(record.brand for record in records),
        color_counts=Counter(record.color for record in records),
        type_counts=Counter(record.vehicle_type for record in records),
        event_count=len(records) if event_count is None else event_count,
        unique_vehicle_count=len(records),
    )


def summarize_routes(routes: list[VehicleRoute]) -> QuerySummary:
    representatives = [route.representative for route in routes]
    return summarize(representatives, event_count=sum(route.event_count for route in routes))


def unique_vehicle_representatives(records: list[CCTVRecord]) -> list[CCTVRecord]:
    return [route.representative for route in build_vehicle_routes(records)]


def build_vehicle_routes(records: list[CCTVRecord]) -> list[VehicleRoute]:
    route_records: list[list[CCTVRecord]] = []
    current_by_signature: dict[tuple[str, str, str, str], list[CCTVRecord]] = {}
    last_seen_by_signature: dict[tuple[str, str, str, str], int] = {}

    sorted_records = sorted(
        records,
        key=lambda record: (
            record.date,
            record.brand.casefold(),
            record.color.casefold(),
            record.vehicle_type.casefold(),
            record.timestamp_seconds,
            record.cctv_id,
        ),
    )
    for record in sorted_records:
        signature = _vehicle_signature(record)
        last_seen = last_seen_by_signature.get(signature)
        if last_seen is None or record.timestamp_seconds - last_seen > UNIQUE_VEHICLE_GAP_SECONDS:
            current_by_signature[signature] = []
            route_records.append(current_by_signature[signature])

        current_by_signature[signature].append(record)
        last_seen_by_signature[signature] = record.timestamp_seconds

    return [VehicleRoute(tuple(route)) for route in route_records]


def _vehicle_signature(record: CCTVRecord) -> tuple[str, str, str, str]:
    return (
        record.date,
        record.brand.casefold(),
        record.color.casefold(),
        record.vehicle_type.casefold(),
    )


def format_answer(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute] | None = None) -> str:
    if spec.language == "th":
        return _format_thai_answer(spec, summary, routes or [])
    return _format_english_answer(spec, summary, routes or [])


def _matches(record: CCTVRecord, spec: QuerySpec) -> bool:
    if spec.date and record.date != spec.date:
        return False
    if spec.cctv_id and record.cctv_id != spec.cctv_id:
        return False
    if spec.vehicle_type and record.vehicle_type.casefold() != spec.vehicle_type.casefold():
        return False
    if spec.brand and record.brand.casefold() != spec.brand.casefold():
        return False
    if spec.color and not _record_matches_color(record.color, spec.color):
        return False
    if spec.start_seconds is not None and spec.end_seconds is not None:
        return _record_in_time_range(record.timestamp_seconds, spec.start_seconds, spec.end_seconds)
    return True


def _record_in_time_range(timestamp_seconds: int, start_seconds: int, end_seconds: int) -> bool:
    if start_seconds <= end_seconds:
        return start_seconds <= timestamp_seconds <= end_seconds
    return timestamp_seconds >= start_seconds or timestamp_seconds <= end_seconds


def _record_matches_color(record_color: str, query_color: str) -> bool:
    return record_color.casefold() == query_color.casefold()


def _format_thai_answer(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    context = _thai_context(spec)
    vehicle_label = THAI_TYPE_LABELS.get(spec.vehicle_type or "", "รถ")
    count = summary.unique_vehicle_count
    if count == 0:
        return f"ไม่พบข้อมูลที่ตรงกับเงื่อนไข: {context}"

    lines = [f"พบ {count} คันสำหรับ {context}{_thai_detection_note(summary)}"]
    if spec.vehicle_type:
        lines[0] = f"พบ{vehicle_label} {count} คันสำหรับ {context}{_thai_detection_note(summary)}"

    if spec.wants_brand_color_breakdown:
        lines.append("ยี่ห้อ/สีที่พบ: " + _format_brand_color_items(summary, unit="คัน"))
    if spec.wants_vehicle_list:
        lines.append("รายการรถไม่ซ้ำ:")
        lines.extend(_format_thai_vehicle_list(routes))
    if spec.wants_route:
        lines.append("ลำดับกล้องที่ผ่าน:")
        lines.extend(_format_thai_routes(routes))
    return "\n".join(lines)


def _format_english_answer(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    context = _english_context(spec)
    count = summary.unique_vehicle_count
    if count == 0:
        return f"No matching records for {context}."

    vehicle_word = _english_vehicle_word(spec.vehicle_type, count)
    lines = [f"Found {count} {vehicle_word} for {context}{_english_detection_note(summary)}."]
    if spec.wants_brand_color_breakdown:
        lines.append("Brand/color breakdown: " + _format_brand_color_items(summary, unit=""))
    if spec.wants_vehicle_list:
        lines.append("Unique vehicles:")
        lines.extend(_format_english_vehicle_list(routes))
    if spec.wants_route:
        lines.append("Camera routes:")
        lines.extend(_format_english_routes(routes))
    return "\n".join(lines)


def _format_brand_color_items(summary: QuerySummary, unit: str) -> str:
    sorted_items = sorted(
        summary.brand_color_counts.items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    if unit:
        return ", ".join(f"{brand} {color} {count} {unit}" for (brand, color), count in sorted_items)
    return ", ".join(f"{brand} {color} {count}" for (brand, color), count in sorted_items)


def _format_thai_routes(routes: list[VehicleRoute]) -> list[str]:
    return [
        f"{index}. {_route_vehicle_label(route)}: {_route_path(route)} "
        f"({route.start_time}-{route.end_time}, ตรวจพบ {route.event_count} ครั้ง)"
        for index, route in enumerate(_sort_routes(routes), start=1)
    ]


def _format_english_routes(routes: list[VehicleRoute]) -> list[str]:
    return [
        f"{index}. {_route_vehicle_label(route)}: {_route_path(route)} "
        f"({route.start_time}-{route.end_time}, {route.event_count} detections)"
        for index, route in enumerate(_sort_routes(routes), start=1)
    ]


def _format_thai_vehicle_list(routes: list[VehicleRoute]) -> list[str]:
    return [
        f"{index}. {_route_vehicle_label(route)} "
        f"เวลา {route.start_time}-{route.end_time} ผ่าน {_route_path(route)} "
        f"(ตรวจพบ {route.event_count} ครั้ง)"
        for index, route in enumerate(_sort_routes(routes), start=1)
    ]


def _format_english_vehicle_list(routes: list[VehicleRoute]) -> list[str]:
    return [
        f"{index}. {_route_vehicle_label(route)} "
        f"{route.start_time}-{route.end_time} via {_route_path(route)} "
        f"({route.event_count} detections)"
        for index, route in enumerate(_sort_routes(routes), start=1)
    ]


def _sort_routes(routes: list[VehicleRoute]) -> list[VehicleRoute]:
    return sorted(
        routes,
        key=lambda route: (
            route.representative.date,
            route.start_time,
            route.representative.brand.casefold(),
            route.representative.color.casefold(),
        ),
    )


def _route_vehicle_label(route: VehicleRoute) -> str:
    representative = route.representative
    return f"{representative.brand} {representative.color} {representative.vehicle_type}"


def _route_path(route: VehicleRoute) -> str:
    return " -> ".join(route.path)


def _thai_detection_note(summary: QuerySummary) -> str:
    if summary.event_count == summary.unique_vehicle_count:
        return ""
    return f" (ตรวจพบ {summary.event_count} ครั้ง)"


def _english_detection_note(summary: QuerySummary) -> str:
    if summary.event_count == summary.unique_vehicle_count:
        return ""
    return f" ({summary.event_count} detections)"


def _thai_context(spec: QuerySpec) -> str:
    parts: list[str] = []
    if spec.date:
        parts.append(f"วันที่ {spec.date}")
    if spec.cctv_id:
        parts.append(spec.cctv_id)
    if spec.start_time and spec.end_time:
        parts.append(f"ช่วง {spec.start_time}-{spec.end_time}")
    if spec.brand:
        parts.append(f"ยี่ห้อ {spec.brand}")
    if spec.color:
        parts.append(f"สี {spec.color}")
    if spec.vehicle_type:
        parts.append(f"ประเภท {THAI_TYPE_LABELS.get(spec.vehicle_type, spec.vehicle_type)}")
    return " ".join(parts) if parts else "ข้อมูลทั้งหมด"


def _english_context(spec: QuerySpec) -> str:
    parts: list[str] = []
    if spec.date:
        parts.append(f"date {spec.date}")
    if spec.cctv_id:
        parts.append(spec.cctv_id)
    if spec.start_time and spec.end_time:
        parts.append(f"from {spec.start_time} to {spec.end_time}")
    if spec.brand:
        parts.append(f"brand {spec.brand}")
    if spec.color:
        parts.append(f"color {spec.color}")
    if spec.vehicle_type:
        parts.append(f"type {spec.vehicle_type}")
    return ", ".join(parts) if parts else "all records"


def _english_vehicle_word(vehicle_type: str | None, count: int) -> str:
    if vehicle_type:
        base = vehicle_type.lower()
        if count == 1:
            return base
        if base == "bus":
            return "buses"
        return base + "s"
    return "vehicle" if count == 1 else "vehicles"
