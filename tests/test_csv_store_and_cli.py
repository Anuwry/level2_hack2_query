import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cctv_query.cli import DEFAULT_CSV, main
from cctv_query.csv_store import load_records


CSV_TEXT = """Date,CCTV_ID,Timestamp,Brand,Color,Type
10-05-2026,CCTV04,01:06:00,Toyota,White,Car
10-05-2026,CCTV04,01:09:30,Honda,Red,Car
10-05-2026,CCTV04,01:16:00,Yamaha,Black,Motorcycle
"""

CSV_EVENT_TEXT = """Date,CCTV_ID,Timestamp,Brand,Color,Type,Event
12-05-2026,CCTV01,08:00:00,Toyota,Red,Car,entry
"""

CSV_TRACK_TEXT = """Date,CCTV_ID,First_Seen,Last_Seen,Brand,Color,Type,Event
12-05-2026,CCTV01,08:00:00,08:00:24,Toyota,Red,Car,entry
"""


class CsvStoreAndCliTests(unittest.TestCase):
    def test_cli_default_csv_uses_routed_log(self):
        self.assertEqual(DEFAULT_CSV.name, "cctv_vehicle_log_routed.csv")

    def test_load_records_normalizes_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "logs.csv"
            path.write_text(CSV_TEXT, encoding="utf-8")

            records = load_records(path)

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].cctv_id, "CCTV04")
        self.assertEqual(records[0].timestamp, "01:06:00")
        self.assertEqual(records[0].last_seen, "01:06:00")
        self.assertEqual(records[0].event, "")
        self.assertFalse(records[0].event_explicit)

    def test_load_records_reads_optional_event_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "logs.csv"
            path.write_text(CSV_EVENT_TEXT, encoding="utf-8")

            records = load_records(path)

        self.assertEqual(records[0].event, "entry")

    def test_load_records_reads_first_and_last_seen_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "logs.csv"
            path.write_text(CSV_TRACK_TEXT, encoding="utf-8")

            records = load_records(path)

        self.assertEqual(records[0].timestamp, "08:00:00")
        self.assertEqual(records[0].last_seen, "08:00:24")

    def test_load_records_rejects_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.csv"
            path.write_text("Date,CCTV_ID\n10-05-2026,CCTV04\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_records(path)

    def test_cli_prints_answer_for_single_question(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "logs.csv"
            path.write_text(CSV_TEXT, encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--csv",
                        str(path),
                        "--question",
                        "CCTV04 between 01:05:00 and 01:10:00 brand and color?",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("Found 2 vehicles", stdout.getvalue())
        self.assertIn("Toyota White 1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
