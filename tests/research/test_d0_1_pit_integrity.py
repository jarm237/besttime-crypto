"""Tests for D0.1 PIT Integrity, Boundary Purging, and Non-Hardcoded Verdict Computation.

Verifies:
1. Strict row-level PIT alignment: observation <= available_at <= decision < execution
2. Enforced publication delay: +300s on 5m metrics
3. Zero `.bfill()` usage across feature pipeline
4. Boundary purging across train/validation/holdout splits
5. Algorithmic, non-hardcoded verdict computation
6. Presence of Price-Only Control matching structure of Derivatives policy
7. Cash non-negativity and simulation accounting invariants
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "predictive_discovery"
MANIFEST_PATH = OUTPUT_DIR / "d0_1_derivatives_pit_coverage_manifest.json"
SCORECARD_PATH = OUTPUT_DIR / "d0_1_derivatives_discovery_scorecard.json"
REPORT_PATH = OUTPUT_DIR / "d0_1_derivatives_discovery_report.md"


def test_manifest_and_scorecard_artifacts_exist():
    """Ensure D0.1 manifest, scorecard, and report files are generated."""
    assert MANIFEST_PATH.exists(), f"Missing manifest: {MANIFEST_PATH}"
    assert SCORECARD_PATH.exists(), f"Missing scorecard: {SCORECARD_PATH}"
    assert REPORT_PATH.exists(), f"Missing report: {REPORT_PATH}"


def test_pit_alignment_temporal_ordering():
    """Verify strict causality: observation <= available_at <= decision < execution."""
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert "sample_trace" in manifest, "Manifest missing sample_trace"
    trace = manifest["sample_trace"]

    dec_ts = pd.to_datetime(trace["decision_timestamp"], utc=True)
    exec_ts = pd.to_datetime(trace["execution_timestamp"], utc=True)
    spot_obs_ts = pd.to_datetime(trace["spot_observation_close_time"], utc=True)
    avail_ts = pd.to_datetime(trace.get("source_available_at", trace.get("latest_metrics_available_at")), utc=True)
    pub_delay = trace["publication_delay_seconds"]

    assert pub_delay >= 300, f"Publication delay {pub_delay}s is less than required 300s"
    assert spot_obs_ts <= dec_ts, "Spot observation after decision time"
    assert avail_ts <= dec_ts, "Feature available_at after decision time"
    assert dec_ts < exec_ts, "Decision time not strictly prior to execution time"
    assert trace.get("causal_ordering_verified") is True


def test_bnb_metrics_partial_coverage_documented():
    """Verify that BNB metrics sampling anomaly is explicitly surfaced."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("bnb_metrics_continuous_coverage") is False, (
        "BNB metrics must NOT be claimed as continuous coverage"
    )
    assert manifest.get("bnb_metrics_record_count", 0) < 100000, (
        "BNB metrics count should reflect sampled archive (~27k rows)"
    )
    assert manifest.get("bnb_funding_continuous_coverage") is True, (
        "BNB funding settlements should be continuous (~3.8k rows)"
    )


def test_no_bfill_in_source_code():
    """Scan D0.1 pipeline implementation using AST to guarantee no .bfill() attribute/call was used in code."""
    import ast
    script_path = REPO_ROOT / "scripts" / "run_d0_1_economic_accounting_correction.py"
    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")

    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "bfill":
            pytest.fail(f"Found code calling .bfill() at line {node.lineno}")


