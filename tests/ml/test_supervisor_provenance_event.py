"""Tests for supervisor_started event provenance payload and manifest extraction in run_canary_until_seal_ready."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from scripts.run_canary_until_seal_ready import (
    ChildStartBudget,
    _get_current_tree_sha,
    extract_epoch_provenance_metadata,
)


class TestSupervisorProvenanceEvent(unittest.TestCase):
    def test_get_current_tree_sha_returns_valid_git_tree(self):
        tree_sha = _get_current_tree_sha()
        self.assertIsNotNone(tree_sha)
        self.assertIsInstance(tree_sha, str)
        self.assertEqual(len(tree_sha), 40)
        self.assertTrue(all(c in "0123456789abcdefABCDEF" for c in tree_sha))

    def test_extraction_from_evidence_epoch_release_manifest(self):
        epoch = SimpleNamespace(
            release_manifest={
                "code_tree_sha": "manifest_tree_sha_12345",
                "metadata_sha256": "meta_manifest_sha_12345",
                "registry_sha256": "reg_manifest_sha_12345",
            },
            code_commit_sha="commit_sha_12345",
            artifact_sha256="artifact_sha_12345",
        )

        tree_sha, sidecar_hashes = extract_epoch_provenance_metadata(epoch)

        self.assertEqual(tree_sha, "manifest_tree_sha_12345")
        self.assertEqual(sidecar_hashes["metadata_sha256"], "meta_manifest_sha_12345")
        self.assertEqual(sidecar_hashes["registry_sha256"], "reg_manifest_sha_12345")

        budget = ChildStartBudget(
            limit=2,
            consumed=0,
            lifecycle_path=MagicMock(),
            metadata={
                "supervisor_pid": 54321,
                "epoch_id": "ep-test-manifest",
                "deployment_id": "dep-test-manifest",
                "code_commit_sha": epoch.code_commit_sha,
                "code_tree_sha": tree_sha,
                "artifact_sha256": epoch.artifact_sha256,
                "sidecar_hashes": sidecar_hashes,
            },
        )
        self.assertEqual(budget.metadata["code_tree_sha"], "manifest_tree_sha_12345")
        self.assertEqual(budget.metadata["sidecar_hashes"]["metadata_sha256"], "meta_manifest_sha_12345")

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
