from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from cctv_query.engine import CCTVQueryEngine
from cctv_query.models import QueryResult
from cctv_query.normalization import normalize_cctv_id, normalize_time


@dataclass(frozen=True)
class BatchQuestionRow:
    question_id: str
    cctv_id: str | None
    time_range: str | None
    query: str


def parse_batch_question_csv(csv_text: str) -> list[BatchQuestionRow]:
    cleaned_text = _clean_question_csv_text(csv_text)
    reader = csv.DictReader(io.StringIO(cleaned_text))
    if not reader.fieldnames:
        raise ValueError("CSV questions must include a header row.")

    rows: list[BatchQuestionRow] = []
    for raw_row in reader:
        normalized_row = {_normalize_header(key): (value or "").strip() for key, value in raw_row.items() if key}
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

    mode = _answer_mode(query_text)
    if mode == "brand_color":
        return _format_brand_color_counts(result)
    if mode == "brand":
        return _format_named_counts(result.summary.brand_counts.items())
    if mode == "color":
        return _format_named_counts(result.summary.color_counts.items())
    return result.answer


def _format_brand_color_counts(result: QueryResult) -> str:
    items = sorted(
        result.summary.brand_color_counts.items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )
    return "[" + ", ".join(f"({brand}, {color}):{count}" for (brand, color), count in items) + "]"


def _format_named_counts(items) -> str:
    sorted_items = sorted(items, key=lambda item: (-item[1], str(item[0]).casefold()))
    return "[" + ", ".join(f"{name}:{count}" for name, count in sorted_items) + "]"


def _answer_mode(query_text: str) -> str:
    normalized = query_text.casefold()
    has_brand = any(term in normalized for term in ("brand", "\u0e22\u0e35\u0e48\u0e2b\u0e49\u0e2d"))
    has_color = any(term in normalized for term in ("color", "colour", "\u0e2a\u0e35"))
    if has_brand and has_color:
        return "brand_color"
    if has_brand:
        return "brand"
    if has_color:
        return "color"
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


def _clean_question_csv_text(csv_text: str) -> str:
    lines: list[str] = []
    for line in csv_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.casefold()
        if "question id" in lowered:
            stripped = stripped[lowered.index("question id") :]
        elif stripped.startswith("#"):
            continue
        lines.append(stripped.rstrip("."))
    return "\n".join(lines)


def _normalize_header(value: str) -> str:
    normalized = value.strip().lstrip("#").strip().casefold().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.replace(" ", "_")
