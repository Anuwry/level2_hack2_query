import unittest
from pathlib import Path

from cctv_query.engine import CCTVQueryEngine
from cctv_query.llm_normalizer import LLMNormalizationResult
from cctv_query.models import CCTVRecord
from cctv_query.web import (
    handle_batch_query_payload,
    handle_csv_files_payload,
    handle_metadata_payload,
    handle_query_payload,
    handle_sql_to_csv_payload,
    resolve_project_csv_path,
)


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

    def test_handle_query_payload_rejects_event_filter_when_dataset_has_no_event_data(self):
        response = handle_query_payload(
            self.engine,
            {
                "question": "vehicles",
                "date": "12-05-2026",
                "cctv_id": "CCTV01",
                "start_time": "08:00",
                "end_time": "08:30",
                "event": "pass",
            },
        )

        self.assertTrue(response["out_of_range"])
        self.assertIn("event", response["out_of_range_reasons"])
        self.assertEqual(response["query"]["date"], "12-05-2026")
        self.assertEqual(response["query"]["cctv_id"], "CCTV01")
        self.assertEqual(response["query"]["start_time"], "08:00:00")
        self.assertEqual(response["query"]["end_time"], "08:30:00")
        self.assertEqual(response["query"]["event"], "pass")

    def test_handle_query_payload_allows_controls_only_query(self):
        response = handle_query_payload(
            self.engine,
            {
                "question": "",
                "date": "12-05-2026",
                "cctv_id": "CCTV01",
            },
        )

        self.assertEqual(response["count"], 2)
        self.assertEqual(response["query"]["cctv_id"], "CCTV01")

    def test_handle_query_payload_rejects_partial_time_filter(self):
        with self.assertRaises(ValueError):
            handle_query_payload(self.engine, {"question": "vehicles", "start_time": "08:00"})

    def test_handle_query_payload_rejects_invalid_event_filter(self):
        with self.assertRaises(ValueError):
            handle_query_payload(self.engine, {"question": "vehicles", "event": "unknown"})

    def test_handle_metadata_payload_returns_filter_options(self):
        response = handle_metadata_payload(self.engine)

        self.assertEqual(response["dates"], ["12-05-2026"])
        self.assertEqual(response["cctv_ids"], ["CCTV01", "CCTV02"])

    def test_handle_csv_files_payload_lists_loadable_project_csvs(self):
        current = resolve_project_csv_path("cctv_vehicle_log_routed.csv")

        response = handle_csv_files_payload(current)
        routed = next(item for item in response["files"] if item["path"] == "cctv_vehicle_log_routed.csv")

        self.assertEqual(response["active_csv"], "cctv_vehicle_log_routed.csv")
        self.assertTrue(routed["active"])
        self.assertTrue(routed["loadable"])
        self.assertGreater(routed["row_count"], 0)

    def test_resolve_project_csv_path_rejects_outside_project(self):
        with self.assertRaises(ValueError):
            resolve_project_csv_path(str(Path("/tmp/outside.csv")))

    def test_handle_query_payload_marks_out_of_range(self):
        response = handle_query_payload(self.engine, {"question": "วันที่ 14 มีรถผ่านกี่คัน"})

        self.assertTrue(response["out_of_range"])
        self.assertEqual(response["out_of_range_reasons"], ["date"])
        self.assertEqual(response["answer"], "Question Out Of Range")
        self.assertEqual(response["csv_answer"], "Question Out Of Range")

    def test_handle_query_payload_returns_warnings_and_color_options(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "08:00:00", "Toyota", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV02", "09:00:00", "Honda", "Red-White", "Car"),
            ]
        )

        response = handle_query_payload(engine, {"question": "red vehicles"})

        self.assertIn("warnings", response)
        self.assertIn("No date specified; searching all dates.", response["warnings"])
        color_clarification = next(item for item in response["clarifications"] if item["field"] == "color")
        self.assertFalse(color_clarification["required"])
        self.assertEqual(color_clarification["options"][0]["value"], "Red")

    def test_handle_query_payload_returns_required_date_clarification(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "08:00:00", "Toyota", "Red", "Car"),
                CCTVRecord.from_values("12-06-2026", "CCTV01", "08:00:00", "Honda", "Red", "Car"),
            ]
        )

        response = handle_query_payload(engine, {"question": "day 12 red cars"})

        self.assertTrue(response["needs_clarification"])
        self.assertEqual(response["clarifications"][0]["field"], "date")
        self.assertEqual(
            [option["value"] for option in response["clarifications"][0]["options"]],
            ["12-05-2026", "12-06-2026"],
        )

    def test_handle_query_payload_returns_csv_style_answer_for_normal_question(self):
        response = handle_query_payload(
            self.engine,
            {"question": "CCTV01 on 2026-05-12 cars by brand and color", "question_id": "Q_SINGLE"},
        )

        self.assertEqual(response["question_id"], "Q_SINGLE")
        self.assertEqual(response["csv_answer"], "[(Toyota, Red):1]")
        self.assertIn("Q_SINGLE", response["answers_csv"])
        self.assertIn('"[(Toyota, Red):1]"', response["answers_csv"])

    def test_handle_query_payload_returns_answer_options_for_entry_without_exit(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "08:00:00", "Toyota", "Red", "Car", event="entry"),
                CCTVRecord.from_values("12-05-2026", "CCTV02", "08:03:00", "Toyota", "Red", "Car", event="exit"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "09:00:00", "Honda", "White", "Car", event="entry"),
            ]
        )

        response = handle_query_payload(engine, {"question": "day 12 entry vehicles without exit"})

        self.assertEqual(response["count"], 1)
        self.assertEqual(response["csv_answer"], "[entry_without_exit:1]")
        option_ids = [option["id"] for option in response["answer_options"]]
        self.assertIn("entry_without_exit", option_ids)
        self.assertIn("event_breakdown", option_ids)

    def test_handle_query_payload_uses_dot_time_range_for_single_question_csv_text(self):
        response = handle_query_payload(
            self.engine,
            {"question": "Q3, CCTVO1, 8.00.00 - 8.10.00.\nจำนวนรถยนต์แยกตามสี", "question_id": "Q3"},
        )

        self.assertEqual(response["query"]["cctv_id"], "CCTV01")
        self.assertEqual(response["query"]["start_time"], "08:00:00")
        self.assertEqual(response["query"]["end_time"], "08:10:00")
        self.assertEqual(response["csv_answer"], "[Red:1]")

    def test_handle_batch_query_payload_returns_answers_csv(self):
        csv_text = "Question ID,CCTV ID,Time Range,Query\nQ1,CCTVO1,8.00.00 - 8.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี\n"

        response = handle_batch_query_payload(self.engine, {"csv_text": csv_text})

        self.assertEqual(response["answers"][0]["question_id"], "Q1")
        self.assertEqual(response["answers"][0]["csv_answer"], "[(Toyota, Red):1]")
        self.assertIn("Question ID,Answer", response["answers_csv"])
        self.assertIn('"[(Toyota, Red):1]"', response["answers_csv"])

    def test_handle_sql_to_csv_payload_returns_tables(self):
        response = handle_sql_to_csv_payload(
            {
                "sql_text": (
                    "CREATE TABLE vehicles (id INTEGER, brand TEXT, color TEXT);"
                    "INSERT INTO vehicles (id, brand, color) VALUES (1, 'Toyota', 'Red');"
                )
            }
        )

        self.assertEqual(response["selected_table"], "vehicles")
        self.assertEqual(response["tables"][0]["columns"], ["id", "brand", "color"])
        self.assertIn("Toyota", response["tables"][0]["csv"])

    def test_handle_query_payload_auto_detects_multi_question_csv_text(self):
        response = handle_query_payload(
            self.engine,
            {
                "question": (
                    "Q1, CCTVO1, 8.00.00 - 8.10.00,\n"
                    "cars by brand and color\n"
                    "Q2, CCTVO1, 8.00.00 - 8.10.00,\n"
                    "cars by brand\n"
                    "Q3, CCTVO1, 8.00.00 - 8.10.00,\n"
                    "cars by color\n"
                )
            },
        )

        self.assertEqual([row["question_id"] for row in response["answers"]], ["Q1", "Q2", "Q3"])
        self.assertEqual(response["answers"][0]["csv_answer"], "[(Toyota, Red):1]")
        self.assertIn("Q3", response["answers_csv"])

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
