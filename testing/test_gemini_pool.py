from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from backend.app.agent_orchestration.providers import gemini_pool


RAW_GEMINI_POOL_OCR_SECRET = "RAW_GEMINI_POOL_OCR_SECRET"
RAW_GEMINI_POOL_CREDENTIAL_VALUE = "RAW_GEMINI_POOL_CREDENTIAL_VALUE"
RAW_GEMINI_POOL_PROVIDER_BODY = "RAW_GEMINI_POOL_PROVIDER_BODY"
RAW_SECONDARY_KEY_TEST_OCR = "RAW_SECONDARY_KEY_TEST_OCR"
RAW_SECONDARY_KEY_TEST_CREDENTIAL = "RAW_SECONDARY_KEY_TEST_CREDENTIAL"
RAW_SECONDARY_KEY_TEST_API_KEY = "RAW_SECONDARY_KEY_TEST_API_KEY"
RAW_SECONDARY_USAGE_OCR_SECRET = "RAW_SECONDARY_USAGE_OCR_SECRET"
RAW_SECONDARY_USAGE_CREDENTIAL_SECRET = "RAW_SECONDARY_USAGE_CREDENTIAL_SECRET"
RAW_SECONDARY_USAGE_API_KEY_SECRET = "RAW_SECONDARY_USAGE_API_KEY_SECRET"
RAW_SECONDARY_USAGE_GEMINI_RESPONSE_SECRET = "RAW_SECONDARY_USAGE_GEMINI_RESPONSE_SECRET"
RAW_ROUND_ROBIN_OCR_SECRET = "RAW_ROUND_ROBIN_OCR_SECRET"
RAW_ROUND_ROBIN_CREDENTIAL_SECRET = "RAW_ROUND_ROBIN_CREDENTIAL_SECRET"
RAW_ROUND_ROBIN_GEMINI_RESPONSE_SECRET = "RAW_ROUND_ROBIN_GEMINI_RESPONSE_SECRET"
RAW_ROUND_ROBIN_API_KEY_SECRET = "RAW_ROUND_ROBIN_API_KEY_SECRET"


class _FakeChatGoogleGenerativeAI:
    calls: list[dict] = []
    responses_by_key: dict[str, list] = {}

    def __init__(self, *, model, google_api_key, temperature, timeout=None, max_retries=None):
        self.model = model
        self.google_api_key = google_api_key
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.structured_schema = None
        self.calls.append(
            {
                "model": model,
                "google_api_key": google_api_key,
                "temperature": temperature,
                "timeout": timeout,
                "max_retries": max_retries,
            }
        )

    def with_structured_output(self, schema):
        structured = type(self)(
            model=self.model,
            google_api_key=self.google_api_key,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )
        structured.structured_schema = schema
        return structured

    def invoke(self, prompt_or_messages):
        outcomes = self.responses_by_key.setdefault(self.google_api_key, [])
        if not outcomes:
            raise AssertionError(f"Unexpected invoke for key {self.google_api_key}")
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return {
            "response": outcome,
            "key": self.google_api_key,
            "schema": self.structured_schema,
            "prompt": prompt_or_messages,
        }


