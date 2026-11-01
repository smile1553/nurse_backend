import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from result_uploader import ResultUploader

class Response:
    def __init__(self, status, body=None):
        self.status_code=status
        self.body=body or {"ok": True}
    def json(self):
        return self.body

class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.path=self.root/"2026-10-28"/"test.json"
        self.path.parent.mkdir()
        self.record=dict(studentId="410123456", sessionId="session1", resultId="550e8400-e29b-41d4-a716-446655440000",
            loginTime="2026-10-28T10:00:00+08:00",correctCount=6,questionScore=60,toneScore=18,totalScore=78,utterances=[])
        self.path.write_text(json.dumps(self.record),encoding="utf-8")
    def tearDown(self): self.tmp.cleanup()
    def uploader(self,send):
        with patch.dict("os.environ", {"RESULT_UPLOAD_INCLUDE_EXISTING": "1"}):
            return ResultUploader(self.root,"https://example.test/api/results","test",send)
    def test_restart_recovers_and_duplicate_discovery_does_not_resend(self):
        calls=[]
        u=self.uploader(lambda payload: calls.append(payload) or Response(200))
        u.discover()
        self.uploader(u._send).tick()
        u.discover()
        u.tick()
        self.assertEqual(len(calls),1)
        self.assertEqual(u.status()["counts"],{"uploaded":1})
    def test_network_failure_is_durable_and_retries(self):
        def fail(payload): raise OSError("offline")
        u=self.uploader(fail);u.discover();u.tick()
        self.assertEqual(u.status()["counts"],{"pending":1})
        with u._connect() as db: db.execute("UPDATE uploads SET next_attempt=0")
        self.uploader(lambda payload: Response(200)).tick()
        self.assertEqual(u.status()["counts"],{"uploaded":1})
    def test_conflict_blocks_without_losing_payload(self):
        u=self.uploader(lambda payload:Response(409));u.discover();u.tick();u.discover()
        self.assertEqual(u.status()["counts"],{"blocked":1})
        self.assertEqual(u.status()["issues"][0]["last_error"],"HTTP 409")
    def test_success_without_ack_is_not_accepted(self):
        u=self.uploader(lambda payload:Response(200,{"ok":False}));u.discover();u.tick()
        self.assertEqual(u.status()["counts"],{"pending":1})
    def test_changed_local_report_keeps_first_upload_snapshot(self):
        u=None
        def send(payload):
            self.record["toneScore"]=17
            self.record["totalScore"]=77
            self.path.write_text(json.dumps(self.record),encoding="utf-8")
            u.enqueue_file(self.path)
            return Response(200)
        u=self.uploader(send);u.discover();u.tick()
        self.assertEqual(u.status()["counts"],{"uploaded":1})
        with u._connect() as db:
            saved = json.loads(db.execute("SELECT payload FROM uploads").fetchone()[0])
        self.assertEqual(saved["toneScore"],18)

    def test_existing_files_skipped_by_default_but_new_files_recovered_after_restart(self):
        import os
        os.utime(self.path, (1, 1))
        with patch.dict("os.environ", {"RESULT_UPLOAD_INCLUDE_EXISTING": "0"}):
            u = ResultUploader(self.root, "https://example.test/api/results", "test")
            u.discover()
            self.assertEqual(u.status()["counts"], {})
            # A newly written report missed by enqueue survives a backend restart.
            self.path.write_text(json.dumps(self.record), encoding="utf-8")
            restarted = ResultUploader(self.root, "https://example.test/api/results", "test", lambda _: Response(200))
            restarted.discover()
            restarted.tick()
            self.assertEqual(restarted.status()["counts"], {"uploaded": 1})
if __name__=="__main__":unittest.main()

