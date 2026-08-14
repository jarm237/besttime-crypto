import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    module_name = name.removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_temporal_eligibility_purges_labels_after_cutoff():
    module = _load_script("train_temporal_research_model.py")
    frame = pd.DataFrame([
        {
            "feature_available_at": pd.Timestamp("2024-11-30T23:45:00Z"),
            "label_available_at": pd.Timestamp("2024-11-30T23:59:00Z"),
            "label_complete": True,
        },
        {
            "feature_available_at": pd.Timestamp("2024-11-30T23:45:00Z"),
            "label_available_at": pd.Timestamp("2024-12-01T00:15:00Z"),
            "label_complete": True,
        },
        {
            "feature_available_at": pd.Timestamp("2024-11-30T23:45:00Z"),
            "label_available_at": pd.Timestamp("2024-11-30T23:59:00Z"),
            "label_complete": False,
        },
    ])

    eligible = module.temporal_eligible(
        frame,
        feature_start=None,
        feature_end=pd.Timestamp("2024-11-30T23:59:59Z"),
        availability_end=pd.Timestamp("2024-11-30T23:59:59Z"),
    )

    assert eligible.index.tolist() == [0]


def test_research_manifest_temporal_gate_uses_derived_earliest_time():
    module = _load_script("hmr_v1_baseline.py")
    manifest = {
        "evaluation_earliest_allowed": "2024-12-31T23:59:59.000001Z",
        "model_version": "research-v1",
        "artifact_sha256": "abc",
        "research_training_run_id": "run-1",
        "training_available_max": "2024-11-30T23:00:00Z",
        "calibration_available_max": "2024-12-31T23:59:59Z",
        "gates": {
            "TRAINING_TEMPORAL_VALIDITY": "PASS",
            "CALIBRATION_TEMPORAL_VALIDITY": "PASS",
            "LABEL_TEMPORAL_VALIDITY": "PASS",
            "DATASET_PROVENANCE": "PASS",
            "ARTIFACT_PROVENANCE": "PASS",
            "DETERMINISTIC_TRAINING": "PASS",
        },
    }

    gate = module._model_temporal_validity(
        pd.Timestamp("2025-01-01T00:00:00Z"), manifest
    )

    assert gate["status"] == "PASS"
    assert gate["classification"] == "PROVEN_PRE_WINDOW"
