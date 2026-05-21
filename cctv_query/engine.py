from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from cctv_query.classification import brand_matches_any_origin, brand_region, origin_counts
from cctv_query.csv_store import load_records
from cctv_query.models import CCTVRecord, QueryResult, QuerySpec, QuerySummary, VehicleRoute
from cctv_query.parser import parse_question


UNIQUE_VEHICLE_GAP_SECONDS = 30 * 60
OUT_OF_RANGE_ANSWER = "Question Out Of Range"
UNRECOGNIZED_ANSWER_EN = (
    "Could not understand the question. Please ask about a date, CCTV camera, time range, vehicle, event, route, "
    "or an aggregate such as busiest hour/camera."
)
UNRECOGNIZED_ANSWER_TH = (
    "\u0e44\u0e21\u0e48\u0e40\u0e02\u0e49\u0e32\u0e43\u0e08\u0e04\u0e33\u0e16\u0e32\u0e21 "
    "\u0e01\u0e23\u0e38\u0e13\u0e32\u0e16\u0e32\u0e21\u0e40\u0e01\u0e35\u0e48\u0e22\u0e27\u0e01\u0e31\u0e1a"
    "\u0e27\u0e31\u0e19\u0e17\u0e35\u0e48, \u0e01\u0e25\u0e49\u0e2d\u0e07, "
    "\u0e0a\u0e48\u0e27\u0e07\u0e40\u0e27\u0e25\u0e32, \u0e23\u0e16, event, "
    "\u0e40\u0e2a\u0e49\u0e19\u0e17\u0e32\u0e07, \u0e2b\u0e23\u0e37\u0e2d"
    "\u0e2a\u0e16\u0e34\u0e15\u0e34\u0e23\u0e32\u0e22\u0e0a\u0e31\u0e48\u0e27\u0e42\u0e21\u0e07/"
    "\u0e23\u0e32\u0e22\u0e01\u0e25\u0e49\u0e2d\u0e07"
)

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
        self.known_cctv_ids = sorted({record.cctv_id for record in records})
        self.known_colors = sorted({record.color for record in records})
        self.known_dates = sorted({record.date for record in records})
        self.known_events = sorted({record.event for record in records if record.event})
        self.has_event_data = any(record.event_explicit for record in records)
        self.known_vehicle_types = sorted({record.vehicle_type for record in records})

    @classmethod
    def from_csv(cls, path: str | Path) -> "CCTVQueryEngine":
        return cls(load_records(path))

    def ask(self, question: str) -> QueryResult:
        try:
            spec = parse_question(
                question,
                known_brands=self.known_brands,
                known_colors=self.known_colors,
                known_dates=self.known_dates,
            )
        except ValueError:
            spec = QuerySpec(raw_question=question, language=_detect_language(question))
            return out_of_range_result(spec, ("invalid_value",))

        required_clarifications = self.required_clarifications(spec)
        if required_clarifications:
            return QueryResult(
                spec=spec,
                matches=[],
                routes=[],
                summary=summarize([]),
                answer=format_clarification_answer(spec, required_clarifications),
                clarifications=tuple(required_clarifications),
            )

        out_of_range_reasons = self.out_of_range_reasons(spec)
        if out_of_range_reasons:
            return out_of_range_result(spec, tuple(out_of_range_reasons))

        if is_unrecognized_query(spec):
            return unrecognized_result(spec)

        warnings = tuple(self.query_warnings(spec))
        matches = self.filter_records(spec)
        if (
            (spec.wants_peak_hour or spec.wants_hour_average or spec.wants_hour_breakdown)
            and not spec.wants_unclosed_entry_count
            and not spec.cross_breakdowns
        ):
            aggregation = aggregate_records(matches, "hour", spec=spec)
            return QueryResult(
                spec=spec,
                matches=matches,
                routes=build_vehicle_routes(matches),
                summary=summarize(matches),
                answer=format_aggregation_answer(spec, aggregation),
                warnings=warnings,
                clarifications=tuple(self.optional_clarifications(spec)),
                answer_options=tuple(self.answer_options(spec)),
                aggregation=aggregation,
            )

        if (
            (spec.wants_peak_camera or spec.wants_camera_breakdown)
            and not spec.wants_unclosed_entry_count
            and not spec.cross_breakdowns
        ):
            aggregation = aggregate_records(matches, "camera")
            return QueryResult(
                spec=spec,
                matches=matches,
                routes=build_vehicle_routes(matches),
                summary=summarize(matches),
                answer=format_aggregation_answer(spec, aggregation),
                warnings=warnings,
                clarifications=tuple(self.optional_clarifications(spec)),
                answer_options=tuple(self.answer_options(spec)),
                aggregation=aggregation,
            )

        if spec.wants_presence_count or spec.wants_tracking_duration:
            matches = _presence_filtered_records(matches, spec) if spec.wants_presence_count else matches
            routes = build_vehicle_routes(matches)
            summary = summarize_routes(routes)
            aggregation = aggregate_tracking_duration(matches, routes, spec)
            answer = format_tracking_duration_answer(spec, summary, aggregation)
            return QueryResult(
                spec=spec,
                matches=matches,
                routes=routes,
                summary=summary,
                answer=answer,
                warnings=warnings,
                clarifications=tuple(self.optional_clarifications(spec)),
                answer_options=tuple(self.answer_options(spec)),
                aggregation=aggregation,
            )

        if spec.wants_unclosed_entry_count:
            all_routes = countable_vehicle_routes(matches, spec)
            routes = routes_with_entry_without_exit(all_routes)
            summary = summarize_routes(routes)
            answer = format_answer(spec, summary, routes=routes)
            clarifications = tuple(self.optional_clarifications(spec))
            return QueryResult(
                spec=spec,
                matches=[record for route in routes for record in route.detections],
                routes=routes,
                summary=summary,
                answer=answer,
                warnings=warnings,
                clarifications=clarifications,
                answer_options=tuple(self.answer_options(spec)),
            )

        if spec.wants_route:
            routes = self.find_routes(spec)
            route_matches = [record for route in routes for record in route.detections]
            summary = summarize_routes(routes)
            answer = format_answer(spec, summary, routes=routes)
            clarifications = tuple(self.optional_clarifications(spec))
            return QueryResult(
                spec=spec,
                matches=route_matches,
                routes=routes,
                summary=summary,
                answer=answer,
                warnings=warnings,
                clarifications=clarifications,
                answer_options=tuple(self.answer_options(spec)),
            )

        routes = countable_vehicle_routes(matches, spec)
        route_matches = [record for route in routes for record in route.detections]
        clarifications = tuple(self.optional_clarifications(spec))
        if spec.vehicle_ordinal is not None:
            ordinal_spec = replace(
                spec,
                cctv_id=None,
                event=None,
                events=(),
                start_time=None,
                end_time=None,
                start_seconds=None,
                end_seconds=None,
            )
            ordinal_matches = self.filter_records(ordinal_spec)
            ordinal_routes = countable_vehicle_routes(ordinal_matches, spec)
            sorted_routes = _sort_ordinal_routes(ordinal_routes, spec)
            selected_route = _select_ordinal_route(sorted_routes, spec.vehicle_ordinal)
            selected_routes = [selected_route] if selected_route else []
            selected_matches = [record for route in selected_routes for record in route.detections]
            return QueryResult(
                spec=spec,
                matches=selected_matches,
                routes=selected_routes,
                summary=summarize_routes(selected_routes),
                answer=format_vehicle_ordinal_answer(spec, selected_route, len(sorted_routes)),
                warnings=warnings,
                clarifications=clarifications,
                answer_options=tuple(self.answer_options(spec)),
                aggregation=_vehicle_ordinal_aggregation(spec, selected_route, len(sorted_routes)),
            )
        if spec.wants_event_breakdown or _needs_detection_cross_summary(spec):
            summary = summarize(matches)
        elif spec.wants_distinct_vehicle_count:
            summary = summarize_routes(routes)
        else:
            summary = summarize_routes(routes)
        answer = format_answer(spec, summary, routes=routes)
        aggregation = group_comparison_aggregation(spec, summary)
        return QueryResult(
            spec=spec,
            matches=matches if spec.wants_event_breakdown or _needs_detection_cross_summary(spec) else route_matches,
            routes=routes,
            summary=summary,
            answer=answer,
            warnings=warnings,
            clarifications=clarifications,
            answer_options=tuple(self.answer_options(spec)),
            aggregation=aggregation,
        )

    def filter_records(self, spec: QuerySpec) -> list[CCTVRecord]:
        return [record for record in self.records if _matches(record, spec)]

    def out_of_range_reasons(self, spec: QuerySpec) -> list[str]:
        reasons = list(spec.out_of_range_fields)
        if not self.has_event_data and _requires_event_data(spec):
            _append_unique(reasons, "event")
        if spec.date and spec.date not in self.known_dates:
            _append_unique(reasons, "date")
        for group in spec.condition_groups:
            group_date = group.get("date")
            if isinstance(group_date, str) and group_date not in self.known_dates:
                _append_unique(reasons, "date")
            for brand in _group_values(group, "brands"):
                if not _casefold_contains(self.known_brands, brand):
                    _append_unique(reasons, "brand")
                    break
            for color in _group_values(group, "colors"):
                if not _casefold_contains(self.known_colors, color) and not _related_color_values(color, self.known_colors):
                    _append_unique(reasons, "color")
                    break
            group_type = group.get("vehicle_type")
            if isinstance(group_type, str) and not _casefold_contains(self.known_vehicle_types, group_type):
                _append_unique(reasons, "vehicle_type")
            group_event = group.get("event")
            if isinstance(group_event, str) and not _casefold_contains(self.known_events, group_event):
                _append_unique(reasons, "event")
        if spec.cctv_id and spec.cctv_id not in self.known_cctv_ids:
            _append_unique(reasons, "cctv_id")
        for brand in spec.brands or ((spec.brand,) if spec.brand else ()):
            if not _casefold_contains(self.known_brands, brand):
                _append_unique(reasons, "brand")
                break
        for color in spec.colors or ((spec.color,) if spec.color else ()):
            if not _casefold_contains(self.known_colors, color) and not _related_color_values(color, self.known_colors):
                _append_unique(reasons, "color")
                break
        if spec.vehicle_type and not _casefold_contains(self.known_vehicle_types, spec.vehicle_type):
            _append_unique(reasons, "vehicle_type")
        if spec.event and not _casefold_contains(self.known_events, spec.event):
            _append_unique(reasons, "event")
        return reasons

    def required_clarifications(self, spec: QuerySpec) -> list[dict]:
        if spec.ambiguous_date_options:
            return [_date_clarification(spec)]
        return []

    def optional_clarifications(self, spec: QuerySpec) -> list[dict]:
        clarifications: list[dict] = []
        color_clarification = self.color_clarification(spec)
        if color_clarification:
            clarifications.append(color_clarification)
        return clarifications

    def query_warnings(self, spec: QuerySpec) -> list[str]:
        if spec.ambiguous_date_options:
            return []

        warnings: list[str] = []
        if not spec.date and not spec.condition_groups:
            warnings.append(_localized_warning(spec.language, "date"))
        if not spec.cctv_id and not (spec.wants_peak_camera or spec.wants_camera_breakdown):
            warnings.append(_localized_warning(spec.language, "cctv"))
        if not (spec.start_time and spec.end_time) and not (
            spec.wants_peak_hour or spec.wants_hour_average or spec.wants_hour_breakdown
        ):
            warnings.append(_localized_warning(spec.language, "time"))
        return warnings

    def color_clarification(self, spec: QuerySpec) -> dict | None:
        selected_colors = spec.colors or ((spec.color,) if spec.color else ())
        if len(selected_colors) != 1:
            return None

        selected_color = selected_colors[0]
        if not _is_base_color(selected_color):
            return None

        related_colors = _related_color_values(selected_color, self.known_colors)
        option_colors = [selected_color]
        for color in related_colors:
            if not _casefold_contains(option_colors, color):
                option_colors.append(color)
        if len(option_colors) <= 1:
            return None

        options = [self._color_option(spec, color, selected=(color.casefold() == selected_color.casefold())) for color in option_colors]
        all_count = self._count_for_colors(spec, tuple(option_colors))
        all_label = "ทุกสีที่เกี่ยวข้อง: " if spec.language == "th" else "All related colors: "
        options.append(
            {
                "value": ", ".join(option_colors),
                "label": all_label + ", ".join(option_colors),
                "colors": option_colors,
                "count": all_count,
                "selected": False,
            }
        )
        return {
            "field": "color",
            "required": False,
            "message": _localized_color_message(spec.language, selected_color),
            "options": options,
        }

    def _color_option(self, spec: QuerySpec, color: str, selected: bool = False) -> dict:
        return {
            "value": color,
            "label": color,
            "colors": [color],
            "count": self._count_for_colors(spec, (color,)),
            "selected": selected,
        }

    def _count_for_colors(self, spec: QuerySpec, colors: tuple[str, ...]) -> int:
        option_spec = replace(spec, color=colors[0] if colors else None, colors=colors)
        matches = self.filter_records(option_spec)
        routes = countable_vehicle_routes(matches, option_spec)
        if spec.wants_distinct_vehicle_count:
            return summarize_routes(routes).unique_vehicle_count
        return summarize_routes(routes).unique_vehicle_count

    def find_routes(self, spec: QuerySpec) -> list[VehicleRoute]:
        return [
            route
            for route in build_vehicle_routes(self.records)
            if _route_matches_spec(route, spec)
        ]

    def answer_options(self, spec: QuerySpec) -> list[dict]:
        if not _should_offer_event_options(spec):
            return []

        base_spec = replace(
            spec,
            event=None,
            wants_route=False,
            wants_vehicle_list=False,
            wants_event_breakdown=False,
            wants_unclosed_entry_count=False,
        )
        base_matches = self.filter_records(base_spec)
        base_routes = build_vehicle_routes(base_matches)
        options = [
            _entry_without_exit_option(spec, routes_with_entry_without_exit(base_routes)),
            _event_breakdown_option(spec, base_matches),
        ]
        for event in ("entry", "exit", "pass"):
            event_spec = replace(base_spec, event=event)
            event_matches = self.filter_records(event_spec)
            event_routes = build_vehicle_routes(event_matches)
            options.append(_event_only_option(spec, event, event_routes))
        return options


