"""Second-pass checks on the intent label, run after the LLM and intent_rules.

Why this file exists (measured on 1,749 logged sentences, 2026-10 ~ 2026-11):

* Scolding without a fixed threat pattern was left as neutral
  ("你只會哭還會幹嘛", "聽得懂人話嗎", "你是白癡嗎", "都四歲了還在哭").
* A harsh sentence that also had a nice word was labelled positive
  ("我已經給你貼紙了 快點配合 ... 我就要叫醫生來打針了" -> encourage).
* "好不好 / 請" softened real commands ("給我配合好不好" -> reassure).
* The game's own mother / Yaya lines were picked up by the microphone and judged
  as if the student had said them ("討厭你" -> threat).
* ASR hallucinations ("是位於美國地區。") were sent to the LLM.
* Same-sound errors hid threats ("妳在哭我就叫醫生" vs "再哭").

intent_rules.py only moves labels toward the positive side. This module can move a
label in either direction, but every rule is a fixed phrase list, so a change can be
traced to one pattern. ``check_before_llm`` lets the caller skip the LLM entirely for
noise and game lines.

Intents: reassure, encourage, neutral, command, force, threat.
"""
import re
from difflib import SequenceMatcher
from typing import Dict, Optional, Tuple

NEGATIVE = ("command", "force", "threat")
POSITIVE = ("reassure", "encourage")

# ---------------------------------------------------------------------------
# 1. Normalisation used only for matching (the displayed transcript is untouched).
# ---------------------------------------------------------------------------
_CHAR = str.maketrans({"爲": "為", "裏": "裡", "着": "著", "纔": "才", "喫": "吃",
                       "妳": "你", "她": "他", "牠": "他"})
_PHRASE_FIXES = [
    (r"[。，,．.！!？? 　、]", ""),
    (r"(亞牙|雅芽|咬牙|亞亞|啞牙|野芽芽|押押|爺爺)", "芽芽"),
    (r"在(哭|鬧|吵|亂動|不乖|不配合)", r"再\1"),          # 再 / 在 sound the same
    (r"(兩|涼|良|糧|娘|嚷)(耳聞|耳溫|耳蝸|耳問)", "量耳溫"),
    (r"兩耳光", "量耳溫"),
    (r"(涼|兩|糧|嚷)(體溫|血壓|呼吸|一下)", r"量\2"),
    (r"不會(透|跳)", "不會痛"),
    (r"給你窮", "給你熊"),
    (r"(羊|楊|揚|養)(志宇|之餘|志於|紫玉|智宇|致宇|致於|字與|子魚|脂魚|隻魚|痣魚|痣 魚)", "楊志宇"),
    (r"(押注|壓注)", "壓住"),
    (r"抵碎", "四歲"),
    (r"(帖子|貼子|帖紙|約紙|貼職|貼紙業|天職)", "貼紙"),
    (r"馬寶", "媽寶"),
    (r"一下面$", "一下而已"),
    (r"逼(神|聲)", "逼一聲"),
]


def normalize(text: str) -> str:
    t = (text or "").translate(_CHAR)
    for pattern, repl in _PHRASE_FIXES:
        t = re.sub(pattern, repl, t)
    return t


# ---------------------------------------------------------------------------
# 2. Not the student: ASR hallucinations and the game's own voice lines.
# ---------------------------------------------------------------------------
_NOISE_RE = re.compile(
    r"(位於|美國|市政府|俄羅斯|唐人|英國人|島市|島民|唐代的譽|瑞典動物|為食動物|生動物)"
    r"|^(是大的|大的|是阿|萊斯|伊姆|萊姆|遠崖|唐好|阿夫|是者|是利|是茲)$")

# Mother / Yaya lines spoken by the game (seen in sessions where the student was silent).
NPC_LINES = [
    "好的麻煩你了", "我不要打針", "芽芽以為你們一進來就是要打針", "姐姐在旁邊看我們就好",
    "在旁邊看我們就好", "我才不要", "我生了不要", "有貼紙耶我們讓姐姐聽聽",
    "有貼紙耶那我們讓姐姐量一下好不好", "芽芽當醫生聽媽媽的心跳來聽診器給你",
    "有沒有聽到撲通撲通的聲音", "芽芽的耳朵痛痛", "芽芽你別怕媽媽在這裡陪你",
    "我不要呀小熊也不要", "我不想要不想要我不要討厭你", "我們的芽芽那麼勇敢",
    "只有冰冰的感覺不會痛痛一下下就好了", "嗚嗚媽咪爸爸",
    "跟小熊一樣棒棒噠讓姐姐也量一下體溫好不好", "姐姐要量哪一隻耳朵呢",
    "芽芽之前有量過血壓因為充氣的時候會緊緊的", "他就一直掙扎說會痛之後他就蠻排斥量血壓的",
    "請問他可以不要量血壓嗎", "那你要輕輕的綁喲", "你怎麼這麼沒禮貌",
    "我不要我不要打針", "我想要不想要也不要討厭你",
]
_NPC_NORM = [normalize(x) for x in NPC_LINES]
_NPC_SHORT = {"討厭你", "小熊也不要", "小小也不要", "耳朵痛痛", "走開", "可以不要量血壓嗎", "我不要討厭你",
              "我說我不要", "我不要我說我不要", "我要怕", "我會怕", "我要怕我", "我要怕呀", "我不要啊", "我不要打針"}
