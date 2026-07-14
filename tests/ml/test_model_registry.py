from btc_scraper.ml_engine.model_registry import ModelRegistry
from btc_scraper.ml_engine.artifact_resolver import sha256_file


def test_registry_promotes_one_version_and_allows_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr("btc_scraper.ml_engine.model_registry.ROOT", tmp_path)
    (tmp_path / "a.bin").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register({"model_name": "x", "version": "1", "status": "production", "artifact_path": "a.bin"})
    registry.register({"model_name": "x", "version": "2", "status": "production", "artifact_path": "b.bin"})
    assert registry.active("x")["version"] == "2"
    assert registry.rollback("x", "1")["status"] == "production"
    assert registry.permits_artifact("x", tmp_path / "a.bin", sha256_file(tmp_path / "a.bin"))
