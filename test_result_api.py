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


if __name__ == "__main__":
    unittest.main()
