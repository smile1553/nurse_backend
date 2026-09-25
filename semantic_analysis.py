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

INTENT_ALIASES = {
    "praise": "encourage",
    "distract": "reassure",
    "ask_consent": "reassure",
    "explain": "neutral",
    "threaten": "threat",
}

INTENT_DELTAS = {
    "reassure": -1.0,
    "encourage": -0.5,
    "neutral": 0.0,
    "command": 0.8,
    "force": 1.2,
    "threat": 1.5,
}

def semantic_tension_score(intent: str, coercion: float) -> float:
    """Return a fixed intent delta; coercion is output metadata only."""
    intent_key = (intent or "").strip().lower()
    intent_key = INTENT_ALIASES.get(intent_key, intent_key)
    return INTENT_DELTAS.get(intent_key, 0.0)


def update_tension(
    prev_tension: float,
    intent: str,
    semantic_score: float,
    confidence: float,
    tone_score: float = 0.0,
) -> float:
    """Apply exactly one fixed intent delta and clamp tension to -5..5."""
    prev = max(-5.0, min(5.0, float(prev_tension or 0.0)))
    delta = float(semantic_score or 0.0)
    return max(-5.0, min(5.0, prev + delta))


def tension_to_patience_score(tension: float) -> float:
    value = max(-5.0, min(5.0, float(tension or 0.0)))
    return max(0.0, min(100.0, 100.0 - ((value + 5.0) * 10.0)))


def tension_to_kid_emotion_state(tension: float) -> str:
    """Map patience score to the shared Unity emotion-state thresholds."""
    score = tension_to_patience_score(tension)
    if score >= 75.0:
        return "Calm"
    if score >= 50.0:
        return "Uneasy"
    if score >= 25.0:
        return "Crying"
    return "Meltdown"


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

    return result, window_text
