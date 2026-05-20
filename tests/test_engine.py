import unittest

from cctv_query.engine import CCTVQueryEngine
from cctv_query.models import CCTVRecord


def make_records():
    return [
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:06:00", "Toyota", "White", "Car"),
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:09:30", "Honda", "Red", "Car"),
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:14:59", "BMW", "Black", "Car"),
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:16:00", "Yamaha", "Black", "Motorcycle"),
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:20:10", "Honda", "White", "Motorcycle"),
        CCTVRecord.from_values("10-05-2026", "CCTV04", "01:24:50", "Yamaha", "Red", "Motorcycle"),
        CCTVRecord.from_values("10-05-2026", "CCTV10", "00:46:01", "Toyota", "Silver", "Car"),
        CCTVRecord.from_values("10-05-2026", "CCTV10", "00:51:20", "Isuzu", "Black", "Truck"),
        CCTVRecord.from_values("10-05-2026", "CCTV10", "00:54:59", "Honda", "White", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV09", "22:27:13", "Toyota", "Red", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV08", "22:29:56", "Toyota", "Red", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "22:30:56", "Toyota", "Red", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV04", "22:34:20", "Toyota", "Red", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "08:10:00", "Toyota", "Red", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "09:00:00", "Honda", "Red", "Motorcycle"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "10:30:00", "Isuzu", "Red", "Truck"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "11:00:00", "Nissan", "Red-White", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "11:15:00", "MG", "Metallic Green", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV04", "12:00:00", "Mercedes-Benz", "Red", "Bus"),
        CCTVRecord.from_values("12-05-2026", "CCTV07", "12:03:00", "Mercedes-Benz", "Red", "Bus"),
        CCTVRecord.from_values("12-05-2026", "CCTV08", "12:05:00", "Mercedes-Benz", "Red", "Bus"),
        CCTVRecord.from_values("12-05-2026", "CCTV09", "13:00:00", "Mercedes-Benz", "Dark Green", "Bus"),
        CCTVRecord.from_values("12-05-2026", "CCTV08", "13:02:00", "Mercedes-Benz", "Dark Green", "Bus"),
        CCTVRecord.from_values("12-05-2026", "CCTV01", "15:00:00", "Mazda", "Blue", "Car"),
        CCTVRecord.from_values("12-05-2026", "CCTV01", "15:05:00", "Yamaha", "Blue", "Motorcycle"),
    ]


class CCTVQueryEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = CCTVQueryEngine(make_records())

    def test_answers_count_and_brand_color_breakdown(self):
        result = self.engine.ask(
            "กล้อง CCTV04 ช่วง 1:05:00-1:15:00 มีรถวิ่งผ่านกี่คัน ยี่ห้อและสีอะไรบ้าง"
        )

        self.assertEqual(result.count, 3)
        self.assertEqual(result.summary.brand_color_counts[("BMW", "Black")], 1)
        self.assertIn("พบ 3 คัน", result.answer)
        self.assertIn("Toyota White 1 คัน", result.answer)

    def test_filters_specific_vehicle_type(self):
        result = self.engine.ask("กล้อง CCTV04 ช่วง 1:15:00-1:25:00 มีมอเตอร์ไซค์วิ่งผ่านกี่คัน")

        self.assertEqual(result.count, 3)
        self.assertEqual(result.summary.type_counts["Motorcycle"], 3)
        self.assertNotIn("Toyota White", result.answer)

    def test_filters_cctv_time_and_ignores_unsupported_direction_word(self):
        result = self.engine.ask(
            "กล้อง CCTV10 ช่วง 0:45:00-0:55:00 มีรถวิ่งออกกี่คัน ยี่ห้อและสีอะไรบ้าง"
        )

        self.assertEqual(result.count, 3)
        self.assertIn("Isuzu Black 1 คัน", result.answer)

    def test_filters_date_and_color(self):
        result = self.engine.ask("วันที่ 12-05-2026 กล้อง CCTV07 มีรถสีแดงผ่านกี่คัน")

        self.assertEqual(result.count, 5)
        self.assertEqual(result.summary.color_counts["Red"], 5)
        self.assertIn("วันที่ 12-05-2026", result.answer)

    def test_day_only_date_and_brand_count_unique_routed_vehicle(self):
        result = self.engine.ask("วันที่ 12 มีรถ Toyota ผ่านกี่คัน")

        self.assertEqual(result.count, 2)
        self.assertEqual(result.event_count, 5)
        self.assertEqual(result.spec.date, "12-05-2026")
        self.assertEqual(result.summary.brand_color_counts[("Toyota", "Red")], 2)

    def test_route_answer_lists_camera_sequence_for_selected_vehicle(self):
        result = self.engine.ask("วันที่ 12 รถ Toyota ช่วง 22:00-23:00 เดินทางไปทางไหนบ้าง")

        self.assertEqual(result.count, 1)
        self.assertEqual(result.event_count, 4)
        self.assertEqual(result.routes[0].path, ["CCTV09", "CCTV08", "CCTV07", "CCTV04"])
        self.assertIn("CCTV09 -> CCTV08 -> CCTV07 -> CCTV04", result.answer)
        self.assertIn("22:27:13-22:34:20", result.answer)

    def test_spaced_date_and_brand_alias_do_not_fall_back_to_all_records(self):
        result = self.engine.ask("12 05 2026 มี Benz เข้าออกกี่คันแล้วมีสีอะไรบ้าง")

        self.assertEqual(result.spec.date, "12-05-2026")
        self.assertEqual(result.spec.brand, "Mercedes-Benz")
        self.assertEqual(result.count, 2)
        self.assertEqual(result.event_count, 5)
        self.assertEqual(result.summary.brand_counts, {"Mercedes-Benz": 2})
        self.assertEqual(result.summary.color_counts["Red"], 1)
        self.assertEqual(result.summary.color_counts["Dark Green"], 1)
        self.assertIn("Mercedes-Benz Red 1 คัน", result.answer)
        self.assertIn("Mercedes-Benz Dark Green 1 คัน", result.answer)
        self.assertNotIn("Toyota", result.answer)

    def test_ordinal_camera_and_private_car_type_filter_to_cctv01_cars(self):
        result = self.engine.ask("วันที่ 12 กล้องตัวที่ 1 มีรถส่วนบุคคลผ่านกี่คัน")

        self.assertEqual(result.spec.date, "12-05-2026")
        self.assertEqual(result.spec.cctv_id, "CCTV01")
        self.assertEqual(result.spec.vehicle_type, "Car")
        self.assertEqual(result.count, 1)
        self.assertEqual(result.summary.type_counts["Car"], 1)
        self.assertNotIn("Motorcycle", result.summary.type_counts)

    def test_unique_vehicle_list_request_lists_vehicles_not_only_count(self):
        result = self.engine.ask("วันที่ 12 รถคันไหนวิ่งผ่านบ้างไม่ซ้ำกัน")

        self.assertTrue(result.spec.wants_vehicle_list)
        self.assertGreater(result.count, 1)
        self.assertIn("รายการรถไม่ซ้ำ:", result.answer)
        self.assertIn("Toyota Red Car", result.answer)
        self.assertIn("CCTV09 -> CCTV08 -> CCTV07 -> CCTV04", result.answer)
        self.assertIn("Mazda Blue Car", result.answer)

    def test_color_filter_is_exact_not_partial(self):
        red_result = self.engine.ask("CCTV07 on 2026-05-12 red vehicles")
        green_result = self.engine.ask("CCTV07 on 2026-05-12 green vehicles")

        self.assertEqual(red_result.count, 5)
        self.assertNotIn("Red-White", red_result.summary.color_counts)
        self.assertEqual(green_result.count, 0)
        self.assertNotIn("Metallic Green", green_result.summary.color_counts)

    def test_returns_clear_no_match_answer(self):
        result = self.engine.ask("CCTV04 between 05:00:00 and 05:10:00 red trucks")

        self.assertEqual(result.count, 0)
        self.assertIn("No matching records", result.answer)


if __name__ == "__main__":
    unittest.main()
