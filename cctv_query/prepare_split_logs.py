from __future__ import annotations

import argparse
import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.prepare_site_csv import OUTPUT_FIELDNAMES, ConversionReport, convert_csv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG1 = PROJECT_ROOT / "log(1).csv"
DEFAULT_LOG2 = PROJECT_ROOT / "log(2).csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "cctv_vehicle_log_split_ready.csv"

LOG1_CAMERA_MAP = {
    "cctv0": "CCTV01",
    "cctv1": "CCTV02",
    "cctv2": "CCTV03",
    "cctv3": "CCTV04",
    "cctv4": "CCTV05",
}
LOG2_CAMERA_MAP = {
    "cctv5": "CCTV01",
    "cctv6": "CCTV02",
    "cctv7": "CCTV03",
    "cctv8": "CCTV04",
    "cctv9": "CCTV05",
}


@dataclass(frozen=True)
class SplitConversionReport:
    output: Path
    log1_report: ConversionReport
    log2_report: ConversionReport

    @property
    def input_rows(self) -> int:
        return self.log1_report.input_rows + self.log2_report.input_rows

    @property
    def output_rows(self) -> int:
        return self.log1_report.output_rows + self.log2_report.output_rows

    @property
    def skipped_rows(self) -> int:
        return self.log1_report.skipped_rows + self.log2_report.skipped_rows


def convert_split_logs(
    log1_path: str | Path = DEFAULT_LOG1,
    log2_path: str | Path = DEFAULT_LOG2,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> SplitConversionReport:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        log1_output = temp_root / "log1_ready.csv"
        log2_output = temp_root / "log2_ready.csv"
        log1_report = convert_csv(log1_path, log1_output, camera_id_map=LOG1_CAMERA_MAP)
        log2_report = convert_csv(log2_path, log2_output, camera_id_map=LOG2_CAMERA_MAP)
        rows = _read_rows(log1_output) + _read_rows(log2_output)

    rows = sorted(rows, key=_sort_key)
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(OUTPUT_FIELDNAMES), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    try:
        load_records(output)
    except Exception as exc:
        raise ValueError(f"Merged CSV is not loadable by the site: {exc}") from exc

    return SplitConversionReport(
        output=output,
        log1_report=log1_report,
        log2_report=log2_report,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert and merge split CCTV log(1)/log(2) CSVs into one ready site CSV.")
    parser.add_argument("--log1", default=str(DEFAULT_LOG1), help="Input CSV for log(1): cctv0-cctv4 -> CCTV01-CCTV05.")
    parser.add_argument("--log2", default=str(DEFAULT_LOG2), help="Input CSV for log(2): cctv5-cctv9 -> CCTV01-CCTV05.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Merged output CSV.")
    parser.add_argument("--strict", action="store_true", help="Fail if any rows are skipped.")
    args = parser.parse_args(argv)

    report = convert_split_logs(args.log1, args.log2, args.output)
    print(f"input_rows={report.input_rows}")
    print(f"output_rows={report.output_rows}")
    print(f"skipped_rows={report.skipped_rows}")
    _print_report("log1", report.log1_report)
    _print_report("log2", report.log2_report)
    print(f"output={report.output.resolve()}")
    if args.strict and report.skipped_rows:
        return 1
    return 0


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


def _print_report(label: str, report: ConversionReport) -> None:
    print(f"{label}_input_rows={report.input_rows}")
    print(f"{label}_output_rows={report.output_rows}")
    print(f"{label}_skipped_rows={report.skipped_rows}")


if __name__ == "__main__":
    raise SystemExit(main())
