from datetime import datetime, timedelta, timezone

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.shadow_validation import (
    SHADOW_READINESS_RULE_VERSION,
    ShadowThresholds,
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
