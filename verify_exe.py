"""Exercise the actual executable in a disposable deployment (no real records/keys)."""
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from datetime import datetime

import httpx
import soundfile as sf


def verify():
    source = Path(__file__).resolve().parent / "dist" / "NurseBackend"
    with tempfile.TemporaryDirectory(prefix="nurse exe test ") as temporary:
        root = Path(temporary) / "部署 測試"
        root.mkdir()
        shutil.copy2(source / "NurseBackend.exe", root)
        # Directory junctions avoid copying the 1.5 GB model for each verification.
        for name in ("_internal", "models"):
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / name), str(source / name)],
                           check=True, capture_output=True)
        try:
            (root / ".env").write_text("LLM_MODEL=deployment-test-model\nASR_WARMUP_ON_START=0\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(OPENAI_API_KEY="", DEEPGRAM_API_KEY="", RESULT_UPLOAD_URL="",
                       RESULT_UPLOAD_API_KEY="", HF_HUB_OFFLINE="1")
            env.pop("ASR_MODEL_NAME", None)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            executable = str(root / "NurseBackend.exe")
            result = subprocess.run([executable, "--self-test"], cwd=temporary, env=env,
                                    capture_output=True, timeout=180)
            assert result.returncode == 0, result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
            assert str(root) in result.stdout.decode("utf-8"), "exe used incorrect deployment path"
            assert '"llm_model": "deployment-test-model"' in result.stdout.decode("utf-8"), "external .env not loaded"
            print("Packaged imports, external paths, OpenCC and offline Whisper model: OK")
            with (root / "verification.log").open("wb") as log:
                process = subprocess.Popen([executable, "--port", str(port)], cwd=temporary,
                                           env=env, stdout=log, stderr=log)
                try:
                    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                        deadline = time.monotonic() + 90
                        while True:
                            try:
                                response = client.get("/last")
                                if response.status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            if process.poll() is not None or time.monotonic() > deadline:
                                raise AssertionError((root / "verification.log").read_text(encoding="utf-8", errors="replace"))
                            time.sleep(0.3)
                        session = client.post("/api/sessions").json()["sessionId"]
                        result_id = str(uuid.uuid4())
                        payload = dict(studentId="EXE_TEST", loginTime=datetime.now().astimezone().isoformat(timespec="seconds"),
                                       correctCount=6, toneScore=18, questionScore=68)
                        started = client.post("/api/student-runs/start", json=dict(sessionId=session, resultId=result_id,
                                              studentId=payload["studentId"], loginTime=payload["loginTime"]))
                        started.raise_for_status()
                        route = f"/api/sessions/{session}/results/{result_id}"
                        submitted = client.put(route, json=payload)
                        submitted.raise_for_status()
                        assert submitted.json()["totalScore"] == 86
                        assert client.put(route, json=payload).json()["duplicate"]
                        assert client.get("/reports", follow_redirects=True).status_code == 200
                        assert not client.get("/api/uploads/status").json()["enabled"]
                        speech = client.get("/tts", params={"text": "護理教學系統啟動測試"})
                        speech.raise_for_status()
                        audio, rate = sf.read(io.BytesIO(speech.content))
                        assert len(audio) > 0 and rate > 0
                        for pattern in ("*.xlsx", "*/*.txt", "*/*.json", "*/*.html"):
                            assert list((root / "out" / "student_results").glob(pattern)), pattern
                        print("Packaged HTTP startup, scores, deduplication, reports, files, upload status and Windows TTS: OK")
                finally:
                    process.terminate()
                    process.wait(timeout=30)
        finally:
            # Unlink only junctions we created, before TemporaryDirectory cleanup.
            for name in ("_internal", "models"):
                os.rmdir(root / name)


if __name__ == "__main__":
    verify()
