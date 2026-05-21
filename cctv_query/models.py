from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CCTVRecord:
    date: str
    cctv_id: str
    timestamp: str
    timestamp_seconds: int
    brand: str
    color: str
    vehicle_type: str
    event: str = ""
    event_explicit: bool = False
    last_seen: str = ""
    last_seen_seconds: int = 0

    @classmethod
    def from_values(
        cls,
        date: str,
        cctv_id: str,
        timestamp: str,
        brand: str,
        color: str,
        vehicle_type: str,
        event: str | None = None,
        last_seen: str | None = None,
    ) -> "CCTVRecord":
        from cctv_query.normalization import (
            normalize_cctv_id,
            normalize_date,
            normalize_event,
            normalize_time,
            time_to_seconds,
        )

        normalized_time = normalize_time(timestamp)
        normalized_last_seen = normalize_time(last_seen or timestamp)
        event_text = event.strip() if event is not None else ""
        normalized_event = normalize_event(event_text) if event_text else ""
        return cls(
            date=normalize_date(date),
            cctv_id=normalize_cctv_id(cctv_id),
            timestamp=normalized_time,
            timestamp_seconds=time_to_seconds(normalized_time),
            brand=brand.strip(),
            color=color.strip(),
            vehicle_type=vehicle_type.strip(),
            event=normalized_event,
            event_explicit=bool(event_text),
            last_seen=normalized_last_seen,
            last_seen_seconds=time_to_seconds(normalized_last_seen),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuerySpec:
    raw_question: str
    language: str
    date: str | None = None
    cctv_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    start_seconds: int | None = None
    end_seconds: int | None = None
    brand: str | None = None
    brands: tuple[str, ...] = ()
    brand_origins: tuple[str, ...] = ()
    color: str | None = None
    colors: tuple[str, ...] = ()
    condition_groups: tuple[dict[str, Any], ...] = ()
    vehicle_type: str | None = None
    event: str | None = None
    events: tuple[str, ...] = ()
    wants_brand_color_breakdown: bool = False
    wants_origin_breakdown: bool = False
    wants_origin_brand_breakdown: bool = False
    cross_breakdowns: tuple[str, ...] = ()
    wants_route: bool = False
    wants_vehicle_list: bool = False
    wants_distinct_vehicle_count: bool = False
    wants_event_breakdown: bool = False
    wants_unclosed_entry_count: bool = False
    wants_presence_count: bool = False
    presence_min_seconds: int | None = None
    wants_tracking_duration: bool = False
    vehicle_ordinal: int | None = None
    wants_peak_hour: bool = False
    wants_hour_average: bool = False
    average_hours: int | None = None
    count_operator: str | None = None
    count_threshold: int | None = None
    group_comparison: dict[str, Any] | None = None
    wants_peak_camera: bool = False
    wants_hour_breakdown: bool = False
    wants_camera_breakdown: bool = False
    wants_metallic_color: bool = False
    out_of_range_fields: tuple[str, ...] = ()
    ambiguous_date_options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuerySummary:
    brand_color_counts: Counter[tuple[str, str]]
    brand_counts: Counter[str]
    color_counts: Counter[str]
    origin_counts: Counter[str]
    origin_brand_counts: Counter[tuple[str, str]]
    cross_counts: dict[str, Counter[tuple[str, str]]]
    type_counts: Counter[str]
    event_counts: Counter[str]
    event_count: int
    unique_vehicle_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "unique_vehicle_count": self.unique_vehicle_count,
            "brand_color_counts": [
                {"brand": brand, "color": color, "count": count}
                for (brand, color), count in self.brand_color_counts.items()
            ],
            "brand_counts": dict(self.brand_counts),
            "color_counts": dict(self.color_counts),
            "origin_counts": dict(self.origin_counts),
            "origin_brand_counts": [
                {"origin": origin, "brand": brand, "count": count}
                for (origin, brand), count in self.origin_brand_counts.items()
            ],
            "cross_counts": {
                name: [
                    {"left": left, "right": right, "count": count}
                    for (left, right), count in counter.items()
                ]
                for name, counter in self.cross_counts.items()
            },
            "type_counts": dict(self.type_counts),
            "event_counts": dict(self.event_counts),
        }


@dataclass(frozen=True)
class QueryResult:
    spec: QuerySpec
    matches: list[CCTVRecord]
    routes: list["VehicleRoute"]
    summary: QuerySummary
    answer: str
    out_of_range: bool = False
    out_of_range_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    clarifications: tuple[dict[str, Any], ...] = ()
    answer_options: tuple[dict[str, Any], ...] = ()
    aggregation: dict[str, Any] | None = None

    @property
    def count(self) -> int:
        return self.summary.unique_vehicle_count

    @property
    def event_count(self) -> int:
        return self.summary.event_count

    @property
    def needs_clarification(self) -> bool:
        return any(bool(item.get("required")) for item in self.clarifications)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "count": self.count,
            "event_count": self.event_count,
            "out_of_range": self.out_of_range,
            "out_of_range_reasons": list(self.out_of_range_reasons),
            "warnings": list(self.warnings),
            "clarifications": list(self.clarifications),
            "answer_options": list(self.answer_options),
            "aggregation": self.aggregation,
            "needs_clarification": self.needs_clarification,
            "query": self.spec.to_dict(),
            "summary": self.summary.to_dict(),
            "routes": [route.to_dict() for route in self.routes],
            "matches": [record.to_dict() for record in self.matches],
        }


@dataclass(frozen=True)
class VehicleRoute:
    detections: tuple[CCTVRecord, ...]

    @property
    def representative(self) -> CCTVRecord:
        return self.detections[0]

    @property
    def path(self) -> list[str]:
        return [record.cctv_id for record in self.detections]

    @property
    def start_time(self) -> str:
        return self.detections[0].timestamp

    @property
    def end_time(self) -> str:
        return self.detections[-1].last_seen or self.detections[-1].timestamp

    @property
    def event_count(self) -> int:
        return len(self.detections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.representative.date,
            "brand": self.representative.brand,
            "color": self.representative.color,
            "type": self.representative.vehicle_type,
            "event": self.representative.event,
            "path": self.path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "event_count": self.event_count,
            "detections": [record.to_dict() for record in self.detections],
        }
