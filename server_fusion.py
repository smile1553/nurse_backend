# server_fusion.py
import asyncio, json, time, io, os, tempfile, subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
from typing import Dict, Any, List, Tuple, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from discovery import udp_discovery_server
import uvicorn
from collections import deque
from deepgram_streaming import DeepgramStreamingError, DeepgramStreamingSession, DeepgramTranscriptResult

from fusion_loop import (
    fuse_once,
    sanitize_transcript,
    clamp,
)
from semantic_analysis import (
    DEFAULT_SEMANTIC_ANALYSIS,
    analyze_semantics,
    semantic_tension_score,
    tension_to_kid_emotion_state,
    update_tension,
)
from tone_analysis import DEFAULT_TONE_ANALYSIS
from test_sensevoice import warmup_model

OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPT_PATH = OUT_DIR / "transcripts.jsonl"
SESSION_AUDIO_DIR = OUT_DIR / "session_audio"
SESSION_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
SESSION_REPORT_DIR = OUT_DIR / "session_reports"
SESSION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
ENERGY_GATE_RMS = float(os.getenv("ENERGY_GATE_RMS", "0.003"))
ASR_WARMUP_ON_START = os.getenv("ASR_WARMUP_ON_START", "1").strip() in {"1", "true", "True", "yes", "on"}
TTS_RATE = int(os.getenv("TTS_RATE", "185"))
TTS_DEFAULT_VOICE = os.getenv("TTS_DEFAULT_VOICE", "").strip()
TTS_VOICE_BY_SPEAKER = {
    "mother": os.getenv("TTS_VOICE_MOTHER", "").strip(),
    "child": os.getenv("TTS_VOICE_CHILD", "").strip(),
    "nurse": os.getenv("TTS_VOICE_NURSE", "").strip(),
    "narrator": os.getenv("TTS_VOICE_NARRATOR", "").strip(),
    "system": os.getenv("TTS_VOICE_SYSTEM", "").strip(),
}
VOICE_IDLE_KEEPALIVE_SEC = float(os.getenv("VOICE_IDLE_KEEPALIVE_SEC", "3.0"))
VOICE_MAX_UTTERANCE_SEC = float(os.getenv("VOICE_MAX_UTTERANCE_SEC", "20.0"))
VOICE_MIN_AUDIO_MS = float(os.getenv("VOICE_MIN_AUDIO_MS", "200"))



def preprocess_audio(mono: np.ndarray) -> np.ndarray:
    """Conservative preprocessing: avoid amplifying silence/noise."""
    if mono is None or len(mono) == 0:
        return mono

    mono = mono.astype(np.float32)

    # remove DC offset
    mono = mono - float(np.mean(mono))

    peak = float(np.max(np.abs(mono))) if len(mono) > 0 else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) > 0 else 0.0

    # Do NOT normalize near-silence/noise; that creates ASR hallucinations.
    if peak < 0.01 or rms < ENERGY_GATE_RMS:
        return mono

    # Normalize only when signal is already strong enough.
    if peak > 0.6:
        mono = mono / peak

    mono = np.clip(mono * 0.95, -1.0, 1.0).astype(np.float32)
    return mono


def compute_rms(x: np.ndarray) -> float:
    if x is None or len(x) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x))))


def read_wav_to_mono16k(bytes_data: bytes) -> tuple[np.ndarray, int]:
    """把上傳的 WAV 轉為 mono/16k/float32（-1..1）"""
    return decode_wav_to_mono16k(bytes_data, apply_preprocess=True)


