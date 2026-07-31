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
    values = {
        "epoch_id": epoch_id,
        "deployment_id": "paper-shadow-20260730-01",
        "started_at": datetime(2026, 7, 30, tzinfo=timezone.utc).isoformat(),
        "code_commit_sha": "c42b802",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "analysis_universe": DEFAULT_ANALYSIS_UNIVERSE,
        "analysis_universe_hash": analysis_universe_hash(
            DEFAULT_ANALYSIS_UNIVERSE
        ),
    }
    values.update(overrides)
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
    assert store.transition_evidence_epoch("epoch-a", "SEALED").status == "SEALED"
    assert store.transition_evidence_epoch("epoch-b", "ACTIVE").status == "ACTIVE"


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
