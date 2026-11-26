import unittest

from tone_guard import apply_tone_guard, check_before_llm, guard_intent
from intent_rules import apply_intent_rules


def llm(intent):
    return {"intent": intent, "action_tag": intent, "sentiment": "neutral",
            "toxicity": 0.0, "coercion": 0.0, "confidence": 0.9, "keywords": []}


def judged(text, intent):
    return guard_intent(text, intent)[0]


class NotTheStudent(unittest.TestCase):
    def test_asr_noise_is_skipped(self):
        for text in ["是位於美國地區。", "位於美國市政府。", "唐代的譽。", "俄羅斯的"]:
            self.assertEqual(check_before_llm(text), "asr_noise", text)

    def test_game_voice_lines_are_skipped(self):
        for text in ["好的麻煩你了", "芽芽以爲你們一進來就是要打針", "討厭你", "我不想要不想要我不要討厭你",
                     "你看有貼紙耶 那我們讓姐姐嚷一下好不好", "你怎麼這麼沒禮貌", "那你要輕輕的綁喲",
                     "我說我不要", "我不要 我不要打消", "我要怕我"]:
            self.assertEqual(check_before_llm(text), "game_voice_line", text)

    def test_student_lines_are_not_mistaken_for_game_lines(self):
        for text in ["你要量哪一隻耳朵", "芽芽想要量哪一隻耳朵呢", "媽媽沒關係的芽芽會怕是正常的",
                     "我也討厭你", "姐姐跟媽媽在這裏陪你"]:
            self.assertIsNone(check_before_llm(text), text)

    def test_jokes_and_game_operation(self):
        for text in ["給我一百萬", "跳過", "下壓", "幫我預測明天台股會漲還是跌", "你可以跟楊志宇在一起"]:
            self.assertEqual(judged(text, "command"), "neutral", text)


class MissedPressure(unittest.TestCase):
    # Sentences from the 2026-11 logs that the LLM labelled neutral.
    THREATS = ["你只會哭還會幹嘛", "聽得懂人話嗎", "你是白癡嗎", "你長得好醜哦", "是屁孩",
               "這小孩是怎樣啊", "你這個爸媽怎麼教小孩的啊只會哭還會幹嘛", "妳在哭我就叫醫生來打針哦",
               "我等一下叫醫生進來打針哦", "不乖的話貼紙我就要拿回來囉", "不聽話小朋友沒有貼紙",
               "都四歲了還在玩熊熊", "姐姐很忙沒有時間一直等你哦", "等一下就插進你的耳朵裏爆炸",
               "空氣的時候會很緊會超級痛喔會痛到哭喔", "我要叫楊志宇過來了", "不要去滾出去滾出這個醫院"]

    def test_become_threat(self):
        for text in self.THREATS:
            self.assertEqual(judged(text, "neutral"), "threat", text)

    def test_force(self):
        for text in ["媽媽你把他押注", "沒有再問你就是要量血壓", "你說你不要就不要喔", "不管你要不要今天就是一定要量",
                     "不管你今天要不要 今天一定要兩碗的人走", "你同不同意都沒差現在就要量"]:
            self.assertEqual(judged(text, "command"), "force", text)

    def test_harsh_part_wins_over_nice_words(self):
        self.assertEqual(judged("我已經給你貼紙了 快點配合 請你配合 如果你不配合 我就要叫醫生來打針了。", "encourage"), "threat")
        self.assertEqual(judged("我也討厭你啊幹嘛又不涼又不會痛", "reassure"), "threat")
        self.assertEqual(judged("給我配合好不好", "reassure"), "command")


class WronglyRaised(unittest.TestCase):
    def test_exact_ear_temperature_demo_keeps_its_neutral_correction(self):
        text = "幫熊熊量耳溫"
        corrected = apply_intent_rules(llm("command"), text)
        result = apply_tone_guard(corrected, text)
        self.assertEqual(result["intent"], "neutral")
        self.assertEqual(result["action_tag"], "role_play_temp")
        self.assertNotIn("guard_rule", result)

        # A following threat must still override even an earlier correction.
        threatened = apply_tone_guard(corrected, text + "，再哭我就叫醫生來打針")
        self.assertEqual(threatened["intent"], "threat")
        self.assertEqual(threatened["guard_rule"], "pressure_phrase")
        # General comforting speech keeps the existing positive behavior.
        self.assertEqual(judged("那我們現在幫熊熊量體溫好嗎", "command"), "reassure")

    def test_beep_and_explanations_are_not_pressure(self):
        self.assertEqual(judged("而溫槍逼一下就好了哦", "command"), "reassure")
        self.assertEqual(judged("逼一下就好了很快不會痛", "force"), "reassure")
        self.assertEqual(judged("要不要也兩耳光呢小時候很棒耶", "threat"), "encourage")
        self.assertEqual(judged("我們現在要來量生命徵象", "command"), "neutral")
        self.assertEqual(judged("那我們現在幫熊熊量體溫好嗎", "command"), "reassure")

    def test_comfort_with_instruction_stays_positive(self):
        self.assertEqual(judged("等一下只會緊緊的不會痛知道嗎手伸出來", "reassure"), "reassure")


class MissedPraise(unittest.TestCase):
    def test_become_positive(self):
        for text in ["給你貼紙", "你好乖哦你很乖啊", "芽芽你的體溫是三六二你很棒哦", "拉耳朵比較準不會痛"]:
            self.assertIn(judged(text, "neutral"), ("encourage", "reassure"), text)


class Untouched(unittest.TestCase):
    def test_correct_labels_are_kept(self):
        cases = [("芽芽你最棒了", "encourage"), ("聽診器不會痛一下下就好了喔", "reassure"),
                 ("再哭我就要叫醫生來打針了", "threat"), ("不要再哭了", "command"),
                 ("媽媽想問一下芽芽平常喜歡什麼呢", "neutral"), ("你別哭", "reassure")]
        for text, intent in cases:
            self.assertEqual(guard_intent(text, intent), (intent, None), text)

    def test_result_records_the_change(self):
        out = apply_tone_guard(llm("neutral"), "你只會哭還會幹嘛")
        self.assertEqual(out["intent"], "threat")
        self.assertEqual(out["guard_from"], "neutral")
        self.assertEqual(out["guard_rule"], "pressure_phrase")


if __name__ == "__main__":
    unittest.main()