def out_of_range_result(spec: QuerySpec, reasons: tuple[str, ...]) -> QueryResult:
    return QueryResult(
        spec=spec,
        matches=[],
        routes=[],
        summary=summarize([]),
        answer=OUT_OF_RANGE_ANSWER,
        out_of_range=True,
        out_of_range_reasons=reasons,
    )


def unrecognized_result(spec: QuerySpec) -> QueryResult:
    answer = UNRECOGNIZED_ANSWER_TH if spec.language == "th" else UNRECOGNIZED_ANSWER_EN
    return QueryResult(
        spec=spec,
        matches=[],
        routes=[],
        summary=summarize([]),
        answer=answer,
        warnings=("unrecognized_question",),
    )


def is_unrecognized_query(spec: QuerySpec) -> bool:
    if _has_any_structured_constraint(spec):
        return False
    return not _looks_like_broad_vehicle_query(spec.raw_question)


def _needs_detection_cross_summary(spec: QuerySpec) -> bool:
    return any(name in {"camera_event", "hour_event"} for name in spec.cross_breakdowns)


def _has_any_structured_constraint(spec: QuerySpec) -> bool:
    return any(
        (
            spec.date,
            spec.cctv_id,
            spec.start_time,
            spec.end_time,
            spec.brand,
            spec.brands,
            spec.brand_origins,
            spec.color,
            spec.colors,
            spec.condition_groups,
            spec.vehicle_type,
            spec.event,
            spec.events,
            spec.wants_brand_color_breakdown,
            spec.wants_origin_breakdown,
            spec.wants_origin_brand_breakdown,
            spec.cross_breakdowns,
            spec.wants_route,
            spec.wants_vehicle_list,
            spec.wants_distinct_vehicle_count,
            spec.wants_event_breakdown,
            spec.wants_unclosed_entry_count,
            spec.wants_presence_count,
            spec.wants_tracking_duration,
            spec.vehicle_ordinal is not None,
            spec.wants_peak_hour,
            spec.wants_hour_average,
            spec.count_operator,
            spec.count_threshold is not None,
            spec.group_comparison,
            spec.wants_peak_camera,
            spec.wants_hour_breakdown,
            spec.wants_camera_breakdown,
            spec.wants_metallic_color,
        )
    )


