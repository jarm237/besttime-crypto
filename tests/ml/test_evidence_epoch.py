import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest

from btc_scraper.core.config import (
    DEFAULT_ANALYSIS_UNIVERSE,
    analysis_universe_hash,
)
from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _epoch_runtime_identity(monkeypatch):
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "paper-shadow-20260730-01")
    monkeypatch.setenv("BTC_PAPER_RUN_ID", "paper-shadow-20260730-01")


def _epoch(epoch_id="epoch-canary-1", **overrides):
    lookup_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "c42b802",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": ",".join(DEFAULT_ANALYSIS_UNIVERSE),
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    values = {
        "epoch_id": epoch_id,
        "deployment_id": "paper-shadow-20260730-01",
        "started_at": datetime(2026, 7, 30, tzinfo=timezone.utc).isoformat(),
        "code_commit_sha": "c42b802",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "analysis_universe": DEFAULT_ANALYSIS_UNIVERSE,
        "paper_run_id": "paper-shadow-20260730-01",
        "release_manifest": dict(lookup_manifest),
    }
    values.update(overrides)
    values["analysis_universe"] = tuple(values.get("analysis_universe") or ())
    values["analysis_universe_hash"] = overrides.get(
        "analysis_universe_hash",
        analysis_universe_hash(values["analysis_universe"]),
    )
    if "release_manifest" not in overrides:
        release_manifest = dict(values["release_manifest"])
        release_manifest["release_sha"] = str(values["code_commit_sha"])
        release_manifest["artifact_sha256"] = str(values["artifact_sha256"])
        release_manifest["deployment_id"] = str(values["deployment_id"])
        release_manifest["paper_run_id"] = str(values["paper_run_id"])
        release_manifest["feature_schema_version"] = str(values["feature_schema_version"])
        release_manifest["analysis_universe"] = ",".join(
            str(symbol).strip().upper() for symbol in values["analysis_universe"]
        )
        values["release_manifest"] = release_manifest
    return EvidenceEpoch(**values)


def _eligible_prediction(prediction_id="p-epoch", **overrides):
    predicted_at = datetime.now(timezone.utc).isoformat()
    prediction = {
        "event_type": "prediction_created",
        "prediction_id": prediction_id,
        "idempotency_key": f"key-{prediction_id}",
        "signal_id": f"signal-{prediction_id}",
        "deployment_id": "paper-shadow-20260730-01",
        "symbol": "BTCUSDT",
        "decision_context": "entry",
        "caller_context": "agent_orchestrator",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "feature_hash": f"hash-{prediction_id}",
        "git_commit": "c42b802",
        "evidence_eligible": True,
        "predicted_at": predicted_at,
    }
    prediction.update(overrides)
    snapshot = {
        "prediction_id": prediction_id,
        "feature_hash": prediction["feature_hash"],
        "features": [1.0, 2.0],
    }
    return prediction, snapshot