NPC_MATCH_RATIO = 0.8


def is_noise(text: str) -> bool:
    return bool(_NOISE_RE.search(normalize(text)))


def is_npc_line(text: str) -> bool:
    n = normalize(text)
    if n in _NPC_NORM or n in _NPC_SHORT:
        return True
    if len(n) >= 8:
        return any(SequenceMatcher(None, n, c).ratio() >= NPC_MATCH_RATIO
                   for c in _NPC_NORM if len(c) >= 8)
    return False


# ---------------------------------------------------------------------------
# 3. Jokes, operating the game, reading answer options.
# ---------------------------------------------------------------------------
_OFFTASK_RE = re.compile(
    r"^(跳過|下壓|呼吸|下一步|不行|不正確.{0,4}|可以跳.*|過了過了|向上向後)$"
    r"|給我(一百萬|一億|一兆|一千萬|一張台積電)|^去付錢$|^丟五千$|^(就)?給我一億$"
    r"|台股|美股|收盤|跟楊志宇在一起|^好啦拜拜$")

# ---------------------------------------------------------------------------
# 4. Pressure. If any of these is present the sentence counts as pressure, even
#    when it also contains 貼紙 / 不會痛 / 好不好.
# ---------------------------------------------------------------------------
FORCE_RE = re.compile(
    r"不管你.{0,4}要不要|你同不同意|沒有說不要的權利|沒有(在|再)問你|說.{0,2}不要就不要|就是要量|一定要量|哭也要量|"
    r"(壓住|抓住|按住)(他|芽芽)?|我叫你.{0,4}就.{0,4}|直接(夾|量|綁)上去")
THREAT_RE = re.compile(
    # conditional threats / consequences
    r"再(哭|鬧|吵|亂動|不乖|不配合|不好好配合).{0,12}(就|我就|的話)|"
    r"(不乖|不配合|不聽話|不好好配合).{0,10}(就|的話|沒有)|"
    r"(就|我就|我要|我只好)(叫|找|請)(醫生|楊志宇)|叫(醫生|楊志宇|護士).{0,6}(過來|進來|打針|抓)|醫生.{0,6}打針|"
    r"賣掉|賣給|綁起來|綁走|關起來|不能回家|請你回家|就回家|回家自己哭|你就離開|一個人(住|留)|不要你了|滾出|"
    r"加護病房|辦理出院|我就走開|"
    # taking rewards back
    r"(貼紙|糖果).{0,6}(拿回來|沒有了|就沒有)|沒有貼紙|不給你貼紙|騙你的沒有|"
    # put-downs and scolding
    r"只會(哭|不要|說痛).{0,3}還會幹嘛|人話|白癡|白吃|白痴|醜|屁孩|媽寶|幼稚|很煩|"
    r"沒禮貌|什麼態度|難搞|怎麼教|是怎樣|太壞|不乖|沒有很乖|不可以喔|不能一直哭|"
    r"一點都不(棒|酷)|不棒|超爛|沒救|討厭你|閉嘴|吵死|草死|你吵(什麼|啥)|太吵|吵鬧|"
    r"哭爽|爽了沒|不爽|腦殘|快死了|"
    r"(\d|四|五|幾|這麼大)歲?了還|這麼大了還|都(四|幾)歲了|羞羞臉|沒(有)?時間(一直)?等你|時間很多嗎|"
    r"故意的|講不聽|有什麼好哭|哭可以解決|一直哭(是要|要怎麼|幹嘛|有什麼)|哭了一直哭|還在哭|"
    r"都給你.{0,4}了(還|不要)|都拿給你看了還|叫我要怎麼|就跟你說|^再(哭|吵|鬧)$|"
    r"不想幫你|沒有很想幫你|才不要幫|來醫院幹嘛|"
    # frightening the child
    r"爆炸|炸飛|插進|扎進|超級痛|痛到哭|專門(治|治療)")
