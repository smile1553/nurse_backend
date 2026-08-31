import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()


class DeepgramStreamingError(RuntimeError):
    pass


@dataclass
class DeepgramTranscriptResult:
    text: str
    confidence: float = 0.0
    language: str = ""
    is_final: bool = False
    speech_final: bool = False
    raw_messages: List[Dict[str, Any]] = field(default_factory=list)


class DeepgramStreamingSession:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        encoding: str = "linear16",
        language: Optional[str] = None,
        model: Optional[str] = None,
        finalize_timeout_sec: Optional[float] = None,
    ):
        self.sample_rate = int(sample_rate or os.getenv("DEEPGRAM_SAMPLE_RATE", "16000"))
        self.channels = int(channels or 1)
        self.encoding = encoding or "linear16"
        self.language = (language or os.getenv("DEEPGRAM_LANGUAGE", "zh")).strip()
        self.model = (model or os.getenv("DEEPGRAM_MODEL", "nova-3")).strip()
        self.finalize_timeout_sec = float(
            finalize_timeout_sec or os.getenv("DEEPGRAM_FINALIZE_TIMEOUT_SEC", "1.2")
        )
        self._api_key = (os.getenv("DEEPGRAM_API_KEY") or "").strip()
        self._ws = None
        self._reader_task: Optional[asyncio.Task] = None
        self._final_event = asyncio.Event()
        self._closed = False
        self._error: Optional[Exception] = None
        self._interim_text = ""
        self._final_parts: List[str] = []
        self._confidence_values: List[float] = []
        self._language_values: List[str] = []
        self._raw_messages: List[Dict[str, Any]] = []

    async def connect(self) -> None:
        if not self._api_key:
            raise DeepgramStreamingError("DEEPGRAM_API_KEY is missing")

        try:
            import websockets
        except ImportError as exc:
            raise DeepgramStreamingError("Missing dependency: websockets") from exc

        url = self._build_url()
        headers = {"Authorization": f"Token {self._api_key}"}

        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                max_size=2 * 1024 * 1024,
            )
        except TypeError:
            self._ws = await websockets.connect(
                url,
                extra_headers=headers,
                ping_interval=20,
                max_size=2 * 1024 * 1024,
            )

        self._reader_task = asyncio.create_task(self._receive_loop())

    def _build_url(self) -> str:
        endpointing = os.getenv("DEEPGRAM_ENDPOINTING_MS", "200").strip()
        params: Dict[str, Any] = {
            "model": self.model,
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "interim_results": "true",
            "punctuate": "true",
            "smart_format": "false",
        }
        if self.language:
            params["language"] = self.language
        if endpointing:
            params["endpointing"] = endpointing

        keyterms = [
            item.strip()
            for item in os.getenv("DEEPGRAM_KEYTERMS", "").split(",")
            if item.strip()
        ]
        if keyterms:
            params["keyterm"] = keyterms

        return "wss://api.deepgram.com/v1/listen?" + urlencode(params, doseq=True)

    async def send_audio(self, chunk: bytes) -> None:
        if self._closed or self._ws is None:
            return
        if not chunk:
            return
        await self._ws.send(chunk)

    async def keep_alive(self) -> None:
        if self._closed or self._ws is None:
            return
        await self._ws.send(json.dumps({"type": "KeepAlive"}))

    async def finalize(self) -> DeepgramTranscriptResult:
        if self._closed:
            return self.result()
        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "Finalize"}))
            try:
                await asyncio.wait_for(self._final_event.wait(), timeout=self.finalize_timeout_sec)
            except asyncio.TimeoutError:
                pass
        if self._error is not None:
            raise self._error
        return self.result()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    def result(self) -> DeepgramTranscriptResult:
        text = " ".join(part for part in self._final_parts if part).strip()
        if not text:
            text = self._interim_text.strip()

        confidence = (
            sum(self._confidence_values) / len(self._confidence_values)
            if self._confidence_values
            else 0.0
        )
        language = self._language_values[-1] if self._language_values else self.language

        return DeepgramTranscriptResult(
            text=text,
            confidence=confidence,
            language=language,
            is_final=bool(self._final_parts),
            speech_final=self._final_event.is_set(),
            raw_messages=self._raw_messages[-8:],
        )

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                self._raw_messages.append(msg)
                if len(self._raw_messages) > 24:
                    self._raw_messages = self._raw_messages[-24:]

                msg_type = msg.get("type")
                if msg_type == "Results":
                    self._handle_results(msg)
                elif msg.get("from_finalize"):
                    self._final_event.set()
                elif msg_type == "Error":
                    self._error = DeepgramStreamingError(str(msg))
                    self._final_event.set()
                    return
                elif msg_type == "Metadata":
                    self._final_event.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error = exc
            self._final_event.set()

    def _handle_results(self, msg: Dict[str, Any]) -> None:
        channel = msg.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        if not alternatives:
            return

        best = alternatives[0] or {}
        transcript = (best.get("transcript") or "").strip()
        if not transcript:
            return

        confidence = best.get("confidence")
        try:
            if confidence is not None:
                self._confidence_values.append(float(confidence))
        except (TypeError, ValueError):
            pass

        detected_language = best.get("language") or msg.get("language")
        if detected_language:
            self._language_values.append(str(detected_language))

        if msg.get("is_final"):
            self._final_parts.append(transcript)
        else:
            self._interim_text = transcript

        if msg.get("speech_final") or msg.get("from_finalize"):
            self._final_event.set()
