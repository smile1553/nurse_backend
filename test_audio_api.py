import asyncio
import io
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

import server_fusion
from deepgram_streaming import DeepgramStreamingError, DeepgramTranscriptResult
from excel_result_service import ExcelResultService
from intent_llm import normalize_llm_output
from semantic_analysis import (
    semantic_tension_score,
    tension_to_kid_emotion_state,
    tension_to_patience_score,
    update_tension,
)


def wav_bytes(amplitude: float) -> bytes:
    timeline = np.arange(1600, dtype=np.float32) / 16000.0
    samples = (amplitude * np.sin(2.0 * np.pi * 440.0 * timeline)).astype(np.float32)
    output = io.BytesIO()
    sf.write(output, samples, 16000, format="WAV", subtype="PCM_16")
    return output.getvalue()


class EmotionRuleTests(unittest.TestCase):
    def test_confidence_does_not_rewrite_intent(self):
        result = normalize_llm_output({"intent": "force", "confidence": 0.01})
        self.assertEqual(result["intent"], "force")

    def test_fixed_deltas_ignore_confidence_coercion_and_tone(self):
        delta = semantic_tension_score("force", coercion=1.0)
        self.assertEqual(delta, 1.2)
        self.assertEqual(update_tension(-5, "force", delta, confidence=0, tone_score=99), -3.8)
        self.assertEqual(update_tension(2, "neutral", 0, confidence=1, tone_score=-99), 2)
        self.assertEqual(update_tension(4.5, "threat", 1.5, confidence=1), 5)

    def test_patience_and_state_thresholds(self):
        self.assertEqual(tension_to_patience_score(-5), 100)
        self.assertEqual(tension_to_patience_score(5), 0)
        self.assertEqual(tension_to_kid_emotion_state(-2.5), "Calm")
        self.assertEqual(tension_to_kid_emotion_state(0), "Uneasy")
        self.assertEqual(tension_to_kid_emotion_state(2.5), "Crying")
        self.assertEqual(tension_to_kid_emotion_state(2.6), "Meltdown")


class AudioApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_service = server_fusion.student_result_service
        self.original_transcribe = server_fusion.transcribe_with_deepgram
        self.original_analyze_transcript = server_fusion.analyze_transcript_for_unity
        server_fusion.student_result_service = ExcelResultService(Path(self.temp_dir.name) / "results")
        server_fusion.audio_request_lock = None
        server_fusion.audio_result_cache.clear()
        server_fusion.active_student_run_id = ""
        server_fusion.fusion_session._lock = None
        server_fusion.fusion_session._prev_tension = -5.0
        server_fusion.fusion_session._history.clear()
        server_fusion.reset_latest_emotion_state()

        transport = httpx.ASGITransport(app=server_fusion.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")
        session = (await self.client.post("/api/sessions")).json()
        self.session_id = session["sessionId"]
        self.student_run_id = str(uuid.uuid4())
        response = await self.client.post("/api/student-runs/start", json={
            "sessionId": self.session_id,
            "resultId": self.student_run_id,
            "studentId": "412345678",
            "loginTime": "2026-09-21T10:35:00+08:00",
        })
        self.assertEqual(response.status_code, 200)

    async def asyncTearDown(self):
        await self.client.aclose()
        server_fusion.transcribe_with_deepgram = self.original_transcribe
        server_fusion.analyze_transcript_for_unity = self.original_analyze_transcript
        server_fusion.student_result_service = self.original_service
        self.temp_dir.cleanup()

    def headers(self, request_id: str):
        return {
            "Content-Type": "audio/wav",
            "X-Request-Id": request_id,
            "X-Scenario-Step-Id": "step-3",
            "X-Student-Run-Id": self.student_run_id,
        }

    async def test_low_energy_is_ignored_and_duplicate_is_cached(self):
        first = await self.client.post("/audio", content=wav_bytes(0), headers=self.headers("silent-1"))
        second = await self.client.post("/audio", content=wav_bytes(0), headers=self.headers("silent-1"))
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["ignored"])
        self.assertFalse(body["duplicate"])
        self.assertEqual(body["reason"], "low_energy")
        self.assertEqual(body["tension"], -5)
        self.assertEqual(body["patienceScore"], 100)
        self.assertEqual(body["kidEmotionState"], "Calm")
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(server_fusion.fusion_session._prev_tension, -5)

    async def test_concurrent_duplicate_runs_analysis_once(self):
        transcription_calls = 0
        intent_calls = 0

        async def fake_transcribe(wav, sr):
            nonlocal transcription_calls
            transcription_calls += 1
            await asyncio.sleep(0.02)
            self.assertEqual(sr, 16000)
            return DeepgramTranscriptResult(
                text="不用怕",
                confidence=0.91,
                language="zh",
                is_final=True,
                speech_final=True,
            )

        async def fake_analyze_transcript(transcript, asr_meta=None, unity_meta=None):
            nonlocal intent_calls
            intent_calls += 1
            self.assertEqual(transcript, "不用怕")
            self.assertEqual(asr_meta["provider"], "deepgram")
            self.assertEqual(unity_meta["scenarioStepId"], "step-3")
            return {
                "text": "不用怕",
                "tension": -4.0,
                "patienceScore": 90.0,
                "previousKidEmotionState": "Calm",
                "kidEmotionState": "Calm",
                "llm": {
                    "intent": "reassure",
                    "action_tag": "reassure_child",
                    "confidence": 0.86,
                    "coercion": 0.1,
                },
            }

        server_fusion.transcribe_with_deepgram = fake_transcribe
        server_fusion.analyze_transcript_for_unity = fake_analyze_transcript
        headers = self.headers("utterance-1")
        first, second = await asyncio.gather(
            self.client.post("/audio", content=wav_bytes(0.2), headers=headers),
            self.client.post("/audio", content=wav_bytes(0.2), headers=headers),
        )
        bodies = [first.json(), second.json()]
        self.assertEqual(transcription_calls, 1)
        self.assertEqual(intent_calls, 1)
        self.assertEqual(sorted(body["duplicate"] for body in bodies), [False, True])
        for body in bodies:
            self.assertEqual(body["requestId"], "utterance-1")
            self.assertEqual(body["utteranceId"], "utterance-1")
            self.assertEqual(body["scenarioStepId"], "step-3")
            self.assertEqual(body["source"], "student_speech")
            self.assertEqual(body["intent"], "reassure")
            self.assertEqual(body["emotionState"], "Calm")
            self.assertIn("processingMs", body)

    async def test_deepgram_failure_returns_503_without_state_or_cache_update(self):
        calls = 0

        async def failing_transcribe(wav, sr):
            nonlocal calls
            calls += 1
            raise DeepgramStreamingError("temporary failure")

        server_fusion.transcribe_with_deepgram = failing_transcribe
        before = server_fusion.fusion_session._prev_tension
        response = await self.client.post(
            "/audio",
            content=wav_bytes(0.2),
            headers=self.headers("deepgram-failure"),
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(server_fusion.fusion_session._prev_tension, before)
        self.assertNotIn(
            (self.student_run_id, "deepgram-failure"),
            server_fusion.audio_result_cache,
        )
        self.assertEqual(calls, 1)

    async def test_deepgram_no_speech_is_ignored_without_intent_analysis(self):
        intent_calls = 0

        async def no_speech(wav, sr):
            return DeepgramTranscriptResult(text="", confidence=0.0, language="zh")

        async def should_not_analyze(*args, **kwargs):
            nonlocal intent_calls
            intent_calls += 1
            raise AssertionError("intent analysis must not run without speech")

        server_fusion.transcribe_with_deepgram = no_speech
        server_fusion.analyze_transcript_for_unity = should_not_analyze
        response = await self.client.post(
            "/audio",
            content=wav_bytes(0.2),
            headers=self.headers("no-speech"),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ignored"])
        self.assertEqual(body["reason"], "no_speech")
        self.assertEqual(body["tension"], -5)
        self.assertEqual(intent_calls, 0)

    async def test_headers_and_active_student_run_are_validated(self):
        missing = await self.client.post(
            "/audio", content=wav_bytes(0), headers={"Content-Type": "audio/wav"}
        )
        self.assertEqual(missing.status_code, 400)

        wrong = self.headers("wrong-run")
        wrong["X-Student-Run-Id"] = str(uuid.uuid4())
        response = await self.client.post("/audio", content=wav_bytes(0), headers=wrong)
        self.assertEqual(response.status_code, 409)

    async def test_new_student_resets_state_but_retry_does_not(self):
        server_fusion.fusion_session._prev_tension = -3.0
        retry = await self.client.post("/api/student-runs/start", json={
            "sessionId": self.session_id,
            "resultId": self.student_run_id,
            "studentId": "412345678",
            "loginTime": "2026-09-21T10:35:00+08:00",
        })
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(server_fusion.fusion_session._prev_tension, -3.0)

        new_run_id = str(uuid.uuid4())
        new_run = await self.client.post("/api/student-runs/start", json={
            "sessionId": self.session_id,
            "resultId": new_run_id,
            "studentId": "400000001",
            "loginTime": "2026-09-21T10:40:00+08:00",
        })
        self.assertEqual(new_run.status_code, 200)
        self.assertEqual(server_fusion.fusion_session._prev_tension, -5.0)
        self.assertEqual(server_fusion.active_student_run_id, new_run_id)
        self.assertFalse(server_fusion.audio_result_cache)


if __name__ == "__main__":
    unittest.main()
