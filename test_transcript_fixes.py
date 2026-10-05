import unittest

from fusion_loop import ASR_REPLACEMENTS, sanitize_transcript


class TranscriptFixTests(unittest.TestCase):
    def test_sentences_seen_in_the_headset_log(self):
        self.assertEqual(sanitize_transcript("媽媽好芽芽好我喫她的護理師"), "媽媽好芽芽好我是她的護理師")
        self.assertIn("量血壓", sanitize_transcript("我們現在要來養血壓跟體溫可以進去嗎"))
        self.assertIn("芽芽", sanitize_transcript("你好養養好"))

    def test_measure_is_only_fixed_before_something_measured(self):
        self.assertIn("量體溫", sanitize_transcript("等一下要養體溫喔我們慢慢來"))
        self.assertIn("量一下耳溫", sanitize_transcript("姊姊幫你亮一下耳溫好不好呢"))
        # Ordinary words that merely sound alike stay as they are.
        self.assertIn("兩個", sanitize_transcript("我們有兩個貼紙可以選一個喔"))
        self.assertIn("涼涼的", sanitize_transcript("這個聽診器摸起來涼涼的不用怕"))

    def test_specific_entries_win_over_short_ones(self):
        self.assertIn("壓脈帶", sanitize_transcript("姊姊幫你選一條鴨脈帶剛剛好的"))
        self.assertNotIn("芽芽脈帶", sanitize_transcript("姊姊幫你選一條鴨脈帶剛剛好的"))

    def test_no_entry_undoes_another(self):
        for wrong, right in ASR_REPLACEMENTS.items():
            for other_wrong in ASR_REPLACEMENTS:
                if other_wrong != wrong and other_wrong in right and ASR_REPLACEMENTS[other_wrong] != right:
                    self.fail(f"'{wrong}' -> '{right}' would be changed again by '{other_wrong}'")


if __name__ == "__main__":
    unittest.main()
