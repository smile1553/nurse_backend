import os, json, re
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import openai

load_dotenv()

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "2.5"))
LLM_CACHE_SIZE = int(os.getenv("LLM_CACHE_SIZE", "256"))
_LLM_CACHE = OrderedDict()
API_KEY_TEMPLATE_VALUE = "PASTE_YOUR_OPENAI_API_KEY_HERE"


FALLBACK = {
    "intent": "explain",
    "action_tag": "neutral",
    "sentiment": "neutral",
    "toxicity": 0.0,
    "coercion": 0.0,
    "confidence": 0.0,
    "keywords": []
}

ALLOWED_INTENTS = {"reassure", "distract", "command", "threaten", "explain", "ask_consent", "praise", "neutral"}
ALLOWED_ACTION_TAGS = {
    "neutral",
    "reassure",
    "distract",
    "command",
    "ask_consent",
    "praise",
    "ask_preference",
    "calm_guidance",
    "coach_comfort_words",
    "delay_temp_exam",
    "engagement_strategy",
    "explain_resp_first",
    "introduce_bp_exam",
    "invite_bp_cooperation",
    "practice_before_exam",
    "praise_child",
    "reassure_child",
    "reduce_fear",
    "role_play_demo",
    "role_play_temp",
    "temp_reassurance",
    "transition_to_temp",
    "closing_praise",
    "scenario_wrap_up",
}
INTENT_ALIASES = {
    "comfort": "reassure",
    "安撫": "reassure",
    "轉移注意": "distract",
    "同意確認": "ask_consent",
    "ask consent": "ask_consent",
    "instruction": "command",
    "命令": "command",
    "解釋": "explain",
    "稱讚": "praise",
    "威脅": "threaten",
}
ACTION_TAG_ALIASES = {
    "greet_and_introduce": "introduce_bp_exam",
    "greeting": "introduce_bp_exam",
    "intro": "introduce_bp_exam",
    "introduce_exam": "introduce_bp_exam",
    "介紹檢查": "introduce_bp_exam",
    "介紹血壓": "introduce_bp_exam",
    "說明先觀察呼吸": "explain_resp_first",
    "先觀察呼吸": "explain_resp_first",
    "呼吸優先": "explain_resp_first",
    "安撫引導": "calm_guidance",
    "同意確認": "ask_consent",
    "詢問喜好": "ask_preference",
    "分散注意": "engagement_strategy",
    "貼紙鼓勵": "reduce_fear",
    "角色扮演示範": "role_play_demo",
    "角色扮演量體溫": "role_play_temp",
    "耳溫安撫": "temp_reassurance",
    "延後耳溫": "delay_temp_exam",
    "轉換到耳溫": "transition_to_temp",
    "鼓勵量血壓": "invite_bp_cooperation",
    "說明量血壓": "introduce_bp_exam",
    "收尾稱讚": "closing_praise",
}
SENTIMENT_ALIASES = {
    "pos": "positive",
    "neg": "negative",
    "中性": "neutral",
    "正向": "positive",
    "負向": "negative",
}
ALLOWED_SENTIMENTS = {"positive", "neutral", "negative"}
KEYWORD_ALIASES = {
    "雅瑤": "芽芽",
    "丫丫": "芽芽",
    "鴨鴨": "芽芽",
    "馬小芽": "芽芽",
    "媽咪": "媽媽",
}
LLM_MIN_CONF = float(os.getenv("LLM_MIN_CONF", "0.40"))


