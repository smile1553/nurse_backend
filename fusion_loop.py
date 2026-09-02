import json
import os
import re
from difflib import SequenceMatcher

try:
    from opencc import OpenCC
    _OPENCC = OpenCC("s2t")
except Exception:
    _OPENCC = None
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from test_sensevoice import sensevoice_infer
from semantic_analysis import (
    DEFAULT_SEMANTIC_ANALYSIS,
    analyze_semantics,
    semantic_tension_score,
    tension_to_kid_emotion_state,
    update_tension,
)
from tone_analysis import analyze_tone



TOKEN_RE = re.compile(r"<\|[^|]+\|>")

ASR_MIN_CONF = float(os.getenv("ASR_MIN_CONF", "0.30"))
ASR_STRICT_MIN_CONF = float(os.getenv("ASR_STRICT_MIN_CONF", "0.60"))
MAX_LATIN_RATIO = float(os.getenv("MAX_LATIN_RATIO", "0.30"))

HALLUCINATION_PHRASES = [
    "明鏡",
    "李宗盛",
    "詞曲",
    "訂閱轉發",
    "請不吝點贊",
    "字幕提供",
    "在我面前",
    "謝謝觀看",
    "謝謝大家",
]

DOMAIN_HINT_TOKENS = ["芽芽", "媽媽", "護生", "耳溫", "血壓", "聽診器", "壓脈帶", "量體溫", "心跳", "呼吸", "熊熊"]

DOMAIN_CANONICAL_PHRASES = [
    "先觀察呼吸",
    "先看呼吸",
    "不會痛",
    "一下就好",
    "放輕鬆",
    "摸摸聽診器",
    "聽心跳",
    "喜歡什麼",
    "分散注意力",
    "量完給貼紙",
    "你很勇敢",
    "做得很好",
    "幫熊熊量體溫",
    "先幫玩偶量",
    "先練習",
    "熟悉步驟",
    "耳朵往上往後拉",
    "輕輕拉耳朵",
    "量耳溫",
    "量血壓",
    "壓脈帶",
    "血壓計",
    "耳溫槍",
    "媽媽",
    "芽芽",
    "熊熊",
    "聽診器",
]

# Common ASR mistakes in this scenario (can keep expanding from transcripts).
ASR_REPLACEMENTS = {
    "雅瑤": "芽芽",
    "馬小也": "芽芽",
    "馬小芽": "芽芽",
    "亞瑤": "芽芽",
    "雅雅": "芽芽",
    "炎炎": "芽芽",
    "牙牙": "芽芽",
    "丫丫": "芽芽",
    "鴨鴨": "芽芽",
    "鴨": "芽芽",
    "媽咪": "媽媽",
    "媽媽跟": "媽媽和",
    "血壓帶": "壓脈帶",
    "壓力帶": "壓脈帶",
    "壓買帶": "壓脈帶",
    "耳溫槍": "耳溫槍",
    "耳溫計": "耳溫槍",
    "耳溫機": "耳溫槍",
    "量耳聞": "量耳溫",
    "量耳文": "量耳溫",
    "量體文": "量體溫",
    "聽整器": "聽診器",
    "聽診機": "聽診器",
    "先觀察呼西": "先觀察呼吸",
    "先關查呼吸": "先觀察呼吸",
    "先看呼西": "先看呼吸",
    "心條": "心跳",
}

SPACE_NORMALIZE_RE = re.compile(r"\s+")
PUNCT_NORMALIZE_RE = re.compile(r"[、,.!?！？；;]+")


def latin_ratio(text: str) -> float:
    if not text:
        return 0.0
    chars = [c for c in text if c.isalpha()]
    if not chars:
        return 0.0
    latin = sum(1 for c in chars if ("a" <= c.lower() <= "z"))
    return latin / max(1, len(chars))


def contains_domain_tokens(text: str) -> bool:
    if not text:
        return False
    return any(tok in text for tok in DOMAIN_HINT_TOKENS)