def _requires_event_data(spec: QuerySpec) -> bool:
    event_cross_breakdowns = {"camera_event", "hour_event", "unclosed_entry_camera"}
    return bool(
        spec.event
        or spec.events
        or spec.wants_event_breakdown
        or spec.wants_unclosed_entry_count
        or event_cross_breakdowns.intersection(spec.cross_breakdowns)
    )


def _looks_like_broad_vehicle_query(question: str) -> bool:
    text = question.casefold()
    vehicle_terms = (
        "vehicle",
        "vehicles",
        "car",
        "cars",
        "traffic",
        "\u0e23\u0e16",
    )
    count_terms = (
        "how many",
        "count",
        "counts",
        "number",
        "total",
        "all",
        "\u0e01\u0e35\u0e48\u0e04\u0e31\u0e19",
        "\u0e08\u0e33\u0e19\u0e27\u0e19",
        "\u0e17\u0e31\u0e49\u0e07\u0e2b\u0e21\u0e14",
        "\u0e2a\u0e23\u0e38\u0e1b",
    )
    return any(term in text for term in vehicle_terms) and any(term in text for term in count_terms)


def format_clarification_answer(spec: QuerySpec, clarifications: list[dict]) -> str:
    if spec.language == "th":
        return "ต้องระบุข้อมูลเพิ่มก่อนตอบคำถาม"
    return "More information is needed before answering this question."


def summarize(records: list[CCTVRecord], event_count: int | None = None) -> QuerySummary:
    return QuerySummary(
        brand_color_counts=Counter((record.brand, record.color) for record in records),
        brand_counts=Counter(record.brand for record in records),
        color_counts=Counter(record.color for record in records),
        origin_counts=origin_counts(records),
        origin_brand_counts=_origin_brand_counts(records),
        cross_counts=_record_cross_counts(records),
        type_counts=Counter(record.vehicle_type for record in records),
        event_counts=Counter(record.event for record in records if record.event),
        event_count=len(records) if event_count is None else event_count,
        unique_vehicle_count=len(records),
    )


