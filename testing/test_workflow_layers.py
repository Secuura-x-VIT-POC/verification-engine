import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.orchestrator.orchestrator import trigger_processing
from backend.app.workflow import repository
from backend.app.workflow.service import (
    WORKER_PHASE_CONNECTOR_EVAL,
    WORKER_PHASE_EXTRACTING,
    WORKER_PHASE_GROUNDING,
    WORKER_PHASE_TRUST_SCORING,
    mark_stale_sessions,
    run_worker_pipeline,
    start_verification,
)


class TriggerProcessingTests(unittest.TestCase):
    def test_trigger_processing_starts_when_lease_is_acquired(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.repository.get_session_state_and_version",
            return_value={"state": repository.PENDING_REVIEW_STATE, "version": 4},
        ), patch(
            "backend.app.orchestrator.orchestrator.repository.acquire_lease",
            return_value=True,
        ):
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "STARTED")
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_trigger_processing_returns_no_op_for_non_pending_sessions(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.repository.get_session_state_and_version",
            return_value={"state": "VERIFYING", "version": 5},
        ), patch(
            "backend.app.orchestrator.orchestrator.repository.acquire_lease"
        ) as acquire_lease:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "NO_OP")
        acquire_lease.assert_not_called()
        conn.rollback.assert_called_once()

    def test_trigger_processing_retries_after_a_failed_compare_and_swap(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.repository.get_session_state_and_version",
            side_effect=[
                {"state": repository.PENDING_REVIEW_STATE, "version": 1},
                {"state": repository.PENDING_REVIEW_STATE, "version": 2},
            ],
        ), patch(
            "backend.app.orchestrator.orchestrator.repository.acquire_lease",
            side_effect=[False, True],
        ) as acquire_lease, patch(
            "backend.app.orchestrator.orchestrator.time.sleep"
        ) as sleep_mock:
            result = trigger_processing(conn, "session-1", "worker-1", max_retries=2)

        self.assertEqual(result, "STARTED")
        self.assertEqual(acquire_lease.call_count, 2)
        conn.rollback.assert_called_once()
        conn.commit.assert_called_once()
        sleep_mock.assert_called_once_with(0.05)


class WorkflowServiceTests(unittest.TestCase):
    def test_start_verification_runs_pipeline_after_start(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.trigger_processing",
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
