import json
import unittest
from unittest.mock import patch

import httpx
import openai

import intent_llm


class ModelRequestTests(unittest.TestCase):
    def check_model(self, model):
        expected = {
            "intent": "neutral", "action_tag": "neutral", "sentiment": "neutral",
            "toxicity": 0.0, "coercion": 0.0, "confidence": 0.9,
        }
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "offline-test", "object": "chat.completion", "created": 0,
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": json.dumps(expected),
                }}],
            })

        with openai.OpenAI(
            api_key="offline-test-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ) as client:
            with patch.object(intent_llm, "LLM_MODEL", model), \
                    patch.object(intent_llm, "openai_client", client), \
                    patch.object(intent_llm, "_LLM_CACHE", {}):
                result = intent_llm.analyze_intent([], "test utterance")

        self.assertEqual(result, {**expected, "keywords": []})
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], model)
        self.assertEqual(requests[0]["temperature"], 0)
        return requests[0]

    def test_luna_sends_non_reasoning_request_and_preserves_result_contract(self):
        request = self.check_model("gpt-6-luna")
        self.assertEqual(request["reasoning_effort"], "none")

    def test_previous_model_remains_usable_without_reasoning_parameter(self):
        request = self.check_model("gpt-4o-mini")
        self.assertNotIn("reasoning_effort", request)


if __name__ == "__main__":
    unittest.main()
