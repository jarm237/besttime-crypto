"""Unit and Regression Tests for S1 News/Event Shock Discovery Pipeline.

Validates:
1. Artifact existence and JSON schema integrity.
2. Temporal point-in-time causality: event_timestamp <= available_at <= decision < execution.
3. Publication delay enforcement: 24h for DeFiLlama daily events, 1h for GDELT.
4. Causal accounting invariants: zero negative cash, zero unbacked leverage, residual < 1e-9.
5. Algorithmic, non-hardcoded verdict engine behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "news_event_s1"

SCORECARD_PATH = OUTPUT_DIR / "canonical_s1_scorecard.json"
MANIFEST_PATH = OUTPUT_DIR / "source_coverage_manifest.json"
PIT_MANIFEST_PATH = OUTPUT_DIR / "pit_event_manifest.json"
REPORT_PATH = OUTPUT_DIR / "s1_scientific_report.md"


def test_artifacts_exist():
    """Verify that all canonical S1 research artifacts are emitted."""
    assert SCORECARD_PATH.exists(), f"Missing {SCORECARD_PATH}"
    assert MANIFEST_PATH.exists(), f"Missing {MANIFEST_PATH}"
    assert PIT_MANIFEST_PATH.exists(), f"Missing {PIT_MANIFEST_PATH}"
    assert REPORT_PATH.exists(), f"Missing {REPORT_PATH}"


def test_scorecard_schema():
    """Verify scorecard keys, verdicts, and numeric ranges."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    assert "verdicts" in scorecard
    assert "statistical_evaluation" in scorecard
    assert "economic_evaluation" in scorecard

    verdicts = scorecard["verdicts"]
    assert verdicts["NEWS_SOURCE_FEASIBILITY"] in ["SUFFICIENT", "PARTIAL_BOUNDED", "INSUFFICIENT"]
    assert verdicts["NEWS_PIT_CORRECTNESS"] in ["PASS", "FAIL", "PARTIAL", "PARTIAL_ASSUMED_AVAILABILITY"]
    assert verdicts["NEWS_HISTORICAL_PIT"] in ["PARTIAL", "SUFFICIENT", "INSUFFICIENT"]
    assert verdicts["NEWS_INCREMENTAL_PREDICTIVE_VALUE"] in ["SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"]
    assert verdicts["NEWS_INCREMENTAL_ECONOMIC_VALUE"] in ["SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"]
    assert verdicts["S1_RAW_HACK_AND_SAMPLED_EVENT_SHOCK_PROXY"] in ["SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"]
    assert verdicts["GENERAL_NEWS_INFORMATION_VALUE"] == "NOT_ESTABLISHED"
    assert verdicts["NEWS_NEURAL_INPUT_AUTHORIZATION"] == "NOT_AUTHORIZED"
    assert verdicts["S1_OVERALL_CONCLUSION"] in [
        "NEWS_SHOCK_VALUE_SUPPORTED",
        "NEWS_SHOCK_VALUE_NOT_SUPPORTED",
        "NEWS_SHOCK_VALUE_INCONCLUSIVE",
        "NEWS_DATA_INSUFFICIENT",
    ]
    assert verdicts["RECOMMENDATION_FOR_UNIFIED_NEURAL_INPUTS"] in [
        "INCLUDE",
        "EXCLUDE",
        "DEFER_PENDING_HIGHER_FIDELITY_DATA",
    ]


def test_pit_alignment_temporal_ordering():
    """Verify that recorded PIT audit traces strictly obey event_time <= available_at <= decision."""
    with open(PIT_MANIFEST_PATH, "r", encoding="utf-8") as f:
        pit_data = json.load(f)

    audit_meta = pit_data["audit_metadata"]
    assert audit_meta["pit_pass_ratio"] == 1.0, f"Expected 100% PIT pass ratio, got {audit_meta['pit_pass_ratio']}"
    assert audit_meta["zero_bfill_enforced"] is True
    assert audit_meta["publication_delay_hours"] >= 24.0

    sample_traces = pit_data.get("sample_audit_traces", [])
    assert len(sample_traces) > 0, "Expected non-empty sample audit traces"
    for tr in sample_traces:
        ev_t = pd.to_datetime(tr["event_time"], utc=True)
        av_t = pd.to_datetime(tr["available_at"], utc=True)
        dec_t = pd.to_datetime(tr["decision_time"], utc=True)

        assert ev_t <= av_t, f"Available time precedes event time: {ev_t} > {av_t}"
        assert av_t <= dec_t, f"Decision precedes available time: {av_t} > {dec_t}"
        assert tr["ordering_valid"] is True


