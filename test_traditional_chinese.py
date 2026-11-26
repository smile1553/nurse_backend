import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from deepgram_streaming import DeepgramStreamingSession
from fusion_loop import sanitize_transcript
from traditional_chinese import to_traditional


class TraditionalChineseTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_mixed_text_and_preserve_traditional(self):
        self.assertEqual(to_traditional("\u62a4\u7406\u5e08\u5e6b\u4f60\u91cf\u4f53\u6e29，\u8840\u538b 120 mmHg。"),
                         "護理師幫你量體溫，血壓 120 mmHg。")
        self.assertEqual(to_traditional("媽媽好，護理師幫你量體溫。"),
                         "媽媽好，護理師幫你量體溫。")
        self.assertEqual(to_traditional(""), "")
        self.assertEqual(to_traditional("\u597d\u4e86，\u91cf\u5b8c\u4f53\u6e29\u4e86"), "好了，量完體溫了")
        self.assertEqual(sanitize_transcript("\u62a4\u7406\u5e08\u5e2e\u4f60\u91cf\u4f53\u6e29"), "護理師幫你量體溫")

    async def test_streaming_interim_final_and_diagnostics_are_traditional(self):
        with patch.dict("os.environ", {"DEEPGRAM_LANGUAGE": "zh-CN"}):
            session = DeepgramStreamingSession(language="zh-Hans")
        self.assertEqual(parse_qs(urlparse(session._build_url()).query)["language"], ["zh-TW"])
        interim = {"type": "Results", "channel": {"alternatives": [{"transcript": "\u91cf\u4f53\u6e29"}]}}
        session._handle_results(interim)
        self.assertEqual(session.result().text, "量體溫")

        class Messages:
            def __aiter__(self):
                return self.messages()

            async def messages(self):
                import json
                yield json.dumps({"type": "Results", "is_final": True, "speech_final": True,
                                  "channel": {"alternatives": [{"transcript": "\u62a4\u7406\u5e08\u5e2e\u4f60\u91cf\u4f53\u6e29",
                                      "words": [{"word": "\u62a4\u7406\u5e08", "punctuated_word": "\u62a4\u7406\u5e08，"}]}]}})

        session._ws = Messages()
        await session._receive_loop()
        result = session.result()
        self.assertEqual(result.text, "護理師幫你量體溫")
        self.assertTrue(result.is_final)
        best = result.raw_messages[0]["channel"]["alternatives"][0]
        self.assertEqual(best["transcript"], result.text)
        self.assertEqual(best["words"][0]["punctuated_word"], "護理師，")