class GeminiPoolTests(unittest.TestCase):
    def setUp(self):
        _FakeChatGoogleGenerativeAI.calls = []
        _FakeChatGoogleGenerativeAI.responses_by_key = {}
        gemini_pool._reset_pool_rotation_for_tests()
        fake_module = types.ModuleType("langchain_google_genai")
        fake_module.ChatGoogleGenerativeAI = _FakeChatGoogleGenerativeAI
        self.module_patcher = patch.dict(sys.modules, {"langchain_google_genai": fake_module})
        self.module_patcher.start()
        self.sleep_patcher = patch.object(gemini_pool, "_sleep", lambda _seconds: None)
        self.sleep_patcher.start()
        self.jitter_patcher = patch.object(gemini_pool, "_jitter", lambda: 0.0)
        self.jitter_patcher.start()
        self.env_patcher = patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY_PRIMARY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
                "GEMINI_API_KEY_SECONDARY": "",
                "GEMINI_POOL_STRATEGY": "",
                "GEMINI_MODEL": "",
                "GEMINI_TEMPERATURE": "",
                "GEMINI_PROVIDER_MAX_RETRIES": "",
                "GEMINI_PROVIDER_TIMEOUT_SECONDS": "",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.jitter_patcher.stop()
        self.sleep_patcher.stop()
        self.module_patcher.stop()

    def test_primary_key_success_returns_primary_response(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_PRIMARY": "primary-key"}, clear=False):
            _FakeChatGoogleGenerativeAI.responses_by_key = {"primary-key": ["primary response"]}

            result = gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual(result["response"], "primary response")
        self.assertEqual(result["key"], "primary-key")
        self.assertEqual(_FakeChatGoogleGenerativeAI.calls[0]["max_retries"], 0)
        self.assertEqual(_FakeChatGoogleGenerativeAI.calls[0]["timeout"], 45)

    def test_configured_key_entries_are_ordered_and_deduped_across_aliases(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEYS": "list-primary, list-secondary, list-primary",
                "GEMINI_API_KEY_PRIMARY": "list-primary",
                "GEMINI_API_KEY": "primary-alias",
                "GOOGLE_API_KEY": "primary-alias",
                "GEMINI_API_KEY_1": "primary-one",
                "GEMINI_API_KEY_SECONDARY": "list-secondary",
                "GEMINI_API_KEY_2": "secondary-two",
            },
            clear=False,
        ):
            entries = gemini_pool._configured_key_entries()

        self.assertEqual([entry.key for entry in entries], ["list-primary", "list-secondary", "primary-alias", "primary-one", "secondary-two"])
        self.assertEqual([entry.slot for entry in entries], ["primary", "secondary", "primary", "primary", "secondary"])

    def test_default_stage_preferred_primary_still_uses_primary_first(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="primary")

        self.assertEqual(result["response"], "primary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["primary-key"])
        self.assertEqual(captured.records[0].selected_first_slot, "primary")

    def test_primary_429_falls_back_to_secondary(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [RuntimeError("429 quota exceeded"), RuntimeError("429 quota exceeded")],
                "secondary-key": ["secondary response"],
            }

            result = gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual(result["key"], "secondary-key")

    def test_primary_resource_exhausted_falls_back_to_secondary(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [
                    RuntimeError("RESOURCE_EXHAUSTED"),
                    RuntimeError("RESOURCE_EXHAUSTED"),
                ],
                "secondary-key": ["secondary response"],
            }

            result = gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual(result["key"], "secondary-key")

    def test_preferred_secondary_success_uses_secondary_first(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="secondary")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["secondary-key"])

    def test_default_stage_preferred_secondary_still_uses_secondary_first(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="secondary")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["secondary-key"])
        self.assertEqual(captured.records[0].selected_first_slot, "secondary")

    def test_preferred_secondary_success_logs_secondary_slot_without_primary_fallback(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="secondary")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["secondary-key"])
        self.assertEqual(captured.records[0].key_slot, "secondary")
        self.assertEqual(captured.records[0].outcome_category, "success")
        self.assertEqual(captured.records[0].attempt_number, 1)

    def test_non_rate_limit_error_raises_invocation_error_without_alternate(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [ValueError("provider failed")],
                "secondary-key": ["secondary response"],
            }

            with self.assertRaises(gemini_pool.GeminiPoolInvocationError):
                gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["primary-key"])

    def test_both_keys_rate_limited_raises_rate_limit_error(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [RuntimeError("ratelimit"), RuntimeError("ratelimit")],
                "secondary-key": [RuntimeError("quota"), RuntimeError("quota")],
            }

            with self.assertRaises(gemini_pool.GeminiPoolRateLimitError):
                gemini_pool.invoke_gemini_balanced("safe prompt")

    def test_preferred_primary_falls_back_to_secondary_only_after_rate_limit(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY_PRIMARY": "primary-key", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [RuntimeError("429 quota exceeded"), RuntimeError("429 quota exceeded")],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="primary")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual(
            [call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls],
            ["primary-key", "secondary-key"],
        )
        observed = [(record.key_slot, record.outcome_category) for record in captured.records]
        self.assertEqual(
            observed,
            [
                ("primary", "rate_limited"),
                ("primary", "fallback"),
                ("secondary", "success"),
            ],
        )

    def test_round_robin_with_both_keys_alternates_successful_invocations(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_POOL_STRATEGY": "round_robin",
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            first = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="secondary")
            second = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="primary")

        self.assertEqual(first["response"], "primary response")
        self.assertEqual(second["response"], "secondary response")
        self.assertEqual(
            [call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls],
            ["primary-key", "secondary-key"],
        )

    def test_round_robin_safe_diagnostic_metadata_shows_primary_then_secondary(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_POOL_STRATEGY": "round_robin",
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": ["primary response"],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                gemini_pool.invoke_gemini_balanced("safe prompt", stage_name="diagnostic_one")
                gemini_pool.invoke_gemini_balanced("safe prompt", stage_name="diagnostic_two")

            diagnostic = {
                "pool_strategy": gemini_pool._pool_strategy(),
                "configured_slots": [
                    slot for slot in ("primary", "secondary")
                    if gemini_pool._api_key_for_slot(slot)
                ],
                "selected_slots": [
                    record.selected_first_slot for record in captured.records
                    if record.outcome_category == "success"
                ],
            }

        self.assertEqual(
            diagnostic,
            {
                "pool_strategy": "round_robin",
                "configured_slots": ["primary", "secondary"],
                "selected_slots": ["primary", "secondary"],
            },
        )
        self.assertNotIn("primary-key", str(diagnostic))
        self.assertNotIn("secondary-key", str(diagnostic))

    def test_round_robin_falls_back_to_alternate_slot_on_resource_exhausted(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_POOL_STRATEGY": "round_robin",
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [RuntimeError("RESOURCE_EXHAUSTED"), RuntimeError("RESOURCE_EXHAUSTED")],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual(
            [call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls],
            ["primary-key", "secondary-key"],
        )
        self.assertEqual(captured.records[0].selected_first_slot, "primary")
        self.assertEqual(captured.records[-1].key_slot, "secondary")
        self.assertEqual(captured.records[-1].outcome_category, "success")

    def test_round_robin_with_only_primary_configured_does_not_crash(self):
        with patch.dict(
            os.environ,
            {"GEMINI_POOL_STRATEGY": "round_robin", "GEMINI_API_KEY_PRIMARY": "primary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {"primary-key": ["primary response"]}

            result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="secondary")

        self.assertEqual(result["response"], "primary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["primary-key"])

    def test_round_robin_with_only_secondary_configured_does_not_crash(self):
        with patch.dict(
            os.environ,
            {"GEMINI_POOL_STRATEGY": "round_robin", "GEMINI_API_KEY_SECONDARY": "secondary-key"},
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {"secondary-key": ["secondary response"]}

            result = gemini_pool.invoke_gemini_balanced("safe prompt", preferred_key="primary")

        self.assertEqual(result["response"], "secondary response")
        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["secondary-key"])

    def test_round_robin_non_rate_limit_error_does_not_fallback_silently(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_POOL_STRATEGY": "round_robin",
                "GEMINI_API_KEY_PRIMARY": "primary-key",
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [ValueError("provider failed")],
                "secondary-key": ["secondary response"],
            }

            with self.assertRaises(gemini_pool.GeminiPoolInvocationError):
                gemini_pool.invoke_gemini_balanced("safe prompt")

        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], ["primary-key"])

    def test_missing_keys_raises_configuration_error(self):
        with self.assertRaisesRegex(
            gemini_pool.GeminiPoolConfigurationError,
            "GEMINI_API_KEY is not configured",
        ):
            gemini_pool.invoke_gemini_balanced("safe prompt")

    def test_structured_output_calls_schema_invoker(self):
        class FakeSchema:
            pass

        with patch.dict(os.environ, {"GEMINI_API_KEY_PRIMARY": "primary-key"}, clear=False):
            _FakeChatGoogleGenerativeAI.responses_by_key = {"primary-key": ["structured response"]}

            result = gemini_pool.invoke_gemini_balanced("safe prompt", schema=FakeSchema)

        self.assertEqual(result["response"], "structured response")
        self.assertIs(result["schema"], FakeSchema)

    def test_sentinel_strings_do_not_appear_in_errors_or_logs(self):
        prompt = {
            "ocr": RAW_GEMINI_POOL_OCR_SECRET,
            "credential": RAW_GEMINI_POOL_CREDENTIAL_VALUE,
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY_PRIMARY": "primary-key"}, clear=False):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                "primary-key": [RuntimeError(RAW_GEMINI_POOL_PROVIDER_BODY)],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="WARNING") as captured:
                with self.assertRaises(gemini_pool.GeminiPoolInvocationError) as raised:
                    gemini_pool.invoke_gemini_balanced(prompt, stage_name="pool_privacy_test")

        combined = "\n".join(captured.output + [str(raised.exception)])
        self.assertNotIn(RAW_GEMINI_POOL_OCR_SECRET, combined)
        self.assertNotIn(RAW_GEMINI_POOL_CREDENTIAL_VALUE, combined)
        self.assertNotIn(RAW_GEMINI_POOL_PROVIDER_BODY, combined)

    def test_secondary_slot_observability_does_not_leak_raw_sentinels(self):
        prompt = {
            "ocr": RAW_SECONDARY_KEY_TEST_OCR,
            "credential": RAW_SECONDARY_KEY_TEST_CREDENTIAL,
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY_SECONDARY": RAW_SECONDARY_KEY_TEST_API_KEY}, clear=False):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                RAW_SECONDARY_KEY_TEST_API_KEY: [ValueError("provider failed")],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="WARNING") as captured:
                with self.assertRaises(gemini_pool.GeminiPoolInvocationError) as raised:
                    gemini_pool.invoke_gemini_balanced(
                        prompt,
                        preferred_key="secondary",
                        stage_name="secondary_privacy_test",
                    )

        self.assertEqual([call["google_api_key"] for call in _FakeChatGoogleGenerativeAI.calls], [RAW_SECONDARY_KEY_TEST_API_KEY])
        combined = "\n".join(captured.output + [str(raised.exception)])
        self.assertNotIn(RAW_SECONDARY_KEY_TEST_OCR, combined)
        self.assertNotIn(RAW_SECONDARY_KEY_TEST_CREDENTIAL, combined)
        self.assertNotIn(RAW_SECONDARY_KEY_TEST_API_KEY, combined)

    def test_selected_slot_logs_do_not_contain_secondary_usage_sentinels(self):
        prompt = {
            "ocr": RAW_SECONDARY_USAGE_OCR_SECRET,
            "credential": RAW_SECONDARY_USAGE_CREDENTIAL_SECRET,
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY_SECONDARY": RAW_SECONDARY_USAGE_API_KEY_SECRET}, clear=False):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                RAW_SECONDARY_USAGE_API_KEY_SECRET: [RAW_SECONDARY_USAGE_GEMINI_RESPONSE_SECRET],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="INFO") as captured:
                result = gemini_pool.invoke_gemini_balanced(
                    prompt,
                    preferred_key="secondary",
                    stage_name="secondary_usage_privacy_test",
                )

        self.assertEqual(result["response"], RAW_SECONDARY_USAGE_GEMINI_RESPONSE_SECRET)
        self.assertEqual(captured.records[0].key_slot, "secondary")
        self.assertEqual(captured.records[0].outcome_category, "success")
        combined = "\n".join(captured.output)
        self.assertNotIn(RAW_SECONDARY_USAGE_OCR_SECRET, combined)
        self.assertNotIn(RAW_SECONDARY_USAGE_CREDENTIAL_SECRET, combined)
        self.assertNotIn(RAW_SECONDARY_USAGE_API_KEY_SECRET, combined)
        self.assertNotIn(RAW_SECONDARY_USAGE_GEMINI_RESPONSE_SECRET, combined)

    def test_round_robin_logs_errors_do_not_contain_raw_sentinels(self):
        prompt = {
            "ocr": RAW_ROUND_ROBIN_OCR_SECRET,
            "credential": RAW_ROUND_ROBIN_CREDENTIAL_SECRET,
        }
        with patch.dict(
            os.environ,
            {
                "GEMINI_POOL_STRATEGY": "round_robin",
                "GEMINI_API_KEY_PRIMARY": RAW_ROUND_ROBIN_API_KEY_SECRET,
                "GEMINI_API_KEY_SECONDARY": "secondary-key",
            },
            clear=False,
        ):
            _FakeChatGoogleGenerativeAI.responses_by_key = {
                RAW_ROUND_ROBIN_API_KEY_SECRET: [ValueError(RAW_ROUND_ROBIN_GEMINI_RESPONSE_SECRET)],
                "secondary-key": ["secondary response"],
            }

            with self.assertLogs(gemini_pool.LOGGER.name, level="WARNING") as captured:
                with self.assertRaises(gemini_pool.GeminiPoolInvocationError) as raised:
                    gemini_pool.invoke_gemini_balanced(prompt, stage_name="round_robin_privacy_test")

        combined = "\n".join(captured.output + [str(raised.exception)])
        self.assertNotIn(RAW_ROUND_ROBIN_OCR_SECRET, combined)
        self.assertNotIn(RAW_ROUND_ROBIN_CREDENTIAL_SECRET, combined)
        self.assertNotIn(RAW_ROUND_ROBIN_GEMINI_RESPONSE_SECRET, combined)
        self.assertNotIn(RAW_ROUND_ROBIN_API_KEY_SECRET, combined)


if __name__ == "__main__":
    unittest.main()
