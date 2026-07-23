from btc_scraper.ml_engine.operational_health import health_snapshot, record_degradation, record_healthy
from btc_scraper.ml_engine.readiness_gate import live_entry_authorized


def test_degradation_is_visible_in_health():
    record_degradation("prediction_audit", "prediction_audit_write_failure_total", "disk full")
    snapshot = health_snapshot()
    assert snapshot["components"]["prediction_audit"]["status"] == "degraded"
    assert snapshot["metrics"]["prediction_audit_write_failure_total"] >= 1
    record_healthy("prediction_audit")


def test_live_readiness_fails_closed_when_config_missing(tmp_path):
    authorized, reason = live_entry_authorized(tmp_path / "missing.json")
    assert authorized is False
    assert reason.startswith("readiness_config_unavailable")
