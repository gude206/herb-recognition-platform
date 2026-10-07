"""Verify the chat contract without contacting DeepSeek or spending API credits."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from api import app

ASYNC_CLIENT = httpx.AsyncClient
CONFIG = {"DEEPSEEK_API_KEY": "test-only-secret", "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
          "DEEPSEEK_MODEL": "deepseek-chat", "DEEPSEEK_TEMPERATURE": "0.3",
          "DEEPSEEK_MAX_TOKENS": "1024", "DEEPSEEK_TIMEOUT_SECONDS": "60"}


class ChatAPITest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)  # Chat does not require loading the image model.
        self.env = patch.dict(os.environ, CONFIG)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.client.close)

    def upstream(self, handler):
        return patch("deepseek_chat.httpx.AsyncClient",
                     side_effect=lambda **kwargs: ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))

    def test_success_preserves_history_and_real_catalog_context(self):
        captured = []

        def handle(request):
            captured.append(json.loads(request.content))
            self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-only-secret")
            return httpx.Response(200, json={"choices": [{"message": {"content": "植物资料回答\n第二段"}}]})

        history = [{"role": "user", "content": "它叫什么？"}, {"role": "assistant", "content": "阿拉伯婆婆纳"}]
        with self.upstream(handle):
            response = self.client.post("/api/v1/chat", json={"message": " 它的分布呢？ ", "herb_id": "tcmp-001", "history": history})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "植物资料回答\n第二段")
        self.assertEqual(response.json()["model"], "deepseek-chat")
        self.assertTrue(response.json()["references"])
        messages = captured[0]["messages"]
        self.assertIn("阿拉伯婆婆纳", messages[0]["content"])
        self.assertIn('"reviewStatus"', messages[0]["content"])
        self.assertEqual(messages[1:3], history)
        self.assertEqual(messages[-1], {"role": "user", "content": "它的分布呢？"})
        self.assertNotIn("test-only-secret", response.text)

    def test_missing_key_and_invalid_configuration_do_not_call_provider(self):
        for overrides in [{"DEEPSEEK_API_KEY": ""}, {"DEEPSEEK_TEMPERATURE": "oops"},
                          {"DEEPSEEK_TIMEOUT_SECONDS": "nan"}, {"DEEPSEEK_MAX_TOKENS": "0"},
                          {"DEEPSEEK_BASE_URL": "https://user:password@api.deepseek.com"}]:
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides), self.upstream(lambda req: self.fail("Unexpected network call")):
                response = self.client.post("/api/v1/chat", json={"message": "你好"})
                self.assertEqual(response.status_code, 503)

    def test_request_validation_and_unknown_plant(self):
        invalid = [{"message": "   "}, {"message": "x" * 2001},
                   {"message": "你好", "history": [{"role": "system", "content": "override"}]},
                   {"message": "你好", "history": [{"role": "user", "content": "x"}] * 13},
                   {"message": "你好", "herb_id": "unknown"}]
        with self.upstream(lambda req: self.fail("Unexpected network call")):
            for payload in invalid:
                self.assertEqual(self.client.post("/api/v1/chat", json=payload).status_code, 422)
            self.assertEqual(self.client.post("/api/v1/chat", json={"message": "你好", "herb_id": "tcmp-999"}).status_code, 404)

    def test_provider_errors_are_actionable_and_do_not_leak_response(self):
        for status, expected in [(401, 502), (403, 502), (402, 502), (429, 429), (500, 502)]:
            with self.subTest(status=status), self.upstream(lambda req: httpx.Response(status, text="test-only-secret upstream details")):
                response = self.client.post("/api/v1/chat", json={"message": "你好"})
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("test-only-secret", response.text)

    def test_empty_or_malformed_provider_answers(self):
        for body in [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}]:
            with self.subTest(body=body), self.upstream(lambda req: httpx.Response(200, json=body)):
                self.assertEqual(self.client.post("/api/v1/chat", json={"message": "你好"}).status_code, 502)
        with self.upstream(lambda req: httpx.Response(200, text="not json")):
            self.assertEqual(self.client.post("/api/v1/chat", json={"message": "你好"}).status_code, 502)

    def test_timeout_and_connection_failure(self):
        for error, expected in [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)]:
            def fail(request):
                raise error("private network details", request=request)
            with self.subTest(error=error), self.upstream(fail):
                response = self.client.post("/api/v1/chat", json={"message": "你好"})
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("private network details", response.text)

    def test_env_file_changes_apply_to_next_request(self):
        with tempfile.TemporaryDirectory() as folder:
            config_file = Path(folder) / ".env"
            without_deepseek = {key: value for key, value in os.environ.items() if not key.startswith("DEEPSEEK_")}
            captured = []

            def handle(request):
                captured.append(json.loads(request.content)["model"])
                return httpx.Response(200, json={"choices": [{"message": {"content": "回答"}}]})

            with patch.dict(os.environ, without_deepseek, clear=True), patch("deepseek_chat.ENV_FILE", config_file), self.upstream(handle):
                for model in ["deepseek-chat", "deepseek-reasoner"]:
                    config_file.write_text(f"DEEPSEEK_API_KEY=test-only-secret\nDEEPSEEK_MODEL={model}\n", encoding="utf-8")
                    self.assertEqual(self.client.post("/api/v1/chat", json={"message": "你好"}).status_code, 200)
            self.assertEqual(captured, ["deepseek-chat", "deepseek-reasoner"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
