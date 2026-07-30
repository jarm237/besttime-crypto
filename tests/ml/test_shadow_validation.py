from datetime import datetime, timedelta, timezone

from btc_scraper.core.config import analysis_universe_hash
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.shadow_validation import (
    SHADOW_READINESS_RULE_VERSION,
    ShadowThresholds,
    _eligible_entry_prediction,
    _prediction_exclusion_reasons,
    _store_signature,
    evaluate_shadow_validation,
)
from btc_scraper.ml_engine.runtime_evidence_store import RUNTIME_EVIDENCE_SCHEMA_VERSION


def _append_trade(store, index, closed_at, symbol, regime):
    prediction_id = f"p-{index}"
    prediction = {
        "prediction_id": prediction_id,
        "calibrated_prediction": 0.7,
        "artifact_sha256": "sha",
        "model_version": "v3",
        "feature_schema_version": "meta-v3",
        "latency_ms": 10 + index,
        "symbol": symbol,
        "regime": regime,
    }
    store.write_prediction_evidence(
        prediction,
        {"prediction_id": prediction_id, "feature_hash": f"h-{index}", "features": [index]},
    )
    store.append_final_decision({
        "decision_id": f"d-{index}", "prediction_id": prediction_id, "action": "BUY",
    })
    store.append_outcome_link({
        "outcome_id": f"o-{index}",
        "outcome_revision": 1,
        "prediction_id": prediction_id,
        "position_id": f"pos-{index}",
        "closed_at": closed_at.isoformat(),
        "is_paper": True,
        "paper_run_id": "shadow-validation-2026q1",
        "symbol": symbol,
        "regime": regime,
        "result": "WIN",
        "net_pnl_pct": 1.0,
    })


def test_shadow_gate_is_derived_from_canonical_evidence(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, (symbol, regime) in enumerate((
        ("BTC", "TREND"), ("ETH", "RANGE"), ("SOL", "PANIC"),
    )):
        _append_trade(store, index, start + timedelta(days=index), symbol, regime)
    result = evaluate_shadow_validation(
        store,
        now=start + timedelta(days=3),
        thresholds=ShadowThresholds(
            minimum_closed_paper_trades=3,
            minimum_elapsed_days=3,
            minimum_active_trading_days=3,
            minimum_symbols=3,
            minimum_regimes=3,
        ),
    )
    assert result["passed"] is True
    assert result["metrics"]["artifact_lineage_coverage"] == 1.0
    assert result["metrics"]["decision_linkage_coverage"] == 1.0
    assert result["metrics"]["latency_ms"]["p95"] is not None
    assert set(result["metrics"]["pnl_drawdown_by_regime"]) == {"TREND", "RANGE", "PANIC"}
    assert result["evidence_schema_version"] == RUNTIME_EVIDENCE_SCHEMA_VERSION
    assert result["readiness_rule_version"] == SHADOW_READINESS_RULE_VERSION
    signature = _store_signature(store)
    assert RUNTIME_EVIDENCE_SCHEMA_VERSION in signature
    assert SHADOW_READINESS_RULE_VERSION in signature


def test_shadow_gate_fails_closed_without_outcomes(tmp_path):
    result = evaluate_shadow_validation(RuntimeEvidenceStore(tmp_path / "empty.sqlite"))
    assert result["passed"] is False
    assert "closed_paper_trades" in result["failed_checks"]
    assert "artifact_lineage_coverage" in result["failed_checks"]


def test_ui_and_exit_predictions_are_not_entry_shadow_evidence():
    base = {
        "event_type": "prediction_created",
        "prediction_id": "p-context",
        "caller_context": "agent_orchestrator",
    }
    assert _eligible_entry_prediction({**base, "decision_context": "entry"}) is True
    assert _eligible_entry_prediction({
        **base,
        "decision_context": "ui_preview",
        "caller_context": "ui_dashboard",
    }) is False
    assert _eligible_entry_prediction({
        **base,
        "decision_context": "exit_recheck",
        "caller_context": "position_tracker",
    }) is False


def test_prediction_exclusion_reasons_are_explicit():
    reasons = _prediction_exclusion_reasons({
        "event_type": "prediction_created",
        "prediction_id": "p-invalid",
        "signal_id": "s-invalid",
        "deployment_id": "deployment",
        "caller_context": "ui_dashboard",
        "decision_context": "ui_preview",
        "model_version": "v3",
        "artifact_sha256": "artifact",
        "feature_schema_version": "schema",
        "feature_hash": "hash-a",
        "symbol": "UNKNOWN",
        "evidence_eligible": False,
    }, {
        "prediction_id": "p-invalid",
        "feature_hash": "hash-b",
    })
    assert "unknown_symbol" in reasons
    assert "non_entry_decision_context" in reasons
    assert "non_production_traffic" in reasons
    assert "runtime_marked_ineligible" in reasons
    assert "feature_hash_mismatch" in reasons


def test_complete_production_prediction_is_eligible():
    universe = ("BTC", "ETH", "BNB")
    prediction = {
        "event_type": "prediction_created",
        "prediction_id": "p-valid",
        "signal_id": "s-valid",
        "deployment_id": "paper-shadow-v1",
        "caller_context": "agent_orchestrator",
        "decision_context": "entry",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "feature_hash": "hash-v3",
        "epoch_id": "epoch-v3",
        "symbol": "BTCUSDT",
        "evidence_eligible": True,
        "analysis_universe": list(universe),
        "analysis_universe_hash": analysis_universe_hash(universe),
    }
    assert _prediction_exclusion_reasons(
        prediction,
        {"prediction_id": "p-valid", "feature_hash": "hash-v3"},
    ) == []


def test_test_or_unscoped_paper_outcomes_never_count(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _append_trade(store, 1, now, "BTC", "TREND")
    with store._connect() as db:
        raw = db.execute("SELECT payload FROM outcome_links WHERE outcome_id='o-1'").fetchone()[0]
        import json
        payload = json.loads(raw)
        payload["created_by"] = "paper_lifecycle_e2e"
        from btc_scraper.ml_engine.runtime_evidence_store import payload_sha256
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        db.execute(
            "UPDATE outcome_links SET payload=?, payload_sha256=? WHERE outcome_id='o-1'",
            (encoded, payload_sha256(payload)),
        )
    result = evaluate_shadow_validation(store, now=now)
    assert result["metrics"]["closed_paper_trades"] == 0
