from __future__ import annotations

import argparse
import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.normalization import time_to_seconds
from cctv_query.prepare_site_csv import OUTPUT_FIELDNAMES, ConversionReport, convert_csv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG1 = PROJECT_ROOT / "detections_v2_20260521_165339 (1).csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "detections_ready.csv"
DEFAULT_TIME_WINDOW_SECONDS = 2


@dataclass(frozen=True)
class DetectionConversionReport:
    output: Path
    input_rows: int
    converted_rows: int
    output_rows: int
    skipped_rows: int
    source_reports: tuple[ConversionReport, ...]


def convert_detection_logs(
    log1_path: str | Path = DEFAULT_LOG1,
    output_path: str | Path = DEFAULT_OUTPUT,
    *,
    log2_path: str | Path | None = None,
    time_window_seconds: int = DEFAULT_TIME_WINDOW_SECONDS,
) -> DetectionConversionReport:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_paths = [Path(log1_path)]
    if log2_path:
        source_paths.append(Path(log2_path))

    source_reports: list[ConversionReport] = []
    converted_rows: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        for index, source_path in enumerate(source_paths, start=1):
            temp_output = temp_root / f"detections_{index}_ready.csv"
            report = convert_csv(source_path, temp_output)
            source_reports.append(report)
            converted_rows.extend(_read_rows(temp_output))

    output_rows = _dedupe_rows(converted_rows, time_window_seconds=max(0, time_window_seconds))
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(OUTPUT_FIELDNAMES), lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    try:
        load_records(output)
    except Exception as exc:
        raise ValueError(f"Converted detection CSV is not loadable by the site: {exc}") from exc

    return DetectionConversionReport(
        output=output,
        input_rows=sum(report.input_rows for report in source_reports),
        converted_rows=sum(report.output_rows for report in source_reports),
        output_rows=len(output_rows),
        skipped_rows=sum(report.skipped_rows for report in source_reports),
        source_reports=tuple(source_reports),
    )


def _dedupe_rows(rows: list[dict[str, str]], *, time_window_seconds: int) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (
            row["Date"],
            row["CCTV_ID"],
            row["Brand"].casefold(),
            row["Color"].casefold(),
            row["Type"].casefold(),
        )
        grouped.setdefault(key, []).append(row)

    deduped: list[dict[str, str]] = []
    for group_rows in grouped.values():
        sorted_rows = sorted(group_rows, key=lambda row: time_to_seconds(row["First_Seen"]))
        current_cluster: list[dict[str, str]] = []
        current_last_seconds: int | None = None
        for row in sorted_rows:
            row_seconds = time_to_seconds(row["First_Seen"])
            if current_cluster and current_last_seconds is not None and row_seconds - current_last_seconds > time_window_seconds:
                deduped.append(_cluster_row(current_cluster))
                current_cluster = []
            current_cluster.append(row)
            current_last_seconds = max(current_last_seconds or row_seconds, time_to_seconds(row["Last_Seen"]))
        if current_cluster:
            deduped.append(_cluster_row(current_cluster))

    return sorted(deduped, key=_sort_key)


def _cluster_row(rows: list[dict[str, str]]) -> dict[str, str]:
    first_seconds = min(time_to_seconds(row["First_Seen"]) for row in rows)
    last_seconds = max(time_to_seconds(row["Last_Seen"]) for row in rows)
    return {
        "Date": rows[0]["Date"],
        "CCTV_ID": rows[0]["CCTV_ID"],
        "First_Seen": _format_seconds(first_seconds),
        "Last_Seen": _format_seconds(last_seconds),
        "Brand": rows[0]["Brand"],
        "Color": rows[0]["Color"],
        "Type": rows[0]["Type"],
    }


def _format_seconds(seconds: int) -> str:
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def _sort_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        row["Date"],
        row["First_Seen"],
        row["CCTV_ID"],
        row["Brand"].casefold(),
        row["Color"].casefold(),
        row["Type"].casefold(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert detection_v2-style CSV logs into a ready site CSV and remove duplicate/nearby rows."
    )
    parser.add_argument("--log1", default=str(DEFAULT_LOG1), help="First detection CSV.")
    parser.add_argument("--log2", default="", help="Optional second detection CSV to merge.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output CSV.")
    parser.add_argument(
        "--time-window-seconds",
        type=int,
        default=DEFAULT_TIME_WINDOW_SECONDS,
        help="Rows with the same camera/brand/color/type within this many seconds are merged.",
    )
    parser.add_argument("--strict", action="store_true", help="Fail if any source rows are skipped.")
    args = parser.parse_args(argv)

    report = convert_detection_logs(
        args.log1,
        args.output,
        log2_path=args.log2 or None,
        time_window_seconds=args.time_window_seconds,
    )
    print(f"input_rows={report.input_rows}")
    print(f"converted_rows={report.converted_rows}")
    print(f"output_rows={report.output_rows}")
    print(f"skipped_rows={report.skipped_rows}")
    print(f"output={report.output.resolve()}")
    if args.strict and report.skipped_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
