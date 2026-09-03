import json
import sqlite3
import hashlib
from pathlib import Path
import pytest

from scripts.repair_evidence_epoch_lineage import calculate_manifest_sha256, repair_sqlite_file


def test_calculate_manifest_sha256_canonical_format():
    manifest = {
        "release_sha": "abc",
        "artifact_sha256": "123",
    }
    manifest_dict, h1 = calculate_manifest_sha256(manifest)
    manifest_dict2, h2 = calculate_manifest_sha256(json.dumps(manifest))
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64


def test_repair_sqlite_file_dry_run_does_not_mutate(tmp_path):
    db_path = tmp_path / "global_evidence_index.sqlite"
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
        "artifact_sha256": "art1",
        "metadata_sha256": "meta1",
        "registry_sha256": "reg1",
        "deployment_id": "dep1",
        "paper_run_id": "dep1",
        "feature_schema_version": "schema1",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)"
    }
    manifest_json = json.dumps(manifest, sort_keys=True)
    bad_hash = "badhash123"

    from btc_scraper.core.config import analysis_universe_hash
    cur.execute("""
        INSERT INTO evidence_epochs VALUES (
            'epoch-1', 'dep1', '2026-01-01T00:00:00Z', 'commit1', 'v1', 'art1', 'schema1',
            'BTC,ETH', ?, 'ACTIVE', 'dep1', ?, 'badhash123', '2026-01-01T00:00:00Z'
        )
    """, (analysis_universe_hash(("BTC", "ETH")), manifest_json))
    conn.commit()
    conn.close()

    res = repair_sqlite_file(db_path, apply=False)
    assert res["scanned"] == 1
    assert res["repaired"] == 0
    assert res["errors"] == 0

    # Verify database was not changed
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute("SELECT release_manifest_sha256 FROM evidence_epochs WHERE epoch_id='epoch-1'").fetchone()
    assert row[0] == "badhash123"
    conn2.close()


def test_repair_sqlite_file_apply_creates_backup_and_audit(tmp_path):
    db_path = tmp_path / "global_evidence_index.sqlite"
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
        "artifact_sha256": "art1",
        "metadata_sha256": "meta1",
        "registry_sha256": "reg1",
        "deployment_id": "dep1",
        "paper_run_id": "dep1",
        "feature_schema_version": "schema1",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)"
    }
    manifest_json = json.dumps(manifest, sort_keys=True)

    from btc_scraper.core.config import analysis_universe_hash
    cur.execute("""
        INSERT INTO evidence_epochs VALUES (
            'epoch-1', 'dep1', '2026-01-01T00:00:00Z', 'commit1', 'v1', 'art1', 'schema1',
            'BTC,ETH', ?, 'ACTIVE', 'dep1', ?, 'badhash123', '2026-01-01T00:00:00Z'
        )
    """, (analysis_universe_hash(("BTC", "ETH")), manifest_json))
    conn.commit()
    conn.close()

    res = repair_sqlite_file(db_path, apply=True)
    assert res["scanned"] == 1
    assert res["repaired"] == 1
    assert res["errors"] == 0

    # Verify DB was updated and audit log written
    conn2 = sqlite3.connect(db_path)
    _, expected_hash = calculate_manifest_sha256(manifest_json)
    row = conn2.execute("SELECT release_manifest_sha256 FROM evidence_epochs WHERE epoch_id='epoch-1'").fetchone()
    assert row[0] == expected_hash

    audit = conn2.execute("SELECT old_hash, new_hash FROM epoch_repair_audit WHERE epoch_id='epoch-1'").fetchone()
    assert audit is not None
    assert audit[0] == "badhash123"
    assert audit[1] == expected_hash
    conn2.close()
