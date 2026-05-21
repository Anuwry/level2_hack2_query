import csv
import tempfile
import unittest
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.prepare_split_logs import convert_split_logs


class PrepareSplitLogsTests(unittest.TestCase):
    def test_merges_log1_and_log2_with_per_file_camera_mapping(self):
        log1 = """timestamp,source_uri,vehicle_type,car_brand,car_color
2026-05-22T06:00:00,rtsp://172.16.30.8:8554/cctv0,car,Toyota,White
2026-05-22T06:01:00,rtsp://172.16.30.8:8554/cctv4,motorbike,Honda,Gray
"""
        log2 = """timestamp,source_uri,vehicle_type,car_brand,car_color
2026-05-22T06:02:00,rtsp://172.16.30.8:8554/cctv5,truck,Isuzu,Black
2026-05-22T06:03:00,rtsp://172.16.30.8:8554/cctv9,car,Ford,Blue
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log1_path = Path(tmpdir) / "log(1).csv"
            log2_path = Path(tmpdir) / "log(2).csv"
            output_path = Path(tmpdir) / "merged_ready.csv"
            log1_path.write_text(log1, encoding="utf-8")
            log2_path.write_text(log2, encoding="utf-8")

            report = convert_split_logs(log1_path, log2_path, output_path)

            with report.output.open(encoding="utf-8") as output_file:
                rows = list(csv.DictReader(output_file))
            records = load_records(report.output)

        self.assertEqual(report.log1_report.input_rows, 2)
        self.assertEqual(report.log1_report.output_rows, 2)
        self.assertEqual(report.log1_report.skipped_rows, 0)
        self.assertEqual(report.log2_report.input_rows, 2)
        self.assertEqual(report.log2_report.output_rows, 2)
        self.assertEqual(report.log2_report.skipped_rows, 0)
        self.assertEqual(report.input_rows, 4)
        self.assertEqual(report.output_rows, 4)
        self.assertEqual(report.skipped_rows, 0)
        self.assertEqual([row["CCTV_ID"] for row in rows], ["CCTV01", "CCTV05", "CCTV01", "CCTV05"])
        self.assertEqual([record.brand for record in records], ["Toyota", "Motorcycle", "Hino", "Ford"])


if __name__ == "__main__":
    unittest.main()