def decode_wav_to_mono16k(bytes_data: bytes, apply_preprocess: bool = True) -> tuple[np.ndarray, int]:
    """把上傳的 WAV 轉為 mono/16k/float32（-1..1）"""
    audio, sr = sf.read(io.BytesIO(bytes_data), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    target_sr = 16000
    if sr != target_sr:
        # 簡單線性重採樣（先用這版就好；日後可換 librosa.resample）
        x_old = np.linspace(0, 1, num=len(mono), endpoint=False, dtype=np.float32)
        new_len = int(len(mono) * (target_sr / sr))
        x_new = np.linspace(0, 1, num=new_len, endpoint=False, dtype=np.float32)
        mono = np.interp(x_new, x_old, mono).astype(np.float32)
        sr = target_sr

    if apply_preprocess:
        mono = preprocess_audio(mono)
    return mono, sr


latest: Dict[str, Any] = {
    "text": "", "emotion": "neutral", "emotion_probs": {},
    "llm": {"intent":"talk","action_tag":"neutral","sentiment":"neutral","toxicity":0.0,"coercion":0.0,"confidence":0.0,"keywords":[]},
    "semantic_analysis": dict(DEFAULT_SEMANTIC_ANALYSIS),
    "tone_analysis": dict(DEFAULT_TONE_ANALYSIS),
    "tension": 0.0, "ts": ""
}

app = FastAPI()


class FusionSession:
    def __init__(self, history_len: int = 3):
        self._prev_tension = 0.0
        self._history = deque(maxlen=history_len)
        self._lock = None

    async def analyze(self, wav: np.ndarray, sr: int) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            prev = self._prev_tension
            history = list(self._history)
            res, tension = await loop.run_in_executor(None, _run_fusion_pipeline, wav, sr, prev, history)

            text = (res.get("text", "") or "").strip()
            self._prev_tension = tension
            if text:
                self._history.append(text)

        return res


class RecordingSession:
    def __init__(self):
        self._lock: Optional[asyncio.Lock] = None
        self._active = False
        self._session_id = ""
        self._path: Optional[Path] = None
        self._writer: Optional[sf.SoundFile] = None
        self._sample_rate = 16000
        self._total_samples = 0

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def start(self, session_id: str = "") -> Dict[str, Any]:
        lock = self._ensure_lock()
        async with lock:
            if self._writer is not None:
                self._writer.close()

            path = build_session_audio_path(session_id)
            writer = sf.SoundFile(str(path), mode="w", samplerate=self._sample_rate, channels=1, subtype="PCM_16")

            self._active = True
            self._session_id = path.stem
            self._path = path
            self._writer = writer
            self._total_samples = 0
            return self.status()

    async def append(self, mono: np.ndarray, sr: int) -> None:
        if mono is None or len(mono) == 0:
            return

        lock = self._ensure_lock()
        async with lock:
            if not self._active or self._writer is None:
                return

            chunk = mono.astype(np.float32, copy=False)
            if sr != self._sample_rate:
                raise ValueError(f"recording sample rate mismatch: expected {self._sample_rate}, got {sr}")

            self._writer.write(chunk)
            self._writer.flush()
            self._total_samples += int(len(chunk))

    async def stop(self) -> Dict[str, Any]:
        lock = self._ensure_lock()
        async with lock:
            info = self.status()
            if self._writer is not None:
                self._writer.close()
            self._writer = None
            self._active = False
            return info

    def status(self) -> Dict[str, Any]:
        seconds = self._total_samples / float(self._sample_rate) if self._sample_rate > 0 else 0.0
        return {
            "active": self._active,
            "session_id": self._session_id,
            "path": str(self._path) if self._path else "",
            "sample_rate": self._sample_rate,
            "samples": self._total_samples,
            "seconds": round(seconds, 3),
        }


def _run_fusion_pipeline(wav: np.ndarray, sr: int, prev_tension: float, history: List[str]) -> Tuple[Dict[str, Any], float]:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, wav, sr)
        tmp_path = tmp.name
    try:
        res, tension = fuse_once(tmp_path, prev_tension, history)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return res, tension


def _run_text_pipeline(input_text: str, prev_tension: float, history: List[str]) -> Tuple[Dict[str, Any], float]:
    raw_text = (input_text or "").strip()
    text = sanitize_transcript(raw_text)

    if text:
        llm, llm_window_text = analyze_semantics(text, history)
        iscore = semantic_tension_score(llm.get("intent", ""), llm.get("coercion", 0.0))
    else:
        llm_window_text = ""
        llm = dict(DEFAULT_SEMANTIC_ANALYSIS)
        iscore = 0.0

    tension = update_tension(
        prev_tension,
        llm.get("intent", ""),
        iscore,
        llm.get("confidence", 0.0),
        0.0,
    )

    kid_emotion_state = tension_to_kid_emotion_state(tension)
    result = {
        "raw_text": raw_text,
        "text": text,
        "semantic_analysis": llm,
        "tone_analysis": dict(DEFAULT_TONE_ANALYSIS),
        "emotion": kid_emotion_state,
        "kidEmotionState": kid_emotion_state,
        "emotion_probs": {},
        "asr": {"asr_confidence": 1.0 if text else 0.0, "language": "zh", "segment_count": 1 if text else 0, "rms": None},
        "llm": llm,
        "llm_window_text": llm_window_text,
        "tension": tension,
    }
    return result, tension


