from btc_scraper.ml_engine.model_registry import ModelRegistry
from btc_scraper.ml_engine.model_registry import RegistryConflictError
from btc_scraper.ml_engine.artifact_resolver import sha256_file
from concurrent.futures import ThreadPoolExecutor
import pytest


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


def test_concurrent_registrations_preserve_every_record(tmp_path, monkeypatch):
    monkeypatch.setattr("btc_scraper.ml_engine.model_registry.ROOT", tmp_path)
    registry = ModelRegistry(tmp_path / "registry.json")
    def register(index):
        path = tmp_path / f"{index}.bin"
        path.write_bytes(str(index).encode())
        registry.register({"model_name": "x", "version": str(index), "status": "candidate", "artifact_path": path.name})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(register, range(20)))
    assert len(registry._read()["records"]) == 20


def test_promotion_uses_compare_and_set(tmp_path, monkeypatch):
    monkeypatch.setattr("btc_scraper.ml_engine.model_registry.ROOT", tmp_path)
    for name in ("prod.bin", "cand.bin"):
        (tmp_path / name).write_bytes(name.encode())
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register({"model_name": "x", "version": "1", "status": "production", "artifact_path": "prod.bin"})
    registry.register({"model_name": "x", "version": "2", "status": "candidate", "artifact_path": "cand.bin"})
    with pytest.raises(RegistryConflictError):
        registry.promote("x", "2", "stale-production")
    promoted = registry.promote("x", "2", "1")
    assert promoted["status"] == "production"
    assert registry.active("x")["version"] == "2"


def test_meta_promotion_requires_holdout_isolation_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("btc_scraper.ml_engine.model_registry.ROOT", tmp_path)
    for name in ("prod.bin", "cand.bin"):
        (tmp_path / name).write_bytes(name.encode())
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register({"model_name": "meta_model", "version": "1", "status": "production", "artifact_path": "prod.bin"})
    registry.register({"model_name": "meta_model", "version": "2", "status": "candidate", "artifact_path": "cand.bin", "metrics": {"holdout_used_for_selection": True}})
    with pytest.raises(ValueError, match="holdout isolation"):
        registry.promote("meta_model", "2", "1")
