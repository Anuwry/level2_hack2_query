import unittest

from cctv_query.engine import CCTVQueryEngine
from cctv_query.llm_normalizer import LLMNormalizationResult
from cctv_query.models import CCTVRecord
from cctv_query.web import handle_batch_query_payload, handle_query_payload


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
        self.assertIn("llm_normalization", response)
        self.assertIn("csv_answer", response)
        self.assertIn("answers_csv", response)
        self.assertEqual(response["question_id"], "Q1")

    def test_handle_query_payload_rejects_empty_question(self):
        with self.assertRaises(ValueError):
            handle_query_payload(self.engine, {"question": "   "})

    def test_handle_query_payload_marks_out_of_range(self):
        response = handle_query_payload(self.engine, {"question": "วันที่ 14 มีรถผ่านกี่คัน"})

        self.assertTrue(response["out_of_range"])
        self.assertEqual(response["out_of_range_reasons"], ["date"])
        self.assertEqual(response["answer"], "Question Out Of Range")
        self.assertEqual(response["csv_answer"], "Question Out Of Range")

    def test_handle_query_payload_returns_csv_style_answer_for_normal_question(self):
        response = handle_query_payload(
            self.engine,
            {"question": "CCTV01 on 2026-05-12 cars by brand and color", "question_id": "Q_SINGLE"},
        )

        self.assertEqual(response["question_id"], "Q_SINGLE")
        self.assertEqual(response["csv_answer"], "[(Toyota, Red):1]")
        self.assertIn("Q_SINGLE", response["answers_csv"])
        self.assertIn('"[(Toyota, Red):1]"', response["answers_csv"])

    def test_handle_batch_query_payload_returns_answers_csv(self):
        csv_text = "Question ID,CCTV ID,Time Range,Query\nQ1,CCTVO1,8.00.00 - 8.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี\n"

        response = handle_batch_query_payload(self.engine, {"csv_text": csv_text})

        self.assertEqual(response["answers"][0]["question_id"], "Q1")
        self.assertEqual(response["answers"][0]["csv_answer"], "[(Toyota, Red):1]")
        self.assertIn("Question ID,Answer", response["answers_csv"])
        self.assertIn('"[(Toyota, Red):1]"', response["answers_csv"])

    def test_handle_query_payload_can_use_llm_normalizer(self):
        def fake_normalizer(question, engine):
            return LLMNormalizationResult(
                original_question=question,
                normalized_question="date 12-05-2026 CCTV01 type Car",
                enabled=True,
                used=True,
                model="Qwen/Qwen3.5-4B",
                base_url="http://127.0.0.1:8080/v1",
                mode="tools",
            )

        response = handle_query_payload(
            self.engine,
            {"question": "กล้องหนึ่ง รถส่วนตัว วันที่สิบสอง"},
            normalizer=fake_normalizer,
        )

        self.assertEqual(response["count"], 1)
        self.assertEqual(response["original_question"], "กล้องหนึ่ง รถส่วนตัว วันที่สิบสอง")
        self.assertEqual(response["normalized_question"], "date 12-05-2026 CCTV01 type Car")
        self.assertTrue(response["llm_normalization"]["used"])


if __name__ == "__main__":
    unittest.main()
