import json
import unittest

from cctv_query.llm_normalizer import (
    DEFAULT_LLM_MODEL,
    LLMHTTPError,
    normalize_question_if_enabled,
)
from cctv_query.parser import parse_question


class LLMNormalizerTests(unittest.TestCase):
    def test_disabled_normalizer_returns_original_question(self):
        result = normalize_question_if_enabled("cam one red benz", enabled=False)

        self.assertFalse(result.used)
        self.assertEqual(result.normalized_question, "cam one red benz")
        self.assertIsNone(result.error)

    def test_tool_call_response_builds_canonical_question_for_parser(self):
        captured = {}

        def fake_transport(url, body, headers, timeout_seconds):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            captured["timeout_seconds"] = timeout_seconds
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "normalize_cctv_query",
                                        "arguments": json.dumps(
                                            {
                                                "date": "12 05 2026",
                                                "cctv_id": "1",
                                                "start_time": "8:00",
                                                "end_time": "9:00:00",
                                                "brand": "Mercedes-Benz",
                                                "colors": ["Red", "Red-White"],
                                                "vehicle_type": "Car",
                                                "wants_brand_color_breakdown": True,
                                                "wants_route": True,
                                                "wants_vehicle_list": True,
                                                "wants_distinct_vehicle_count": True,
                                            }
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

        result = normalize_question_if_enabled(
            "กล้องหนึ่ง เบนซ์ แดงกับแดงขาว รถส่วนตัว route คันไหน",
            known_brands=["Mercedes-Benz", "Toyota"],
            known_colors=["Red", "Red-White", "White"],
            known_dates=["12-05-2026"],
            enabled=True,
            base_url="http://127.0.0.1:8080/v1",
            model=DEFAULT_LLM_MODEL,
            mode="tools",
            transport=fake_transport,
        )

        self.assertTrue(result.used)
        self.assertEqual(result.model, "Qwen/Qwen3.5-4B")
        self.assertEqual(captured["url"], "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "Qwen/Qwen3.5-4B")
        self.assertIn("tools", captured["body"])

        spec = parse_question(
            result.normalized_question,
            known_brands=["Mercedes-Benz", "Toyota"],
            known_colors=["Red", "Red-White", "White"],
            known_dates=["12-05-2026"],
        )
        self.assertEqual(spec.date, "12-05-2026")
        self.assertEqual(spec.cctv_id, "CCTV01")
        self.assertEqual(spec.start_time, "08:00:00")
        self.assertEqual(spec.end_time, "09:00:00")
        self.assertEqual(spec.brand, "Mercedes-Benz")
        self.assertEqual(spec.colors, ("Red", "Red-White"))
        self.assertEqual(spec.vehicle_type, "Car")
        self.assertTrue(spec.wants_brand_color_breakdown)
        self.assertTrue(spec.wants_route)
        self.assertTrue(spec.wants_vehicle_list)
        self.assertTrue(spec.wants_distinct_vehicle_count)

    def test_json_mode_content_response_is_supported(self):
        def fake_transport(url, body, headers, timeout_seconds):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"date":"12-05-2026","brand":"Toyota","colors":["Red"]}'
                                "\n```"
                            )
                        }
                    }
                ]
            }

        result = normalize_question_if_enabled(
            "toyota red date twelve",
            known_brands=["Toyota"],
            known_colors=["Red"],
            known_dates=["12-05-2026"],
            enabled=True,
            mode="json",
            transport=fake_transport,
        )

        self.assertTrue(result.used)
        self.assertIn("date 12-05-2026", result.normalized_question)
        self.assertIn("brand Toyota", result.normalized_question)
        self.assertIn("color Red", result.normalized_question)

    def test_auto_mode_retries_json_when_tools_are_rejected(self):
        calls = []

        def fake_transport(url, body, headers, timeout_seconds):
            calls.append(body)
            if "tools" in body:
                raise LLMHTTPError(400, "tools unsupported")
            return {"choices": [{"message": {"content": '{"vehicle_type":"Motorcycle"}'}}]}

        result = normalize_question_if_enabled(
            "two wheel",
            enabled=True,
            mode="auto",
            transport=fake_transport,
        )

        self.assertTrue(result.used)
        self.assertEqual(len(calls), 2)
        self.assertIn("tools", calls[0])
        self.assertNotIn("tools", calls[1])
        self.assertIn("type Motorcycle", result.normalized_question)

    def test_transport_error_falls_back_to_original_question(self):
        def failing_transport(url, body, headers, timeout_seconds):
            raise RuntimeError("offline")

        result = normalize_question_if_enabled(
            "still answer with parser",
            enabled=True,
            transport=failing_transport,
        )

        self.assertFalse(result.used)
        self.assertEqual(result.normalized_question, "still answer with parser")
        self.assertIn("offline", result.error)


if __name__ == "__main__":
    unittest.main()
