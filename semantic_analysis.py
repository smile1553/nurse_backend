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
        "reassure": -1.0,
        "praise": -0.8,
        "explain": -0.4,
        "distract": -0.2,
        "ask_consent": -0.3,
        "command": 0.7,
        "threaten": 2.0,
    }
    return table.get(intent, 0.0) + 0.8 * float(coercion)


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