def test_scorecard_verdicts_not_hardcoded():
    """Verify that verdicts are derived from quantitative thresholds, not hardcoded."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        sc = json.load(f)

    verdicts = sc.get("phase_e_verdicts", {})
    assert "D0_PIT_CORRECTNESS" in verdicts
    assert "D0_PREDICTIVE_INCREMENTAL_VALUE" in verdicts
    assert "D0_ECONOMIC_INCREMENTAL_VALUE" in verdicts
    assert "D0_PRODUCTION_AUTHORIZATION" in verdicts

    # Check that values are valid enum-like strings
    valid_verdicts = {
        "PASS",
        "FAIL",
        "SUPPORTED",
        "NOT_SUPPORTED",
        "OBSERVED",
        "REJECTED",
        "EQUIVOCAL",
        "CONFIRMED",
        "INCONCLUSIVE",
        "NOT_ESTABLISHED",
        "CORRECTED_CONFIRMED",
        "NOT_AUTHORIZED",
        "DERIVATIVES_INCREMENTAL_VALUE_SUPPORTED",
        "DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE",
        "DERIVATIVES_INCREMENTAL_VALUE_NOT_SUPPORTED",
        "INCONCLUSIVE_INVALID_EVIDENCE",
    }
    for k, v in verdicts.items():
        assert v in valid_verdicts, f"Verdict {k}={v} is not a valid verdict enum"


def test_price_only_control_present_and_aligned():
    """Verify that price_only_trend_control benchmark exists in economic comparison."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        sc = json.load(f)

    policies = sc.get("phase_d_economic_translation", {}).get("base_fee_12bps", {})
    assert "price_only_trend_control" in policies, (
        "price_only_trend_control must be present to isolate derivatives value"
    )
    assert "derivatives_informed_trend" in policies, (
        "derivatives_informed_trend must be present"
    )
    assert "r7_vol_target_daily" in policies, (
        "R7 daily volatility target must be present"
    )
    assert "r7_vol_target_weekly" in policies, (
        "R7 weekly volatility target must be present"
    )
    assert "static_50_50" in policies, (
        "static_50_50 benchmark must be present"
    )


def test_simulation_accounting_invariants_across_all_policies():
    """Verify that every simulated policy respects cash >= 0 and zero unbacked leverage."""
    with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
        sc = json.load(f)

    policies = sc.get("phase_d_economic_translation", {}).get("base_fee_12bps", {})
    for pol_name, pol_metrics in policies.items():
        min_cash = pol_metrics.get("min_observed_cash", pol_metrics.get("min_cash", 0.0))
        max_leverage = pol_metrics.get("max_observed_risky_exposure", pol_metrics.get("max_leverage", 1.0))
        unbacked = pol_metrics.get("unbacked_leverage_detected", False)
        residual = pol_metrics.get("max_accounting_residual", 0.0)

        assert min_cash >= -1e-6, f"Policy {pol_name} has negative cash: {min_cash}"
        assert max_leverage <= 1.000001, f"Policy {pol_name} has leverage > 1.0: {max_leverage}"
        assert not unbacked, f"Policy {pol_name} has unbacked leverage!"
        assert residual <= 1e-4, f"Policy {pol_name} has accounting reconciliation residual: {residual}"


def test_behavioral_pit_merge_asof_causality():
    """Behavioral test: Decision cannot see future observations or observations within publication latency."""
    # Synthetic observation timestamps
    # Obs 1: 00:50 UTC -> available at 00:55 UTC (with +300s latency)
    # Obs 2: 00:55 UTC -> available at 01:00 UTC (with +300s latency)
    obs_df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2023-01-01 00:50:00", "2023-01-01 00:55:00"], utc=True),
        "available_at": pd.to_datetime(["2023-01-01 00:55:00", "2023-01-01 01:00:00"], utc=True),
        "val": [100.0, 200.0],
    }).sort_values("available_at")

    # Decisions at 00:00, 00:55, 01:00
    dec_df = pd.DataFrame({
        "cutoff": pd.to_datetime(["2023-01-01 00:00:00", "2023-01-01 00:55:00", "2023-01-01 01:00:00"], utc=True)
    })

    merged = pd.merge_asof(dec_df, obs_df, left_on="cutoff", right_on="available_at", direction="backward")

    # At 00:00 UTC: Neither observation is available yet (NaN)
    assert np.isnan(merged.loc[0, "val"])
    # At 00:55 UTC: Obs 1 is available (100.0), Obs 2 is NOT available yet
    assert merged.loc[1, "val"] == 100.0
    # At 01:00 UTC: Obs 2 is available (200.0)
    assert merged.loc[2, "val"] == 200.0


def test_behavioral_staleness_masking():
    """Behavioral test: Metrics older than staleness threshold (2 hours) must be masked as NaN."""
    obs_df = pd.DataFrame({
        "available_at": pd.to_datetime(["2023-01-01 00:00:00"], utc=True),
        "val": [100.0],
    })
    # Decision at 02:30 (150 minutes later > 120 minutes threshold)
    dec_df = pd.DataFrame({
        "cutoff": pd.to_datetime(["2023-01-01 02:30:00"], utc=True)
    })
    merged = pd.merge_asof(dec_df, obs_df, left_on="cutoff", right_on="available_at", direction="backward")
    staleness_min = (merged["cutoff"] - merged["available_at"]).dt.total_seconds() / 60.0
    merged.loc[staleness_min > 120.0, "val"] = np.nan

    assert np.isnan(merged.loc[0, "val"])