def sanitize_transcript(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    cleaned = TOKEN_RE.sub("", raw).replace("\uFFFD", "").strip()
    cleaned = PUNCT_NORMALIZE_RE.sub(" ", cleaned)
    cleaned = SPACE_NORMALIZE_RE.sub(" ", cleaned).strip()

    if _OPENCC is not None:
        cleaned = _OPENCC.convert(cleaned)

    for wrong, right in ASR_REPLACEMENTS.items():
        cleaned = cleaned.replace(wrong, right)

    cleaned = maybe_snap_to_canonical_phrase(cleaned)

    # 若清洗後可用字元太少，視為無效轉寫，避免誤送 LLM
    alnum_count = sum(ch.isalnum() for ch in cleaned)
    if alnum_count < 2:
        return ""

    return cleaned


def maybe_snap_to_canonical_phrase(text: str) -> str:
    cleaned = SPACE_NORMALIZE_RE.sub(" ", (text or "").strip())
    if not cleaned:
        return ""

    compact = cleaned.replace(" ", "")
    if len(compact) < 2:
        return cleaned

    best_phrase = ""
    best_score = 0.0
    for phrase in DOMAIN_CANONICAL_PHRASES:
        phrase_compact = phrase.replace(" ", "")
        if abs(len(phrase_compact) - len(compact)) > 4:
            continue
        score = SequenceMatcher(None, compact, phrase_compact).ratio()
        if score > best_score:
            best_score = score
            best_phrase = phrase

    # Only snap short/mid-length noisy utterances to known scenario phrases.
    if best_phrase and len(compact) <= 12 and best_score >= 0.74:
        return best_phrase
    return cleaned


def has_repeated_tokens(text: str) -> bool:
    toks = [t for t in text.replace("，", " ").replace("。", " ").split() if t]
    if len(toks) < 4:
        return False

    # e.g. "耳溫 耳溫 耳溫 耳溫"
    if len(set(toks)) == 1 and len(toks) >= 4:
        return True

    top = max(toks.count(t) for t in set(toks))
    return top >= 5


def is_likely_hallucination(text: str, asr_meta: Dict[str, Any]) -> bool:
    if not text:
        return True

    t = text.strip()
    if not t:
        return True

    if has_repeated_tokens(t):
        return True

    # Common Whisper hallucination phrases in silence/noise.
    for p in HALLUCINATION_PHRASES:
        if p in t:
            return True

    # Extreme repetition pattern (e.g. same phrase looped many times).
    if len(t) >= 16:
        uniq_ratio = len(set(t)) / max(1, len(t))
        if uniq_ratio < 0.22:
            return True

    seg_count = int(asr_meta.get("segment_count", 0) or 0)
    if len(t) > 40 and seg_count >= 8:
        return True

    return False


def clamp(x, a, b): return max(a, min(b, x))


def fuse_once(wav_path: str, prev_tension: float = 0.0, recent_texts: Optional[List[str]] = None) -> Tuple[Dict[str, Any], float]:
    sv = sensevoice_infer(wav_path)
    raw_text = sv.get("text", "") or ""
    text = sanitize_transcript(raw_text)
    asr_meta = sv.get("meta", {}) or {}
    asr_conf = float(asr_meta.get("asr_confidence", 0.0) or 0.0)
    if text and asr_conf < ASR_MIN_CONF:
        text = ""

    if text and not contains_domain_tokens(text) and asr_conf < ASR_STRICT_MIN_CONF and len(text.replace(" ", "")) <= 8:
        text = ""

    if text and is_likely_hallucination(text, asr_meta):
        text = ""

    if text and latin_ratio(text) > MAX_LATIN_RATIO:
        text = ""

    # Suppress ultra-short, non-domain fragments (common in noisy mic capture).
    if text and len(text.replace(" ", "")) < 3 and not contains_domain_tokens(text):
        text = ""

    # Do not hard-drop non-domain transcript; keep text for LLM semantic matching.
    # Domain tokens can still be used by upper layers as a soft signal.
    tone = analyze_tone(sv.get("emotion", ""), sv.get("emotion_probs", {}))
    tone_score = float(tone["tone_score"])

    if text:
        llm, llm_window_text = analyze_semantics(text, recent_texts)
        iscore = semantic_tension_score(llm["intent"], llm["coercion"])
    else:
        llm_window_text = ""
        llm = dict(DEFAULT_SEMANTIC_ANALYSIS)
        iscore = 0.0

    tension = update_tension(
        prev_tension,
        llm.get("intent", ""),
        iscore,
        llm.get("confidence", 0.0),
        tone_score,
    )

    kid_emotion_state = tension_to_kid_emotion_state(tension)
    result = {
        "raw_text": raw_text,
        "text": text,
        "semantic_analysis": llm,
        "tone_analysis": tone,
        "emotion": kid_emotion_state,
        "kidEmotionState": kid_emotion_state,
        "speechEmotion": tone["emotion"],
        "emotion_probs": tone["emotion_probs"],
        "asr": asr_meta,
        "llm": llm,
        "llm_window_text": llm_window_text,
        "tension": tension
    }
    return result, tension

if __name__ == "__main__":
    Path("Assets/MyAssests/Analysis/out").mkdir(parents=True, exist_ok=True)
    wav = "Assets/MyAssests/Analysis/audio/sample.wav"
    res, _ = fuse_once(wav)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    with open("Assets/MyAssests/Analysis/out/last_result.json","w",encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