def _build_unity_emotion_payload(
    fusion_res: Dict[str, Any],
    result_type: str = "emotion_result",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "type": result_type,
        "text": fusion_res.get("text", ""),
        "raw_text": fusion_res.get("raw_text", ""),
        "emotion": fusion_res.get("emotion", "neutral"),
        "tension": fusion_res.get("tension", 0.0),
        "llm": fusion_res.get("llm", fusion_res.get("semantic_analysis", {})),
        "semantic_analysis": fusion_res.get("semantic_analysis", {}),
        "tone_analysis": fusion_res.get("tone_analysis", {}),
        "asr": fusion_res.get("asr", {}),
        "ts": fusion_res.get("ts", ""),
    }
    if extra:
        payload.update(extra)
    return payload


async def analyze_transcript_for_unity(
    transcript: str,
    asr_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    if fusion_session._lock is None:
        fusion_session._lock = asyncio.Lock()

    async with fusion_session._lock:
        prev = fusion_session._prev_tension
        history = list(fusion_session._history)
        fusion_res, tension = await loop.run_in_executor(
            None,
            _run_text_pipeline,
            transcript,
            prev,
            history,
        )
        fusion_session._prev_tension = tension

        text = (fusion_res.get("text", "") or "").strip()
        if text:
            fusion_session._history.append(text)

    fusion_res = dict(fusion_res)
    fusion_res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if asr_meta:
        fusion_res["asr"] = {**fusion_res.get("asr", {}), **asr_meta}

    latest.update(fusion_res)
    if (fusion_res.get("text", "") or fusion_res.get("raw_text", "")):
        append_transcript_entry(fusion_res)

    return _build_unity_emotion_payload(fusion_res)


fusion_session = FusionSession()
recording_session = RecordingSession()


def reset_transcripts_file() -> None:
    """Reset transcript log on each server startup for easier debugging."""
    try:
        with open(TRANSCRIPT_PATH, "w", encoding="utf-8") as fp:
            fp.write("")
        print(f"[transcripts] reset: {TRANSCRIPT_PATH}")
    except OSError as e:
        print(f"[transcripts] reset failed: {e}")


def append_transcript_entry(data: Dict[str, Any]) -> None:
    entry = {
        "ts": data.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "text": data.get("text", ""),
        "raw_text": data.get("raw_text", ""),
        "emotion": data.get("emotion", ""),
        "tone_available": data.get("tone_analysis", {}).get("available", False),
        "tone_confidence": data.get("tone_analysis", {}).get("confidence", 0.0),
        "tone_score": data.get("tone_analysis", {}).get("tone_score", 0.0),
        "tension": data.get("tension", 0.0),
        "intent": data.get("semantic_analysis", data.get("llm", {})).get("intent"),
        "sentiment": data.get("semantic_analysis", data.get("llm", {})).get("sentiment"),
        "toxicity": data.get("semantic_analysis", data.get("llm", {})).get("toxicity"),
        "coercion": data.get("semantic_analysis", data.get("llm", {})).get("coercion"),
        "llm_window_text": data.get("llm_window_text", ""),
        "asr_confidence": data.get("asr", {}).get("asr_confidence"),
        "asr_language": data.get("asr", {}).get("language"),
        "asr_segments": data.get("asr", {}).get("segment_count"),
        "asr_rms": data.get("asr", {}).get("rms"),
    }
    try:
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[fusion] failed to append transcript: {e}")


def build_session_audio_path(session_id: str) -> Path:
    raw = (session_id or "").strip() or time.strftime("session_%Y%m%d_%H%M%S", time.localtime())
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    safe = safe[:80] or time.strftime("session_%Y%m%d_%H%M%S", time.localtime())
    return SESSION_AUDIO_DIR / f"{safe}.wav"


def build_session_report_path(session_id: str) -> Path:
    raw = (session_id or "").strip() or time.strftime("report_%Y%m%d_%H%M%S", time.localtime())
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    safe = safe[:80] or time.strftime("report_%Y%m%d_%H%M%S", time.localtime())
    return SESSION_REPORT_DIR / f"{safe}.json"


def build_public_url(request: Request, route_path: str) -> str:
    return str(request.base_url).rstrip("/") + route_path


def read_recent_transcripts(limit: int = 100) -> List[Dict[str, Any]]:
    if not TRANSCRIPT_PATH.exists():
        return []
    lines: List[str] = []
    try:
        with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as fp:
            lines = fp.readlines()
    except OSError as e:
        print(f"[fusion] failed to read transcripts: {e}")
        return []

    entries: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def resolve_tts_voice(speaker: str) -> str:
    key = (speaker or "").strip().lower()
    voice = TTS_VOICE_BY_SPEAKER.get(key) or TTS_DEFAULT_VOICE
    return voice.strip()


def synthesize_tts_wav(text: str, speaker: str = "") -> bytes:
    content = (text or "").strip()
    if not content:
        raise ValueError("text is required")

    with tempfile.TemporaryDirectory() as tmpdir:
        aiff_path = Path(tmpdir) / "tts.aiff"
        cmd = ["say", "-r", str(TTS_RATE), "-o", str(aiff_path)]
        voice = resolve_tts_voice(speaker)
        if voice:
            cmd.extend(["-v", voice])
        cmd.append(content)

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError as e:
            raise RuntimeError("system TTS command `say` is not available on this host") from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
            raise RuntimeError(f"TTS synthesis failed: {stderr.strip()}") from e

        audio, sr = sf.read(str(aiff_path), dtype="float32", always_2d=True)
        wav_io = io.BytesIO()
        sf.write(wav_io, audio, sr, format="WAV")
        return wav_io.getvalue()


@app.post("/audio")
async def upload_audio(request: Request):
    """
    直接接 Unity 丟來的 audio/wav 原始位元流
    """
    try:
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="empty request body")

        record_wav, record_sr = decode_wav_to_mono16k(raw, apply_preprocess=False)
        await recording_session.append(record_wav, record_sr)

        wav, sr = decode_wav_to_mono16k(raw, apply_preprocess=True)
        rms = compute_rms(wav)
        peak = float(np.max(np.abs(wav))) if len(wav) > 0 else 0.0
        print(f"[audio] bytes={len(raw)} samples={len(wav)} sr={sr} rms={rms:.6f} peak={peak:.6f} gate={ENERGY_GATE_RMS:.6f}")

        if rms < ENERGY_GATE_RMS:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fusion_res = {
                "raw_text": "",
                "text": "",
                "emotion": "",
                "emotion_probs": {},
                "semantic_analysis": dict(DEFAULT_SEMANTIC_ANALYSIS),
                "tone_analysis": dict(DEFAULT_TONE_ANALYSIS),
                "asr": {"asr_confidence": 0.0, "language": "", "segment_count": 0, "rms": rms},
                "llm": {"intent":"neutral","action_tag":"neutral","sentiment":"neutral","toxicity":0.0,"coercion":0.0,"confidence":0.0,"keywords":[]},
                "tension": latest.get("tension", 0.0),
                "ts": now
            }
            latest.update(fusion_res)
            print("[audio] dropped: low_energy")
            return {
                "ok": True,
                "len": len(wav),
                "sr": sr,
                "text": "",
                "raw_text": "",
                "semantic_analysis": fusion_res["semantic_analysis"],
                "tone_analysis": fusion_res["tone_analysis"],
                "tension": fusion_res["tension"],
                "reason": "low_energy",
                "rms": rms,
            }

        fusion_res = await fusion_session.analyze(wav, sr)
        fusion_res = dict(fusion_res)
        fusion_res.setdefault("text", f"(voice {len(wav)/sr:.2f}s)")
        fusion_res.setdefault("emotion_probs", {})
        fusion_res.setdefault("asr", {})
        fusion_res["asr"].setdefault("rms", rms)
        fusion_res.setdefault("llm", {"intent":"explain","action_tag":"neutral","sentiment":"neutral","toxicity":0.0,"coercion":0.0,"confidence":0.0,"keywords":[]})
        fusion_res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        latest.update(fusion_res)
        if (fusion_res.get("text", "") or fusion_res.get("raw_text", "")):
            append_transcript_entry(fusion_res)

        try:
            summary = {
                "text": fusion_res.get("text", ""),
                "emotion": fusion_res.get("emotion", ""),
                "tension": fusion_res.get("tension", 0.0),
                "intent": fusion_res.get("llm", {}).get("intent", "")
            }
            print("[fusion]", json.dumps(summary, ensure_ascii=False))
        except Exception:
            pass

        return {
            "ok": True,
            "len": len(wav),
            "sr": sr,
            "text": fusion_res.get("text", ""),
            "raw_text": fusion_res.get("raw_text", ""),
            "semantic_analysis": fusion_res.get("semantic_analysis", {}),
            "tone_analysis": fusion_res.get("tone_analysis", {}),
            "tension": fusion_res.get("tension", 0.0)
        }
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/text")
async def upload_text(request: Request):
    """
    測試模式：直接用打字文字走 fusion，排除收音/ASR 問題。
    body: {"text":"..."}
    """
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid json body")

        typed = str(payload.get("text", "")).strip()
        if not typed:
            raise HTTPException(status_code=400, detail="text is required")

        # Reuse session state so /text and /audio share same tension/history behavior.
        if fusion_session._lock is None:
            fusion_session._lock = asyncio.Lock()

        async with fusion_session._lock:
            prev = fusion_session._prev_tension
            history = list(fusion_session._history)
            fusion_res, tension = _run_text_pipeline(typed, prev, history)
            fusion_session._prev_tension = tension
            text = (fusion_res.get("text", "") or "").strip()
            if text:
                fusion_session._history.append(text)

        fusion_res = dict(fusion_res)
        fusion_res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        latest.update(fusion_res)
        append_transcript_entry(fusion_res)

        return {
            "ok": True,
            "mode": "text",
            "text": fusion_res.get("text", ""),
            "raw_text": fusion_res.get("raw_text", ""),
            "semantic_analysis": fusion_res.get("semantic_analysis", {}),
            "tone_analysis": fusion_res.get("tone_analysis", {}),
            "tension": fusion_res.get("tension", 0.0),
        }
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/tts")
def get_tts(text: str, speaker: str = ""):
    try:
        wav_bytes = synthesize_tts_wav(text, speaker)
        return Response(content=wav_bytes, media_type="audio/wav")
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/session_audio")
async def upload_session_audio(request: Request, session_id: str = ""):
    try:
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="empty request body")

        out_path = build_session_audio_path(session_id)
        with open(out_path, "wb") as fp:
            fp.write(raw)
        print(f"[session_audio] saved -> {out_path}")
        resolved_session_id = out_path.stem
        public_url = build_public_url(request, f"/session_audio/{resolved_session_id}")
        return {"ok": True, "session_id": resolved_session_id, "path": str(out_path), "url": public_url, "bytes": len(raw)}
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/session_audio/{session_id}")
def get_session_audio(session_id: str):
    path = build_session_audio_path(session_id)
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "session audio not found"})
    return FileResponse(str(path), media_type="audio/wav", filename=path.name)


