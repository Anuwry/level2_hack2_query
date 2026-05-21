from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass

from cctv_query.engine import CCTVQueryEngine
from cctv_query.models import QueryResult
from cctv_query.normalization import normalize_cctv_id, normalize_time


DEFAULT_QUESTION_HEADER = "Question ID,CCTV ID,Time Range,Query"
CROSS_MODES = {
    "origin_brand",
    "origin_type",
    "brand_type",
    "camera_event",
    "hour_event",
    "color_type",
    "origin_color",
    "route_od",
    "brand_route",
    "unclosed_entry_camera",
}


@dataclass(frozen=True)
class BatchQuestionRow:
    question_id: str
    cctv_id: str | None
    time_range: str | None
    query: str


def parse_batch_question_csv(csv_text: str) -> list[BatchQuestionRow]:
    space_table_rows = _parse_space_separated_question_table(csv_text)
    if space_table_rows:
        return space_table_rows

    cleaned_text = _clean_question_csv_text(csv_text)
    reader = csv.DictReader(io.StringIO(cleaned_text))
    if not reader.fieldnames:
        raise ValueError("CSV questions must include a header row.")

    rows: list[BatchQuestionRow] = []
    for raw_row in reader:
        normalized_row = {_normalize_header(key): (value or "").strip() for key, value in raw_row.items() if key}
        extra_values = raw_row.get(None) or []
        if extra_values:
            query_key = "query" if "query" in normalized_row else "question" if "question" in normalized_row else "query"
            current_query = normalized_row.get(query_key, "")
            normalized_row[query_key] = (current_query + "," + ",".join(value or "" for value in extra_values)).strip()
        if not any(normalized_row.values()):
            continue
        question_id = normalized_row.get("question_id") or normalized_row.get("id") or ""
        query = normalized_row.get("query") or normalized_row.get("question") or ""
        if not question_id:
            raise ValueError("Each CSV row must include Question ID.")
        if not query:
            raise ValueError(f"CSV row {question_id} must include Query.")
        rows.append(
            BatchQuestionRow(
                question_id=question_id,
                cctv_id=normalized_row.get("cctv_id") or normalized_row.get("camera_id") or None,
                time_range=normalized_row.get("time_range") or normalized_row.get("time") or None,
                query=query,
            )
        )

    if not rows:
        raise ValueError("CSV questions did not contain any rows.")
    return rows


def build_batch_question(row: BatchQuestionRow) -> str:
    parts: list[str] = []
    if row.cctv_id:
        parts.append(_normalize_loose_cctv_id(row.cctv_id))
    if row.time_range:
        start_time, end_time = _normalize_time_range(row.time_range)
        parts.append(f"from {start_time} to {end_time}")
    parts.append(row.query)
    return " ".join(parts)


def answer_batch_questions(engine: CCTVQueryEngine, csv_text: str) -> dict:
    rows = parse_batch_question_csv(csv_text)
    answers: list[dict] = []
    for row in rows:
        composed_question = build_batch_question(row)
        result = engine.ask(composed_question)
        csv_answer = format_csv_style_answer(result, row.query)
        answers.append(
            {
                "question_id": row.question_id,
                "cctv_id": row.cctv_id,
                "time_range": row.time_range,
                "query": row.query,
                "composed_question": composed_question,
                "answer": result.answer,
                "csv_answer": csv_answer,
                "count": result.count,
                "event_count": result.event_count,
                "out_of_range": result.out_of_range,
                "out_of_range_reasons": list(result.out_of_range_reasons),
                "warnings": list(result.warnings),
                "clarifications": list(result.clarifications),
                "answer_options": list(result.answer_options),
                "needs_clarification": result.needs_clarification,
            }
        )

    answers_csv = render_answers_csv(answers)
    return {"answers": answers, "answers_csv": answers_csv}


