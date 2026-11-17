"""Targeted unit tests for D0 Derivatives Positioning Economic Discovery."""

import json
from pathlib import Path
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "predictive_discovery"


def test_d0_manifest_and_scorecard_schema():
    """Verify that D0 manifest, scorecard, and report exist with complete schemas."""
    manifest_p = OUTPUT_DIR / "d0_derivatives_pit_coverage_manifest.json"
    scorecard_p = OUTPUT_DIR / "d0_derivatives_discovery_scorecard.json"
    report_p = OUTPUT_DIR / "d0_derivatives_discovery_report.md"
    
    assert manifest_p.exists(), f"Missing {manifest_p}"
    assert scorecard_p.exists(), f"Missing {scorecard_p}"
    assert report_p.exists(), f"Missing {report_p}"
    
    with open(manifest_p, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["program"] == "D0_DERIVATIVES_POSITIONING_ECONOMIC_DISCOVERY"
    assert "futures_funding" in manifest
    assert "futures_metrics" in manifest
    assert manifest["feasibility_assessment"]["coverage_verdict"] == "PARTIAL"
    
    with open(scorecard_p, "r", encoding="utf-8") as f:
        scorecard = json.load(f)
    assert "phase_a_coverage" in scorecard
    assert "phase_c_predictive_falsification" in scorecard
    assert "phase_d_economic_translation" in scorecard
    assert "phase_e_verdicts" in scorecard
    
    verdicts = scorecard["phase_e_verdicts"]
    assert verdicts["DERIVATIVES_PIT_COVERAGE"] == "PARTIAL"
    assert verdicts["DERIVATIVES_INCREMENTAL_INFORMATION"] == "SUPPORTED"
    assert verdicts["DERIVATIVES_ECONOMIC_OPPORTUNITY"] == "SUPPORTED"


def test_d0_pit_funding_coverage_and_continuity():
    """Verify that BTCUSDT funding has 3800+ contiguous settlements without 8h gaps."""
    with open(OUTPUT_DIR / "d0_derivatives_pit_coverage_manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    btc_f = manifest["futures_funding"]["BTCUSDT"]
    assert btc_f["record_count"] >= 3800
    assert btc_f["gaps_gt_8h_count"] == 0
    assert btc_f["settlement_hours_utc"] == [0, 8, 16]


def test_d0_predictive_falsification_incremental_metrics():
    """Verify that derivatives features provide positive incremental value over baseline."""
    with open(OUTPUT_DIR / "d0_derivatives_discovery_scorecard.json", "r", encoding="utf-8") as f:
        scorecard = json.load(f)
        
    p_c = scorecard["phase_c_predictive_falsification"]
    assert "downside_24h" in p_c
    assert "downside_72h" in p_c
    assert "downside_168h" in p_c
    
    # 168h downside should show substantial incremental ROC-AUC and PR-AUC
    inc_168 = p_c["downside_168h"]["incremental_validation"]
    assert inc_168["delta_roc_auc"] > 0.05
    assert inc_168["delta_pr_auc"] > 0.03
    assert inc_168["risk_spread_pct"] > 0.0
    
    # Block permutation negative control must show lower skill than combined model
    p24 = p_c["downside_24h"]
    assert p24["combined_model"]["validation"]["brier_skill_score"] > p24["block_permutation_control"]["validation"]["brier_skill_score"]


def test_d0_economic_simulation_and_stress_fee_persistence():
    """Verify economic simulation properties, causal order fills, and fee drag under stress."""
    with open(OUTPUT_DIR / "d0_derivatives_discovery_scorecard.json", "r", encoding="utf-8") as f:
        scorecard = json.load(f)
        
    p_d = scorecard["phase_d_economic_translation"]
    base = p_d["base_fee_12bps"]
    stress = p_d["stress_fee_25bps_slippage_5bps"]
    
    # Basic invariants
    assert base["100_cash"]["full_horizon_net_return_pct"] == 0.0
    assert base["100_cash"]["total_fees_paid_usd"] == 0.0
    assert base["btc_buy_and_hold"]["one_way_turnover"] == 1.0
    
    # Derivatives-informed trend filter beats simple trend following in Sharpe and Validation
    d_trend_base = base["derivatives_informed_trend"]
    s_trend_base = base["simple_trend_following"]
    assert d_trend_base["annualized_sharpe"] > s_trend_base["annualized_sharpe"]
    assert d_trend_base["val_net_return_pct"] > s_trend_base["val_net_return_pct"]
    
    # Stress fee persistence (30 bps total cost)
    d_trend_stress = stress["derivatives_informed_trend"]
    s_trend_stress = stress["simple_trend_following"]
    assert d_trend_stress["annualized_sharpe"] > s_trend_stress["annualized_sharpe"]
    assert d_trend_stress["val_net_return_pct"] > s_trend_stress["val_net_return_pct"]
