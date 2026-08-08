import json
import math
import os
from pathlib import Path

import soundfile as sf

_MODEL = None
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "medium")
ASR_BEAM_SIZE = int(os.getenv("ASR_BEAM_SIZE", "4"))
ASR_BEST_OF = int(os.getenv("ASR_BEST_OF", "4"))
ASR_INITIAL_PROMPT = os.getenv(
    "ASR_INITIAL_PROMPT",
    "這是兒科護理教學情境對話。常見詞包含：芽芽、媽媽、護生、熊熊、聽診器、耳溫、耳溫槍、"
    "血壓、血壓計、壓脈帶、量體溫、量血壓、心跳、呼吸、貼紙、不會痛、放輕鬆、一下就好、先觀察呼吸。"
)
ASR_VAD_FILTER = os.getenv("ASR_VAD_FILTER", "1").strip() in {"1", "true", "True", "yes", "on"}
ASR_NO_SPEECH_THRESHOLD = float(os.getenv("ASR_NO_SPEECH_THRESHOLD", "0.85"))
ASR_LOG_PROB_THRESHOLD = float(os.getenv("ASR_LOG_PROB_THRESHOLD", "-1.0"))
ASR_COMPRESSION_RATIO_THRESHOLD = float(os.getenv("ASR_COMPRESSION_RATIO_THRESHOLD", "2.0"))


def record_wav(path="Assets/MyAssests/Analysis/audio/sample.wav", secs=5, sr=16000):
    import sounddevice as sd

    Path("Assets/MyAssests/Analysis/audio").mkdir(parents=True, exist_ok=True)
    print(f"[REC] speak for {secs}s ...")
    audio = sd.rec(int(secs * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    sf.write(path, audio, sr)
    print(f"[REC] saved -> {path}")
    return path


def _load_faster_whisper_model():
    from faster_whisper import WhisperModel

    # Keep settings pragmatic for real-time-ish clinic dialogue testing.
    try:
        import torch

        use_cuda = torch.cuda.is_available()
    except Exception:
        use_cuda = False

    device = "cuda" if use_cuda else "cpu"
    compute_type = "int8_float16" if use_cuda else "int8"

    # small is a good tradeoff for Mandarin accuracy vs speed.
    return WhisperModel(ASR_MODEL_NAME, device=device, compute_type=compute_type)


def _avg_logprob_to_conf(avg_logprob: float) -> float:
    # avg_logprob is usually <= 0; map to 0..1 for gating.
    if avg_logprob is None:
        return 0.0
    x = max(-5.0, min(0.0, float(avg_logprob)))
    return math.exp(x)


def warmup_model() -> None:
    global _MODEL
    if _MODEL is not None:
        return
    _MODEL = _load_faster_whisper_model()


def sensevoice_infer(wav_path):
    global _MODEL
    if _MODEL is None:
        warmup_model()

    segments, info = _MODEL.transcribe(
        wav_path,
        language="zh",
        vad_filter=ASR_VAD_FILTER,
        beam_size=max(1, ASR_BEAM_SIZE),
        best_of=max(1, ASR_BEST_OF),
        temperature=0.0,
        condition_on_previous_text=False,
        no_speech_threshold=ASR_NO_SPEECH_THRESHOLD,
        log_prob_threshold=ASR_LOG_PROB_THRESHOLD,
        compression_ratio_threshold=ASR_COMPRESSION_RATIO_THRESHOLD,
        initial_prompt=ASR_INITIAL_PROMPT if ASR_INITIAL_PROMPT else None,
    )

    segments = list(segments)

    text_parts = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            text_parts.append(t)
    transcript = "".join(text_parts).strip()

    avg_logprob = None
    if segments:
        vals = []
        for seg in segments:
            v = getattr(seg, "avg_logprob", None)
            if v is not None:
                vals.append(float(v))
        if vals:
            avg_logprob = sum(vals) / len(vals)

    lang_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
    logprob_conf = _avg_logprob_to_conf(avg_logprob)
    asr_confidence = max(0.0, min(1.0, 0.6 * lang_prob + 0.4 * logprob_conf)) if segments else 0.0

    # Keep output schema compatible with existing fusion pipeline.
    return {
        "text": transcript,
        "emotion": "",
        "emotion_probs": {},
        "meta": {
            "language": getattr(info, "language", ""),
            "language_probability": lang_prob,
            "avg_logprob": avg_logprob if avg_logprob is not None else 0.0,
            "asr_confidence": asr_confidence,
            "segment_count": len(segments),
        },
    }


if __name__ == "__main__":
    wav = record_wav()
    result = sensevoice_infer(wav)
    print(json.dumps(result, ensure_ascii=False, indent=2))
