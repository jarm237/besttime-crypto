from btc_scraper.ml_engine.operational_health import health_snapshot, record_degradation, record_healthy
import json

from btc_scraper.ml_engine.readiness_gate import derive_readiness, live_entry_authorized


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


def test_live_ready_is_derived_and_cannot_be_claimed(tmp_path, monkeypatch):
    config = {
        "live_ready": True,
        "status": "AUTHORIZED",
        "automated_live_entry": True,
        "implementation_gate": True,
        "offline_regression_gate": True,
        "decision_correctness_gate": True,
        "calibration_methodology_gate": True,
        "artifact_governance_gate": True,
        "runtime_evidence_gate": True,
        "rl_policy_required_for_live_entry": False,
        "rl_policy_enabled": False,
        "shadow_validation_gate": False,
        "manual_authorization_gate": True,
    }
    path = tmp_path / "readiness.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("ML_ENGINE_LIVE_AUTHORIZED", "true")
    authorized, reason = live_entry_authorized(path)
    assert authorized is False
    assert "shadow_validation_gate" in reason


def test_disabled_optional_rl_does_not_block_foundation():
    readiness = derive_readiness({
        **{name: True for name in (
            "implementation_gate", "offline_regression_gate", "decision_correctness_gate",
            "calibration_methodology_gate", "artifact_governance_gate", "runtime_evidence_gate",
            "shadow_validation_gate", "manual_authorization_gate",
        )},
        "rl_policy_required_for_live_entry": False,
        "rl_policy_enabled": False,
        "rl_policy_gate": False,
    })
    assert readiness["rl_policy_gate"] is True
    assert readiness["live_ready"] is True