COMMAND_RE = re.compile(
    r"給我(坐好|做好|躺好|安靜|配合|閉嘴|起立|乖乖|做|裝)|快點|快一點|趕快|不准|塞進去|"
    r"^(安靜|坐下|站起來|答我)$|不要(動|晃|拖)|別晃|"
    r"(手|耳朵).{0,4}(伸出來|指出來)|給我躺好|你配合一下|配合一下吧|"
    r"請(坐下|你聽話)|我命令|我叫你")
# Bare "別哭 / 不要再哭了" is left to the LLM: it can be a comfort or an order.

# ---------------------------------------------------------------------------
# 5. Comfort and praise.
# ---------------------------------------------------------------------------
SOOTHE_RE = re.compile(
    r"(逼|比|嗶)一(下|聲)(就好|而已|正好)|不會(痛|燙)|一下(下|子)?就好|很快|別怕|不要怕|不用怕|"
    r"不要緊張|別緊張|不用擔心|沒事|陪你|會怕是正常|害怕(也)?是正常|一下(下)?而已|深呼吸|冷靜一下|"
    r"最後一次|跟(熊熊|小熊|他)(講|說)|幫(熊熊|小熊)量|聽兒歌")
PRAISE_RE = re.compile(
    r"很棒|好棒|超棒|最棒|結棒|很乖|好乖|超乖|最乖|勇敢|厲害|一級棒|好讚|(給你|送你).{0,4}貼紙|貼紙給你|當獎勵")

# Explaining the next step ("我們現在要來量體溫").
PROCESS_RE = re.compile(r"^(芽芽)?(我們)?(現在|等一下|接下來|下一個)?(要|應該)?來?量")
GENTLE_ASK_RE = re.compile(r"要不然|好不好|好嗎|可以.{0,8}嗎")


def check_before_llm(text: str) -> Optional[str]:
    """Return a rule name when the sentence should not be judged at all."""
    if is_noise(text):
        return "asr_noise"
    if is_npc_line(text):
        return "game_voice_line"
    if _OFFTASK_RE.search(normalize(text)):
        return "off_task"
    return None


def guard_intent(text: str, intent: str) -> Tuple[str, Optional[str]]:
    """Return (intent, rule). rule is None when the intent is kept."""
    skip = check_before_llm(text)
    if skip:
        return ("neutral", skip) if intent != "neutral" else (intent, None)

    t = normalize(text)
    joke_yang = re.search(r"楊志宇", t) and re.search(r"貼紙|鼓勵|熊熊|示範", t)
    if FORCE_RE.search(t):
        new = "force"
    elif THREAT_RE.search(t) and not joke_yang:
        new = "threat"
    elif COMMAND_RE.search(t):
        # An instruction wrapped in comfort ("不會痛喔，手伸出來") is judged as comfort below.
        new = None if (PRAISE_RE.search(t) or SOOTHE_RE.search(t)) else "command"
    else:
        new = None
    if new:
        return (new, "pressure_phrase") if new != intent else (intent, None)

    if PRAISE_RE.search(t):
        return ("encourage", "praise_phrase") if intent not in POSITIVE else (intent, None)
    if SOOTHE_RE.search(t):
        return ("reassure", "comfort_phrase") if intent not in POSITIVE else (intent, None)
    if intent in NEGATIVE and (PROCESS_RE.search(t) or GENTLE_ASK_RE.search(t)):
        return ("neutral", "explain_or_gentle_ask")
    return (intent, None)


# Toxicity / coercion values written when a rule raises or lowers the label.
_SCORES = {
    "threat": {"sentiment": "negative", "toxicity": 0.7, "coercion": 0.5},
    "force": {"sentiment": "negative", "toxicity": 0.4, "coercion": 0.8},
    "command": {"sentiment": "negative", "toxicity": 0.2, "coercion": 0.6},
    "reassure": {"sentiment": "positive", "toxicity": 0.0, "coercion": 0.0},
    "encourage": {"sentiment": "positive", "toxicity": 0.0, "coercion": 0.0},
    "neutral": {"sentiment": "neutral", "toxicity": 0.0, "coercion": 0.0},
}


def apply_tone_guard(data: Dict, text: str) -> Dict:
    """Return a copy of the semantic result with the guard applied."""
    out = dict(data or {})
    intent = out.get("intent", "neutral")
    new, rule = guard_intent(text, intent)
    # Keep the exact ear-temperature demonstration correction from intent_rules.
    # Pressure rules still take precedence over this broad comfort match.
    if (rule == "comfort_phrase" and intent == "neutral"
            and out.get("rule") == "ear_temperature_phrase"
            and out.get("action_tag") == "role_play_temp"):
        return out
    if rule is None:
        return out
    out["guard_from"] = intent
    out["guard_rule"] = rule
    out["intent"] = new
    if out.get("action_tag") in (None, "", "neutral", intent):
        out["action_tag"] = new
    out.update(_SCORES[new])
    return out
