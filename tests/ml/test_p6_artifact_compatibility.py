from __future__ import annotations

import copy
import json

import joblib
import pytest

from btc_scraper.ml_engine.artifact_compatibility import (
    CompatibilityStatus,
    RuntimeFeatureSchema,
    compatibility_manifest_path_for_artifact,
    compute_compatibility_hash,
    load_compatibility_manifest,
    validate_artifact_compatibility,
)
from btc_scraper.ml_engine.governed_artifact_loader import (
    ArtifactGovernanceError,
    get_governed_artifact_loader,
)
from btc_scraper.ml_engine.inference_contract import feature_schema_hash


FEATURES = ("return_8", "return_32", "return_72", "abs_move_72")
SCHEMA = RuntimeFeatureSchema.from_names(FEATURES, schema_version="meta-v3.1-43f")


def manifest() -> dict:
    path = compatibility_manifest_path_for_artifact("logs/meta_model.joblib")
    return load_compatibility_manifest(path)


def test_manifest_hash_is_deterministic_and_pinned():
    item = manifest()
    assert item["feature_schema"]["inference_feature_schema_hash"] == feature_schema_hash(FEATURES)
    assert item["compatibility_hash"] == compute_compatibility_hash(item)


def test_canonical_artifact_validates_ready_without_training_csv_dependency():
    item = manifest()
    artifact = joblib.load("logs/meta_model.joblib")
    result = validate_artifact_compatibility(
        "logs/meta_model.joblib",
        item,
        SCHEMA,
        artifact_obj=artifact,
        metadata=json.loads(open("logs/meta_model.json", encoding="utf-8").read()),
    )

    assert result.status is CompatibilityStatus.READY
    assert result.ready
    assert result.artifact_sha256 == item["artifact"]["sha256"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda item: item["artifact"].update({"sha256": "0" * 64}), "ARTIFACT_HASH_MISMATCH"),
        (
            lambda item: item["feature_schema"].update(
                {"ordered_names": list(reversed(item["feature_schema"]["ordered_names"]))}
            ),
            "FEATURE_ORDER_MISMATCH",
        ),
        (lambda item: item["model_config"].update({"runtime_wrapper_class": "wrong.Wrapper"}), "MODEL_METADATA_MISMATCH"),
        (lambda item: item["preprocessing"].update({"required_parameter_sets": ["BTC"]}), "PREPROCESSING_MISMATCH"),
        (lambda item: item["calibration"].update({"status": "isotonic"}), "CALIBRATION_MISMATCH"),
    ],
)
def test_negative_matrix_fails_closed(mutation, reason):
    item = copy.deepcopy(manifest())
    mutation(item)
    item["compatibility_hash"] = compute_compatibility_hash(item)
    artifact = joblib.load("logs/meta_model.joblib")

    result = validate_artifact_compatibility(
        "logs/meta_model.joblib",
        item,
        SCHEMA,
        artifact_obj=artifact,
    )

    assert result.status is not CompatibilityStatus.READY
    assert result.reason_code == reason


def test_missing_manifest_is_incompatible_artifact_not_hold():
    result = validate_artifact_compatibility("logs/meta_model.joblib", None, SCHEMA)

    assert result.status is CompatibilityStatus.INCOMPATIBLE_ARTIFACT
    assert result.reason_code == "MANIFEST_MISSING"
    assert result.status.value != "HOLD"


def test_runtime_loader_exposes_artifact_closure_result():
    loaded = get_governed_artifact_loader().load_production("meta_model", "meta-v3.1-43f")

    assert loaded.metadata["artifact_compatibility"]["status"] == "READY"
    assert loaded.metadata["artifact_compatibility"]["compatibility_hash"] == manifest()["compatibility_hash"]


def test_runtime_loader_rejects_missing_manifest_before_economic_decision(monkeypatch):
    missing = compatibility_manifest_path_for_artifact("logs/meta_model.joblib").with_name("missing.compatibility.json")
    monkeypatch.setattr(
        "btc_scraper.ml_engine.governed_artifact_loader.compatibility_manifest_path_for_artifact",
        lambda path: missing,
    )

    with pytest.raises(ArtifactGovernanceError, match="INCOMPATIBLE_ARTIFACT:MANIFEST_MISSING"):
        get_governed_artifact_loader().load_production("meta_model", "meta-v3.1-43f")
