import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.inference.nvidia import (
    DEFAULT_NVIDIA_BASE_URL,
    DEFAULT_NVIDIA_PII_MODEL,
    DEFAULT_NVIDIA_REASONING_MODEL,
    NvidiaChatClient,
    NvidiaInferenceError,
    load_nvidia_inference_config,
)
from backend.app.verifier_providers.http_client import HttpJsonResponse


class NvidiaInferenceConfigTests(unittest.TestCase):
    def test_load_nvidia_inference_config_uses_stage11_env_names(self):
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "test-key",
                "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
                "NVIDIA_REASONING_MODEL": "minimaxai/minimax-m2.5",
                "NVIDIA_PII_MODEL": "nvidia/gliner-pii",
                "NVIDIA_TIMEOUT_MS": "5100",
                "NVIDIA_RETRY_BUDGET": "2",
                "NVIDIA_MAX_TEXT_LENGTH": "2048",
                "NVIDIA_REASONING_ENABLED": "1",
                "NVIDIA_GLINER_PREPROCESSING_ENABLED": "1",
            },
            clear=False,
        ):
            config = load_nvidia_inference_config()

        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, DEFAULT_NVIDIA_BASE_URL)
        self.assertEqual(config.reasoning_model, DEFAULT_NVIDIA_REASONING_MODEL)
        self.assertEqual(config.pii_model, DEFAULT_NVIDIA_PII_MODEL)
        self.assertEqual(config.timeout_ms, 5100)
        self.assertEqual(config.retry_budget, 2)
        self.assertEqual(config.max_input_chars, 2048)
        self.assertTrue(config.reasoning_enabled)
        self.assertTrue(config.pii_enrichment_enabled)

    def test_chat_client_requires_api_key(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}, clear=False):
            client = NvidiaChatClient(load_nvidia_inference_config())
        available, reason = client.is_configured()
        self.assertFalse(available)
        self.assertIn("API key", reason)


class NvidiaInferenceRequestTests(unittest.TestCase):
    def test_chat_client_builds_openai_compatible_chat_completion_request(self):
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "secret",
                "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
            },
            clear=False,
        ):
            client = NvidiaChatClient(load_nvidia_inference_config())

        captured = {}

        def _fake_post_json(**kwargs):
            captured.update(kwargs)
            return HttpJsonResponse(
                payload={
                    "choices": [
                        {
                            "message": {
                                "content": '{"status":"ok"}',
                            }
                        }
                    ]
                },
                http_status=200,
                retry_count=0,
            )

        with patch("backend.app.inference.nvidia.SafeHttpJsonClient.post_json", side_effect=_fake_post_json):
            response = client.chat_json(
                model=DEFAULT_NVIDIA_REASONING_MODEL,
                system_prompt="Return JSON only.",
                user_payload={"task": "demo"},
            )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(captured["url"], "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], DEFAULT_NVIDIA_REASONING_MODEL)
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(captured["domain_allowlist"], ("integrate.api.nvidia.com",))

    def test_chat_client_raises_when_response_is_not_json(self):
        with patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "secret",
                "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
            },
            clear=False,
        ):
            client = NvidiaChatClient(load_nvidia_inference_config())

        with patch(
            "backend.app.inference.nvidia.SafeHttpJsonClient.post_json",
            return_value=HttpJsonResponse(
                payload={"choices": [{"message": {"content": "not-json"}}]},
                http_status=200,
                retry_count=0,
            ),
        ):
            with self.assertRaises(NvidiaInferenceError):
                client.chat_json(
                    model=DEFAULT_NVIDIA_REASONING_MODEL,
                    system_prompt="Return JSON only.",
                    user_payload={"task": "demo"},
                )


if __name__ == "__main__":
    unittest.main()
