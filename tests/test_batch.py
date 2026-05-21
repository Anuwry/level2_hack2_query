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

        self.assertEqual(answers["Q1"], "[(Hino, Gray):1, (Honda, Gray):1, (Toyota, Gray):1, (Toyota, Red):1]")
        self.assertEqual(answers["Q2"], "[Toyota:2, Hino:1, Honda:1]")
        self.assertEqual(answers["Q3"], "[Gray:3, Red:1]")

        parsed_csv = list(csv.DictReader(io.StringIO(response["answers_csv"])))
        self.assertEqual(parsed_csv[0]["Question ID"], "Q1")
        self.assertEqual(parsed_csv[0]["Answer"], answers["Q1"])

    def test_parse_space_separated_question_answer_example(self):
        rows = parse_batch_question_csv(_sample_space_table())

        self.assertEqual([row.question_id for row in rows], ["Q1", "Q2", "Q3", "Q4"])
        self.assertEqual(rows[0].cctv_id, "CCTV01")
        self.assertEqual(rows[0].time_range, "0.01.00 - 0.10.00")
        self.assertEqual(rows[0].query, "จำนวนรถยนต์แยกตามยี่ห้อและสี")
        self.assertEqual(rows[3].query, "จำนวนรถยนต์")

    def test_answer_batch_questions_outputs_plain_count_for_count_only_question(self):
        response = answer_batch_questions(self.engine, _sample_space_table())
        answers = {row["question_id"]: row["csv_answer"] for row in response["answers"]}

        self.assertEqual(answers["Q1"], "[(Hino, Gray):1, (Honda, Gray):1, (Toyota, Gray):1, (Toyota, Red):1]")
        self.assertEqual(answers["Q2"], "[Toyota:2, Hino:1, Honda:1]")
        self.assertEqual(answers["Q3"], "[Gray:3, Red:1]")
        self.assertEqual(answers["Q4"], "4")

    def test_answer_batch_questions_outputs_vehicle_type_breakdown(self):
        response = answer_batch_questions(
            self.engine,
            'Q28,CCTV01,00:00:00 - 23:59:59,"อยากรู้ว่ากล้อง CCTV01 ตรวจเจอรถประเภทไหนบ้าง และแต่ละประเภทมีจำนวนเท่าไหร่"\n',
        )

        self.assertEqual(response["answers"][0]["csv_answer"], "[Car:3, Truck:1]")
        self.assertIn('Q28,"[Car:3, Truck:1]"', response["answers_csv"])

    def test_answer_batch_questions_outputs_origin_breakdown(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "BYD", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "BMW", "Black", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:04:30", "Kia", "Silver", "Car"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,vehicles by country\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[Chinese:1, European:1, Japanese:1, Korean:1]")

    def test_answer_batch_questions_outputs_origin_brand_breakdown(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "Honda", "Red", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "BYD", "Black", "Car"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,vehicles by country and brand\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[(Chinese, BYD):1, (Japanese, Honda):1, (Japanese, Toyota):1]")

    def test_answer_batch_questions_outputs_metallic_color_counts(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Bronze", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "BYD", "Silver", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "BMW", "Gold", "Car"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:04:30", "Kia", "Red", "Car"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,metallic vehicles by color\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[Bronze:1, Gold:1, Silver:1]")

    def test_answer_batch_questions_outputs_event_breakdown(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car", event="entry"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "Toyota", "Gray", "Car", event="pass"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "Toyota", "Gray", "Car", event="exit"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,vehicles by event\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[entry:1, exit:1, pass:1]")

    def test_answer_batch_questions_outputs_bare_entry_breakdown(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car", event="entry"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "Toyota", "Gray", "Car", event="exit"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,entry vehicles\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[entry:1]")

    def test_answer_batch_questions_outputs_entry_without_exit_answer(self):
        engine = CCTVQueryEngine(
            [
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:01:30", "Toyota", "Gray", "Car", event="entry"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:02:30", "Toyota", "Gray", "Car", event="exit"),
                CCTVRecord.from_values("12-05-2026", "CCTV01", "00:03:30", "Honda", "White", "Car", event="entry"),
            ]
        )

        response = answer_batch_questions(engine, "Q1,CCTV01,00:00:00 - 00:10:00,entry without exit\n")

        self.assertEqual(response["answers"][0]["csv_answer"], "[entry_without_exit:1]")
        self.assertTrue(response["answers"][0]["answer_options"])

    def test_parse_project_multiline_question_format(self):
        rows = parse_batch_question_csv(
            "Question ID,CCTV ID,Time Range,Query\n"
            "Q3,CCTVO1,0.01.00 - 0.10.00.\n"
            "จำนวนรถยนต์แยกตามสี\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].question_id, "Q3")
        self.assertEqual(rows[0].query, "จำนวนรถยนต์แยกตามสี")
        self.assertEqual(build_batch_question(rows[0]), "CCTV01 from 00:01:00 to 00:10:00 จำนวนรถยนต์แยกตามสี")

    def test_parse_headerless_project_multiline_question_format(self):
        rows = parse_batch_question_csv(
            "Q1, CCTVO1, 5.00.00 - 10.00.00,\n"
            "cars by brand and color\n"
            "Q2, CCTVO1, 5.00.00 - 10.00.00,\n"
            "cars by brand\n"
            "Q3, CCTVO1, 5.00.00 - 10.00.00,\n"
            "cars by color\n"
        )

        self.assertEqual([row.question_id for row in rows], ["Q1", "Q2", "Q3"])
        self.assertEqual(rows[0].cctv_id, "CCTVO1")
        self.assertEqual(rows[0].time_range, "5.00.00 - 10.00.00")
        self.assertEqual(rows[2].query, "cars by color")
        self.assertEqual(build_batch_question(rows[0]), "CCTV01 from 05:00:00 to 10:00:00 cars by brand and color")

    def test_answer_headerless_project_multiline_questions(self):
        response = answer_batch_questions(
            self.engine,
            "Q1, CCTVO1, 0.01.00 - 0.10.00,\n"
            "cars by brand and color\n"
            "Q2, CCTVO1, 0.01.00 - 0.10.00,\n"
            "cars by brand\n"
            "Q3, CCTVO1, 0.01.00 - 0.10.00,\n"
            "cars by color\n",
        )

        answers = {row["question_id"]: row["csv_answer"] for row in response["answers"]}
        self.assertEqual(len(response["answers"]), 3)
        self.assertEqual(answers["Q1"], "[(Honda, Gray):1, (Toyota, Gray):1, (Toyota, Red):1]")
        self.assertEqual(answers["Q2"], "[Toyota:2, Honda:1]")
        self.assertEqual(answers["Q3"], "[Gray:2, Red:1]")

    def test_pending_multiline_query_can_contain_commas(self):
        rows = parse_batch_question_csv(
            "Q1, CCTVO1, 0.01.00 - 0.10.00,\n"
            "count cars, by color\n"
            "Q2, CCTVO1, 0.01.00 - 0.10.00,\n"
            "count cars by brand\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].query, "count cars, by color")
        self.assertEqual(rows[1].query, "count cars by brand")

    def test_unquoted_query_commas_are_kept_in_last_column(self):
        rows = parse_batch_question_csv(
            "Question ID,CCTV ID,Time Range,Query\n"
            "Q1,CCTVO1,0.01.00 - 0.10.00,count cars, by color, please\n"
        )

        self.assertEqual(rows[0].query, "count cars, by color, please")


def _sample_csv() -> str:
    return """Question ID,CCTV ID,Time Range,Query
Q1,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อ
Q3,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามสี
"""


def _sample_space_table() -> str:
    return """Question ID CCTV ID Time Range Query
Q1 CCTV01 0.01.00 - 0.10.00 จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2 CCTV01 0.01.00 - 0.10.00 จำนวนรถยนต์แยกตามยี่ห้อ
Q3 CCTV01 0.01.00 - 0.10.00 จำนวนรถยนต์แยกตามสี
Q4 CCTV01 0.01.00 - 0.10.00 จำนวนรถยนต์

Question ID    Answer
Q1    [(Toyota, Gray):1, ...]
Q2    [Toyota:2, ...]
Q3    [Gray:5, ...]
Q4    8
"""


if __name__ == "__main__":
    unittest.main()
