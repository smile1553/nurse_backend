import os
from typing import Any, Dict, List, Optional, Tuple

from intent_llm import analyze_intent


DEFAULT_SEMANTIC_ANALYSIS = {
    "intent": "neutral",
    "action_tag": "neutral",
    "sentiment": "neutral",
    "toxicity": 0.0,
    "coercion": 0.0,
    "confidence": 0.0,
    "keywords": [],
}

RULE_OVERRIDE_MIN_SCORE = float(os.getenv("RULE_OVERRIDE_MIN_SCORE", "1.6"))
RECOVERY_INTENTS = {"reassure", "praise", "ask_consent", "distract"}
AGITATING_INTENTS = {"command", "threaten"}

INTENT_RULES = {
    "reassure": ["不會痛", "不用怕", "沒事", "別怕", "放輕鬆", "很快就好", "一下就好", "你很棒"],
    "distract": ["看這邊", "看這個", "玩具", "故事", "熊熊", "深呼吸", "唱歌"],
    "command": ["請", "先", "現在", "不要動", "坐好", "躺好", "把手", "張開嘴巴"],
    "ask_consent": ["可以嗎", "好嗎", "願意", "要不要", "行嗎", "可不可以", "你覺得"],
    "threaten": ["不乖", "打針", "不然", "處罰", "會痛死", "不聽話"],
    "praise": ["好棒", "真棒", "很勇敢", "做得好", "你好厲害"],
    "explain": ["因為", "等等", "接下來", "我們要", "檢查", "量", "這是"],
}


def semantic_tension_score(intent: str, coercion: float) -> float:
    table = {
        "reassure": -2.4,
        "praise": -2.0,
        "explain": -0.8,
        "distract": -1.2,
        "ask_consent": -1.4,
        "command": 0.7,
        "threaten": 2.4,
    }
    return table.get(intent, 0.0) + 0.8 * float(coercion)


def update_tension(
    prev_tension: float,
    intent: str,
    semantic_score: float,
    confidence: float,
    tone_score: float = 0.0,
) -> float:
    """Update child tension with faster recovery for good nursing responses."""
    intent_key = (intent or "").strip().lower()
    prev = max(-5.0, min(5.0, float(prev_tension or 0.0)))
    score = float(semantic_score or 0.0) + 0.7 * float(tone_score or 0.0)
    conf = max(0.0, min(1.0, float(confidence or 0.0)))

    if intent_key in RECOVERY_INTENTS and conf >= 0.55:
        target = min(score, -4.0)
        blend = 0.65 if conf >= 0.75 else 0.5
        updated = prev * (1.0 - blend) + target * blend
        if prev > 0.0:
            updated -= min(0.8, prev * 0.25)
        if conf >= 0.75:
            updated = min(updated, -3.2)
        return max(-5.0, min(5.0, updated))

    if intent_key in AGITATING_INTENTS:
        blend = 0.45 if intent_key == "threaten" else 0.35
        return max(-5.0, min(5.0, prev * (1.0 - blend) + score * blend))

    return max(-5.0, min(5.0, prev * 0.75 + score * 0.25))


def tension_to_kid_emotion_state(tension: float) -> str:
    """Map backend tension to the C# KidEmotionState enum thresholds."""
    value = max(-5.0, min(5.0, float(tension or 0.0)))
    score = ((value + 5.0) / 10.0) * 100.0
    if score >= 80.0:
        return "Meltdown"
    if score >= 55.0:
        return "Crying"
    if score >= 20.0:
        return "Uneasy"
    return "Calm"


def rule_based_intent(text: str) -> Optional[Tuple[str, float]]:
    value = (text or "").strip()
    if not value:
        return None

    scores: Dict[str, float] = {}
    for intent, keywords in INTENT_RULES.items():
        score = 0.0
        for keyword in keywords:
            if keyword in value:
                score += 1.0 + min(0.8, len(keyword) * 0.08)
        if score > 0:
            scores[intent] = score

    if not scores:
        return None
    best_intent = max(scores, key=scores.get)
    return best_intent, scores[best_intent]


def analyze_semantics(
    text: str,
    recent_texts: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Analyze what was said, independently from how it was spoken."""
    value = (text or "").strip()
    if not value:
        return dict(DEFAULT_SEMANTIC_ANALYSIS), ""

    history = [item for item in (recent_texts or []) if item]
    previous = history[-1] if history else ""
    window_text = f"{previous} | {value}" if previous else value
    result = analyze_intent([previous] if previous else [], value, context=context)

    rule_match = rule_based_intent(value)
    llm_confidence = float(result.get("confidence", 0.0) or 0.0)
    llm_intent = str(result.get("intent", "neutral") or "neutral")
    if rule_match is not None:
        rule_intent, rule_score = rule_match
        if llm_intent == "neutral" or llm_confidence < 0.50 or rule_score >= RULE_OVERRIDE_MIN_SCORE:
            result["intent"] = rule_intent
            if not str(result.get("action_tag", "") or "").strip() or result.get("action_tag") == "neutral":
                result["action_tag"] = rule_intent
            result["confidence"] = max(llm_confidence, min(0.85, 0.45 + rule_score * 0.18))

    return result, window_text