def render_answers_csv(answers: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Question ID", "Answer"], lineterminator="\n")
    writer.writeheader()
    for item in answers:
        writer.writerow({"Question ID": item["question_id"], "Answer": item["csv_answer"]})
    return output.getvalue()


def format_csv_style_answer(result: QueryResult, query_text: str) -> str:
    if result.out_of_range:
        return result.answer

    if result.spec.wants_unclosed_entry_count and result.spec.cross_breakdowns:
        return _format_cross_counts(result, result.spec.cross_breakdowns[0])
    if result.spec.wants_unclosed_entry_count:
        return f"[entry_without_exit:{result.count}]"
    if result.spec.wants_event_breakdown:
        return _format_event_counts(Counter(record.event for record in result.matches))
    if result.spec.wants_peak_hour or result.spec.wants_hour_breakdown or result.spec.wants_peak_camera or result.spec.wants_camera_breakdown:
        return _format_aggregation_csv(result.aggregation or {})

    mode = _answer_mode(query_text)
    if mode in CROSS_MODES:
        return _format_cross_counts(result, mode)
    if mode == "origin_brand":
        return _format_cross_counts(result, "origin_brand")
    if mode == "brand_color":
        return _format_brand_color_counts(result)
    if mode == "brand":
        return _format_named_counts(result.summary.brand_counts.items())
    if mode == "color":
        return _format_named_counts(result.summary.color_counts.items())
    if mode == "origin":
        if result.spec.brand_origins:
            return _format_named_counts((origin, result.summary.origin_counts.get(origin, 0)) for origin in result.spec.brand_origins)
        return _format_named_counts(result.summary.origin_counts.items())
    if mode == "type":
        return _format_named_counts(result.summary.type_counts.items())
    if mode == "event":
        return _format_event_counts(Counter(record.event for record in result.matches))
    return str(result.count)


def _format_brand_color_counts(result: QueryResult) -> str:
    items = sorted(
        result.summary.brand_color_counts.items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    return "[" + ", ".join(f"({brand}, {color}):{count}" for (brand, color), count in items) + "]"


def _format_cross_counts(result: QueryResult, mode: str) -> str:
    items = sorted(
        result.summary.cross_counts.get(mode, Counter()).items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    return "[" + ", ".join(f"({left}, {right}):{count}" for (left, right), count in items) + "]"


def _format_named_counts(items) -> str:
    sorted_items = sorted(items, key=lambda item: (-item[1], str(item[0]).casefold()))
    return "[" + ", ".join(f"{name}:{count}" for name, count in sorted_items) + "]"


def _format_event_counts(counts: Counter[str]) -> str:
    items = [(event, counts[event]) for event in ("entry", "exit", "pass") if counts[event]]
    extras = sorted((event, count) for event, count in counts.items() if event not in {"entry", "exit", "pass"})
    return "[" + ", ".join(f"{event}:{count}" for event, count in items + extras) + "]"


def _format_aggregation_csv(aggregation: dict) -> str:
    rows = aggregation.get("top") or aggregation.get("rows") or []
    return "[" + ", ".join(f"{row.get('label') or row.get('key')}:{row.get('count', 0)}" for row in rows) + "]"


def _answer_mode(query_text: str) -> str:
    normalized = query_text.casefold()
    has_brand = any(term in normalized for term in ("brand", "\u0e22\u0e35\u0e48\u0e2b\u0e49\u0e2d"))
    has_color = any(term in normalized for term in ("color", "colour", "\u0e2a\u0e35"))
    has_origin = any(
        term in normalized
        for term in (
            "country",
            "countries",
            "origin",
            "region",
            "nationality",
            "\u0e1b\u0e23\u0e30\u0e40\u0e17\u0e28",
            "\u0e2a\u0e31\u0e0d\u0e0a\u0e32\u0e15\u0e34",
            "\u0e0d\u0e35\u0e48\u0e1b\u0e38\u0e48\u0e19",
            "\u0e08\u0e35\u0e19",
            "\u0e40\u0e01\u0e32\u0e2b\u0e25\u0e35",
            "\u0e22\u0e38\u0e42\u0e23\u0e1b",
        )
    )
    has_type = any(term in normalized for term in ("vehicle type", "vehicle types", "type", "types", "\u0e1b\u0e23\u0e30\u0e40\u0e20\u0e17\u0e23\u0e16", "\u0e1b\u0e23\u0e30\u0e40\u0e20\u0e17"))
    has_camera = any(term in normalized for term in ("camera", "cctv", "\u0e01\u0e25\u0e49\u0e2d\u0e07"))
    has_hour = any(term in normalized for term in ("hour", "hours", "time", "\u0e0a\u0e31\u0e48\u0e27\u0e42\u0e21\u0e07", "\u0e40\u0e27\u0e25\u0e32"))
    has_route = any(term in normalized for term in ("route", "path", "\u0e40\u0e2a\u0e49\u0e19\u0e17\u0e32\u0e07", "\u0e40\u0e14\u0e34\u0e19\u0e17\u0e32\u0e07"))
    has_start_end = any(term in normalized for term in ("start", "end", "origin destination", "od", "from", "to", "\u0e15\u0e49\u0e19\u0e17\u0e32\u0e07", "\u0e1b\u0e25\u0e32\u0e22\u0e17\u0e32\u0e07", "\u0e08\u0e32\u0e01", "\u0e44\u0e1b"))
    has_event = any(term in normalized for term in ("event", "events", "\u0e2a\u0e16\u0e32\u0e19\u0e30"))
    has_event_word = any(
        re.search(pattern, normalized)
        for pattern in (
            r"\bentry\b",
            r"\bexit\b",
            r"\bexits\b",
            r"\bpass\b",
            r"\bpassed\b",
            r"\bpassing\b",
        )
    )
    if has_origin and has_brand:
        return "origin_brand"
    if has_origin and has_type:
        return "origin_type"
    if has_brand and has_type:
        return "brand_type"
    if has_camera and (has_event or has_event_word):
        return "camera_event"
    if has_hour and (has_event or has_event_word):
        return "hour_event"
    if has_color and has_type:
        return "color_type"
    if has_origin and has_color:
        return "origin_color"
    if has_route and has_start_end:
        return "route_od"
    if has_brand and has_route:
        return "brand_route"
    if has_brand and has_color:
        return "brand_color"
    if has_brand:
        return "brand"
    if has_color:
        return "color"
    if has_origin:
        return "origin"
    if has_type:
        return "type"
    if has_event or has_event_word:
        return "event"
    return "answer"


def _normalize_time_range(value: str) -> tuple[str, str]:
    tokens = re.findall(r"\d{1,2}[:.]\d{1,2}(?:[:.]\d{1,2})?", value)
    if len(tokens) < 2:
        raise ValueError(f"Invalid Time Range '{value}'. Expected start - end.")
    return _normalize_loose_time(tokens[0]), _normalize_loose_time(tokens[1])


def _normalize_loose_time(value: str) -> str:
    return normalize_time(value.strip().strip(".").replace(".", ":"))


def _normalize_loose_cctv_id(value: str) -> str:
    text = value.strip().replace("O", "0").replace("o", "0")
    return normalize_cctv_id(text)


def _parse_space_separated_question_table(text: str) -> list[BatchQuestionRow]:
    rows: list[BatchQuestionRow] = []
    in_question_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip(".")
        if not line:
            if rows:
                break
            continue
        if not in_question_table:
            if _is_space_question_header(line):
                in_question_table = True
                continue
            row = _parse_space_question_row(line)
            if row:
                in_question_table = True
                rows.append(row)
            continue
        if _is_space_answer_header(line):
            break
        row = _parse_space_question_row(line)
        if row:
            rows.append(row)
    return rows


def _is_space_question_header(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.strip().casefold())
    return normalized == "question id cctv id time range query"


def _is_space_answer_header(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.strip().casefold())
    return normalized == "question id answer"


def _parse_space_question_row(line: str) -> BatchQuestionRow | None:
    time_token = r"\d{1,2}[:.]\d{1,2}(?:[:.]\d{1,2})?"
    match = re.match(
        rf"^(Q[\w\-]*)\s+(CCTV\s*[0-9oO]+)\s+({time_token}\s*-\s*{time_token})\s+(.+)$",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return BatchQuestionRow(
        question_id=match.group(1).strip(),
        cctv_id=match.group(2).strip(),
        time_range=match.group(3).strip(),
        query=match.group(4).strip(),
    )


def _clean_question_csv_text(csv_text: str) -> str:
    raw_lines: list[str] = []
    for line in csv_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.casefold()
        if "question id" in lowered:
            stripped = stripped[lowered.index("question id") :]
        elif stripped.startswith("#"):
            continue
        raw_lines.append(stripped.rstrip("."))

    if not raw_lines:
        return ""

    if _is_question_header(raw_lines[0]):
        header = raw_lines[0]
        data_lines = raw_lines[1:]
    else:
        header = DEFAULT_QUESTION_HEADER
        data_lines = raw_lines

    expected_columns = len(next(csv.reader([header])))
    lines: list[str] = [header]
    pending: str | None = None
    for line in data_lines:
        if pending and _row_needs_query(pending, expected_columns) and not _looks_like_question_row(line):
            lines.append(pending.rstrip(",") + "," + line)
            pending = None
            continue
        if pending:
            lines.append(pending)
            pending = None
        if _row_needs_query(line, expected_columns):
            pending = line
        else:
            lines.append(line)

    if pending:
        lines.append(pending)
    return "\n".join(lines)


def _is_question_header(line: str) -> bool:
    try:
        row = next(csv.reader([line]))
    except csv.Error:
        return False
    headers = {_normalize_header(value) for value in row}
    has_question_id = bool({"question_id", "id"} & headers)
    has_query = bool({"query", "question"} & headers)
    return has_question_id and has_query


def _row_needs_query(line: str, expected_columns: int) -> bool:
    try:
        row = next(csv.reader([line]))
    except csv.Error:
        return False
    return len(row) < expected_columns or (len(row) >= expected_columns and not row[expected_columns - 1].strip())


def _looks_like_question_row(line: str) -> bool:
    if _is_question_header(line):
        return True
    try:
        row = next(csv.reader([line]))
    except csv.Error:
        return False
    if len(row) < 2:
        return False
    return bool(re.fullmatch(r"Q[\w\-]*", row[0].strip(), flags=re.IGNORECASE))


def _normalize_header(value: str) -> str:
    normalized = value.strip().lstrip("#").strip().casefold().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.replace(" ", "_")
