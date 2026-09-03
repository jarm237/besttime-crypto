import hashlib
import json

import joblib
import pytest

from btc_scraper.ml_engine.artifact_resolver import ArtifactResolver
from btc_scraper.ml_engine.governed_artifact_loader import ArtifactGovernanceError, GovernedArtifactLoader
from btc_scraper.ml_engine.model_registry import ModelRegistry


def _setup(tmp_path, monkeypatch, *, registered=True, metadata_hash=None, schema="schema-v1"):
    monkeypatch.setattr("btc_scraper.ml_engine.artifact_resolver.ROOT", tmp_path)
    monkeypatch.setattr("btc_scraper.ml_engine.model_registry.ROOT", tmp_path)
    artifact = tmp_path / "model.joblib"
    joblib.dump({"model": "approved"}, artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({
        "artifact_sha256": metadata_hash or digest, "feature_schema_version": schema,
        "model_version": "1", "status": "production", "runtime_contract": "sklearn-joblib-v1",
    }))
    config = tmp_path / "artifacts.yaml"
    config.write_text(
        "demo:\n  production_path: model.joblib\n  metadata_path: metadata.json\n"
        "  schema_version: schema-v1\n  status: production\n"
    )
    registry = ModelRegistry(tmp_path / "registry.json", approved_root=tmp_path)
    if registered:
        registry.register({"model_name": "demo", "version": "1", "status": "production", "artifact_path": "model.joblib"})
    return GovernedArtifactLoader(ArtifactResolver(config), registry, approved_root=tmp_path), artifact


def test_approved_production_artifact_loads(tmp_path, monkeypatch):
    loader, _ = _setup(tmp_path, monkeypatch)
    loaded = loader.load_production("demo", "schema-v1")
    assert loaded.model["model"] == "approved"
    assert len(loaded.registry_revision) == 64
    assert loaded.deployment_slot == "production"
    assert loaded.loaded_at.endswith("+00:00")
    assert "python" in loaded.runtime_versions


def test_unpromoted_artifact_fails_closed(tmp_path, monkeypatch):
    loader, _ = _setup(tmp_path, monkeypatch, registered=False)
    with pytest.raises(ArtifactGovernanceError, match="not_permitted"):
        loader.load_production("demo", "schema-v1")


def test_tampered_artifact_rejected_before_deserialize(tmp_path, monkeypatch):
    loader, artifact = _setup(tmp_path, monkeypatch)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ArtifactGovernanceError, match="sha256_mismatch"):
        loader.load_production("demo", "schema-v1")


def test_schema_mismatch_fails_closed(tmp_path, monkeypatch):
    loader, _ = _setup(tmp_path, monkeypatch)
    with pytest.raises(ArtifactGovernanceError, match="schema_mismatch"):
        loader.load_production("demo", "schema-v2")