def test_eligible_prediction_requires_active_epoch(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(RuntimeError, match="ACTIVE epoch"):
        store.write_prediction_evidence(*_eligible_prediction())
    assert store.count_rows("predictions") == 0


def test_epoch_cli_runs_directly_outside_repo_cwd(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "manage_evidence_epoch.py"),
            "--help",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--evidence-path" in result.stdout


def _manifest_sha(manifest: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def test_epoch_cli_create_and_load_round_trip(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "manage_evidence_epoch.py"),
            "--evidence-path",
            str(path),
            "create",
            "--epoch-id",
            "epoch-cli-1",
            "--deployment-id",
            "paper-shadow-20260730-01",
            "--code-commit-sha",
            "91cf0e9",
            "--model-version",
            "meta-v3",
            "--artifact-sha256",
            "artifact-v3",
            "--feature-schema-version",
            "schema-v3",
            "--analysis-universe",
            "BTC,ETH,BNB",
            "--release-manifest-file",
            str(manifest_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    store = RuntimeEvidenceStore(path)
    loaded = store.get_evidence_epoch("epoch-cli-1")
    assert loaded is not None
    assert loaded.paper_run_id == "paper-shadow-20260730-01"
    assert loaded.release_manifest_sha256 == _manifest_sha(loaded.release_manifest)


def test_release_manifest_hash_is_key_order_independent():
    left = {
        "release_sha": "abc",
        "artifact_sha256": "artifact",
        "manifest_schema_version": "evidence-manifest-v1",
        "metadata_sha256": "meta",
        "registry_sha256": "registry",
        "deployment_id": "paper-shadow",
        "paper_run_id": "paper-shadow",
        "feature_schema_version": "schema-v1",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    right = {
        "artifact_sha256": "artifact",
        "release_sha": "abc",
        "manifest_schema_version": "evidence-manifest-v1",
        "registry_sha256": "registry",
        "metadata_sha256": "meta",
        "deployment_id": "paper-shadow",
        "feature_schema_version": "schema-v1",
        "paper_run_id": "paper-shadow",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    assert _manifest_sha(left) == _manifest_sha(right)


def test_release_manifest_hash_is_whitespace_independent(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "abc",
        "artifact_sha256": "artifact",
        "metadata_sha256": "meta",
        "registry_sha256": "registry",
        "deployment_id": "paper-shadow",
        "paper_run_id": "paper-shadow",
        "feature_schema_version": "schema-v1",
        "analysis_universe": "BTC, ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = _epoch(
        epoch_id="epoch-whitespace-1",
        code_commit_sha="abc",
        artifact_sha256="artifact",
        feature_schema_version="schema-v1",
        analysis_universe=("BTC", "ETH"),
        release_manifest=manifest,
    )
    normalized = store._normalize_release_manifest(manifest, epoch)
    expected = store._normalize_release_manifest(normalized, epoch)
    assert store._release_manifest_sha256(normalized) == store._release_manifest_sha256(expected)


def test_release_manifest_hash_normalizes_analysis_universe_list_and_string(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest_list = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": ["BTC", "ETH", "BNB"],
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = _epoch(
        epoch_id="epoch-canonical-universe",
        code_commit_sha="91cf0e9",
        analysis_universe=("BTC", "ETH", "BNB"),
        release_manifest=manifest_list,
    )
    result = store.create_evidence_epoch(epoch)
    assert result.release_manifest["analysis_universe"] == "BTC,ETH,BNB"
    assert result.release_manifest_sha256 == _manifest_sha(result.release_manifest)


def test_release_manifest_hash_changes_when_field_changes():
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "abc",
        "artifact_sha256": "artifact",
        "metadata_sha256": "meta",
        "registry_sha256": "registry",
        "deployment_id": "paper-shadow",
        "paper_run_id": "paper-shadow",
        "feature_schema_version": "schema-v1",
        "analysis_universe": "BTC,ETH",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    modified = dict(manifest)
    modified["artifact_sha256"] = "artifact-2"
    assert _manifest_sha(manifest) != _manifest_sha(modified)


def test_tampered_release_manifest_rejects_activation(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = store.create_evidence_epoch(
        _epoch(
            epoch_id="epoch-tampered",
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    with store._global_transaction() as db:
        db.execute(
            "UPDATE evidence_epochs SET release_manifest=? WHERE epoch_id=?",
            (
                json.dumps({**epoch.release_manifest, "release_sha": "other"}),
                epoch.epoch_id,
            ),
        )
    with pytest.raises(ValueError, match="evidence epoch release_manifest"):
        store.transition_evidence_epoch("epoch-tampered", "ACTIVE")


def test_stored_release_manifest_sha_mismatch_rejects_activation(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = store.create_evidence_epoch(
        _epoch(
            epoch_id="epoch-bad-sha",
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    with store._global_transaction() as db:
        db.execute(
            "UPDATE evidence_epochs SET release_manifest_sha256=? WHERE epoch_id=?",
            ("deadbeef", epoch.epoch_id),
        )
    with pytest.raises(ValueError, match="release_manifest_sha256"):
        store.transition_evidence_epoch("epoch-bad-sha", "ACTIVE")


def test_create_evidence_epoch_reuses_same_payload_and_rejects_conflicts(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = store.create_evidence_epoch(
        _epoch(
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    loaded = store.get_evidence_epoch(epoch.epoch_id)
    assert loaded is not None
    assert loaded.paper_run_id == "paper-shadow-20260730-01"
    assert loaded.release_manifest == {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    assert loaded.release_manifest_sha256 == hashlib.sha256(
        json.dumps(loaded.release_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("field,value", [
    ("release_sha", "other-sha"),
    ("artifact_sha256", "other-artifact"),
    ("deployment_id", "other-deployment"),
    ("paper_run_id", "other-paper-run"),
    ("feature_schema_version", "other-schema"),
    ("analysis_universe", "BTC"),
])
def test_create_evidence_epoch_rejects_mismatched_release_manifest(tmp_path, field, value):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    manifest[field] = value
    with pytest.raises(ValueError, match="release_manifest"):
        store.create_evidence_epoch(_epoch(paper_run_id="paper-shadow-20260730-01", release_manifest=manifest))


def test_create_evidence_epoch_requires_manifest_schema_and_paper_run_id(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    incomplete_manifest = {
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    with pytest.raises(ValueError, match="manifest_schema_version"):
        store.create_evidence_epoch(
            _epoch(
                code_commit_sha="91cf0e9",
                paper_run_id="paper-shadow-20260730-01",
                release_manifest=incomplete_manifest,
            )
        )
    with pytest.raises(ValueError, match="paper_run_id"):
        store.create_evidence_epoch(
            _epoch(
                code_commit_sha="91cf0e9",
                analysis_universe=("BTC", "ETH", "BNB"),
                analysis_universe_hash=analysis_universe_hash(("BTC", "ETH", "BNB")),
                paper_run_id="",
                release_manifest={
                    "manifest_schema_version": "evidence-manifest-v1",
                    "release_sha": "91cf0e9",
                    "artifact_sha256": "artifact-v3",
                    "metadata_sha256": "meta-v3",
                    "registry_sha256": "registry-v3",
                    "deployment_id": "paper-shadow-20260730-01",
                    "paper_run_id": "paper-shadow-20260730-01",
                    "feature_schema_version": "schema-v3",
                    "analysis_universe": "BTC,ETH,BNB",
                    "decision_contract": "side-probability-v2",
                    "probability_semantics": "P(up)",
                },
            )
        )


def test_create_evidence_epoch_reuses_same_payload_and_rejects_conflicts(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    first = store.create_evidence_epoch(
        _epoch(
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    second = store.create_evidence_epoch(
        _epoch(
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    assert second.epoch_id == first.epoch_id

    conflicting_manifest = dict(manifest)
    conflicting_manifest["metadata_sha256"] = "other-metadata"
    with pytest.raises(ValueError, match="conflict"):
        store.create_evidence_epoch(
            _epoch(
                epoch_id="epoch-canary-1",
                code_commit_sha="91cf0e9",
                analysis_universe=("BTC", "ETH", "BNB"),
                release_manifest=conflicting_manifest,
            )
        )


def test_create_evidence_epoch_is_idempotent_when_started_at_differs(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    first = store.create_evidence_epoch(
        _epoch(
            code_commit_sha="91cf0e9",
            started_at="2026-07-30T00:00:00+00:00",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    second = store.create_evidence_epoch(
        _epoch(
            code_commit_sha="91cf0e9",
            started_at="2026-07-30T00:00:01+00:00",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    assert second.epoch_id == first.epoch_id
    assert second.started_at == first.started_at


def test_existing_global_index_is_migrated_without_data_loss(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    global_index = path.parent / "global_evidence_index.sqlite"
    with sqlite3.connect(global_index) as db:
        db.executescript("""
            CREATE TABLE evidence_epochs (
                epoch_id TEXT PRIMARY KEY,
                deployment_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                activated_at TEXT,
                code_commit_sha TEXT NOT NULL,
                model_version TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                feature_schema_version TEXT NOT NULL,
                analysis_universe TEXT NOT NULL,
                analysis_universe_hash TEXT NOT NULL,
                evidence_policy_version TEXT NOT NULL,
                risk_policy_version TEXT NOT NULL,
                runtime_schema_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                runtime_pause_policy TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                written_at TEXT NOT NULL
            );
            INSERT INTO evidence_epochs (
                epoch_id, deployment_id, started_at, activated_at, code_commit_sha,
                model_version, artifact_sha256, feature_schema_version,
                analysis_universe, analysis_universe_hash, evidence_policy_version,
                risk_policy_version, runtime_schema_version, status,
                runtime_pause_policy, updated_at
            ) VALUES (
                'legacy-epoch', 'legacy-deployment', '2026-01-01T00:00:00+00:00', NULL,
                'legacy-commit', 'legacy-model', 'legacy-artifact', 'legacy-schema',
                '[]', 'legacy-hash', 'evidence-v4', 'risk-fail-closed-v1', 6,
                'DRAFT', '{}', '2026-01-01T00:00:00+00:00'
            );
            INSERT INTO audit_events (event_type, payload, payload_sha256, written_at)
            VALUES (
                'LEGACY_AUDIT', '{"epoch_id":"legacy-epoch"}',
                'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef',
                '2026-01-01T00:00:00+00:00'
            );
        """)

    store = RuntimeEvidenceStore(path)
    with store._global_connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(evidence_epochs)").fetchall()}
        assert {"paper_run_id", "release_manifest", "release_manifest_sha256"} <= columns
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(1) FROM evidence_epochs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(1) FROM audit_events").fetchone()[0] == 1

    row = store.get_evidence_epoch("legacy-epoch")
    assert row is not None
    assert row.epoch_id == "legacy-epoch"
    assert row.status == "DRAFT"
    assert row.paper_run_id == ""
    assert row.release_manifest is None

    with pytest.raises(ValueError, match="evidence epoch"):
        store.transition_evidence_epoch("legacy-epoch", "ACTIVE")
    assert store.get_evidence_epoch("legacy-epoch").status == "DRAFT"

    new_epoch = store.create_evidence_epoch(
        _epoch(
            epoch_id="new-epoch",
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
        )
    )
    assert new_epoch.epoch_id == "new-epoch"

    reopened = RuntimeEvidenceStore(path)
    assert reopened.get_evidence_epoch("legacy-epoch") is not None
    assert reopened.get_evidence_epoch("new-epoch") is not None
    assert reopened.get_evidence_epoch("legacy-epoch").status == "DRAFT"
    assert reopened.get_evidence_epoch("new-epoch").status == "DRAFT"


def test_create_evidence_epoch_conflicts_with_legacy_epoch(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    global_index = path.parent / "global_evidence_index.sqlite"
    with sqlite3.connect(global_index) as db:
        db.executescript("""
            CREATE TABLE evidence_epochs (
                epoch_id TEXT PRIMARY KEY,
                deployment_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                activated_at TEXT,
                code_commit_sha TEXT NOT NULL,
                model_version TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                feature_schema_version TEXT NOT NULL,
                analysis_universe TEXT NOT NULL,
                analysis_universe_hash TEXT NOT NULL,
                evidence_policy_version TEXT NOT NULL,
                risk_policy_version TEXT NOT NULL,
                runtime_schema_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                runtime_pause_policy TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            INSERT INTO evidence_epochs (
                epoch_id, deployment_id, started_at, activated_at, code_commit_sha,
                model_version, artifact_sha256, feature_schema_version,
                analysis_universe, analysis_universe_hash, evidence_policy_version,
                risk_policy_version, runtime_schema_version, status,
                runtime_pause_policy, updated_at
            ) VALUES (
                'legacy-epoch', 'legacy-deployment', '2026-01-01T00:00:00+00:00', NULL,
                'legacy-commit', 'legacy-model', 'legacy-artifact', 'legacy-schema',
                '[]', 'legacy-hash', 'evidence-v4', 'risk-fail-closed-v1', 6,
                'DRAFT', '{}', '2026-01-01T00:00:00+00:00'
            );
        """)
    store = RuntimeEvidenceStore(path)
    with pytest.raises(ValueError, match="conflict"):
        store.create_evidence_epoch(_epoch(epoch_id="legacy-epoch"))


def test_legacy_epoch_cannot_be_activated(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    global_index = path.parent / "global_evidence_index.sqlite"
    with sqlite3.connect(global_index) as db:
        db.executescript("""
            CREATE TABLE evidence_epochs (
                epoch_id TEXT PRIMARY KEY,
                deployment_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                activated_at TEXT,
                code_commit_sha TEXT NOT NULL,
                model_version TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                feature_schema_version TEXT NOT NULL,
                analysis_universe TEXT NOT NULL,
                analysis_universe_hash TEXT NOT NULL,
                evidence_policy_version TEXT NOT NULL,
                risk_policy_version TEXT NOT NULL,
                runtime_schema_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                runtime_pause_policy TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            INSERT INTO evidence_epochs (
                epoch_id, deployment_id, started_at, activated_at, code_commit_sha,
                model_version, artifact_sha256, feature_schema_version,
                analysis_universe, analysis_universe_hash, evidence_policy_version,
                risk_policy_version, runtime_schema_version, status,
                runtime_pause_policy, updated_at
            ) VALUES (
                'legacy-epoch', 'legacy-deployment', '2026-01-01T00:00:00+00:00', NULL,
                'legacy-commit', 'legacy-model', 'legacy-artifact', 'legacy-schema',
                '[]', 'legacy-hash', 'evidence-v4', 'risk-fail-closed-v1', 6,
                'DRAFT', '{}', '2026-01-01T00:00:00+00:00'
            );
        """)
    store = RuntimeEvidenceStore(path)
    with pytest.raises(ValueError, match="evidence epoch"):
        store.transition_evidence_epoch("legacy-epoch", "ACTIVE")


def test_active_epoch_is_persisted_and_attached_to_evidence(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    store.create_evidence_epoch(_epoch())
    assert store.get_evidence_epoch("epoch-canary-1").activated_at is None
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    prediction = store.write_prediction_evidence(*_eligible_prediction())
    assert prediction["epoch_id"] == "epoch-canary-1"
    assert store.get_feature_snapshot("p-epoch")["epoch_id"] == "epoch-canary-1"
    assert store.get_active_evidence_epoch().activated_at is not None

    restarted = RuntimeEvidenceStore(path)
    assert restarted.get_active_evidence_epoch().epoch_id == "epoch-canary-1"


def test_transition_to_active_records_audit_event(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch(code_commit_sha="91cf0e9"))

    assert store.count_rows("audit_events") == 0
    active_epoch = store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    assert active_epoch.status == "ACTIVE"
    assert store.count_rows("audit_events") == 1
    audit_payload = store.shadow_evidence_rows()["audit_events"][0]
    assert audit_payload["event_type"] == "EPOCH_ACTIVATION_RECORDED"
    assert audit_payload["epoch_id"] == "epoch-canary-1"
    assert audit_payload["deployment_id"] == "paper-shadow-20260730-01"
    assert audit_payload["previous_status"] == "DRAFT"
    assert audit_payload["new_status"] == "ACTIVE"
    assert audit_payload["release_manifest_sha256"] == active_epoch.release_manifest_sha256
    assert audit_payload["paper_run_id"] == "paper-shadow-20260730-01"
    assert audit_payload["code_commit_sha"] == "91cf0e9"
    assert audit_payload["artifact_sha256"] == "artifact-v3"
    assert audit_payload["activated_at"] == active_epoch.activated_at
    assert store.get_evidence_epoch("epoch-canary-1").activated_at == audit_payload["activated_at"]


def test_activation_rolls_back_when_audit_insert_fails(tmp_path, monkeypatch):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())

    def fail_audit(db, event):
        raise sqlite3.OperationalError("audit insert failed")

    monkeypatch.setattr(store, "_insert_audit_event_db", fail_audit)
    with pytest.raises(sqlite3.OperationalError, match="audit insert failed"):
        store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    epoch = store.get_evidence_epoch("epoch-canary-1")
    assert epoch is not None
    assert epoch.status == "DRAFT"
    assert epoch.activated_at is None
    assert store.count_rows("audit_events") == 0
    assert store.get_active_evidence_epoch() is None


def test_activation_replay_is_idempotent_and_does_not_duplicate_audit(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    first = store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    second = store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    assert first.epoch_id == second.epoch_id
    assert first.status == "ACTIVE"
    assert second.status == "ACTIVE"
    assert store.count_rows("audit_events") == 1
    audit_payload = store.shadow_evidence_rows()["audit_events"][0]
    assert audit_payload["event_type"] == "EPOCH_ACTIVATION_RECORDED"
    assert audit_payload["epoch_id"] == "epoch-canary-1"
    assert audit_payload["new_status"] == "ACTIVE"
    assert audit_payload["activated_at"] == first.activated_at


@pytest.mark.parametrize("field,value,match", [
    ("release_sha", "other-sha", "release_manifest release_sha mismatch"),
    ("artifact_sha256", "other-artifact", "release_manifest artifact_sha256 mismatch"),
    ("deployment_id", "other-deployment", "release_manifest deployment_id mismatch"),
    ("paper_run_id", "other-paper-run", "release_manifest paper_run_id mismatch"),
    ("feature_schema_version", "other-schema", "release_manifest feature_schema_version mismatch"),
    ("analysis_universe", "BTC", "release_manifest analysis_universe mismatch"),
    ("decision_contract", "other-contract", "release_manifest decision_contract mismatch"),
    ("probability_semantics", "other-semantics", "release_manifest probability_semantics mismatch"),
])
def test_activation_rejects_mismatched_release_manifest_fields(tmp_path, field, value, match):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = store.create_evidence_epoch(
        _epoch(
            epoch_id="epoch-activation-reject",
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    with store._global_transaction() as db:
        db.execute(
            "UPDATE evidence_epochs SET release_manifest=? WHERE epoch_id=?",
            (
                json.dumps({**epoch.release_manifest, field: value}),
                epoch.epoch_id,
            ),
        )
    assert store.get_evidence_epoch(epoch.epoch_id).status == "DRAFT"
    with pytest.raises(ValueError, match=match):
        store.transition_evidence_epoch(epoch.epoch_id, "ACTIVE")
    epoch_after = store.get_evidence_epoch(epoch.epoch_id)
    assert epoch_after is not None
    assert epoch_after.status == "DRAFT"
    assert epoch_after.activated_at is None
    assert store.count_rows("audit_events") == 0


def test_activation_does_not_record_audit_event_when_manifest_is_tampered(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "91cf0e9",
        "artifact_sha256": "artifact-v3",
        "metadata_sha256": "meta-v3",
        "registry_sha256": "registry-v3",
        "deployment_id": "paper-shadow-20260730-01",
        "paper_run_id": "paper-shadow-20260730-01",
        "feature_schema_version": "schema-v3",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = store.create_evidence_epoch(
        _epoch(
            epoch_id="epoch-tampered-2",
            code_commit_sha="91cf0e9",
            analysis_universe=("BTC", "ETH", "BNB"),
            release_manifest=manifest,
        )
    )
    with store._global_transaction() as db:
        db.execute(
            "UPDATE evidence_epochs SET release_manifest=? WHERE epoch_id=?",
            (
                json.dumps({**epoch.release_manifest, "release_sha": "other"}),
                epoch.epoch_id,
            ),
        )

    assert store.count_rows("audit_events") == 0
    with pytest.raises(ValueError, match="evidence epoch release_manifest"):
        store.transition_evidence_epoch("epoch-tampered-2", "ACTIVE")
    assert store.count_rows("audit_events") == 0


@pytest.mark.parametrize("field,value", [
    ("deployment_id", "other-deployment"),
    ("model_version", "other-model"),
    ("artifact_sha256", "other-artifact"),
    ("feature_schema_version", "other-schema"),
    ("git_commit", "other-commit"),
    ("epoch_id", "other-epoch"),
])
def test_active_epoch_rejects_mixed_lineage(tmp_path, field, value):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    prediction, snapshot = _eligible_prediction(**{field: value})
    with pytest.raises(RuntimeError, match="active evidence epoch mismatch"):
        store.write_prediction_evidence(prediction, snapshot)
    assert store.count_rows("predictions") == 0


def test_sealed_epoch_cannot_receive_new_evidence(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    store.transition_evidence_epoch("epoch-canary-1", "SEAL_READY")
    store.transition_evidence_epoch("epoch-canary-1", "SEALED")

    with pytest.raises(RuntimeError, match="ACTIVE epoch"):
        store.write_prediction_evidence(*_eligible_prediction())


def test_epoch_state_machine_and_single_active_epoch(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch("epoch-a"))
    store.create_evidence_epoch(_epoch("epoch-b"))
    store.transition_evidence_epoch("epoch-a", "ACTIVE")
    with pytest.raises(Exception):
        store.transition_evidence_epoch("epoch-b", "ACTIVE")
    with pytest.raises(ValueError, match="invalid evidence epoch transition"):
        store.transition_evidence_epoch("epoch-a", "DRAFT")
    assert store.transition_evidence_epoch("epoch-a", "SEAL_BLOCKED").status == "SEAL_BLOCKED"
    with pytest.raises(Exception):
        store.transition_evidence_epoch("epoch-b", "ACTIVE")
    assert store.transition_evidence_epoch("epoch-a", "SEAL_READY").status == "SEAL_READY"
    assert store.transition_evidence_epoch("epoch-a", "SEALED").status == "SEALED"
    assert store.transition_evidence_epoch("epoch-b", "ACTIVE").status == "ACTIVE"


def test_invalidate_active_epoch_records_audit_event(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    result = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
        contributing_reasons=[
            "ACTIVATION_BEFORE_PREFLIGHT",
            "UNIVERSE_EXPANDED_OUTSIDE_APPROVED_CANARY",
            "PINNED_RUNTIME_NOT_USED_FOR_ACTIVATION",
            "PAPER_RUN_ID_REUSED",
        ],
    )

    assert result.status == "INVALIDATED"
    assert store.get_evidence_epoch("epoch-canary-1").status == "INVALIDATED"
    assert store.count_rows("audit_events") == 2
    payloads = store.shadow_evidence_rows()["audit_events"]
    invalidation_payloads = [
        payload for payload in payloads
        if payload["event_type"] == "EPOCH_INVALIDATION_AUDIT_RECORDED"
    ]
    assert len(invalidation_payloads) == 1
    payload = invalidation_payloads[0]
    assert payload["epoch_id"] == "epoch-canary-1"
    assert payload["reason_code"] == "DEPLOYMENT_RUNTIME_NAMESPACE_REUSED"
    assert payload["retroactive_audit"] is True


def test_invalidate_missing_reason_is_rejected(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    with pytest.raises(ValueError, match="reason_code is required for invalidate"):
        store.invalidate_evidence_epoch(
            "epoch-canary-1",
            reason_code="",
            reason_detail="Deployment, paper-run and runtime namespace were reused.",
        )

    with pytest.raises(ValueError, match="reason_detail is required for invalidate"):
        store.invalidate_evidence_epoch(
            "epoch-canary-1",
            reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
            reason_detail="",
        )


def test_repeated_invalidation_with_same_reason_is_idempotent(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    first = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
    )
    second = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
    )

    assert first.epoch_id == second.epoch_id
    assert store.count_rows("audit_events") == 2


def test_invalidate_already_invalidated_without_audit_appends_retroactive_audit(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    with store._global_connect() as db:
        db.execute(
            "UPDATE evidence_epochs SET status='INVALIDATED', updated_at=? WHERE epoch_id=?",
            (datetime(2026, 8, 4, 16, 34, 43, 194035, tzinfo=timezone.utc).isoformat(), "epoch-canary-1"),
        )
        db.commit()

    result = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
        contributing_reasons=[
            "ACTIVATION_BEFORE_PREFLIGHT",
            "UNIVERSE_EXPANDED_OUTSIDE_APPROVED_CANARY",
            "PINNED_RUNTIME_NOT_USED_FOR_ACTIVATION",
            "PAPER_RUN_ID_REUSED",
        ],
    )

    assert result.status == "INVALIDATED"
    assert store.get_evidence_epoch("epoch-canary-1").status == "INVALIDATED"
    assert store.count_rows("audit_events") == 2
    payloads = store.shadow_evidence_rows()["audit_events"]
    invalidation_payloads = [
        payload for payload in payloads
        if payload["event_type"] == "EPOCH_INVALIDATION_AUDIT_RECORDED"
    ]
    assert len(invalidation_payloads) == 1
    payload = invalidation_payloads[0]
    assert payload["epoch_id"] == "epoch-canary-1"
    assert payload["reason_code"] == "DEPLOYMENT_RUNTIME_NAMESPACE_REUSED"
    assert payload["retroactive_audit"] is True
    assert payload["invalidated_at"] == "2026-08-04T16:34:43.194035+00:00"
    assert payload["audit_recorded_at"] != payload["invalidated_at"]


def test_invalidate_already_invalidated_with_matching_audit_is_noop(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    with store._global_connect() as db:
        db.execute(
            "UPDATE evidence_epochs SET status='INVALIDATED', updated_at=? WHERE epoch_id=?",
            (datetime(2026, 8, 4, 16, 34, 43, 194035, tzinfo=timezone.utc).isoformat(), "epoch-canary-1"),
        )
        db.commit()

    first = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
    )
    second = store.invalidate_evidence_epoch(
        "epoch-canary-1",
        reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
        reason_detail="Deployment, paper-run and runtime namespace were reused.",
    )

    assert first.epoch_id == second.epoch_id
    assert store.count_rows("audit_events") == 2


def test_invalidate_already_invalidated_with_conflicting_reason_is_rejected(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    with store._global_connect() as db:
        db.execute(
            "UPDATE evidence_epochs SET status='INVALIDATED', updated_at=? WHERE epoch_id=?",
            (datetime(2026, 8, 4, 16, 34, 43, 194035, tzinfo=timezone.utc).isoformat(), "epoch-canary-1"),
        )
        payload = {
            "event_type": "EPOCH_INVALIDATION_AUDIT_RECORDED",
            "epoch_id": "epoch-canary-1",
            "reason_code": "DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
            "reason_detail": "Deployment, paper-run and runtime namespace were reused.",
            "contributing_reasons": [],
            "invalidated_at": "2026-08-04T16:34:43.194035+00:00",
            "audit_recorded_at": "2026-08-04T16:40:00+00:00",
            "retroactive_audit": True,
        }
        db.execute(
            "INSERT INTO audit_events(event_type,payload,payload_sha256,written_at) VALUES (?,?,?,?)",
            (
                payload["event_type"],
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest(),
                datetime(2026, 8, 4, 16, 40, tzinfo=timezone.utc).isoformat(),
            ),
        )
        db.commit()

    with pytest.raises(ValueError, match="already invalidated with a different reason"):
        store.invalidate_evidence_epoch(
            "epoch-canary-1",
            reason_code="SOME_OTHER_REASON",
            reason_detail="Different reason",
        )


def test_invalidate_unknown_epoch_is_rejected(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(ValueError, match="unknown evidence epoch"):
        store.invalidate_evidence_epoch(
            "missing-epoch",
            reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
            reason_detail="Missing epoch",
        )


def test_invalidate_atomicity_rolls_back_on_audit_failure(tmp_path, monkeypatch):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    def fail_insert(db, event):
        raise sqlite3.OperationalError("insert failed")

    monkeypatch.setattr(store, "_insert_audit_event_db", fail_insert)
    with pytest.raises(sqlite3.OperationalError, match="insert failed"):
        store.invalidate_evidence_epoch(
            "epoch-canary-1",
            reason_code="DEPLOYMENT_RUNTIME_NAMESPACE_REUSED",
            reason_detail="Deployment, paper-run and runtime namespace were reused.",
        )
    assert store.get_evidence_epoch("epoch-canary-1").status == "ACTIVE"


def test_external_pause_policy_is_pinned_without_changing_epoch_state(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    created = store.create_evidence_epoch(_epoch())
    assert created.runtime_pause_policy["policy_version"] == "runtime-pause-v1"
    active = store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    restarted = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    persisted = restarted.get_evidence_epoch(active.epoch_id)

    assert persisted is not None
    assert persisted.status == "ACTIVE"
    assert "RUNTIME_PAUSED_MONGODB_UNAVAILABLE" in persisted.runtime_pause_policy[
        "pausable_reason_codes"
    ]


def test_epoch_policy_versions_fail_closed(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(ValueError, match="evidence policy"):
        store.create_evidence_epoch(_epoch(
            evidence_policy_version="legacy-policy",
        ))
    with pytest.raises(ValueError, match="risk policy"):
        store.create_evidence_epoch(_epoch(
            risk_policy_version="legacy-risk",
        ))


def test_epoch_universe_mismatch_blocks_eligibility_after_restart(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH,BNB")
    universe = ("BTC", "ETH", "BNB")
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch(
        analysis_universe=universe,
        analysis_universe_hash=analysis_universe_hash(universe),
    ))
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH")
    restarted = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(RuntimeError, match="analysis_universe"):
        restarted.assert_runtime_epoch_ready(require_active=True)
    with pytest.raises(RuntimeError, match="analysis_universe"):
        restarted.write_prediction_evidence(*_eligible_prediction())
    assert restarted.count_rows("predictions") == 0


def test_epoch_rejects_symbol_outside_locked_universe(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH,BNB")
    universe = ("BTC", "ETH", "BNB")
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch(
        analysis_universe=universe,
        analysis_universe_hash=analysis_universe_hash(universe),
    ))
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    prediction, snapshot = _eligible_prediction(symbol="SOLUSDT")
    with pytest.raises(RuntimeError, match="symbol_outside_analysis_universe"):
        store.write_prediction_evidence(prediction, snapshot)
    assert store.count_rows("predictions") == 0


def test_epoch_rejects_prediction_before_activation_boundary(tmp_path):
    activated_at = datetime(2026, 7, 30, 1, tzinfo=timezone.utc)
    store = RuntimeEvidenceStore(
        tmp_path / "runtime_evidence.sqlite",
        clock=lambda: activated_at,
    )
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    prediction, snapshot = _eligible_prediction(
        predicted_at=datetime(2026, 7, 30, tzinfo=timezone.utc).isoformat(),
    )
    with pytest.raises(
        RuntimeError, match="prediction_before_epoch_activation",
    ):
        store.write_prediction_evidence(prediction, snapshot)
    assert store.count_rows("predictions") == 0
