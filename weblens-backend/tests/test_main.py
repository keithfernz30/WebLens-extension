import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, text: str):
        self._text = text

    def generate_content(self, model: str, contents: str):
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text: str):
        self.models = _FakeModels(text)


class MainApiTests(unittest.TestCase):
    def setUp(self):
        main._rate_limit_store.clear()
        main._result_cache.clear()
        os.environ.pop("WEBLENS_API_KEY", None)
        self.client = TestClient(main.app)

    def test_health(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "WebLens backend running")
        self.assertIn("request_id", payload)
        self.assertIn("X-Request-ID", response.headers)

    def test_generate_is_invalid_mode(self):
        response = self.client.post(
            "/analyze",
            json={"mode": "generate", "task": "", "content": "hello"},
        )
        self.assertEqual(response.status_code, 400)

    def test_summarize_success(self):
        with patch("main.get_client", return_value=_FakeClient("Short summary")):
            response = self.client.post(
                "/analyze",
                json={"mode": "summarize", "task": "", "content": "long text"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Summary:", payload["result"])
        self.assertIn("Short summary", payload["result"])
        self.assertIn("request_id", payload)

    def test_extract_requires_valid_json(self):
        with patch("main.get_client", return_value=_FakeClient("not-json")):
            response = self.client.post(
                "/analyze",
                json={"mode": "extract", "task": "", "content": "text"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        parsed = json.loads(payload["result"])
        self.assertIn("summary", parsed)

    def test_extract_success(self):
        body = {
            "title": "T",
            "summary": "S",
            "key_points": ["A", "B"],
            "entities": ["X"],
        }
        with patch("main.get_client", return_value=_FakeClient(json.dumps(body))):
            response = self.client.post(
                "/analyze",
                json={"mode": "extract", "task": "", "content": "text"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        parsed = json.loads(payload["result"])
        self.assertEqual(parsed["title"], "T")

    def test_api_key_guard(self):
        os.environ["WEBLENS_API_KEY"] = "secret"
        response = self.client.post(
            "/analyze",
            json={"mode": "summarize", "task": "", "content": "text"},
        )
        self.assertEqual(response.status_code, 401)

    def test_build_prompt_modes(self):
        for mode in [
            "summarize",
            "explain",
            "extract",
            "translate",
            "quiz",
            "action_items",
            "fact_check",
        ]:
            prompt = main.build_prompt(mode, "task", "content", "Hindi", "short")
            self.assertIn("content", prompt)


if __name__ == "__main__":
    unittest.main()
