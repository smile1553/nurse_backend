import unittest
from intent_rules import apply_intent_rules, is_apology, is_polite_request


def llm(intent, toxicity=0.0, coercion=0.0):
    return {"intent": intent, "action_tag": intent, "sentiment": "negative",
            "toxicity": toxicity, "coercion": coercion, "confidence": 0.9, "keywords": []}


class PoliteRequests(unittest.TestCase):
    # Sentences from the 2026-10/11 practice logs that were labelled command / force.
    CASES = [
        "我們先幫小省量體溫好不好",
        "芽芽你可以先躺下來嗎",
        "我們先幫熊熊兩耳聞好不好一下子就好了",
        "我們先幫熊熊量耳溫好不好",
        "琴雅芽幫熊熊先量耳溫好不好",
        "那我們現在幫熊熊量體溫好嗎",
        "我們會你有逼逼過嗎我們拿耳溫槍往耳朵裏逼逼一下那我先逼一下我自己好嗎",
    ]

    def test_become_reassure(self):
        for text in self.CASES:
            for intent in ("command", "force"):
                out = apply_intent_rules(llm(intent, coercion=0.8), text)
                self.assertEqual(out["intent"], "reassure", text)
                self.assertLessEqual(out["coercion"], 0.3)

    def test_harsh_requests_stay(self):
        for text in ["你快點躺下來好不好", "不要再哭了好不好", "你再不配合我就叫醫生來好嗎",
                     "給我躺好可以嗎", "你怎麼這麼不乖啊好不好"]:
            self.assertFalse(is_polite_request(text), text)
            self.assertEqual(apply_intent_rules(llm("command"), text)["intent"], "command", text)

    def test_plain_commands_stay(self):
        for text in ["不要亂動，快一點。", "躺下", "你快點平靜一點"]:
            self.assertEqual(apply_intent_rules(llm("command"), text)["intent"], "command", text)

    def test_threat_is_not_softened_by_politeness(self):
        # Only apologies may soften a threat; a polite ending alone must not.
        self.assertEqual(apply_intent_rules(llm("threat", 0.7), "你這樣很不乖耶我們打針好不好")["intent"], "threat")


class Apologies(unittest.TestCase):
    CASES = [
        "對不起亞亞我們剛剛太兇了",
        "盧奇亞亞姐姐剛剛太兇了對不起",
        "不好意思我剛剛太大聲了",
        "對不起芽芽",
        "姐姐剛剛太兇了我們慢慢來",
    ]

    def test_become_reassure(self):
        for text in self.CASES:
            out = apply_intent_rules(llm("threat", toxicity=0.8), text)
            self.assertEqual(out["intent"], "reassure", text)
            self.assertLessEqual(out["toxicity"], 0.1)

    def test_scolding_with_sorry_stays(self):
        for text in ["對不起喔但是你再哭我就叫醫生", "不好意思你怎麼這麼不乖"]:
            self.assertFalse(is_apology(text), text)
            self.assertEqual(apply_intent_rules(llm("threat", 0.8), text)["intent"], "threat", text)

    def test_unrelated_labels_untouched(self):
        self.assertEqual(apply_intent_rules(llm("neutral"), "對不起剛剛太兇了")["intent"], "neutral")
        self.assertEqual(apply_intent_rules(llm("encourage"), "芽芽好棒好不好")["intent"], "encourage")


if __name__ == "__main__":
    unittest.main()
