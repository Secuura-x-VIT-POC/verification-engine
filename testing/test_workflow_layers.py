import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.orchestrator.orchestrator import trigger_processing
from backend.app.sessions.constants import SessionState
from backend.app.workflow.state_machine import InvalidStateTransitionError, validate_transition
from backend.app.workflow.service import (
    WORKER_PHASE_CONNECTOR_EVAL,
    WORKER_PHASE_EXTRACTING,
    WORKER_PHASE_GROUNDING,
    WORKER_PHASE_TRUST_SCORING,
    acquire_lease,
    mark_stale_sessions,
    run_worker_pipeline,
    start_verification,
)


class StateMachineTests(unittest.TestCase):
    def test_validate_transition_allows_known_valid_transition(self):
        validate_transition(
            SessionState.UPLOADED_PENDING_REVIEW,
            SessionState.VERIFYING,
        )

    def test_validate_transition_rejects_invalid_transition(self):
        with self.assertRaises(InvalidStateTransitionError):
            validate_transition(
                SessionState.CREATED,
                SessionState.VERIFYING,
            )


class TriggerProcessingTests(unittest.TestCase):
    def test_trigger_processing_starts_when_lease_is_acquired(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=True,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "STARTED")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()

    def test_trigger_processing_returns_no_op_when_lease_is_rejected(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=False,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "NO_OP")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()

    def test_trigger_processing_does_not_retry_after_rejected_lease(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=False,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1", max_retries=2)

        self.assertEqual(result, "NO_OP")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()


class LeaseServiceTests(unittest.TestCase):
    def test_acquire_lease_commits_and_logs_when_successful(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.acquire_lease",
            return_value=True,
        ):
            with self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
                result = acquire_lease(conn, "session-1", "worker-1")

        self.assertTrue(result)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        self.assertTrue(any("LEASE_ACQUIRED" in entry for entry in logs.output))

    def test_acquire_lease_rolls_back_and_logs_when_rejected(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.acquire_lease",
            return_value=False,
        ):
            with self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
                result = acquire_lease(conn, "session-1", "worker-1")

        self.assertFalse(result)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        self.assertTrue(any("LEASE_REJECTED" in entry for entry in logs.output))


class WorkflowServiceTests(unittest.TestCase):
    def test_start_verification_runs_pipeline_after_start(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.trigger_processing",
            return_value="STARTED",
        ) as trigger_mock, patch(
            "backend.app.workflow.service.run_worker_pipeline"
        ) as pipeline_mock:
            result = start_verification(
                conn,
                "session-1",
                worker_id="worker-1",
                heartbeat_interval_seconds=0,
            )

        self.assertEqual(result, "STARTED")
        trigger_mock.assert_called_once_with(
            conn,
            "session-1",
            "worker-1",
            max_retries=3,
        )
        pipeline_mock.assert_called_once()

    def test_run_worker_pipeline_advances_all_phases_and_completes(self):
        conn = MagicMock()
        extraction_data = {
            "is_unsafe": False,
            "critical_tamper_signal": False,
            "fields": [{"name": "name", "is_mandatory": True, "is_grounded": True}],
        }
        connector_responses = [
            {
                "connector_id": "vit_registry",
                "status": "VERIFIED",
                "assurance_class": "HIGH",
                "mismatched_claims": [],
            }
        ]
        policy = {
            "requires_high_assurance": True,
            "required_connectors": ["vit_registry"],
        }

        with patch("backend.app.workflow.service.update_worker_phase") as phase_mock, patch(
            "backend.app.workflow.service.complete_processing"
        ) as complete_mock:
            result = run_worker_pipeline(
                conn,
                "session-1",
                "worker-1",
                extraction_stage=lambda *_: extraction_data,
                grounding_stage=lambda *_: extraction_data,
                connector_stage=lambda *_: connector_responses,
                policy_loader=lambda *_: policy,
                heartbeat_interval_seconds=0,
            )

        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(
            phase_mock.call_args_list,
            [
                call(conn, "session-1", "worker-1", WORKER_PHASE_EXTRACTING),
                call(conn, "session-1", "worker-1", WORKER_PHASE_GROUNDING),
                call(conn, "session-1", "worker-1", WORKER_PHASE_CONNECTOR_EVAL),
                call(conn, "session-1", "worker-1", WORKER_PHASE_TRUST_SCORING),
            ],
        )
        complete_mock.assert_called_once()
        complete_args = complete_mock.call_args.args
        self.assertEqual(complete_args[0], conn)
        self.assertEqual(complete_args[1], "session-1")
        self.assertEqual(complete_args[2], "GREEN")
        self.assertEqual(set(complete_args[3]), {"TRUSTED_SOURCE_VERIFIED", "GROUNDING_OK"})
        self.assertEqual(complete_args[4], ["vit_registry"])

    def test_run_worker_pipeline_marks_red_when_a_stage_fails(self):
        conn = MagicMock()

        with patch("backend.app.workflow.service.complete_processing") as complete_mock:
            with self.assertRaises(RuntimeError):
                run_worker_pipeline(
                    conn,
                    "session-1",
                    "worker-1",
                    extraction_stage=lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
                    heartbeat_interval_seconds=0,
                )

        complete_mock.assert_called_once_with(
            conn,
            "session-1",
            "RED",
            ["WORKFLOW_EXECUTION_FAILED"],
            [],
        )

    def test_mark_stale_sessions_commits_and_returns_updated_count(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.mark_stale_sessions",
            return_value=3,
        ) as stale_mock:
            result = mark_stale_sessions(conn, timeout_seconds=75)

        self.assertEqual(result, 3)
        stale_mock.assert_called_once_with(conn, timeout_seconds=75)
        conn.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
