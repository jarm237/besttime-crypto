from __future__ import annotations

import os
from pathlib import Path

import pytest

from btc_scraper.ml_engine import meta_model
from btc_scraper.ml_engine import runtime_evidence_store as evidence_module
from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.governed_artifact_loader import get_governed_artifact_loader
from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.signal_score import score_signal
from tests.ml.fixtures.production_lineage import (
    build_smoke_analysis,
    configure_smoke_runtime,
    install_evidence_store,
)


def test_configure_smoke_runtime_uses_non_production_smoke_namespace(monkeypatch, tmp_path):
    runtime_root = configure_smoke_runtime(monkeypatch, tmp_path)

    assert "runtime/production" not in str(runtime_root)
    assert "runtime/smoke" in str(runtime_root)
    assert runtime_root.name == "paper-canary-20260805-01-preflight"
    assert os.getenv("BTC_DEPLOYMENT_ID") == "paper-canary-20260805-01-smoke"
    assert os.getenv("BTC_PAPER_RUN_ID") == "paper-canary-20260805-01-smoke"
    assert os.getenv("BTC_EVIDENCE_ELIGIBLE") == "false"


def test_real_meta_model_artifact_loads_with_governed_loader(monkeypatch, tmp_path):
    configure_smoke_runtime(monkeypatch, tmp_path)
    loaded = get_governed_artifact_loader().load_production("meta_model", "meta-v3.1-43f")

    assert loaded.path is not None
    assert loaded.path.name == "meta_model.joblib"
    assert loaded.feature_schema_version == "meta-v3.1-43f"
    assert loaded.lifecycle_status == "production"
    assert loaded.artifact_sha256


def test_non_evidence_inference_smoke_persists_prediction_lineage(monkeypatch, tmp_path):
    configure_smoke_runtime(monkeypatch, tmp_path)
    evidence_store = install_evidence_store(monkeypatch, tmp_path)
    monkeypatch.setattr(meta_model, "_MODEL_CACHE", None)
    monkeypatch.setattr(meta_model, "_MODEL_LOAD_ERROR", None)

    loaded = get_governed_artifact_loader().load_production("meta_model", "meta-v3.1-43f")
    prediction = InferenceCoordinator().predict_once(build_smoke_analysis(), symbol="BTC")

    assert prediction.prediction_id
    assert prediction.signal_id
    assert prediction.deployment_id == "paper-canary-20260805-01-smoke"
    assert prediction.paper_run_id == "paper-canary-20260805-01-smoke"
    assert prediction.artifact_sha256 == loaded.artifact_sha256
    assert evidence_store.count_rows("predictions") == 1
    assert evidence_store.count_rows("feature_snapshots") == 1
    assert evidence_store.count_rows("final_decisions") == 0
    persisted = evidence_store.get_prediction(prediction.prediction_id)
    assert persisted is not None
    assert persisted["signal_id"] == prediction.signal_id
    assert persisted["prediction_id"] == prediction.prediction_id
    assert persisted["deployment_id"] == "paper-canary-20260805-01-smoke"
    assert persisted["paper_run_id"] == "paper-canary-20260805-01-smoke"
    assert persisted["artifact_sha256"] == loaded.artifact_sha256
    assert persisted["evidence_eligible"] is False
    assert persisted["analysis_universe"] == ["BTC", "ETH", "BNB"]


def test_non_evidence_decision_contract_stays_sell_side_probability_v2(monkeypatch, tmp_path):
    configure_smoke_runtime(monkeypatch, tmp_path)
    evidence_store = install_evidence_store(monkeypatch, tmp_path)

    decision = MetaDecisionEngine().decide(
        {
            "signal": "STRONG SELL",
            "action": "SELL",
            "fear_greed": 20,
            "sentiment_momentum": -0.8,
            "regime": "bear",
            "atr_pct": 1.0,
            "_meta_prediction": {
                "probability": 0.2,
                "probability_semantics": "P(up)",
                "expected_return": -0.1,
                "prediction_id": "pred-smoke-sell",
                "signal_id": "sig-smoke-sell",
                "artifact_sha256": "sha256-smoke-sell",
                "model_version": "smoke-v1",
                "feature_schema_version": "meta-v3.1-43f",
                "deployment_id": "paper-canary-20260805-01-smoke",
                "paper_run_id": "paper-canary-20260805-01-smoke",
                "cycle_id": "smoke-cycle-001",
                "feature_hash": "feature-hash-smoke",
            },
        },
        persist_final=False,
    )

    assert decision["action"] == "SELL"
    assert decision["terminal_status"] == "TRADE"
    assert decision["decision_contract_version"] == "side-probability-v2"
    assert decision["evidence_eligible"] is False
    assert decision["execution_probability"] == pytest.approx(0.8)
    assert decision["meta_probability"] == pytest.approx(0.8)
    assert decision["side_probability"] >= 0.65
    assert decision["posterior_probability"] <= 0.35
    assert evidence_store.count_rows("final_decisions") == 0


def test_signal_score_reports_inference_owner_required_when_meta_owner_is_missing(monkeypatch, tmp_path):
    runtime_root = configure_smoke_runtime(monkeypatch, tmp_path)
    evidence_store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", evidence_store)

    result = score_signal(
        "BUY",
        {"close": 100.0, "atr": 2.0, "rsi": 30.0},
        {"disable_ml": False},
        meta_prediction=None,
    )

    assert result["meta_error"] == "inference_owner_required"
    assert result["meta_confidence"] is None
    assert result["meta_probability"] is None
    assert evidence_store.count_rows("predictions") == 0
    assert evidence_store.count_rows("feature_snapshots") == 0
    assert evidence_store.count_rows("final_decisions") == 0
    assert evidence_store.count_rows("outcome_links") == 0
    assert not (runtime_root / "runtime_pause_state.json").exists()
    assert not (runtime_root / "runtime_pause_events.jsonl").exists()
    assert not any((runtime_root / "state").glob("*.pid"))
    assert not any((runtime_root / "state").glob("*lease*"))
    assert not any((runtime_root / "state").glob("*lock*"))
