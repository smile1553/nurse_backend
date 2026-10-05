import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx
import server_fusion
from excel_result_service import ExcelResultService
from result_models import StudentResultSubmission, StudentRunStart


class ResultApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_service = server_fusion.student_result_service
        server_fusion.student_result_service = ExcelResultService(
            Path(self.temp_dir.name) / "student_results"
        )

    def tearDown(self):
        server_fusion.student_result_service = self.original_service
        self.temp_dir.cleanup()

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def test_full_api_flow_and_idempotent_retry(self):
        session = self.run_async(server_fusion.create_experiment_session())
        session_id = session["sessionId"]
        result_id = uuid.uuid4()

        started = self.run_async(
            server_fusion.start_student_run(
                StudentRunStart(
                    sessionId=session_id,
                    resultId=result_id,
                    studentId="412345678",
                    loginTime="2026-09-21T10:35:00+08:00",
                )
            )
        )
        self.assertTrue(started["ok"])
        self.assertEqual(started["resultId"], str(result_id))

        payload = StudentResultSubmission(
            studentId="412345678",
            loginTime="2026-09-21T10:35:00+08:00",
            correctCount=7,
            toneScore=18,
        )
        first = self.run_async(
            server_fusion.submit_student_result(session_id, result_id, payload)
        )
        second = self.run_async(
            server_fusion.submit_student_result(session_id, result_id, payload)
        )
        self.assertEqual(first["questionScore"], 70)
        self.assertEqual(first["totalScore"], 88)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

    def test_detailed_question_score_replaces_count_times_ten(self):
        session = self.run_async(server_fusion.create_experiment_session())
        session_id = session["sessionId"]
        result_id = uuid.uuid4()
        payload = StudentResultSubmission(
            studentId="412345678",
            loginTime="2026-09-21T10:35:00+08:00",
            correctCount=6,
            toneScore=18,
            questionScore=68,
        )
        first = self.run_async(
            server_fusion.submit_student_result(session_id, result_id, payload)
        )
        second = self.run_async(
            server_fusion.submit_student_result(session_id, result_id, payload)
        )
        self.assertEqual(first["correctCount"], 6)
        self.assertEqual(first["questionScore"], 68)
        self.assertEqual(first["totalScore"], 86)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["questionScore"], 68)
        self.assertEqual(second["totalScore"], 86)

    def test_question_score_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            StudentResultSubmission(
                studentId="412345678",
                loginTime="2026-09-21T10:35:00+08:00",
                correctCount=6,
                toneScore=18,
                questionScore=81,
            )

    def test_old_session_submission_returns_conflict(self):
        old_session = self.run_async(server_fusion.create_experiment_session())
        self.run_async(server_fusion.create_experiment_session())
        response = self.run_async(
            server_fusion.submit_student_result(
                old_session["sessionId"],
                uuid.uuid4(),
                StudentResultSubmission(
                    studentId="412345678",
                    loginTime="2026-09-21T10:35:00+08:00",
                    correctCount=7,
                    toneScore=18,
                ),
            )
        )
        self.assertEqual(response.status_code, 409)
        body = json.loads(response.body)
        self.assertFalse(body["ok"])

    def test_http_routes_accept_unity_contract_and_validate_timezone(self):
        async def exercise_routes():
            transport = httpx.ASGITransport(app=server_fusion.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                session_response = await client.post("/api/sessions")
                self.assertEqual(session_response.status_code, 201)
                session_id = session_response.json()["sessionId"]
                result_id = str(uuid.uuid4())

                invalid_start = await client.post(
                    "/api/student-runs/start",
                    json={
                        "sessionId": session_id,
                        "resultId": result_id,
                        "studentId": "412345678",
                        "loginTime": "2026-09-21T10:35:00",
                    },
                )
                self.assertEqual(invalid_start.status_code, 422)

                start_response = await client.post(
                    "/api/student-runs/start",
                    json={
                        "sessionId": session_id,
                        "resultId": result_id,
                        "studentId": "412345678",
                        "loginTime": "2026-09-21T10:35:00+08:00",
                    },
                )
                self.assertEqual(start_response.status_code, 200)

                result_response = await client.put(
                    f"/api/sessions/{session_id}/results/{result_id}",
                    json={
                        "studentId": "412345678",
                        "loginTime": "2026-09-21T10:35:00+08:00",
                        "correctCount": 7,
                        "toneScore": 18,
                    },
                )
                self.assertEqual(result_response.status_code, 200)
                self.assertEqual(result_response.json()["totalScore"], 88)

        self.run_async(exercise_routes())

    def test_items_are_accepted_and_reports_are_served(self):
        session = self.run_async(server_fusion.create_experiment_session())
        session_id = session["sessionId"]
        result_id = uuid.uuid4()
        self.assertEqual(server_fusion.get_latest_report_overview().status_code, 404)

        payload = StudentResultSubmission(
            studentId="412345678",
            loginTime="2026-09-21T10:35:00+08:00",
            correctCount=7,
            toneScore=18,
            questionScore=60,
            items=[
                {"id": "quiz_1", "isQuiz": True, "wrongAttempts": 0, "solved": True, "points": 8},
                {"id": "cuff", "isQuiz": False, "wrongAttempts": 1, "solved": True, "points": 4},
            ],
        )
        first = self.run_async(server_fusion.submit_student_result(session_id, result_id, payload))
        self.assertEqual(first["totalScore"], 78)

        # The same result sent again without the details is still the same result.
        retry = StudentResultSubmission(
            studentId="412345678", loginTime="2026-09-21T10:35:00+08:00",
            correctCount=7, toneScore=18, questionScore=60,
        )
        second = self.run_async(server_fusion.submit_student_result(session_id, result_id, retry))
        self.assertTrue(second["duplicate"])

        latest = server_fusion.get_latest_report_overview()
        self.assertEqual(latest.headers["location"], "/reports/2026-09-21/index.html")
        overview = server_fusion.get_report("2026-09-21", "index.html")
        self.assertTrue(Path(overview.path).is_file())
        report = server_fusion.get_report("2026-09-21", f"412345678_{str(result_id)[:8]}.html")
        self.assertIn("選擇壓脈帶", Path(report.path).read_text(encoding="utf-8"))
        self.assertEqual(server_fusion.get_report("2026-09-21", "..%2Fsecret.html").status_code, 404)
        self.assertEqual(server_fusion.get_report("..", "index.html").status_code, 404)

    def test_odd_item_details_never_refuse_a_result(self):
        payload = StudentResultSubmission.model_validate_json(
            '{"studentId":"412345678","loginTime":"2026-09-21T10:35:00+08:00","correctCount":7,"toneScore":18,'
            '"questionScore":60,"items":[{"id":"","points":8},{"id":"quiz_1","points":-3,"extra":1},"x",'
            '{"id":"cuff","wrongAttempts":"two"}]}'
        )
        from result_models import clean_result_items
        self.assertEqual(
            clean_result_items(payload.items),
            [{"id": "quiz_1", "isQuiz": True, "wrongAttempts": 0, "solved": False, "points": 0}],
        )


if __name__ == "__main__":
    unittest.main()
