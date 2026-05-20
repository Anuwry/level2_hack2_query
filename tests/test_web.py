import unittest

from cctv_query.engine import CCTVQueryEngine
from cctv_query.models import CCTVRecord
from cctv_query.web import handle_query_payload


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "08:00:00", "Toyota", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV02", "08:03:00", "Toyota", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "09:00:00", "Yamaha", "Black", "Motorcycle"),
            ]
        )

    def test_handle_query_payload_returns_structured_answer(self):
        response = handle_query_payload(
            self.engine,
            {"question": "วันที่ 12 กล้องตัวที่ 1 มีรถส่วนบุคคลผ่านกี่คัน"},
        )

        self.assertEqual(response["count"], 1)
        self.assertEqual(response["query"]["cctv_id"], "CCTV01")
        self.assertEqual(response["query"]["vehicle_type"], "Car")
        self.assertIn("answer", response)

    def test_handle_query_payload_rejects_empty_question(self):
        with self.assertRaises(ValueError):
            handle_query_payload(self.engine, {"question": "   "})


if __name__ == "__main__":
    unittest.main()
