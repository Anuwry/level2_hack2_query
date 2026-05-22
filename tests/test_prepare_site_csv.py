import csv
import tempfile
import unittest
from pathlib import Path

from cctv_query.csv_store import load_records
from cctv_query.engine import CCTVQueryEngine
from cctv_query.prepare_site_csv import convert_csv


class PrepareSiteCsvTests(unittest.TestCase):
    def test_converts_required_output_tracks_to_site_contract(self):
        source = """Date,CCTV_ID,Timestamp,Track_ID,Brand,Color,Type,first_seen_iso,last_seen_iso
22-05-2026,CCTV01,04:59:53,1,Geely,Gray,Car,2026-05-22T04:59:53.875186,2026-05-22T05:00:01.750371
22-05-2026,CCTV01,04:59:54,1,Toyota,Gray,Car,2026-05-22T04:59:53.875186,2026-05-22T05:00:01.750371
22-05-2026,CCTV01,04:59:55,1,Toyota,Gray,Car,2026-05-22T04:59:53.875186,2026-05-22T05:00:01.750371
22-05-2026,CCTV02,05:00:40,27,Unknown,Gray,Motorbike,2026-05-22T05:00:37.857355,2026-05-22T05:00:40.234770
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "all_required_output.csv"
            output_path = Path(tmpdir) / "ready.csv"
            input_path.write_text(source, encoding="utf-8")

            report = convert_csv(input_path, output_path)

            with output_path.open(encoding="utf-8") as output_file:
                rows = list(csv.DictReader(output_file))
            records = load_records(output_path)
            result = CCTVQueryEngine(records).ask("date 22-05-2026 type Car")
            event_result = CCTVQueryEngine(records).ask("date 22-05-2026 event pass vehicles")

        self.assertEqual(report.input_rows, 4)
        self.assertEqual(report.output_rows, 2)
        self.assertEqual(report.skipped_rows, 0)
        self.assertEqual(list(rows[0].keys()), ["Date", "CCTV_ID", "First_Seen", "Last_Seen", "Brand", "Color", "Type"])
        self.assertEqual(rows[0]["Brand"], "Toyota")
        self.assertEqual(rows[1]["Brand"], "Motorcycle")
        self.assertEqual(rows[1]["Type"], "Motorcycle")
        self.assertEqual(records[0].timestamp, "04:59:53")
        self.assertEqual(records[0].last_seen, "05:00:01")
        self.assertEqual(result.count, 1)
        self.assertTrue(event_result.out_of_range)
        self.assertIn("event", event_result.out_of_range_reasons)

    def test_accepts_detection_style_aliases_and_skips_unusable_rows(self):
        source = """timestamp,camera_id,vehicle_type,car_brand,car_color
2026-05-21T16:54:10.796,cam1,car,Toyota,Bronze Silver
not-a-time,cam2,truck,Isuzu,White
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "detections.csv"
            output_path = Path(tmpdir) / "ready.csv"
            input_path.write_text(source, encoding="utf-8")

            report = convert_csv(input_path, output_path)

            with output_path.open(encoding="utf-8") as output_file:
                rows = list(csv.DictReader(output_file))
            records = load_records(output_path)

        self.assertEqual(report.input_rows, 2)
        self.assertEqual(report.output_rows, 1)
        self.assertEqual(report.skipped_rows, 1)
        self.assertEqual(rows[0]["Date"], "21-05-2026")
        self.assertEqual(rows[0]["CCTV_ID"], "CCTV01")
        self.assertEqual(rows[0]["First_Seen"], "16:54:10")
        self.assertEqual(rows[0]["Last_Seen"], "16:54:10")
        self.assertEqual(rows[0]["Brand"], "Toyota")
        self.assertEqual(rows[0]["Color"], "Bronze Silver")
        self.assertEqual(rows[0]["Type"], "Car")
        self.assertEqual(records[0].cctv_id, "CCTV01")

    def test_uses_regular_camera_id_normalization_without_video_name_mapping(self):
        source = """timestamp,source_uri,vehicle_type,car_brand,car_color
2026-05-21T16:54:10.796,rtsp://172.16.30.8:8554/cctv1,car,Toyota,White
2026-05-21T16:55:10.796,camera02,truck,Isuzu,Gray
2026-05-21T16:56:10.796,pathum.mp4,motorbike,Honda,Black
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "streams.csv"
            output_path = Path(tmpdir) / "ready.csv"
            input_path.write_text(source, encoding="utf-8")

            report = convert_csv(input_path, output_path)

            records = load_records(output_path)

        self.assertEqual(report.output_rows, 2)
        self.assertEqual(report.skipped_rows, 1)
        self.assertEqual([record.cctv_id for record in records], ["CCTV01", "CCTV02"])
        self.assertEqual([record.brand for record in records], ["Toyota", "Hino"])

    def test_maps_vehicle_class_like_brand_values(self):
        source = """Date,CCTV_ID,Timestamp,Track_ID,Brand,Color,Type
22-05-2026,CCTV01,05:00:00,1,Truck,Gray,Car
22-05-2026,CCTV02,05:00:01,2,Motorbike,Black,Car
22-05-2026,CCTV03,05:00:02,3,Motorcycle,White,Car
22-05-2026,CCTV04,05:00:03,4,Honda,Red,Motorbike
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "class_brand.csv"
            output_path = Path(tmpdir) / "ready.csv"
            input_path.write_text(source, encoding="utf-8")

            convert_csv(input_path, output_path)

            records = load_records(output_path)

        self.assertEqual([record.brand for record in records], ["Hino", "Unknown", "Unknown", "Motorcycle"])


if __name__ == "__main__":
    unittest.main()
