"""Deterministic corrections applied after the LLM intent analysis.

Two mistakes were seen in the real practice logs (2026-10 ~ 2026-11):

1. Polite requests ("我們先幫熊熊量耳溫好不好", "芽芽你可以先躺下來嗎") were labelled
   command / force, which raised Yaya's tension although the nurse was asking for consent.
2. Apologies ("對不起芽芽我們剛剛太兇了") were labelled threat because of words like 太兇.

The rules only ever move a label toward the positive side, and never when the sentence
also contains a real scolding / threat / hurry-up word, so harsh speech is still caught.
"""
import re
from typing import Dict

# Words that show the sentence really is harsh: if any is present, no rule applies.
HARSH_RE = re.compile(
    r"不乖|很醜|好醜|醜死|白癡|笨蛋|煩不煩|煩死|吵死|閉嘴|不准|不許|給我|快一點|快點|快啦|"
    r"再哭|不要再哭|一直哭|叫醫生|要打針了|打你|罵你|揍|兇你|耳光|生氣了喔|"
    r"不然|否則|再不|不聽話|怎麼這麼|怎麼可以"
)

# Asking for consent / inviting: the sentence ends with (or contains) a question that lets
# the child choose.
POLITE_RE = re.compile(
    r"好不好|好嗎|好嘛|可以嗎|可不可以|可以.{0,12}嗎|要不要|想不想|願不願意|"
    r"一起.{0,8}(好嗎|好不好|吧)|我們先.{0,15}(好嗎|好不好|吧)|請.{0,4}(你|妳|芽芽|媽媽)"
)

# Apologising / taking back earlier harsh words.
APOLOGY_RE = re.compile(r"對不起|不好意思|抱歉|sorry", re.IGNORECASE)
# Admitting one's own harshness without the word "sorry" (also catches a misheard 對不起):
# "姐姐剛剛太兇了", "我剛才太大聲了".
SELF_ADMIT_RE = re.compile(r"(我|我們|姐姐|阿姨|哥哥)(剛剛|剛才)?(太|很|有點)(兇|凶|大聲)")
APOLOGY_REASON_RE = re.compile(r"剛剛|剛才|太兇|太凶|兇|凶|大聲|生氣|嚇到|讓你難過|讓妳難過")

# Phrases that would look harsh but are only being quoted inside an apology.
APOLOGY_HARSH_OK = ("太兇", "太凶", "很兇", "很凶")

# Full phrases only, so an additional command or threat cannot be softened.
EAR_TEMPERATURE_CORRECTIONS = (
    (re.compile(r"(?:耳溫槍)?嗶(?:一聲|一下)就好(?:了)?[喔哦囉]?"), "reassure", "temp_reassurance"),
    (re.compile(r"(?:我們)?(?:先)?幫熊熊(?:先)?量(?:一下)?耳溫[吧喔哦囉]?"), "neutral", "role_play_temp"),
    (re.compile(r"要不要(?:也)?量(?:一下)?耳溫[呢呀喔]?"), "reassure", "temp_reassurance"),
)


def _has_harsh(text: str, ignore: tuple = ()) -> bool:
    for m in HARSH_RE.finditer(text):
        if m.group(0) not in ignore:
            return True
    return False


def is_apology(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if SELF_ADMIT_RE.search(t):
        return not _has_harsh(t, APOLOGY_HARSH_OK)
    if not APOLOGY_RE.search(t):
        return False
    if not APOLOGY_REASON_RE.search(t):
        # "對不起" alone is still an apology when it is short (e.g. "對不起芽芽").
        if len(t) > 12:
            return False
    return not _has_harsh(t, APOLOGY_HARSH_OK)


def is_polite_request(text: str) -> bool:
    t = (text or "").strip()
    if not t or not POLITE_RE.search(t):
        return False
    return not _has_harsh(t)


def apply_intent_rules(data: Dict, text: str) -> Dict:
    """Return a copy of the normalized LLM result with local corrections applied."""
    out = dict(data or {})
    intent = out.get("intent", "neutral")
    t = (text or "").strip()

    if intent in ("threat", "force", "command"):
        phrase = re.sub(r"\s+", "", t.strip("。？！?!"))
        for pattern, corrected_intent, action_tag in EAR_TEMPERATURE_CORRECTIONS:
            if pattern.fullmatch(phrase):
                out.update(intent=corrected_intent, action_tag=action_tag, sentiment="neutral",
                           toxicity=0.0, coercion=0.0, rule="ear_temperature_phrase")
                return out

    if intent in ("threat", "force", "command") and is_apology(t):
        out["intent"] = "reassure"
        out["action_tag"] = "reassure_child"
        out["sentiment"] = "positive"
        out["toxicity"] = min(float(out.get("toxicity", 0.0)), 0.1)
        out["coercion"] = min(float(out.get("coercion", 0.0)), 0.1)
        out["rule"] = "apology"
        return out

    if intent in ("command", "force") and is_polite_request(t):
        out["intent"] = "reassure"
        if out.get("action_tag") in (None, "", "neutral", "command", "force"):
            out["action_tag"] = "ask_consent"
        if out.get("sentiment") == "negative":
            out["sentiment"] = "neutral"
        out["coercion"] = min(float(out.get("coercion", 0.0)), 0.3)
        out["rule"] = "polite_request"
        return out

    return out
