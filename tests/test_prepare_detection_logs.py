import csv
import tempfile
import unittest
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.prepare_detection_logs import convert_detection_logs


class PrepareDetectionLogsTests(unittest.TestCase):
    def test_merges_detection_logs_and_dedupes_nearby_rows(self):
        log1 = """timestamp,camera_id,vehicle_type,detection_conf,car_brand,brand_conf,car_color,color_score
2026-05-21T16:54:10.796,cam1,car,0.5488,Toyota,0.8309,Bronze Silver,0.4848
2026-05-21T16:54:10.796,cam1,car,0.3979,Toyota,0.8953,Bronze Silver,0.5016
2026-05-21T16:54:12.100,cam1,car,0.2991,Toyota,0.5592,Bronze Silver,0.4753
2026-05-21T16:54:20.000,cam1,car,0.8569,Honda,0.9795,White,0.4375
"""
        log2 = """timestamp,camera_id,vehicle_type,detection_conf,car_brand,brand_conf,car_color,color_score
2026-05-21T16:55:00.000,cam5,motorcycle,0.4824,,,, 
2026-05-21T16:55:01.000,cam5,motorcycle,0.4534,Motorcycle,0.6176,Gray,0.3391
2026-05-21T16:55:10.000,cam5,truck,0.4055,Isuzu,0.6710,Black,0.4607
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log1_path = Path(tmpdir) / "detections_log1.csv"
            log2_path = Path(tmpdir) / "detections_log2.csv"
            output_path = Path(tmpdir) / "ready.csv"
            log1_path.write_text(log1, encoding="utf-8")
            log2_path.write_text(log2, encoding="utf-8")

            report = convert_detection_logs(log1_path, output_path, log2_path=log2_path, time_window_seconds=2)

            with output_path.open(encoding="utf-8") as output_file:
                rows = list(csv.DictReader(output_file))
            records = load_records(output_path)

        self.assertEqual(report.input_rows, 7)
        self.assertEqual(report.converted_rows, 7)
        self.assertEqual(report.output_rows, 5)
        self.assertEqual(report.skipped_rows, 0)
        self.assertEqual(list(rows[0].keys()), ["Date", "CCTV_ID", "First_Seen", "Last_Seen", "Brand", "Color", "Type"])
        self.assertEqual(rows[0]["CCTV_ID"], "CCTV01")
        self.assertEqual(rows[0]["First_Seen"], "16:54:10")
        self.assertEqual(rows[0]["Last_Seen"], "16:54:12")
        self.assertEqual(rows[0]["Brand"], "Toyota")
        self.assertEqual(rows[2]["CCTV_ID"], "CCTV05")
        self.assertEqual(rows[2]["Brand"], "Motorcycle")
        self.assertEqual(rows[4]["Brand"], "Hino")
        self.assertEqual([record.event for record in records], ["", "", "", "", ""])


if __name__ == "__main__":
    unittest.main()
