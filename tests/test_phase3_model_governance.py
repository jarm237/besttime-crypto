from __future__ import annotations

from btc_scraper.ml_engine.model_governance import ModelRegistry, PromotionPolicy, calibration_metrics, evaluate_promotion, schema_hash


def _metrics(**changes):
    values = {"n_samples": 1200, "cv_auc": .62, "holdout_auc": .60, "calibration_error": .04}
    values.update(changes)
    return values


def _artifact(tmp_path, name, content=b"model"):
    path = tmp_path / name; path.write_bytes(content); return path


def test_promotion_gate_rejects_weak_holdout_and_calibration():
    decision = evaluate_promotion(_metrics(holdout_auc=.50, calibration_error=.20))
    assert decision.status == "REJECTED"
    assert len(decision.reasons) >= 2


def test_registry_promotes_atomically_and_blocks_schema_mismatch(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(_artifact(tmp_path, "candidate.bin"), version="v1", features=["a", "b"], metrics=_metrics())
    assert registry.promote("v1").status == "PROMOTED"
    assert registry.load_production(["a", "b"]).exists()
    try: registry.load_production(["b", "a"])
    except ValueError as exc: assert str(exc) == "feature_schema_mismatch"
    else: assert False, "schema mismatch must block loading"


def test_rejected_candidate_never_overwrites_production(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(_artifact(tmp_path, "one.bin"), version="v1", features=["a"], metrics=_metrics())
    registry.promote("v1")
    registry.register(_artifact(tmp_path, "two.bin"), version="v2", features=["a"], metrics=_metrics(n_samples=10))
    assert registry.promote("v2").status == "REJECTED"
    assert registry.dashboard()["current_model"] == "v1"


def test_rollback_and_shadow_dashboard(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(_artifact(tmp_path, "one.bin"), version="v1", features=["a"], metrics=_metrics())
    registry.promote("v1")
    registry.register(_artifact(tmp_path, "two.bin"), version="v2", features=["a"], metrics=_metrics(cv_auc=.63))
    registry.promote("v2")
    registry.rollback("v1")
    registry.record_shadow(.9, .2, outcome=1, pnl_impact=.02)
    dashboard = registry.dashboard()
    assert dashboard["current_model"] == "v1"
    assert dashboard["rollback_history"]
    assert dashboard["shadow"]["disagreements"] == 1
    assert dashboard["shadow"]["calibration"]["high_confidence"] is None


def test_calibration_reports_ece_brier_and_high_confidence_bucket():
    metrics = calibration_metrics([.9, .85, .2, .1], [1, 0, 0, 0])
    assert metrics["ece"] is not None and metrics["brier_score"] is not None
    assert metrics["high_confidence"]["count"] == 2
    assert schema_hash(["a"]) != schema_hash(["b"])
