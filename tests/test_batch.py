import csv
import io
import unittest

from cctv_query.batch import answer_batch_questions, build_batch_question, parse_batch_question_csv
from cctv_query.engine import CCTVQueryEngine
from cctv_query.models import CCTVRecord


class BatchCsvTests(unittest.TestCase):
    def setUp(self):
        self.engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "Toyota", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "Honda", "Gray", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:04:30", "Hino", "Gray", "Truck"),
                CCTVRecord.from_values("12-05-2026", "CCTV02", "00:05:30", "Toyota", "Gray", "Car"),
            ]
        )

    def test_parse_batch_questions_accepts_cctvo_and_dot_time_range(self):
        rows = parse_batch_question_csv(_sample_csv())

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].question_id, "Q1")
        self.assertEqual(rows[0].cctv_id, "CCTVO1")
        self.assertEqual(build_batch_question(rows[0]), "CCTV01 from 00:01:00 to 00:10:00 จำนวนรถยนต์แยกตามยี่ห้อและสี")

    def test_answer_batch_questions_outputs_project_csv_answers(self):
        response = answer_batch_questions(self.engine, _sample_csv())
        answers = {row["question_id"]: row["csv_answer"] for row in response["answers"]}

        self.assertEqual(answers["Q1"], "[(Honda, Gray):1, (Toyota, Gray):1, (Toyota, Red):1]")
        self.assertEqual(answers["Q2"], "[Toyota:2, Honda:1]")
        self.assertEqual(answers["Q3"], "[Gray:2, Red:1]")

        parsed_csv = list(csv.DictReader(io.StringIO(response["answers_csv"])))
        self.assertEqual(parsed_csv[0]["Question ID"], "Q1")
        self.assertEqual(parsed_csv[0]["Answer"], answers["Q1"])


def _sample_csv() -> str:
    return """Question ID,CCTV ID,Time Range,Query
Q1,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อ
Q3,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามสี
"""


if __name__ == "__main__":
    unittest.main()