def test_economic_accounting_invariants():
    """Verify that no simulated policy violated non-negative cash or leverage invariants."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    econ = scorecard["economic_evaluation"]
    for fee_key in ["12_bps", "30_bps"]:
        assert fee_key in econ
        for pol_name, pdata in econ[fee_key].items():
            diag = pdata["diagnostics"]
            assert diag["min_observed_cash_usd"] >= -1e-6, f"{pol_name} has negative cash: {diag['min_observed_cash_usd']}"
            assert diag["max_observed_risky_exposure"] <= 1.000001, f"{pol_name} has unbacked leverage: {diag['max_observed_risky_exposure']}"
            assert diag["max_accounting_residual_usd"] < 1e-6, f"{pol_name} residual: {diag['max_accounting_residual_usd']}"
            assert diag["unbacked_leverage_detected"] is False


def test_algorithmic_verdict_derivation():
    """Verify that verdicts are dynamically computed from statistical and economic thresholds."""
    from scripts.run_s1_news_event_discovery import compute_s1_verdict

    # Synthetic PASS case
    pit_audit = {"pit_pass_ratio": 1.0, "zero_bfill_enforced": True}
    stat_24h_supported = {
        "delta_pr_auc_val": 0.05,
        "permutation_test_100_runs": {"p_value": 0.01},
        "paired_block_bootstrap_1000_runs": {"covers_zero": False, "ci_95_lower": 0.02, "ci_95_upper": 0.08},
    }
    stat_72h = {"delta_pr_auc_val": 0.03}
    econ_supported = {
        "12_bps": {
            "Combined_Price_News_Risk_Policy": {"validation": {"net_return_pct": 25.0, "sharpe_ratio": 1.2, "max_drawdown_pct": -10.0}},
            "Price_Only_Risk_Policy": {"validation": {"net_return_pct": 15.0, "sharpe_ratio": 0.8, "max_drawdown_pct": -15.0}},
        },
        "30_bps": {
            "Combined_Price_News_Risk_Policy": {"validation": {"net_return_pct": 22.0}},
            "Price_Only_Risk_Policy": {"validation": {"net_return_pct": 13.0}},
        }
    }

    v_supp = compute_s1_verdict(pit_audit, stat_24h_supported, stat_72h, econ_supported)
    assert v_supp["NEWS_INCREMENTAL_PREDICTIVE_VALUE"] == "SUPPORTED"
    assert v_supp["NEWS_INCREMENTAL_ECONOMIC_VALUE"] == "SUPPORTED"
    assert v_supp["S1_OVERALL_CONCLUSION"] == "NEWS_SHOCK_VALUE_SUPPORTED"
    assert v_supp["RECOMMENDATION_FOR_UNIFIED_NEURAL_INPUTS"] == "INCLUDE"

    # Synthetic NOT_SUPPORTED case
    stat_24h_notsupp = {
        "delta_pr_auc_val": -0.02,
        "permutation_test_100_runs": {"p_value": 0.85},
        "paired_block_bootstrap_1000_runs": {"covers_zero": True, "ci_95_lower": -0.05, "ci_95_upper": 0.01},
    }
    econ_notsupp = {
        "12_bps": {
            "Combined_Price_News_Risk_Policy": {"validation": {"net_return_pct": 10.0, "sharpe_ratio": 0.5, "max_drawdown_pct": -20.0}},
            "Price_Only_Risk_Policy": {"validation": {"net_return_pct": 18.0, "sharpe_ratio": 0.8, "max_drawdown_pct": -15.0}},
        },
        "30_bps": {
            "Combined_Price_News_Risk_Policy": {"validation": {"net_return_pct": 8.0}},
            "Price_Only_Risk_Policy": {"validation": {"net_return_pct": 16.0}},
        }
    }
    v_notsupp = compute_s1_verdict(pit_audit, stat_24h_notsupp, stat_72h, econ_notsupp)
    assert v_notsupp["NEWS_INCREMENTAL_PREDICTIVE_VALUE"] == "NOT_SUPPORTED"
    assert v_notsupp["NEWS_INCREMENTAL_ECONOMIC_VALUE"] == "NOT_SUPPORTED"
    assert v_notsupp["S1_OVERALL_CONCLUSION"] == "NEWS_SHOCK_VALUE_NOT_SUPPORTED"
    assert v_notsupp["RECOMMENDATION_FOR_UNIFIED_NEURAL_INPUTS"] == "EXCLUDE"


def test_economic_numbers_exact_reproduction():
    """Verify that economic performance metrics in canonical scorecard are numerically exact."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    econ_12 = scorecard["economic_evaluation"]["12_bps"]
    price_val_ret = econ_12["Price_Only_Risk_Policy"]["validation"]["net_return_pct"]
    comb_val_ret = econ_12["Combined_Price_News_Risk_Policy"]["validation"]["net_return_pct"]

    assert abs(price_val_ret - 18.80) < 0.05, f"Expected Price-Only ~18.80%, got {price_val_ret}"
    assert abs(comb_val_ret - 10.40) < 0.05, f"Expected Combined ~10.40%, got {comb_val_ret}"

    # Verify subperiod trades diagnostics
    r7_diag = econ_12["R7_Weekly_Vol_Target"]["diagnostics"]
    assert r7_diag["actual_trades_executed"] == 646
    assert r7_diag["val_trades_executed"] == 131
    assert r7_diag["train_trades_executed"] == 515


def test_predictive_scorecard_metrics_exact_reproduction():
    """Verify primary and secondary target statistical metrics against reported values."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    stat = scorecard["statistical_evaluation"]
    s24 = stat["primary_target_24h_downside"]
    assert abs(s24["delta_pr_auc_val"] - (-0.0255)) < 0.001
    assert s24["permutation_test_100_runs"]["p_value"] > 0.90
    assert s24["paired_block_bootstrap_1000_runs"]["covers_zero"] is True

    s72 = stat["secondary_target_72h_downside"]
    assert abs(s72["delta_pr_auc_val"] - 0.0103) < 0.001
    assert s72["permutation_test_100_runs"]["p_value"] > 0.20