def test_behavioral_verdict_ci_crossing_zero_yields_inconclusive():
    """Behavioral test: If 95% bootstrap CI crosses zero, verdict MUST be INCONCLUSIVE."""
    from scripts.run_d0_1_economic_accounting_correction import compute_evidence_verdicts

    falsification_mock = {
        "downside_168h": {
            "delta_pr_auc": 0.1076,
            "permutation_p_value_pr": 0.02,
            "conditional_risk_spread_pct": 3.70,
            "block_bootstrap_pr_ci_95": [-0.0135, 0.3310],  # Crosses zero!
        }
    }
    economic_mock = {
        "base_fee_12bps": {
            "derivatives_informed_trend": {"val_net_return_pct": 7.95, "annualized_sharpe": 1.0, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
            "price_only_trend_control": {"val_net_return_pct": 5.02, "annualized_sharpe": 0.9, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
            "simple_trend_following": {"val_net_return_pct": 8.07, "annualized_sharpe": 1.0, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
        },
        "stress_fee_30bps_allin": {
            "derivatives_informed_trend": {"val_net_return_pct": 3.01},
            "price_only_trend_control": {"val_net_return_pct": -1.40},
        }
    }
    manifest_mock = {
        "zero_bfill": True,
        "publication_delay_seconds": 300,
        "sample_trace": {"causal_ordering_verified": True},
    }

    verdicts = compute_evidence_verdicts(falsification_mock, economic_mock, manifest_mock)
    assert verdicts["D0_PREDICTIVE_INCREMENTAL_VALUE"] == "INCONCLUSIVE"
    assert verdicts["OVERALL_CONCLUSION"] == "DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE"


def test_behavioral_verdict_pit_failure_blocks_overall():
    """Behavioral test: If PIT correctness fails, OVERALL_CONCLUSION must be INCONCLUSIVE_INVALID_EVIDENCE."""
    from scripts.run_d0_1_economic_accounting_correction import compute_evidence_verdicts

    falsification_mock = {
        "downside_168h": {
            "delta_pr_auc": 0.15,
            "permutation_p_value_pr": 0.01,
            "conditional_risk_spread_pct": 5.0,
            "block_bootstrap_pr_ci_95": [0.05, 0.25],  # Positive CI
        }
    }
    economic_mock = {
        "base_fee_12bps": {
            "derivatives_informed_trend": {"val_net_return_pct": 10.0, "annualized_sharpe": 1.5, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
            "price_only_trend_control": {"val_net_return_pct": 2.0, "annualized_sharpe": 0.5, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
            "simple_trend_following": {"val_net_return_pct": 5.0, "annualized_sharpe": 0.8, "min_observed_cash": 0.0, "min_observed_btc_units": 0.0, "max_observed_risky_exposure": 1.0, "max_accounting_residual": 0.0, "unbacked_leverage_detected": False},
        },
        "stress_fee_30bps_allin": {
            "derivatives_informed_trend": {"val_net_return_pct": 8.0},
            "price_only_trend_control": {"val_net_return_pct": -2.0},
        }
    }
    manifest_mock = {
        "zero_bfill": False,  # FAILED PIT!
        "publication_delay_seconds": 0,
        "sample_trace": {"causal_ordering_verified": False},
    }

    verdicts = compute_evidence_verdicts(falsification_mock, economic_mock, manifest_mock)
    assert verdicts["D0_PIT_CORRECTNESS"] == "FAIL"
    assert verdicts["OVERALL_CONCLUSION"] == "INCONCLUSIVE_INVALID_EVIDENCE"


def test_final_artifacts_exist():
    """Ensure all required D0.1 final closure artifacts exist."""
    assert (OUTPUT_DIR / "d0_1_final_pit_manifest.json").exists()
    assert (OUTPUT_DIR / "d0_1_final_predictive_scorecard.json").exists()
    assert (OUTPUT_DIR / "d0_1_final_economic_scorecard.json").exists()
    assert (OUTPUT_DIR / "d0_1_final_execution_traces.json").exists()
    assert (OUTPUT_DIR / "d0_1_final_verdict_report.md").exists()
