import json
import sqlite3
import hashlib
from pathlib import Path
import pytest

from scripts.verify_full_governance_lineage import verify_governance_closure, sha256_file


def test_verify_5way_governance_success(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr("scripts.verify_full_governance_lineage.REPO_ROOT", root)

    logs = root / "logs"
    logs.mkdir(parents=True)
    config = root / "config" / "artifact_compatibility"
    config.mkdir(parents=True)

    joblib = logs / "meta_model.joblib"
    joblib.write_bytes(b"dummy artifact content")
    artifact_sha = sha256_file(joblib)

    # Patch expected canonical SHA for test
    monkeypatch.setattr("scripts.verify_full_governance_lineage.EXPECTED_CANONICAL_SHA", artifact_sha)

    meta = {
        "artifact_sha256": artifact_sha,
        "assembly_kind": "FROZEN_WEIGHTS_RUNTIME_WRAPPER",
        "version": "windows-v5-filter-1.0.0"
    }
    meta_json = logs / "meta_model.json"
    meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    metadata_sha = sha256_file(meta_json)

    registry_path = logs / "model_registry.json"
    from btc_scraper.ml_engine.model_registry import ModelRegistry
    reg = ModelRegistry(registry_path, approved_root=root)
    reg.register({
        "model_name": "meta_model",
        "version": "windows-v5-filter-1.0.0",
        "status": "production",
        "artifact_path": str(joblib),
        "sha256": artifact_sha
    })
    registry_sha = sha256_file(registry_path)

    compat_manifest = {
        "artifact": {"sha256": artifact_sha}
    }
    compat_json = config / "meta_model.compatibility.json"
    compat_json.write_text(json.dumps(compat_manifest, indent=2), encoding="utf-8")

    db_path = logs / "global_evidence_index.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE evidence_epochs (
            epoch_id TEXT PRIMARY KEY,
            deployment_id TEXT,
            started_at TEXT,
            code_commit_sha TEXT,
            model_version TEXT,
            artifact_sha256 TEXT,
            feature_schema_version TEXT,
            analysis_universe TEXT,
            analysis_universe_hash TEXT,
            status TEXT,
            paper_run_id TEXT,
            release_manifest TEXT,
            release_manifest_sha256 TEXT,
            activated_at TEXT
        )
    """)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "commit1",
        "artifact_sha256": artifact_sha,
        "metadata_sha256": metadata_sha,
        "registry_sha256": registry_sha,
        "deployment_id": "dep1",
        "paper_run_id": "dep1",
        "feature_schema_version": "schema1",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)"
    }
    manifest_json = json.dumps(manifest, sort_keys=True)
    manifest_sha = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    from btc_scraper.core.config import analysis_universe_hash
    cur.execute("""
        INSERT INTO evidence_epochs VALUES (
            'epoch-1', 'dep1', '2026-01-01T00:00:00Z', 'commit1', 'windows-v5-filter-1.0.0', ?, 'schema1',
            'BTC,ETH', ?, 'ACTIVE', 'dep1', ?, ?, '2026-01-01T00:00:00Z'
        )
    """, (artifact_sha, analysis_universe_hash(("BTC", "ETH")), manifest_json, manifest_sha))
    conn.commit()
    conn.close()

    monkeypatch.setattr("scripts.verify_full_governance_lineage.KNOWN_STORE_CLASSIFICATIONS", {
        db_path: {
            "category": "TEST_STORE",
            "expected_epoch": "epoch-1",
            "expected_status": "ACTIVE",
            "expected_deployment": "dep1"
        }
    })

    db_stat_before = db_path.stat().st_mtime
    meta_stat_before = meta_json.stat().st_mtime

    res = verify_governance_closure(require_store=db_path)
    assert res is True

    # Read-only proof: files must not have been modified
    assert db_path.stat().st_mtime == db_stat_before
    assert meta_json.stat().st_mtime == meta_stat_before


def test_verify_governance_closure_fails_on_missing_store(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr("scripts.verify_full_governance_lineage.REPO_ROOT", root)
    res = verify_governance_closure(require_store=root / "non_existent.sqlite")
    assert res is False
