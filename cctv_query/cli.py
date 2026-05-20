from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cctv_query.engine import CCTVQueryEngine
from cctv_query.llm_normalizer import LLMNormalizationResult, normalize_question_if_enabled


DEFAULT_CSV = Path(__file__).resolve().parents[1] / "cctv_vehicle_log_routed.csv"


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Query CCTV vehicle logs from a CSV file.")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="Path to CCTV CSV log. Defaults to cctv_vehicle_log_routed.csv in this project.",
    )
    parser.add_argument("--question", "-q", help="Thai or English question to ask.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON output.")
    llm_group = parser.add_mutually_exclusive_group()
    llm_group.add_argument("--llm", action="store_true", help="Normalize the question with the configured LLM first.")
    llm_group.add_argument("--no-llm", action="store_true", help="Disable LLM normalization even if env is enabled.")
    args = parser.parse_args(argv)
    llm_enabled = True if args.llm else False if args.no_llm else None

    engine = CCTVQueryEngine.from_csv(args.csv)
    if args.question:
        result, normalization = _ask(engine, args.question, llm_enabled=llm_enabled)
        _print_result(result, as_json=args.json, normalization=normalization)
        return 0

    print("Enter a Thai or English CCTV question. Press Enter on a blank line to exit.")
    while True:
        question = input("> ").strip()
        if not question:
            return 0
        result, normalization = _ask(engine, question, llm_enabled=llm_enabled)
        _print_result(result, as_json=args.json, normalization=normalization)


def _ask(engine: CCTVQueryEngine, question: str, *, llm_enabled: bool | None):
    normalization = normalize_question_if_enabled(
        question,
        known_brands=engine.known_brands,
        known_colors=engine.known_colors,
        known_dates=engine.known_dates,
        enabled=llm_enabled,
    )
    return engine.ask(normalization.normalized_question), normalization


def _print_result(result, as_json: bool, normalization: LLMNormalizationResult | None = None) -> None:
    if as_json:
        payload = result.to_dict()
        if normalization is not None:
            payload["llm_normalization"] = normalization.to_dict()
            payload["original_question"] = normalization.original_question
            payload["normalized_question"] = normalization.normalized_question
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if normalization and normalization.used and normalization.changed:
            print(f"Normalized: {normalization.normalized_question}")
        if normalization and normalization.error:
            print(f"LLM normalization fallback: {normalization.error}", file=sys.stderr)
        print(result.answer)


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