@app.post("/recording/start")
async def start_recording(request: Request, session_id: str = ""):
    try:
        info = await recording_session.start(session_id)
        public_url = build_public_url(request, f"/session_audio/{info['session_id']}")
        print(f"[recording] started -> {info['path']}")
        return {"ok": True, **info, "url": public_url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/recording/stop")
async def stop_recording(request: Request):
    try:
        info = await recording_session.stop()
        if not info.get("session_id"):
            return {"ok": True, **info, "url": ""}
        public_url = build_public_url(request, f"/session_audio/{info['session_id']}")
        print(f"[recording] stopped -> {info['path']} ({info['seconds']}s)")
        return {"ok": True, **info, "url": public_url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/recording/status")
def get_recording_status(request: Request):
    info = recording_session.status()
    public_url = build_public_url(request, f"/session_audio/{info['session_id']}") if info.get("session_id") else ""
    return {"ok": True, **info, "url": public_url}


@app.post("/session_report")
async def upload_session_report(request: Request, session_id: str = ""):
    try:
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="empty request body")

        out_path = build_session_report_path(session_id)
        with open(out_path, "wb") as fp:
            fp.write(raw)
        resolved_session_id = out_path.stem
        public_url = build_public_url(request, f"/session_report/{resolved_session_id}")
        print(f"[session_report] saved -> {out_path}")
        return {"ok": True, "session_id": resolved_session_id, "path": str(out_path), "url": public_url, "bytes": len(raw)}
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"ok": False, "error": str(e.detail)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/session_report/{session_id}")
def get_session_report(session_id: str):
    path = build_session_report_path(session_id)
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "session report not found"})
    return FileResponse(str(path), media_type="application/json", filename=path.name)


