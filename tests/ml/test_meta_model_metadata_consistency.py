"""Tests for _artifact_metadata_consistency and meta_model metadata contracts."""
from __future__ import annotations

import unittest
from btc_scraper.ml_engine.meta_model import _artifact_metadata_consistency


class TestMetaModelMetadataConsistency(unittest.TestCase):
    def test_empty_metadata_returns_none(self):
        self.assertIsNone(_artifact_metadata_consistency({}, ["f1"], "v1"))

    def test_canonical_ready_metadata_returns_true(self):
        metadata = {
            "status": "production",
            "features": ["f1", "f2", "f3", "f4"],
            "n_features": 4,
            "artifact_compatibility": {"status": "READY"},
        }
        res = _artifact_metadata_consistency(metadata, ["f1", "f2", "f3", "f4"], "meta-v3.1-43f")
        self.assertTrue(res)

    def test_nested_incompatible_artifact_returns_false(self):
        metadata = {
            "status": "production",
            "features": ["f1", "f2", "f3", "f4"],
            "n_features": 4,
            "artifact_compatibility": {"status": "INCOMPATIBLE_ARTIFACT"},
        }
        res = _artifact_metadata_consistency(metadata, ["f1", "f2", "f3", "f4"], "meta-v3.1-43f")
        self.assertFalse(res)

    def test_mismatched_feature_names_returns_false(self):
        metadata = {
            "status": "production",
            "features": ["f1", "f2", "f3", "f4"],
            "n_features": 4,
        }
        res = _artifact_metadata_consistency(metadata, ["wrong1", "wrong2", "wrong3", "wrong4"], "meta-v3.1-43f")
        self.assertFalse(res)

    def test_mismatched_feature_count_returns_false(self):
        metadata = {
            "status": "production",
            "features": ["f1", "f2"],
            "n_features": 2,
        }
        res = _artifact_metadata_consistency(metadata, ["f1", "f2", "f3", "f4"], "meta-v3.1-43f")
        self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()
