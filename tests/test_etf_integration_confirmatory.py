"""Tests for HMR-V4D-1-r1 confirmatory ETF volatility integration audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v4/v4d_1r1_etf_integration_audit.json"


@pytest.fixture(scope="module")
def data():
    assert AUDIT_JSON.exists(), f"Audit JSON not found: {AUDIT_JSON}"
    return json.loads(AUDIT_JSON.read_text())


def test_program_and_run_class(data):
    """Program is V4D-1-r1 and run class is CONFIRMATORY."""
    assert data["program"] == "HMR-V4D-1-r1"
    assert data["run_class"] == "CONFIRMATORY"


def test_i1_rule_frozen(data):
    """I1 rule is frozen as pre-registered."""
    assert "Q5" in data["i1_frozen_rule"]
    assert "0.5x" in data["i1_frozen_rule"] or "0.5" in data["i1_frozen_rule"]
    assert "Q1-Q4" in data["i1_frozen_rule"]


def test_i2_rule_frozen(data):
    """I2 rule is frozen as pre-registered with Q5/Q1-Q4 terminology."""
    assert "Q5" in data["i2_frozen_rule"]
    assert "2.25" in data["i2_frozen_rule"]
    assert "Q1-Q4" in data["i2_frozen_rule"]
    # Must NOT contain Bin terminology
    assert "Bin 4" not in data["i2_frozen_rule"]
    assert "Bins 0" not in data["i2_frozen_rule"]


def test_pre_registered_thresholds_independent(data):
    """Pre-registered thresholds must not be set to match exploratory run numbers.
    Exploratory run observed: EV delta = -1.86 bps, Sharpe delta = -0.33.
    G2 floor must be < -1.86 (more permissive to be independent) or
    it must be documentably from a different source."""
    thresholds = data["pre_registered_thresholds"]
    g2_floor = thresholds["G2_ev_degradation_floor_bps"]
    g5_floor = thresholds["G5_sharpe_degradation_floor"]
    # G2 floor should NOT be set to just below -1.86 bps (contaminated)
    # Policy: floor is -5.0 bps (1 tick equivalent)
    assert g2_floor == -5.0, f"G2 floor changed from pre-registered -5.0; got {g2_floor}"
    assert g5_floor == -0.5, f"G5 floor changed from pre-registered -0.5; got {g5_floor}"


def test_g0_g1_pass(data):
    """G0 (data/PIT) and G1 (clustered inference) must pass."""
    gates = data["gate_results"]["gates"]
    assert gates["G0_data_pit"] == "PASS"
    assert "PASS" in gates["G1_clustered_inference_i1"]
    assert "PASS" in gates["G1_clustered_inference_i2"]


def test_g2_verdict(data):
    """G2 (EV non-inferiority) result must be consistent with ev_delta."""
    gates = data["gate_results"]["gates"]
    ev_delta = data["gate_results"]["ev_delta_i1_bps"]
    g2 = gates["G2_ev_noninferiority_i1"]
    if ev_delta >= -5.0:
        assert g2 == "PASS", f"G2 should PASS when EV delta {ev_delta:.2f} >= -5 bps; got {g2}"
    else:
        assert g2.startswith("FAIL"), f"G2 should FAIL when EV delta {ev_delta:.2f} < -5 bps; got {g2}"


def test_i1_verdict_consistent_with_gates(data):
    """I1 verdict must be consistent with G2, G3, G4, and G5 gate results.
    Survival gates (G2/G5) pass, but utility gates (G3/G4) fail, so verdict
    must be INTEGRATION_NOT_PROMOTED."""
    gr = data["gate_results"]
    i1_verdict = gr["i1_verdict"]
    economic_non_inferiority = gr["economic_non_inferiority"]
    risk_improvement = gr["risk_improvement"]
    risk_adjusted_utility = gr["risk_adjusted_utility"]

    assert economic_non_inferiority == "PASS"
    assert risk_improvement == "FAIL"
    assert risk_adjusted_utility == "NOT_DEMONSTRATED"
    assert i1_verdict == "INTEGRATION_NOT_PROMOTED"


def test_clustered_inference_unique_states(data):
    """Unique ETF states must be less than total signals (intraday correlation removed)."""
    uc1 = data["use_case_1_sizing"]["volatility_aware_clustered"]
    assert uc1["unique_etf_states"] < data["total_signals"], (
        f"unique_etf_states ({uc1['unique_etf_states']}) >= total_signals ({data['total_signals']})"
    )
    assert uc1["unique_etf_states"] > 0

    baseline_clust = data["use_case_1_sizing"]["baseline_clustered"]
    assert baseline_clust["unique_etf_states"] == uc1["unique_etf_states"]


def test_q5_signal_fraction_reported(data):
    """Q5 signal count and fraction must be present and plausible."""
    assert "n_q5_signals" in data
    assert "q5_fraction_pct" in data
    assert 0 < data["q5_fraction_pct"] < 100
    assert data["n_q5_signals"] < data["total_signals"]
    assert data["n_q5_signals"] + data["n_q1_q4_signals"] == data["total_signals"]


def test_simulation_architecture_note_present(data):
    """Simulation architecture limitation must be documented in gate results."""
    note = data["gate_results"].get("simulation_architecture_note", "")
    assert "scaffold" in note.lower() or "intrabar" in note.lower() or "path-aware" in note.lower(), (
        "Simulation architecture limitation not documented"
    )


def test_full_metric_fields_present(data):
    """Both baseline and I1 metrics must include the full required field set."""
    required_fields = {
        "net_ev_bps", "sharpe", "max_drawdown_pct", "worst_trade_pct",
        "profit_factor", "win_rate_pct", "avg_win_pct", "avg_loss_pct",
        "cvar_95_pct", "cvar_99_pct", "n_trades",
    }
    baseline = data["use_case_1_sizing"]["baseline"]
    i1 = data["use_case_1_sizing"]["volatility_aware"]
    missing_baseline = required_fields - set(baseline.keys())
    missing_i1 = required_fields - set(i1.keys())
    assert not missing_baseline, f"Baseline missing fields: {missing_baseline}"
    assert not missing_i1, f"I1 missing fields: {missing_i1}"


def test_ml_training_blocked_unless_promoted(data):
    """ML training must remain BLOCKED unless overall_verdict == INTEGRATION_PROMOTED."""
    verdict = data["overall_verdict"]
    ml_status = data["ml_training"]
    assert verdict == "INTEGRATION_NOT_PROMOTED"
    assert "BLOCKED" in ml_status


def test_g6_g7_evaluated(data):
    """G6 and G7 must be dynamically evaluated and pass."""
    gates = data["gate_results"]["gates"]
    assert gates["G6_period_stability"].startswith("PASS")
    assert gates["G7_lag_robustness"].startswith("PASS")

