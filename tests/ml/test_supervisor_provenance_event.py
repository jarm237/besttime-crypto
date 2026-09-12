"""Tests for supervisor_started event provenance payload in run_canary_until_seal_ready."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock
from scripts.run_canary_until_seal_ready import ChildStartBudget


class TestSupervisorProvenanceEvent(unittest.TestCase):
    def test_supervisor_started_event_payload_fields(self):
        recorded_events = []

        def mock_event(event_type, payload=None):
            recorded_events.append({"event_type": event_type, "payload": payload})

        budget = ChildStartBudget(
            limit=2,
            consumed=0,
            lifecycle_path=MagicMock(),
            metadata={
                "supervisor_pid": 12345,
                "epoch_id": "ep-1",
                "deployment_id": "dep-1",
                "code_commit_sha": "abc1234",
                "code_tree_sha": "tree1234",
                "artifact_sha256": "art1234",
                "sidecar_hashes": {
                    "metadata_sha256": "meta1234",
                    "registry_sha256": "reg1234",
                },
            },
        )
        budget.event = mock_event
        budget.event("supervisor_started", {"started_at": "2026-09-12T00:00:00Z"})

        self.assertEqual(len(recorded_events), 1)
        event = recorded_events[0]
        self.assertEqual(event["event_type"], "supervisor_started")
        self.assertIsNotNone(budget.metadata.get("code_tree_sha"))
        self.assertIsNotNone(budget.metadata.get("sidecar_hashes"))
        self.assertEqual(budget.metadata["code_tree_sha"], "tree1234")
        self.assertEqual(budget.metadata["sidecar_hashes"]["metadata_sha256"], "meta1234")


if __name__ == "__main__":
    unittest.main()
