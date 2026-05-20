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

    @classmethod
    def from_values(
        cls,
        date: str,
        cctv_id: str,
        timestamp: str,
        brand: str,
        color: str,
        vehicle_type: str,
    ) -> "CCTVRecord":
        from cctv_query.normalization import (
            normalize_cctv_id,
            normalize_date,
            normalize_time,
            time_to_seconds,
        )

        normalized_time = normalize_time(timestamp)
        return cls(
            date=normalize_date(date),
            cctv_id=normalize_cctv_id(cctv_id),
            timestamp=normalized_time,
            timestamp_seconds=time_to_seconds(normalized_time),
            brand=brand.strip(),
            color=color.strip(),
            vehicle_type=vehicle_type.strip(),
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
    color: str | None = None
    colors: tuple[str, ...] = ()
    vehicle_type: str | None = None
    wants_brand_color_breakdown: bool = False
    wants_route: bool = False
    wants_vehicle_list: bool = False
    wants_distinct_vehicle_count: bool = False
    out_of_range_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuerySummary:
    brand_color_counts: Counter[tuple[str, str]]
    brand_counts: Counter[str]
    color_counts: Counter[str]
    type_counts: Counter[str]
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
            "type_counts": dict(self.type_counts),
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

    @property
    def count(self) -> int:
        return self.summary.unique_vehicle_count

    @property
    def event_count(self) -> int:
        return self.summary.event_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "count": self.count,
            "event_count": self.event_count,
            "out_of_range": self.out_of_range,
            "out_of_range_reasons": list(self.out_of_range_reasons),
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
        return self.detections[-1].timestamp

    @property
    def event_count(self) -> int:
        return len(self.detections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.representative.date,
            "brand": self.representative.brand,
            "color": self.representative.color,
            "type": self.representative.vehicle_type,
            "path": self.path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "event_count": self.event_count,
            "detections": [record.to_dict() for record in self.detections],
        }