def _origin_brand_counts(records: list[CCTVRecord]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for record in records:
        origin = brand_region(record.brand)
        if origin:
            counts[(origin, record.brand)] += 1
    return counts


def _record_cross_counts(records: list[CCTVRecord]) -> dict[str, Counter[tuple[str, str]]]:
    counts: dict[str, Counter[tuple[str, str]]] = {
        "origin_brand": Counter(),
        "origin_type": Counter(),
        "brand_type": Counter(),
        "camera_event": Counter(),
        "hour_event": Counter(),
        "color_type": Counter(),
        "origin_color": Counter(),
    }
    for record in records:
        origin = brand_region(record.brand)
        hour = record.timestamp[:2]
        if origin:
            counts["origin_brand"][(origin, record.brand)] += 1
            counts["origin_type"][(origin, record.vehicle_type)] += 1
            counts["origin_color"][(origin, record.color)] += 1
        counts["brand_type"][(record.brand, record.vehicle_type)] += 1
        if record.event:
            counts["camera_event"][(record.cctv_id, record.event)] += 1
            counts["hour_event"][(f"{hour}:00-{hour}:59", record.event)] += 1
        counts["color_type"][(record.color, record.vehicle_type)] += 1
    return counts


def summarize_routes(routes: list[VehicleRoute]) -> QuerySummary:
    representatives = [route.representative for route in routes]
    summary = summarize(representatives, event_count=sum(route.event_count for route in routes))
    return replace(summary, cross_counts={**summary.cross_counts, **_route_cross_counts(routes)})


def _route_cross_counts(routes: list[VehicleRoute]) -> dict[str, Counter[tuple[str, str]]]:
    counts: dict[str, Counter[tuple[str, str]]] = {
        "route_od": Counter(),
        "brand_route": Counter(),
        "unclosed_entry_camera": Counter(),
    }
    for route in routes:
        if not route.detections:
            continue
        origin = route.path[0]
        destination = route.path[-1]
        path = _route_path(route)
        counts["route_od"][(origin, destination)] += 1
        counts["brand_route"][(route.representative.brand, path)] += 1
        if _route_has_entry_without_exit(route):
            entry_record = next((record for record in route.detections if record.event == "entry"), route.representative)
            counts["unclosed_entry_camera"][(entry_record.cctv_id, "entry_without_exit")] += 1
    return counts


def countable_vehicle_routes(records: list[CCTVRecord], spec: QuerySpec) -> list[VehicleRoute]:
    routes = build_vehicle_routes(records)
    if _keeps_pass_only_routes(spec):
        return routes
    return [route for route in routes if _is_countable_vehicle_route(route)]


def aggregate_records(records: list[CCTVRecord], group_by: str, spec: QuerySpec | None = None) -> dict:
    buckets: dict[str, dict] = {}
    for record in records:
        key = _aggregation_key(record, group_by)
        item = buckets.setdefault(
            key,
            {
                "key": key,
                "label": _aggregation_label(key, group_by),
                "count": 0,
                "event_counts": Counter(),
            },
        )
        item["count"] += 1
        item["event_counts"][record.event] += 1

    rows = sorted(buckets.values(), key=lambda item: (-item["count"], item["key"]))
    normalized_rows = [
        {
            "key": item["key"],
            "label": item["label"],
            "count": item["count"],
            "event_counts": dict(item["event_counts"]),
        }
        for item in rows
    ]
    top_count = normalized_rows[0]["count"] if normalized_rows else 0
    aggregation = {
        "group_by": group_by,
        "total_count": len(records),
        "top_count": top_count,
        "top": [item for item in normalized_rows if item["count"] == top_count] if top_count else [],
        "rows": normalized_rows,
    }
    if group_by == "hour" and spec and spec.wants_hour_average:
        denominator = _hour_average_denominator(records, spec)
        aggregation["average_count"] = (len(records) / denominator) if denominator else 0
        aggregation["average_denominator"] = denominator
    return aggregation


def _aggregation_key(record: CCTVRecord, group_by: str) -> str:
    if group_by == "hour":
        return record.timestamp[:2]
    if group_by == "camera":
        return record.cctv_id
    raise ValueError(f"Unsupported aggregation group '{group_by}'.")


def _aggregation_label(key: str, group_by: str) -> str:
    if group_by == "hour":
        return f"{key}:00-{key}:59"
    return key


def _hour_average_denominator(records: list[CCTVRecord], spec: QuerySpec) -> int:
    if spec.average_hours:
        return spec.average_hours
    days = {spec.date} if spec.date else {record.date for record in records}
    day_count = max(1, len(days))
    return day_count * _hour_slot_count(spec.start_seconds, spec.end_seconds)


def _hour_slot_count(start_seconds: int | None, end_seconds: int | None) -> int:
    if start_seconds is None or end_seconds is None:
        return 24
    start_hour = start_seconds // 3600
    end_hour = end_seconds // 3600
    if start_seconds <= end_seconds:
        return end_hour - start_hour + 1
    return (24 - start_hour) + end_hour + 1


def aggregate_tracking_duration(records: list[CCTVRecord], routes: list[VehicleRoute], spec: QuerySpec) -> dict:
    durations = [_record_duration_seconds(record) for record in records]
    overlap_durations = [
        _record_overlap_seconds(record, spec.start_seconds, spec.end_seconds)
        for record in records
    ]
    max_record = max(records, key=_record_duration_seconds) if records else None
    return {
        "type": "tracking_duration",
        "vehicle_count": len(routes),
        "detection_count": len(records),
        "average_duration_seconds": _average(durations),
        "max_duration_seconds": max(durations, default=0),
        "min_duration_seconds": min(durations, default=0),
        "average_overlap_seconds": _average(overlap_durations),
        "max_overlap_seconds": max(overlap_durations, default=0),
        "has_time_range": spec.start_seconds is not None and spec.end_seconds is not None,
        "presence_min_seconds": spec.presence_min_seconds,
        "longest_detection": max_record.to_dict() if max_record else None,
    }


def _presence_filtered_records(records: list[CCTVRecord], spec: QuerySpec) -> list[CCTVRecord]:
    min_seconds = spec.presence_min_seconds or 0
    if min_seconds <= 0:
        return records
    return [
        record
        for record in records
        if _presence_qualifying_seconds(record, spec.start_seconds, spec.end_seconds) >= min_seconds
    ]


def _presence_qualifying_seconds(record: CCTVRecord, start_seconds: int | None, end_seconds: int | None) -> int:
    if start_seconds is not None and end_seconds is not None:
        return _record_overlap_seconds(record, start_seconds, end_seconds)
    return _record_duration_seconds(record)


def _record_duration_seconds(record: CCTVRecord) -> int:
    return max(0, (record.last_seen_seconds or record.timestamp_seconds) - record.timestamp_seconds)


def _record_overlap_seconds(record: CCTVRecord, start_seconds: int | None, end_seconds: int | None) -> int:
    duration = _record_duration_seconds(record)
    if start_seconds is None or end_seconds is None:
        return duration
    record_start = record.timestamp_seconds
    record_end = record.last_seen_seconds or record.timestamp_seconds
    if start_seconds <= end_seconds:
        return max(0, min(record_end, end_seconds) - max(record_start, start_seconds))
    return max(
        _interval_overlap_seconds(record_start, record_end, start_seconds, 23 * 3600 + 59 * 60 + 59),
        _interval_overlap_seconds(record_start, record_end, 0, end_seconds),
    )


def _interval_overlap_seconds(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _average(values: list[int]) -> float:
    return (sum(values) / len(values)) if values else 0


def routes_with_entry_without_exit(routes: list[VehicleRoute]) -> list[VehicleRoute]:
    return [
        route
        for route in routes
        if _route_has_entry_without_exit(route)
    ]


def _route_has_entry_without_exit(route: VehicleRoute) -> bool:
    return any(record.event == "entry" for record in route.detections) and not any(
        record.event == "exit" for record in route.detections
    )


def _route_matches_spec(route: VehicleRoute, spec: QuerySpec) -> bool:
    if not _keeps_pass_only_routes(spec) and not _is_countable_vehicle_route(route):
        return False
    return any(_matches(record, spec) for record in route.detections)


def _keeps_pass_only_routes(spec: QuerySpec) -> bool:
    return bool(spec.cctv_id) or spec.event == "pass" or spec.events == ("pass",)


def _has_boundary_event(route: VehicleRoute) -> bool:
    return any(record.event in {"entry", "exit"} for record in route.detections)


def _is_countable_vehicle_route(route: VehicleRoute) -> bool:
    if _has_boundary_event(route):
        return True
    return not any(record.event_explicit for record in route.detections)


def summarize_distinct_vehicle_identities(routes: list[VehicleRoute]) -> QuerySummary:
    earliest_by_signature: dict[tuple[str, str, str, str], CCTVRecord] = {}
    for route in routes:
        representative = route.representative
        signature = _vehicle_signature(representative)
        current = earliest_by_signature.get(signature)
        if current is None or representative.timestamp_seconds < current.timestamp_seconds:
            earliest_by_signature[signature] = representative

    representatives = sorted(
        earliest_by_signature.values(),
        key=lambda record: (
            record.date,
            record.timestamp_seconds,
            record.brand.casefold(),
            record.color.casefold(),
            record.vehicle_type.casefold(),
        ),
    )
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


def format_aggregation_answer(spec: QuerySpec, aggregation: dict) -> str:
    if spec.language == "th":
        return _format_thai_aggregation_answer(spec, aggregation)
    return _format_english_aggregation_answer(spec, aggregation)


def format_tracking_duration_answer(spec: QuerySpec, summary: QuerySummary, aggregation: dict) -> str:
    if spec.language == "th":
        return _format_thai_tracking_duration_answer(spec, summary, aggregation)
    return _format_english_tracking_duration_answer(spec, summary, aggregation)


def format_vehicle_ordinal_answer(spec: QuerySpec, route: VehicleRoute | None, total_routes: int) -> str:
    if spec.language == "th":
        return _format_thai_vehicle_ordinal_answer(spec, route, total_routes)
    return _format_english_vehicle_ordinal_answer(spec, route, total_routes)


def _select_ordinal_route(routes: list[VehicleRoute], ordinal: int) -> VehicleRoute | None:
    if not routes:
        return None
    if ordinal == -1:
        return routes[-1]
    if ordinal <= 0 or ordinal > len(routes):
        return None
    return routes[ordinal - 1]


def _sort_ordinal_routes(routes: list[VehicleRoute], spec: QuerySpec) -> list[VehicleRoute]:
    indexed_routes: list[tuple[tuple, VehicleRoute]] = []
    for route in routes:
        anchor = _ordinal_anchor_record(route, spec)
        if anchor is None:
            continue
        indexed_routes.append(
            (
                (
                    anchor.date,
                    anchor.timestamp_seconds,
                    anchor.cctv_id,
                    route.representative.brand.casefold(),
                    route.representative.color.casefold(),
                    route.representative.vehicle_type.casefold(),
                ),
                route,
            )
        )
    return [route for _, route in sorted(indexed_routes, key=lambda item: item[0])]


def _ordinal_anchor_record(route: VehicleRoute, spec: QuerySpec) -> CCTVRecord | None:
    candidates = [record for record in route.detections if _matches(record, spec)]
    if not candidates:
        return None
    return min(candidates, key=lambda record: (record.date, record.timestamp_seconds, record.cctv_id))


def _vehicle_ordinal_aggregation(spec: QuerySpec, route: VehicleRoute | None, total_routes: int) -> dict:
    ordinal = spec.vehicle_ordinal
    anchor = _ordinal_anchor_record(route, spec) if route else None
    return {
        "type": "vehicle_ordinal",
        "ordinal": ordinal,
        "label": _ordinal_label(ordinal),
        "total_count": total_routes,
        "anchor": anchor.to_dict() if anchor else None,
        "route": route.to_dict() if route else None,
    }


def _matches(record: CCTVRecord, spec: QuerySpec) -> bool:
    if spec.cctv_id and record.cctv_id != spec.cctv_id:
        return False
    if spec.vehicle_type and record.vehicle_type.casefold() != spec.vehicle_type.casefold():
        return False
    if spec.event and record.event.casefold() != spec.event.casefold():
        return False
    if spec.events and record.event.casefold() not in {event.casefold() for event in spec.events}:
        return False
    if spec.condition_groups:
        if not any(_record_matches_condition_group(record, group) for group in spec.condition_groups):
            return False
    elif spec.date and record.date != spec.date:
        return False
    query_brands = spec.brands or ((spec.brand,) if spec.brand else ())
    if query_brands and not any(record.brand.casefold() == brand.casefold() for brand in query_brands):
        return False
    if spec.brand_origins and not brand_matches_any_origin(record.brand, spec.brand_origins):
        return False
    if spec.colors and not any(_record_matches_color(record.color, color) for color in spec.colors):
        return False
    if not spec.colors and spec.color and not _record_matches_color(record.color, spec.color):
        return False
    if spec.start_seconds is not None and spec.end_seconds is not None:
        return _record_overlaps_time_range(record, spec.start_seconds, spec.end_seconds)
    return True


def _record_matches_condition_group(record: CCTVRecord, group: dict) -> bool:
    date = group.get("date")
    if isinstance(date, str) and record.date != date:
        return False

    brands = _group_values(group, "brands")
    if brands and not any(record.brand.casefold() == brand.casefold() for brand in brands):
        return False

    colors = _group_values(group, "colors")
    if colors and not any(_record_matches_color(record.color, color) for color in colors):
        return False

    vehicle_type = group.get("vehicle_type")
    if isinstance(vehicle_type, str) and record.vehicle_type.casefold() != vehicle_type.casefold():
        return False

    event = group.get("event")
    if isinstance(event, str) and record.event.casefold() != event.casefold():
        return False

    start_seconds = group.get("start_seconds")
    end_seconds = group.get("end_seconds")
    if isinstance(start_seconds, int) and isinstance(end_seconds, int):
        return _record_overlaps_time_range(record, start_seconds, end_seconds)

    return True


def _group_values(group: dict, key: str) -> tuple[str, ...]:
    value = group.get(key)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _record_overlaps_time_range(record: CCTVRecord, start_seconds: int, end_seconds: int) -> bool:
    record_start = record.timestamp_seconds
    record_end = record.last_seen_seconds or record.timestamp_seconds
    if start_seconds <= end_seconds:
        return record_start <= end_seconds and record_end >= start_seconds
    return record_end >= start_seconds or record_start <= end_seconds


def _record_matches_color(record_color: str, query_color: str) -> bool:
    return record_color.casefold() == query_color.casefold()


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _casefold_contains(values: list[str], value: str) -> bool:
    normalized = value.casefold()
    return any(item.casefold() == normalized for item in values)


def _date_clarification(spec: QuerySpec) -> dict:
    options = [
        {
            "value": date,
            "label": _date_option_label(date),
            "date": date,
        }
        for date in spec.ambiguous_date_options
    ]
    day = spec.ambiguous_date_options[0].split("-", maxsplit=1)[0] if spec.ambiguous_date_options else ""
    if spec.language == "th":
        message = f"วันที่ {day} มีหลายเดือนในข้อมูล กรุณาเลือกเดือน/วันที่ที่ต้องการ"
    else:
        message = f"Day {day} appears in multiple months. Select the date/month to use."
    return {
        "field": "date",
        "required": True,
        "message": message,
        "options": options,
    }


def _date_option_label(date: str) -> str:
    day, month, year = date.split("-")
    return f"{month}-{year} ({date})"


def _localized_warning(language: str, field: str) -> str:
    if language == "th":
        return {
            "date": "ไม่ได้ระบุวันที่ จึงค้นหาทุกวันที่ในข้อมูล",
            "cctv": "ไม่ได้ระบุกล้อง จึงค้นหาทุกกล้อง",
            "time": "ไม่ได้ระบุช่วงเวลา จึงค้นหาทั้งวัน",
        }[field]
    return {
        "date": "No date specified; searching all dates.",
        "cctv": "No CCTV camera specified; searching all cameras.",
        "time": "No time range specified; searching the full day.",
    }[field]


def _localized_color_message(language: str, selected_color: str) -> str:
    if language == "th":
        return f"ระบบตอบตามสี {selected_color} แบบ exact match หากหมายถึงสีอื่นให้เลือกจากรายการ"
    return f"The answer uses exact color {selected_color}. Select another related color if needed."


def _is_base_color(color: str) -> bool:
    return len(_color_tokens(color)) == 1


def _related_color_values(query_color: str, known_colors: list[str]) -> list[str]:
    query = query_color.casefold()
    related: list[str] = []
    for color in sorted(known_colors, key=lambda value: (value.casefold() != query, value.casefold())):
        if color.casefold() == query:
            continue
        tokens = _color_tokens(color)
        if query in tokens:
            related.append(color)
    return related


def _color_tokens(color: str) -> set[str]:
    return {token for token in re.split(r"[\s\-]+", color.casefold()) if token}


def _detect_language(text: str) -> str:
    return "th" if any("\u0E00" <= char <= "\u0E7F" for char in text) else "en"


def _format_thai_answer(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    context = _thai_context(spec)
    vehicle_label = THAI_TYPE_LABELS.get(spec.vehicle_type or "", "รถ")
    count = summary.unique_vehicle_count
    group_comparison = group_comparison_aggregation(spec, summary)
    if group_comparison:
        return _format_thai_group_comparison_answer(spec, group_comparison, context)
    if spec.wants_unclosed_entry_count:
        if count == 0:
            lines = [f"ไม่พบรถที่ entry แล้วไม่ exit สำหรับ {context}"]
            lines.extend(_thai_count_comparison_lines(spec, count))
            return "\n".join(lines)
        lines = [f"พบรถที่ entry แล้วไม่ exit {count} คันสำหรับ {context}{_thai_count_note(spec, summary, routes)}"]
        lines.extend(_format_thai_cross_breakdowns(spec, summary))
        lines.extend(_thai_count_comparison_lines(spec, count))
        return "\n".join(lines)
    if count == 0:
        lines = [f"ไม่พบข้อมูลที่ตรงกับเงื่อนไข: {context}"]
        lines.extend(_thai_count_comparison_lines(spec, count))
        return "\n".join(lines)

    count_label = " คันไม่ซ้ำ" if spec.wants_distinct_vehicle_count else " คัน"
    lines = [f"พบ {count}{count_label}สำหรับ {context}{_thai_count_note(spec, summary, routes)}"]
    if spec.vehicle_type:
        lines[0] = f"พบ{vehicle_label} {count}{count_label}สำหรับ {context}{_thai_count_note(spec, summary, routes)}"

    if spec.wants_brand_color_breakdown and not spec.cross_breakdowns:
        lines.append("ยี่ห้อ/สีที่พบ: " + _format_brand_color_items(summary, unit="คัน", spec=spec))
    lines.extend(_format_thai_cross_breakdowns(spec, summary))
    if spec.wants_origin_breakdown:
        lines.append("\u0e2a\u0e23\u0e38\u0e1b\u0e15\u0e32\u0e21\u0e1b\u0e23\u0e30\u0e40\u0e17\u0e28/\u0e20\u0e39\u0e21\u0e34\u0e20\u0e32\u0e04: " + _format_origin_counts(spec, summary))
    if spec.wants_event_breakdown:
        lines.append("สรุปตาม event: " + _format_named_counts_from_counter(summary.event_counts, spec=spec))
    if spec.wants_vehicle_list:
        lines.append("รายการรถไม่ซ้ำ:")
        lines.extend(_format_thai_vehicle_list(routes))
    if spec.wants_route:
        lines.append("ลำดับกล้องที่ผ่าน:")
        lines.extend(_format_thai_routes(routes))
    lines.extend(_thai_count_comparison_lines(spec, count))
    return "\n".join(lines)


def _format_english_answer(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    context = _english_context(spec)
    count = summary.unique_vehicle_count
    group_comparison = group_comparison_aggregation(spec, summary)
    if group_comparison:
        return _format_english_group_comparison_answer(spec, group_comparison, context)
    if spec.wants_unclosed_entry_count:
        if count == 0:
            lines = [f"No vehicles with entry and no exit for {context}."]
            lines.extend(_english_count_comparison_lines(spec, count))
            return "\n".join(lines)
        lines = [f"Found {count} vehicles with entry and no exit for {context}{_english_count_note(spec, summary, routes)}."]
        lines.extend(_format_english_cross_breakdowns(spec, summary))
        lines.extend(_english_count_comparison_lines(spec, count))
        return "\n".join(lines)
    if count == 0:
        lines = [f"No matching records for {context}."]
        lines.extend(_english_count_comparison_lines(spec, count))
        return "\n".join(lines)

    vehicle_word = _english_vehicle_word(spec.vehicle_type, count)
    lines = [f"Found {count} {vehicle_word} for {context}{_english_count_note(spec, summary, routes)}."]
    if spec.wants_brand_color_breakdown and not spec.cross_breakdowns:
        lines.append("Brand/color breakdown: " + _format_brand_color_items(summary, unit="", spec=spec))
    lines.extend(_format_english_cross_breakdowns(spec, summary))
    if spec.wants_origin_breakdown:
        lines.append("Origin breakdown: " + _format_origin_counts(spec, summary))
    if spec.wants_event_breakdown:
        lines.append("Event breakdown: " + _format_named_counts_from_counter(summary.event_counts, spec=spec))
    if spec.wants_vehicle_list:
        lines.append("Unique vehicles:")
        lines.extend(_format_english_vehicle_list(routes))
    if spec.wants_route:
        lines.append("Camera routes:")
        lines.extend(_format_english_routes(routes))
    lines.extend(_english_count_comparison_lines(spec, count))
    return "\n".join(lines)


def _format_brand_color_items(summary: QuerySummary, unit: str, spec: QuerySpec | None = None) -> str:
    sorted_items = sorted(
        _comparison_filtered_items(summary.brand_color_counts.items(), spec),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    if not sorted_items:
        return "ไม่มี" if unit else "none"
    if unit:
        return ", ".join(f"{brand} {color} {count} {unit}" for (brand, color), count in sorted_items)
    return ", ".join(f"{brand} {color} {count}" for (brand, color), count in sorted_items)


def _format_origin_brand_items(summary: QuerySummary, unit: str) -> str:
    sorted_items = sorted(
        summary.origin_brand_counts.items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    if unit:
        return ", ".join(f"{origin} {brand} {count} {unit}" for (origin, brand), count in sorted_items)
    return ", ".join(f"{origin} {brand} {count}" for (origin, brand), count in sorted_items)


def group_comparison_aggregation(spec: QuerySpec, summary: QuerySummary) -> dict | None:
    comparison = spec.group_comparison or {}
    if comparison.get("dimension") != "brand":
        return None
    left = comparison.get("left")
    right = comparison.get("right")
    if not isinstance(left, str) or not isinstance(right, str):
        return None

    left_count = summary.brand_counts.get(left, 0)
    right_count = summary.brand_counts.get(right, 0)
    difference = left_count - right_count
    if difference > 0:
        winner = left
    elif difference < 0:
        winner = right
    else:
        winner = None
    return {
        "type": "group_comparison",
        "dimension": "brand",
        "left": left,
        "right": right,
        "left_count": left_count,
        "right_count": right_count,
        "difference": difference,
        "absolute_difference": abs(difference),
        "winner": winner,
    }


def _format_thai_group_comparison_answer(spec: QuerySpec, aggregation: dict, context: str) -> str:
    left = aggregation["left"]
    right = aggregation["right"]
    left_count = aggregation["left_count"]
    right_count = aggregation["right_count"]
    absolute_difference = aggregation["absolute_difference"]
    if aggregation["winner"] is None:
        return f"{left} และ {right} มีจำนวนเท่ากันสำหรับ {context}: {left_count} คันเท่ากัน"
    if aggregation["winner"] == left:
        return f"{left} เยอะกว่า {right} {absolute_difference} คันสำหรับ {context} ({left} {left_count} คัน, {right} {right_count} คัน)"
    return f"{left} น้อยกว่า {right} {absolute_difference} คันสำหรับ {context} ({left} {left_count} คัน, {right} {right_count} คัน)"


def _format_english_group_comparison_answer(spec: QuerySpec, aggregation: dict, context: str) -> str:
    left = aggregation["left"]
    right = aggregation["right"]
    left_count = aggregation["left_count"]
    right_count = aggregation["right_count"]
    absolute_difference = aggregation["absolute_difference"]
    if aggregation["winner"] is None:
        return f"{left} and {right} are tied for {context}: {left_count} vehicles each."
    if aggregation["winner"] == left:
        return f"{left} has {absolute_difference} more vehicles than {right} for {context} ({left}: {left_count}, {right}: {right_count})."
    return f"{left} has {absolute_difference} fewer vehicles than {right} for {context} ({left}: {left_count}, {right}: {right_count})."


def _comparison_filtered_items(items, spec: QuerySpec | None):
    if not spec or not spec.count_operator or spec.count_threshold is None:
        return list(items)
    return [(name, count) for name, count in items if _count_matches_comparison(count, spec)]


def _count_matches_comparison(count: int, spec: QuerySpec) -> bool:
    threshold = spec.count_threshold
    if threshold is None:
        return True
    return {
        "gt": count > threshold,
        "gte": count >= threshold,
        "lt": count < threshold,
        "lte": count <= threshold,
        "eq": count == threshold,
    }.get(spec.count_operator or "", True)


def _comparison_symbol(operator: str | None) -> str:
    return {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "=",
    }.get(operator or "", "")


def _thai_count_comparison_lines(spec: QuerySpec, count: int) -> list[str]:
    if not spec.count_operator or spec.count_threshold is None:
        return []
    symbol = _comparison_symbol(spec.count_operator)
    verdict = "ใช่" if _count_matches_comparison(count, spec) else "ไม่ใช่"
    return [f"ตรวจเงื่อนไขจำนวน: {count} {symbol} {spec.count_threshold} = {verdict}"]


def _english_count_comparison_lines(spec: QuerySpec, count: int) -> list[str]:
    if not spec.count_operator or spec.count_threshold is None:
        return []
    symbol = _comparison_symbol(spec.count_operator)
    verdict = "yes" if _count_matches_comparison(count, spec) else "no"
    return [f"Count comparison: {count} {symbol} {spec.count_threshold} = {verdict}"]


THAI_CROSS_LABELS = {
    "origin_brand": "สรุปตามประเทศ/ยี่ห้อ",
    "origin_type": "สรุปตามประเทศ/ประเภทรถ",
    "brand_type": "สรุปตามยี่ห้อ/ประเภทรถ",
    "camera_event": "สรุปตามกล้อง/event",
    "hour_event": "สรุปตามชั่วโมง/event",
    "color_type": "สรุปตามสี/ประเภทรถ",
    "origin_color": "สรุปตามประเทศ/สี",
    "route_od": "สรุปตามกล้องต้นทาง/ปลายทาง",
    "brand_route": "สรุปตามยี่ห้อ/เส้นทาง",
    "unclosed_entry_camera": "รถ entry แล้วไม่ exit ตามกล้อง entry",
}

ENGLISH_CROSS_LABELS = {
    "origin_brand": "Origin/brand breakdown",
    "origin_type": "Origin/type breakdown",
    "brand_type": "Brand/type breakdown",
    "camera_event": "Camera/event breakdown",
    "hour_event": "Hour/event breakdown",
    "color_type": "Color/type breakdown",
    "origin_color": "Origin/color breakdown",
    "route_od": "Route start/end breakdown",
    "brand_route": "Brand/route breakdown",
    "unclosed_entry_camera": "Entry without exit by entry camera",
}


def _format_thai_cross_breakdowns(spec: QuerySpec, summary: QuerySummary) -> list[str]:
    return [
        f"{THAI_CROSS_LABELS.get(name, name)}: {_format_cross_items(summary.cross_counts.get(name, Counter()), unit='คัน', spec=spec)}"
        for name in spec.cross_breakdowns
        if summary.cross_counts.get(name)
    ]


def _format_english_cross_breakdowns(spec: QuerySpec, summary: QuerySummary) -> list[str]:
    return [
        f"{ENGLISH_CROSS_LABELS.get(name, name)}: {_format_cross_items(summary.cross_counts.get(name, Counter()), unit='', spec=spec)}"
        for name in spec.cross_breakdowns
        if summary.cross_counts.get(name)
    ]


def _format_cross_items(counter: Counter[tuple[str, str]], unit: str, spec: QuerySpec | None = None) -> str:
    sorted_items = sorted(
        _comparison_filtered_items(counter.items(), spec),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    if not sorted_items:
        return "ไม่มี" if unit else "none"
    if unit:
        return ", ".join(f"{left} {right} {count} {unit}" for (left, right), count in sorted_items)
    return ", ".join(f"{left} {right} {count}" for (left, right), count in sorted_items)


def _format_named_counts_from_counter(counter: Counter[str], spec: QuerySpec | None = None) -> str:
    items = sorted(_comparison_filtered_items(counter.items(), spec), key=lambda item: item[0])
    return ", ".join(f"{name}:{count}" for name, count in items) if items else "none"


def _format_origin_counts(spec: QuerySpec, summary: QuerySummary) -> str:
    if spec.brand_origins:
        items = [(origin, summary.origin_counts.get(origin, 0)) for origin in spec.brand_origins]
        return ", ".join(f"{origin}:{count}" for origin, count in _comparison_filtered_items(items, spec)) or "none"
    return _format_named_counts_from_counter(summary.origin_counts, spec=spec)


def _should_offer_event_options(spec: QuerySpec) -> bool:
    return spec.wants_event_breakdown or spec.wants_unclosed_entry_count


def _entry_without_exit_option(spec: QuerySpec, routes: list[VehicleRoute]) -> dict:
    count = len(routes)
    label = "รถที่ entry แล้วไม่ exit" if spec.language == "th" else "Entry without exit"
    answer = f"{label}: {count}"
    return {
        "id": "entry_without_exit",
        "label": label,
        "answer": answer,
        "csv_answer": f"[entry_without_exit:{count}]",
        "count": count,
    }


def _event_breakdown_option(spec: QuerySpec, records: list[CCTVRecord]) -> dict:
    counts = Counter(record.event for record in records)
    csv_answer = _format_event_counts(counts)
    label = "แยกตาม event" if spec.language == "th" else "Event breakdown"
    return {
        "id": "event_breakdown",
        "label": label,
        "answer": f"{label}: {csv_answer}",
        "csv_answer": csv_answer,
        "count": sum(counts.values()),
    }


def _event_only_option(spec: QuerySpec, event: str, routes: list[VehicleRoute]) -> dict:
    count = len(routes)
    label = f"เฉพาะ {event}" if spec.language == "th" else f"{event} only"
    return {
        "id": f"{event}_only",
        "label": label,
        "answer": f"{label}: {count}",
        "csv_answer": f"[{event}:{count}]",
        "count": count,
    }


def _format_bracketed_named_counts(items) -> str:
    sorted_items = sorted(items, key=lambda item: (-item[1], str(item[0]).casefold()))
    return "[" + ", ".join(f"{name}:{count}" for name, count in sorted_items) + "]"


def _format_event_counts(counts: Counter[str]) -> str:
    items = [(event, counts[event]) for event in ("entry", "exit", "pass") if counts[event]]
    extras = sorted((event, count) for event, count in counts.items() if event not in {"entry", "exit", "pass"})
    return "[" + ", ".join(f"{event}:{count}" for event, count in items + extras) + "]"


def _format_thai_tracking_duration_answer(spec: QuerySpec, summary: QuerySummary, aggregation: dict) -> str:
    context = _thai_context(spec)
    count = summary.unique_vehicle_count
    minimum = _format_presence_minimum(spec, language="th")
    if count == 0:
        if spec.wants_presence_count:
            return f"ไม่พบรถที่จอด/ค้างอยู่{minimum}สำหรับ {context}"
        return f"ไม่พบรถที่มีช่วง tracking ทับกับเงื่อนไข: {context}"

    detection_count = aggregation.get("detection_count", 0)
    average = _format_duration(aggregation.get("average_duration_seconds", 0), language="th")
    longest = _format_duration(aggregation.get("max_duration_seconds", 0), language="th")
    overlap_average = _format_duration(aggregation.get("average_overlap_seconds", 0), language="th")
    if spec.wants_presence_count:
        lines = [
            f"พบรถที่จอด/ค้างอยู่{minimum}ทับกับ {context} จำนวน {count} คัน "
            f"(ตรวจพบ {detection_count} ครั้ง)"
        ]
    else:
        lines = [
            f"พบรถที่มีช่วง tracking ทับกับ {context} จำนวน {count} คัน "
            f"(ตรวจพบ {detection_count} ครั้ง)"
        ]
    if aggregation.get("has_time_range"):
        lines.append(f"เวลาอยู่ในช่วงที่ถามเฉลี่ย {overlap_average}")
    if spec.wants_tracking_duration:
        lines.append(f"ระยะ tracking เฉลี่ย {average}, นานสุด {longest}")
    lines.append("หมายเหตุ: นับจาก First_Seen-Last_Seen ที่ทับช่วงเวลา ไม่ได้ยืนยันว่ารถจอดนิ่งจริง")
    return "\n".join(lines)


def _format_english_tracking_duration_answer(spec: QuerySpec, summary: QuerySummary, aggregation: dict) -> str:
    context = _english_context(spec)
    count = summary.unique_vehicle_count
    minimum = _format_presence_minimum(spec, language="en")
    if count == 0:
        if spec.wants_presence_count:
            return f"No vehicles parked/present{minimum} for {context}."
        return f"No vehicles with tracking intervals overlapping {context}."

    detection_count = aggregation.get("detection_count", 0)
    average = _format_duration(aggregation.get("average_duration_seconds", 0), language="en")
    longest = _format_duration(aggregation.get("max_duration_seconds", 0), language="en")
    overlap_average = _format_duration(aggregation.get("average_overlap_seconds", 0), language="en")
    if spec.wants_presence_count:
        lines = [
            f"Found {count} vehicles parked/present{minimum} overlapping {context} "
            f"({detection_count} detections)."
        ]
    else:
        lines = [
            f"Found {count} vehicles with tracking intervals overlapping {context} "
            f"({detection_count} detections)."
        ]
    if aggregation.get("has_time_range"):
        lines.append(f"Average time inside the requested window: {overlap_average}.")
    if spec.wants_tracking_duration:
        lines.append(f"Average tracking duration: {average}; longest: {longest}.")
    lines.append("Note: this uses First_Seen-Last_Seen overlap, not confirmed stationary parking.")
    return "\n".join(lines)


def _format_presence_minimum(spec: QuerySpec, *, language: str) -> str:
    if not spec.wants_presence_count or not spec.presence_min_seconds:
        return ""
    duration = _format_presence_minimum_duration(spec.presence_min_seconds, language=language)
    if language == "th":
        return f"อย่างน้อย {duration}"
    return f" for at least {duration}"


def _format_presence_minimum_duration(seconds: int, *, language: str) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}h" if language == "en" else f"{hours} ชม."
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes}m" if language == "en" else f"{minutes} นาที"
    return _format_duration(seconds, language=language)


def _format_duration(seconds: float | int, *, language: str) -> str:
    total_seconds = int(round(seconds))
    minutes, second = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    if language == "en":
        if hours:
            return f"{hours}h {minute}m {second}s"
        if minute:
            return f"{minute}m {second}s"
        return f"{second}s"
    if hours:
        return f"{hours} ชม. {minute} นาที {second} วินาที"
    if minute:
        return f"{minute} นาที {second} วินาที"
    return f"{second} วินาที"


def _format_thai_aggregation_answer(spec: QuerySpec, aggregation: dict) -> str:
    context = _thai_context(replace(spec, event=None, events=()))
    context_phrase = f"ใน{context}" if context == "ข้อมูลทั้งหมด" else f"สำหรับ {context}"
    if aggregation["total_count"] == 0:
        return f"ไม่พบข้อมูล{context_phrase}"

    metric = _thai_event_scope(spec)
    top = aggregation["top"]
    top_text = ", ".join(f"{item['label']} ({item['count']} ครั้ง{_event_count_note(item)})" for item in top)
    if aggregation["group_by"] == "hour":
        if spec.wants_hour_average:
            average = aggregation.get("average_count", 0)
            denominator = aggregation.get("average_denominator", 0)
            return f"ค่าเฉลี่ยจำนวนรถต่อ 1 ชั่วโมง{context_phrase} คือ {average:.2f} ครั้ง/ชั่วโมง จาก {aggregation['total_count']} ครั้งใน {denominator} ชั่วโมง"
        if spec.wants_hour_breakdown and not spec.wants_peak_hour:
            return f"สรุปตามชั่วโมง{context_phrase}: {_format_aggregation_rows(aggregation)}"
        return f"ชั่วโมงที่มี{metric}มากที่สุด{context_phrase} คือ {top_text}"

    if spec.wants_camera_breakdown and not spec.wants_peak_camera:
        return f"สรุปตามกล้อง{context_phrase}: {_format_aggregation_rows(aggregation)}"
    return f"กล้องที่มี{metric}มากที่สุด{context_phrase} คือ {top_text}"


def _format_english_aggregation_answer(spec: QuerySpec, aggregation: dict) -> str:
    context = _english_context(replace(spec, event=None, events=()))
    if aggregation["total_count"] == 0:
        return f"No matching records for {context}."

    metric = _english_event_scope(spec)
    top = aggregation["top"]
    top_text = ", ".join(f"{item['label']} ({item['count']} records{_event_count_note(item)})" for item in top)
    if aggregation["group_by"] == "hour":
        if spec.wants_hour_average:
            average = aggregation.get("average_count", 0)
            denominator = aggregation.get("average_denominator", 0)
            return (
                f"Average vehicles per 1 hour for {context}: {average:.2f} records/hour "
                f"from {aggregation['total_count']} records across {denominator} hours."
            )
        if spec.wants_hour_breakdown and not spec.wants_peak_hour:
            return f"Hourly breakdown for {context}: {_format_aggregation_rows(aggregation)}"
        return f"The busiest hour for {metric} in {context} is {top_text}."

    if spec.wants_camera_breakdown and not spec.wants_peak_camera:
        return f"Camera breakdown for {context}: {_format_aggregation_rows(aggregation)}"
    return f"The busiest camera for {metric} in {context} is {top_text}."


def _format_thai_vehicle_ordinal_answer(spec: QuerySpec, route: VehicleRoute | None, total_routes: int) -> str:
    context = _thai_context(spec)
    label = _thai_ordinal_label(spec.vehicle_ordinal)
    if total_routes == 0:
        return f"ไม่พบรถไม่ซ้ำสำหรับ {context}"
    if route is None:
        return f"ไม่มีรถลำดับ {label} สำหรับ {context} (มีทั้งหมด {total_routes} คันไม่ซ้ำ)"
    return (
        f"รถลำดับ {label} สำหรับ {context} คือ {_route_vehicle_label(route)} "
        f"เวลา {route.start_time}-{route.end_time} ผ่าน {_route_path(route)} "
        f"(จากทั้งหมด {total_routes} คันไม่ซ้ำ, ตรวจพบ {route.event_count} ครั้ง)"
    )


def _format_english_vehicle_ordinal_answer(spec: QuerySpec, route: VehicleRoute | None, total_routes: int) -> str:
    context = _english_context(spec)
    label = _english_ordinal_label(spec.vehicle_ordinal)
    if total_routes == 0:
        return f"No unique vehicles for {context}."
    if route is None:
        return f"No vehicle at position {label} for {context}; there are {total_routes} unique vehicles."
    return (
        f"The {label} vehicle for {context} is {_route_vehicle_label(route)} "
        f"from {route.start_time} to {route.end_time} via {_route_path(route)} "
        f"({route.event_count} detections out of {total_routes} unique vehicles)."
    )


def _ordinal_label(ordinal: int | None) -> str:
    if ordinal == -1:
        return "last"
    return str(ordinal or "")


def _thai_ordinal_label(ordinal: int | None) -> str:
    if ordinal == -1:
        return "สุดท้าย"
    return str(ordinal or "")


def _english_ordinal_label(ordinal: int | None) -> str:
    if ordinal == -1:
        return "last"
    if ordinal is None:
        return ""
    suffix = "th"
    if ordinal % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(ordinal % 10, "th")
    return f"{ordinal}{suffix}"


def _format_aggregation_rows(aggregation: dict, limit: int = 10) -> str:
    rows = aggregation["rows"][:limit]
    return ", ".join(f"{item['label']}:{item['count']}" for item in rows)


def _event_count_note(item: dict) -> str:
    counts = Counter(item.get("event_counts") or {})
    if not counts:
        return ""
    return "; " + _format_event_counts(counts).strip("[]")


def _thai_event_scope(spec: QuerySpec) -> str:
    if spec.events == ("entry", "exit"):
        return "รถเข้าออก"
    if spec.events:
        return f"event {', '.join(spec.events)}"
    if spec.event:
        return f"event {spec.event}"
    return "รถ"


def _english_event_scope(spec: QuerySpec) -> str:
    if spec.events == ("entry", "exit"):
        return "entry/exit traffic"
    if spec.events:
        return ", ".join(spec.events)
    if spec.event:
        return spec.event
    return "traffic"


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


def _thai_count_note(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    if spec.wants_distinct_vehicle_count and len(routes) != summary.unique_vehicle_count:
        detection_note = ""
        if summary.event_count != len(routes):
            detection_note = f", ตรวจพบ {summary.event_count} ครั้ง"
        return f" (รวมซ้ำ {len(routes)} รายการ{detection_note})"
    return _thai_detection_note(summary)


def _english_detection_note(summary: QuerySummary) -> str:
    if summary.event_count == summary.unique_vehicle_count:
        return ""
    return f" ({summary.event_count} detections)"


def _english_count_note(spec: QuerySpec, summary: QuerySummary, routes: list[VehicleRoute]) -> str:
    if spec.wants_distinct_vehicle_count and len(routes) != summary.unique_vehicle_count:
        detection_note = ""
        if summary.event_count != len(routes):
            detection_note = f", {summary.event_count} detections"
        return f" ({len(routes)} repeated route groups{detection_note})"
    return _english_detection_note(summary)


def _thai_context(spec: QuerySpec) -> str:
    parts: list[str] = []
    if spec.condition_groups:
        parts.append("เงื่อนไขรวม " + " + ".join(_thai_condition_group_label(group) for group in spec.condition_groups))
    if spec.date:
        parts.append(f"วันที่ {spec.date}")
    if spec.cctv_id:
        parts.append(spec.cctv_id)
    if spec.start_time and spec.end_time:
        parts.append(f"ช่วง {spec.start_time}-{spec.end_time}")
    brands = spec.brands or ((spec.brand,) if spec.brand else ())
    if brands:
        parts.append(f"ยี่ห้อ {', '.join(brands)}")
    if spec.brand_origins:
        parts.append(f"\u0e1b\u0e23\u0e30\u0e40\u0e17\u0e28/\u0e20\u0e39\u0e21\u0e34\u0e20\u0e32\u0e04 {', '.join(spec.brand_origins)}")
    colors = spec.colors or ((spec.color,) if spec.color else ())
    if colors:
        if spec.wants_metallic_color:
            parts.append(f"metallic ({', '.join(colors)})")
        else:
            parts.append(f"สี {', '.join(colors)}")
    if spec.vehicle_type:
        parts.append(f"ประเภท {THAI_TYPE_LABELS.get(spec.vehicle_type, spec.vehicle_type)}")
    if spec.event:
        parts.append(f"event {spec.event}")
    if spec.events:
        parts.append(f"events {', '.join(spec.events)}")
    return " ".join(parts) if parts else "ข้อมูลทั้งหมด"


def _english_context(spec: QuerySpec) -> str:
    parts: list[str] = []
    if spec.condition_groups:
        parts.append("combined filters " + " + ".join(_english_condition_group_label(group) for group in spec.condition_groups))
    if spec.date:
        parts.append(f"date {spec.date}")
    if spec.cctv_id:
        parts.append(spec.cctv_id)
    if spec.start_time and spec.end_time:
        parts.append(f"from {spec.start_time} to {spec.end_time}")
    brands = spec.brands or ((spec.brand,) if spec.brand else ())
    if brands:
        parts.append(f"brand {', '.join(brands)}")
    if spec.brand_origins:
        parts.append(f"origin {', '.join(spec.brand_origins)}")
    colors = spec.colors or ((spec.color,) if spec.color else ())
    if colors:
        if spec.wants_metallic_color:
            parts.append(f"metallic colors ({', '.join(colors)})")
        else:
            parts.append(f"color {', '.join(colors)}")
    if spec.vehicle_type:
        parts.append(f"type {spec.vehicle_type}")
    if spec.event:
        parts.append(f"event {spec.event}")
    if spec.events:
        parts.append(f"events {', '.join(spec.events)}")
    return ", ".join(parts) if parts else "all records"


def _thai_condition_group_label(group: dict) -> str:
    parts: list[str] = []
    date = group.get("date")
    if isinstance(date, str):
        parts.append(f"วันที่ {date}")
    start_time = group.get("start_time")
    end_time = group.get("end_time")
    if isinstance(start_time, str) and isinstance(end_time, str):
        parts.append(f"ช่วง {start_time}-{end_time}")
    brands = _group_values(group, "brands")
    if brands:
        parts.append(f"ยี่ห้อ {', '.join(brands)}")
    colors = _group_values(group, "colors")
    if colors:
        parts.append(f"สี {', '.join(colors)}")
    vehicle_type = group.get("vehicle_type")
    if isinstance(vehicle_type, str):
        parts.append(f"ประเภท {THAI_TYPE_LABELS.get(vehicle_type, vehicle_type)}")
    event = group.get("event")
    if isinstance(event, str):
        parts.append(f"event {event}")
    return " ".join(parts)


def _english_condition_group_label(group: dict) -> str:
    parts: list[str] = []
    date = group.get("date")
    if isinstance(date, str):
        parts.append(f"date {date}")
    start_time = group.get("start_time")
    end_time = group.get("end_time")
    if isinstance(start_time, str) and isinstance(end_time, str):
        parts.append(f"from {start_time} to {end_time}")
    brands = _group_values(group, "brands")
    if brands:
        parts.append(f"brand {', '.join(brands)}")
    colors = _group_values(group, "colors")
    if colors:
        parts.append(f"color {', '.join(colors)}")
    vehicle_type = group.get("vehicle_type")
    if isinstance(vehicle_type, str):
        parts.append(f"type {vehicle_type}")
    event = group.get("event")
    if isinstance(event, str):
        parts.append(f"event {event}")
    return " ".join(parts)


def _english_vehicle_word(vehicle_type: str | None, count: int) -> str:
    if vehicle_type:
        base = vehicle_type.lower()
        if count == 1:
            return base
        if base == "bus":
            return "buses"
        return base + "s"
    return "vehicle" if count == 1 else "vehicles"