def _read_key_file(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        key = data.get("apiKey") or data.get("OPENAI_API_KEY")
        if not isinstance(key, str):
            return None
        key = key.strip()
        if not key or key == API_KEY_TEMPLATE_VALUE:
            return None
        return key
    except Exception as e:
        print(f"[intent_llm] failed to read {os.path.basename(path)}: {e}")
        return None


def ensure_api_key_template(path: str) -> bool:
    """Create a safe API-key template once; never overwrite an existing file."""
    if os.path.exists(path):
        return False
    try:
        with open(path, "x", encoding="utf-8") as f:
            json.dump({"apiKey": API_KEY_TEMPLATE_VALUE}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"[intent_llm] created API key template: {path}")
        return True
    except FileExistsError:
        return False
    except OSError as e:
        print(f"[intent_llm] failed to create API key template: {e}")
        return False


def load_api_key() -> Optional[str]:
    base = os.path.dirname(__file__)
    legacy_key_path = os.path.join(base, "openai_api.json")
    ensure_api_key_template(legacy_key_path)

    # 對新手友善：優先本地檔案
    local_key = _read_key_file(os.path.join(base, "openai_api.local.json"))
    if local_key:
        return local_key

    # 其次是環境變數
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 最後相容舊檔名
    return _read_key_file(legacy_key_path)


api_key = load_api_key()
if api_key:
    openai.api_key = api_key
else:
    print("[intent_llm] API key missing, fallback mode enabled.")


class IntentSchema(BaseModel):
    intent: str = Field(description="reassure|distract|command|threaten|explain|ask_consent|praise|neutral")
    action_tag: str = Field(description="specific scenario semantic tag in snake_case; use neutral if unclear")
    sentiment: str = Field(description="positive|neutral|negative")
    toxicity: float
    coercion: float
    confidence: float
    keywords: List[str]


SYSTEM_PROMPT = (
    "你是兒科護理情境的語言分析器。輸入包含 previous_utterance（前一句）與 current_utterance（當前句）。"
    "請用 previous_utterance 協助理解當前句，但最終 intent 必須對應 current_utterance。"
    "除了 general intent，還要輸出更具體的 action_tag，專門描述這句話在兒科護理教學劇情中的行動語意。"
    "intent 要選最通用的語用目的，例如 reassure、explain、ask_consent；"
    "action_tag 要盡量選更貼近教案步驟的細分類。若一句話同時符合通用 intent 與特定教案行動，"
    "intent 保持通用類別，action_tag 選最具體的教案標籤，不要把兩者混為一談。"
    "action_tag 優先從以下集合選擇：introduce_bp_exam、explain_resp_first、calm_guidance、ask_preference、engagement_strategy、"
    "role_play_demo、reduce_fear、praise_child、transition_to_temp、reassure_child、delay_temp_exam、role_play_temp、"
    "practice_before_exam、coach_comfort_words、temp_reassurance、invite_bp_cooperation、closing_praise、scenario_wrap_up、"
    "ask_consent、reassure、distract、praise、command、neutral。"
    "如果輸入有 current_step_id、player_prompt、expected_intents，請把它們當成當前教案上下文來判斷 action_tag。"
    "如果句子太模糊或不屬於任何具體劇情行動，就用 neutral。"
    "只輸出 JSON：intent（reassure|distract|command|threaten|explain|ask_consent|praise|neutral）、action_tag、"
    "sentiment（positive|neutral|negative）、toxicity(0~1)、coercion(0~1)、"
    "confidence(0~1)、keywords（字串陣列）。只回 JSON，勿包含其他文字。"
)



def _cache_key(prev: str, current: str, context: Optional[Dict[str, Any]] = None) -> str:
    ctx = ""
    if context:
        try:
            ctx = json.dumps(context, ensure_ascii=False, sort_keys=True)
        except Exception:
            ctx = str(context)
    return f"{(prev or '').strip()}||{(current or '').strip()}||{ctx}"


def _cache_get(key: str):
    if key in _LLM_CACHE:
        val = _LLM_CACHE.pop(key)
        _LLM_CACHE[key] = val
        return val
    return None


def _cache_set(key: str, value: dict) -> None:
    _LLM_CACHE[key] = value
    while len(_LLM_CACHE) > max(1, LLM_CACHE_SIZE):
        _LLM_CACHE.popitem(last=False)


def _extract_json_object(text: str) -> dict:
    s = (text or "").strip()
    if not s:
        raise ValueError("empty LLM response")
    if s.startswith("```"):
        s = s.strip("`")
        s = s.replace("json\n", "", 1).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            raise
        return json.loads(m.group(0))


def _to_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _normalize_intent(x: str) -> str:
    key = (x or "").strip().lower()
    mapped = INTENT_ALIASES.get(key, key)
    return mapped if mapped in ALLOWED_INTENTS else "neutral"


def _normalize_sentiment(x: str) -> str:
    key = (x or "").strip().lower()
    mapped = SENTIMENT_ALIASES.get(key, key)
    return mapped if mapped in ALLOWED_SENTIMENTS else "neutral"


def _normalize_action_tag(x: str) -> str:
    raw = (x or "").strip().lower()
    if not raw:
        return "neutral"
    raw = raw.replace("-", "_").replace(" ", "_")
    raw = ACTION_TAG_ALIASES.get(raw, raw)
    return raw if raw in ALLOWED_ACTION_TAGS else "neutral"


def _normalize_keywords(items) -> List[str]:
    if not isinstance(items, list):
        return []
    out: List[str] = []
    seen = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        k = raw.strip()
        if not k:
            continue
        k = KEYWORD_ALIASES.get(k, k)
        if len(k) > 20:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out[:8]


def normalize_llm_output(data: dict) -> dict:
    base = dict(FALLBACK)
    if not isinstance(data, dict):
        return base

    base["intent"] = _normalize_intent(data.get("intent", ""))
    base["action_tag"] = _normalize_action_tag(data.get("action_tag", ""))
    base["sentiment"] = _normalize_sentiment(data.get("sentiment", ""))
    base["toxicity"] = max(0.0, min(1.0, _to_float(data.get("toxicity", 0.0))))
    base["coercion"] = max(0.0, min(1.0, _to_float(data.get("coercion", 0.0))))
    base["confidence"] = max(0.0, min(1.0, _to_float(data.get("confidence", 0.0))))
    base["keywords"] = _normalize_keywords(data.get("keywords", []))

    if base["confidence"] < LLM_MIN_CONF and base["intent"] != "neutral":
        base["intent"] = "neutral"
        base["action_tag"] = "neutral"
    return base


def analyze_intent(recent_utterances: list[str], current: str, context: Optional[Dict[str, Any]] = None) -> dict:
    if not api_key:
        return FALLBACK.copy()

    prev = ""
    if recent_utterances:
        prev = (recent_utterances[-1] or "").strip()

    key = _cache_key(prev, current, context)
    cached = _cache_get(key)
    if cached is not None:
        return dict(cached)

    user_payload = {
        "previous_utterance": prev,
        "current_utterance": current
    }
    if context:
        for k in ("current_step_id", "player_prompt", "expected_intents"):
            v = context.get(k)
            if v:
                user_payload[k] = v
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
    ]
    try:
        resp = openai.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0,
            timeout=LLM_TIMEOUT_SEC,
        )
        txt = resp.choices[0].message.content
        raw = _extract_json_object(txt)
        data = normalize_llm_output(raw)
        IntentSchema(**data)  # 驗證格式
        _cache_set(key, data)
        return dict(data)
    except Exception as e:
        print("[LLM fallback]", e)
        return FALLBACK.copy()
