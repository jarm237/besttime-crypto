import hashlib
import json

from btc_scraper.ml_engine.artifact_resolver import ArtifactResolver


def _write_config(tmp_path, digest):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"model")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"artifact_sha256": digest, "feature_schema_version": "v1"}), encoding="utf-8")
    config = tmp_path / "models.yaml"
    config.write_text("demo:\n  production_path: artifact.bin\n  metadata_path: metadata.json\n  schema_version: v1\n  status: production\n", encoding="utf-8")
    return artifact, metadata, config


def test_resolver_rejects_hash_mismatch(tmp_path, monkeypatch):
    artifact, _, config = _write_config(tmp_path, "bad")
    monkeypatch.setattr("btc_scraper.ml_engine.artifact_resolver.ROOT", tmp_path)
    result = ArtifactResolver(config).resolve("demo", require_metadata=True)
    assert result.available and not result.healthy and result.reason == "sha256_mismatch"


def test_resolver_accepts_canonical_artifact(tmp_path, monkeypatch):
    digest = hashlib.sha256(b"model").hexdigest()
    _, _, config = _write_config(tmp_path, digest)
    monkeypatch.setattr("btc_scraper.ml_engine.artifact_resolver.ROOT", tmp_path)
    result = ArtifactResolver(config).resolve("demo", require_metadata=True)
    assert result.healthy and result.sha256 == digest