@app.get("/last")
def get_last():
    return JSONResponse(latest)


@app.get("/transcripts")
def get_transcripts(limit: int = 50):
    limit = max(1, min(limit, 500))
    entries = read_recent_transcripts(limit)
    return {"items": entries, "count": len(entries)}


def _voice_error(code: str, message: str) -> Dict[str, Any]:
    return {
        "type": "error",
        "code": code,
        "message": message,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _audio_ms(byte_count: int, sample_rate: int, channels: int = 1) -> float:
    bytes_per_sample = 2
    denom = max(1, sample_rate * channels * bytes_per_sample)
    return (byte_count / denom) * 1000.0


def _parse_voice_control(raw_text: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        return {"type": "invalid_json"}
    if not isinstance(payload, dict):
        return {"type": "invalid_json"}
    return payload


@app.websocket("/voice")
async def voice_ws(ws: WebSocket):
    await ws.accept()

    dg_session: Optional[DeepgramStreamingSession] = None
    sample_rate = int(os.getenv("DEEPGRAM_SAMPLE_RATE", "16000"))
    audio_bytes = 0
    utterance_started_at = 0.0
    request_id = ""

    async def close_deepgram_session() -> None:
        nonlocal dg_session
        if dg_session is not None:
            try:
                await dg_session.close()
            except Exception as e:
                print(f"[voice] deepgram close failed: {e}")
            dg_session = None

    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=VOICE_IDLE_KEEPALIVE_SEC)
            except asyncio.TimeoutError:
                if dg_session is not None:
                    try:
                        await dg_session.keep_alive()
                    except Exception as e:
                        print(f"[voice] keepalive failed: {e}")
                        await ws.send_json(_voice_error("deepgram_disconnected", "Deepgram stream disconnected"))
                        await close_deepgram_session()
                continue

            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            raw_text = message.get("text")
            audio_chunk = message.get("bytes")

            if raw_text is not None:
                payload = _parse_voice_control(raw_text)
                msg_type = str(payload.get("type", "")).strip().lower()

                if msg_type == "start_utterance":
                    await close_deepgram_session()

                    try:
                        sample_rate = int(payload.get("sampleRate") or payload.get("sample_rate") or sample_rate)
                    except (TypeError, ValueError):
                        sample_rate = 16000

                    audio_bytes = 0
                    utterance_started_at = time.perf_counter()
                    request_id = str(payload.get("requestId") or payload.get("request_id") or "")

                    try:
                        dg_session = DeepgramStreamingSession(sample_rate=sample_rate)
                        await dg_session.connect()
                    except DeepgramStreamingError as e:
                        await ws.send_json(_voice_error("deepgram_start_failed", str(e)))
                        await close_deepgram_session()
                        continue
                    except Exception as e:
                        await ws.send_json(_voice_error("deepgram_start_failed", str(e)))
                        await close_deepgram_session()
                        continue

                    await ws.send_json({
                        "type": "voice_ready",
                        "sampleRate": sample_rate,
                        "encoding": "linear16",
                        "requestId": request_id,
                    })
                    continue

                if msg_type == "end_utterance":
                    if dg_session is None:
                        await ws.send_json(_voice_error("not_recording", "No active utterance"))
                        continue

                    end_received_at = time.perf_counter()
                    audio_duration_ms = _audio_ms(audio_bytes, sample_rate)
                    if audio_duration_ms < VOICE_MIN_AUDIO_MS:
                        await close_deepgram_session()
                        await ws.send_json(_voice_error("too_short", "Audio is too short"))
                        continue

                    try:
                        dg_result: DeepgramTranscriptResult = await dg_session.finalize()
                    except Exception as e:
                        await close_deepgram_session()
                        await ws.send_json(_voice_error("deepgram_finalize_failed", str(e)))
                        continue
                    finally:
                        await close_deepgram_session()

                    transcript = (dg_result.text or "").strip()
                    transcript_at = time.perf_counter()
                    if not transcript:
                        await ws.send_json(_voice_error("no_speech", "No speech detected"))
                        continue

                    try:
                        response = await analyze_transcript_for_unity(
                            transcript,
                            asr_meta={
                                "provider": "deepgram",
                                "model": os.getenv("DEEPGRAM_MODEL", "nova-3"),
                                "language": dg_result.language,
                                "asr_confidence": dg_result.confidence,
                                "sample_rate": sample_rate,
                                "audio_ms": round(audio_duration_ms, 1),
                            },
                        )
                    except Exception as e:
                        await ws.send_json(_voice_error("emotion_analysis_failed", str(e)))
                        continue

                    sent_at = time.perf_counter()
                    response["requestId"] = request_id
                    response["latency"] = {
                        "utterance_ms": round((end_received_at - utterance_started_at) * 1000.0, 1),
                        "deepgram_finalize_ms": round((transcript_at - end_received_at) * 1000.0, 1),
                        "emotion_analysis_ms": round((sent_at - transcript_at) * 1000.0, 1),
                        "end_to_result_ms": round((sent_at - end_received_at) * 1000.0, 1),
                    }
                    await ws.send_json(response)
                    print("[voice]", json.dumps({
                        "text": response.get("text", ""),
                        "tension": response.get("tension", 0.0),
                        "intent": response.get("llm", {}).get("intent", ""),
                        "end_to_result_ms": response["latency"]["end_to_result_ms"],
                    }, ensure_ascii=False))
                    continue

                if msg_type in {"cancel_utterance", "cancel"}:
                    await close_deepgram_session()
                    await ws.send_json({"type": "voice_cancelled", "requestId": request_id})
                    continue

                await ws.send_json(_voice_error("unknown_message", f"Unknown control message: {msg_type}"))
                continue

            if audio_chunk is not None:
                if dg_session is None:
                    await ws.send_json(_voice_error("not_recording", "Audio received before start_utterance"))
                    continue

                if time.perf_counter() - utterance_started_at > VOICE_MAX_UTTERANCE_SEC:
                    await close_deepgram_session()
                    await ws.send_json(_voice_error("utterance_timeout", "Utterance exceeded max duration"))
                    continue

                audio_bytes += len(audio_chunk)
                try:
                    await dg_session.send_audio(audio_chunk)
                except Exception as e:
                    await close_deepgram_session()
                    await ws.send_json(_voice_error("deepgram_send_failed", str(e)))
                continue
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[voice] websocket error: {e}")
        try:
            await ws.send_json(_voice_error("server_error", str(e)))
        except Exception:
            pass
    finally:
        await close_deepgram_session()

@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_text(json.dumps(latest, ensure_ascii=False))
            await asyncio.sleep(0.5)  # 推播頻率，可調
    except Exception:
        pass

@app.on_event("startup")
async def on_start():
    asyncio.create_task(udp_discovery_server(http_port=8000))
    reset_transcripts_file()

    if not ASR_WARMUP_ON_START:
        print("[warmup] skipped on startup (ASR_WARMUP_ON_START=0)")
        return

    try:
        print("[warmup] loading ASR model... this may take a while on first run")
        warmup_start = time.time()
        warmup_model()
        elapsed = time.time() - warmup_start
        print(f"[warmup] SenseVoice ready in {elapsed:.2f}s")
    except Exception as e:
        print(f"[warmup] SenseVoice warmup failed: {e}")

if __name__ == "__main__":
    # 0.0.0.0 讓區網裝置（Quest）可連；port 可自訂
    uvicorn.run(app, host="0.0.0.0", port=8000)
