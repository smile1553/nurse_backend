from typing import Any, Dict, Mapping, Optional


DEFAULT_TONE_ANALYSIS = {
    "emotion": "neutral",
    "emotion_probs": {},
    "tone_score": 0.0,
    "confidence": 0.0,
    "available": False,
}


def _probability(values: Mapping[str, Any], *names: str) -> float:
    for name in names:
        try:
            if name in values:
                return max(0.0, min(1.0, float(values[name])))
        except (TypeError, ValueError):
            continue
    return 0.0


def analyze_tone(
    emotion: str = "",
    emotion_probs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyze how speech sounded, without using transcript semantics.

    The current ASR may not provide an emotion model. In that case this returns
    an explicit unavailable/neutral result instead of inventing a tone label.
    """
    raw_probabilities = dict(emotion_probs or {})
    probabilities: Dict[str, float] = {}
    for name, value in raw_probabilities.items():
        try:
            probabilities[str(name)] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    label = (emotion or "").strip().lower()

    angry = _probability(probabilities, "angry", "anger")
    sad = _probability(probabilities, "sad", "sadness")
    happy = _probability(probabilities, "happy", "positive")
    calm = _probability(probabilities, "calm", "neutral")
    tone_score = (angry + sad) - (happy + calm)
    confidence = max(probabilities.values(), default=0.0)

    available = bool(label or probabilities)
    if not label:
        label = max(probabilities, key=probabilities.get) if probabilities else "neutral"

    return {
        "emotion": label,
        "emotion_probs": probabilities,
        "tone_score": tone_score,
        "confidence": confidence,
        "available": available,
    }
