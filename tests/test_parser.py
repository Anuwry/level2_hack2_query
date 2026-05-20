import unittest

from cctv_query.parser import parse_question


class ParseQuestionTests(unittest.TestCase):
    def test_parse_thai_camera_time_range_and_brand_color_request(self):
        spec = parse_question(
            "กล้อง CCTV04 ช่วง 1:05:00-1:15:00 มีรถวิ่งผ่านกี่คัน ยี่ห้อและสีอะไรบ้าง",
            known_brands=["Toyota", "Honda", "BMW"],
        )

        self.assertEqual(spec.cctv_id, "CCTV04")
        self.assertEqual(spec.start_time, "01:05:00")
        self.assertEqual(spec.end_time, "01:15:00")
        self.assertIsNone(spec.vehicle_type)
        self.assertTrue(spec.wants_brand_color_breakdown)
        self.assertEqual(spec.language, "th")

    def test_parse_specific_motorcycle_type(self):
        spec = parse_question("กล้อง CCTV04 ช่วง 1:15:00-1:25:00 มีมอเตอร์ไซค์วิ่งผ่านกี่คัน")

        self.assertEqual(spec.cctv_id, "CCTV04")
        self.assertEqual(spec.vehicle_type, "Motorcycle")
        self.assertFalse(spec.wants_brand_color_breakdown)

    def test_parse_thai_date_and_color_filter(self):
        spec = parse_question("วันที่ 12-05-2026 กล้อง CCTV07 มีรถสีแดงผ่านกี่คัน")

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.cctv_id, "CCTV07")
        self.assertEqual(spec.color, "Red")

    def test_parse_english_question(self):
        spec = parse_question(
            "How many red motorcycles passed CCTV7 on 2026-05-12 between 08:00 and 10:00?"
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.cctv_id, "CCTV07")
        self.assertEqual(spec.start_time, "08:00:00")
        self.assertEqual(spec.end_time, "10:00:00")
        self.assertEqual(spec.color, "Red")
        self.assertEqual(spec.vehicle_type, "Motorcycle")
        self.assertEqual(spec.language, "en")

    def test_parse_brand_from_known_csv_values(self):
        spec = parse_question(
            "CCTV04 between 01:00:00 and 02:00:00 Toyota cars",
            known_brands=["Toyota", "Honda"],
        )

        self.assertEqual(spec.brand, "Toyota")
        self.assertEqual(spec.vehicle_type, "Car")

    def test_parse_day_only_date_from_known_dates(self):
        spec = parse_question(
            "วันที่ 12 มีรถ Toyota ผ่านกี่คัน",
            known_brands=["Toyota"],
            known_dates=["10-05-2026", "11-05-2026", "12-05-2026"],
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.brand, "Toyota")

    def test_day_only_date_outside_known_dates_is_marked_out_of_range(self):
        spec = parse_question(
            "วันที่ 14 มีรถผ่านกี่คัน",
            known_dates=["10-05-2026", "12-05-2026", "13-05-2026"],
        )

        self.assertIsNone(spec.date)
        self.assertEqual(spec.out_of_range_fields, ("date",))

    def test_parse_route_request(self):
        spec = parse_question(
            "วันที่ 12 รถ Toyota เดินทางไปทางไหนบ้าง",
            known_brands=["Toyota"],
            known_dates=["12-05-2026"],
        )

        self.assertTrue(spec.wants_route)
        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.brand, "Toyota")

    def test_parse_spaced_date_and_brand_alias(self):
        spec = parse_question(
            "12 05 2026 มี Benz เข้าออกกี่คันแล้วมีสีอะไรบ้าง",
            known_brands=["Mercedes-Benz", "Toyota"],
            known_dates=["12-05-2026"],
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.brand, "Mercedes-Benz")
        self.assertTrue(spec.wants_brand_color_breakdown)

    def test_parse_ordinal_camera_and_private_car_type(self):
        spec = parse_question(
            "วันที่ 12 กล้องตัวที่ 1 มีรถส่วนบุคคลผ่านกี่คัน",
            known_dates=["12-05-2026"],
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.cctv_id, "CCTV01")
        self.assertEqual(spec.vehicle_type, "Car")

    def test_parse_cctv_id_with_letter_o_typo(self):
        spec = parse_question("CCTVO1 from 00:01:00 to 00:10:00 cars")

        self.assertEqual(spec.cctv_id, "CCTV01")

    def test_parse_unique_vehicle_list_request(self):
        spec = parse_question(
            "วันที่ 12 รถคันไหนวิ่งผ่านบ้างไม่ซ้ำกัน",
            known_dates=["12-05-2026"],
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertTrue(spec.wants_vehicle_list)
        self.assertTrue(spec.wants_distinct_vehicle_count)
        self.assertFalse(spec.wants_route)

    def test_parse_distinct_vehicle_count_request(self):
        spec = parse_question(
            "กระผมอยากทราบว่ารถ truck ในวันที่ 12 นี่มีกี่คันครับ รถไม่ซ้ำ",
            known_dates=["12-05-2026"],
        )

        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.vehicle_type, "Truck")
        self.assertTrue(spec.wants_distinct_vehicle_count)

    def test_parse_multiple_exact_colors(self):
        spec = parse_question(
            "มีรถสี Red and Red-White กี่คัน",
            known_colors=["Red", "Red-White", "White"],
        )

        self.assertEqual(spec.colors, ("Red", "Red-White"))
        self.assertEqual(spec.color, "Red")


if __name__ == "__main__":
    unittest.main()
