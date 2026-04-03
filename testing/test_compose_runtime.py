import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.inference.nvidia import load_nvidia_inference_config
from backend.app.main import app as main_app
from backend.app.verifier_providers.policies import load_provider_runtime_policy
from backend.app.verifier_providers.providers.local_mock import (
    _resolve_local_verification_fixture_path,
)


class MainAppHealthTests(unittest.TestCase):
    def test_healthz_returns_ok(self):
        with patch("backend.app.main.init_db"):
            with TestClient(main_app) as client:
                response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_checks_database_connectivity(self):
        with patch("backend.app.main.init_db"), patch("backend.app.main.engine.connect") as mock_connect:
            mock_connection = mock_connect.return_value.__enter__.return_value
            mock_connection.execute.return_value = None

            with TestClient(main_app) as client:
                response = client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        mock_connection.execute.assert_called_once()


class ComposeEnvCompatibilityTests(unittest.TestCase):
    def test_provider_policy_accepts_legacy_transition_aliases(self):
        with patch.dict(
            os.environ,
            {
                "PROVIDER_OPERATING_MODE": "LOCAL_MOCK",
                "EXECUTION_ENVIRONMENT_LABEL": "Compose smoke test",
                "DEMO_PROFILE_KEY": "academic_transcript_demo",
            },
            clear=True,
        ):
            policy = load_provider_runtime_policy()

        self.assertEqual(policy.transition_config.provider_operating_mode, "LOCAL_MOCK")
        self.assertEqual(policy.transition_config.execution_environment_label, "Compose smoke test")
        self.assertEqual(policy.transition_config.demo_profile_key, "academic_transcript_demo")

    def test_local_verification_store_path_can_be_overridden_by_env(self):
        overridden_path = Path("/tmp/local-store.json")
        with patch.dict(
            os.environ,
            {
                "VERIFIER_LOCAL_VERIFICATION_STORE_PATH": str(overridden_path),
            },
            clear=True,
        ):
            resolved = _resolve_local_verification_fixture_path()

        self.assertEqual(resolved, overridden_path)

    def test_nvidia_config_accepts_agent_aliases(self):
        with patch.dict(
            os.environ,
            {
                "AGENT_REQUEST_TIMEOUT_MS": "2500",
                "AGENT_ENABLE_REASONING": "0",
                "AGENT_ENABLE_PII_ENRICHMENT": "0",
            },
            clear=True,
        ):
            config = load_nvidia_inference_config()

        self.assertEqual(config.timeout_ms, 2500)
        self.assertFalse(config.reasoning_enabled)
        self.assertFalse(config.pii_enrichment_enabled)


if __name__ == "__main__":
    unittest.main()
