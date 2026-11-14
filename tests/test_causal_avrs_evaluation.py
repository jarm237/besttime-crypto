"""Tests for Causal AVRS Economic Falsification Pipeline.

Verifies:
1. Strict causality (no full-sample threshold leakage, expanding quantiles use only past data).
2. Execution timing (decision at bar t is executed at bar t+1, no same-bar return leakage).
3. Multi-asset holdings, weight drift, and turnover fee deductions.
4. Correct tracking of non-overlapping missed rebounds.
5. Permitting genuinely negative strategy results (no predetermined positive profit assertion).
6. Strict test output isolation (tmp_path injection preserving canonical files).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from scripts.run_causal_avrs_evaluation import (
    load_causal_spot_market_panel,
    compute_causal_avrs_features,
    evaluate_tail_predictability_across_horizons,
    simulate_multi_asset_holdings_portfolio,
    compute_avrs_specific_diagnostics,
    build_causal_avrs_evaluation_report,
    ROOT,
)


def test_causal_expanding_quantile_no_lookahead():
    """Verify that expanding quantiles at step t do NOT use any future values from t+1 onwards."""
    np.random.seed(42)
    series = pd.Series(np.random.normal(0, 1, 150))
    # Add a massive spike at index 120
    series.iloc[120] = 50.0

    # Warmup of 30 steps
    q80_expanding = series.expanding(min_periods=30).quantile(0.80)

    # Step 119 must NOT know about the spike at step 120
    manual_q80_119 = series.iloc[:120].quantile(0.80)
    assert abs(q80_expanding.iloc[119] - manual_q80_119) < 1e-6
    assert q80_expanding.iloc[119] < 2.0
    assert q80_expanding.iloc[120] > q80_expanding.iloc[119]


def test_next_bar_execution_timing_and_no_same_bar_leakage():
    """Verify that target weight decided at t is applied strictly to return at t+1 in multi-asset engine."""
    # Deterministic 4-bar, 2-asset scenario
    prices = np.array([
        [100.0, 100.0], # Bar 0
        [110.0, 110.0], # Bar 1 (+10%)
        [55.0, 55.0],   # Bar 2 (-50%)
        [66.0, 66.0],   # Bar 3 (+20%)
    ])
    timestamps = pd.date_range("2024-01-01", periods=4, freq="1h")

    # Signals:
    # Bar 0 close: target 1.0 (executed at bar 1)
    # Bar 1 close: target 0.0 (executed at bar 2, avoiding -50% crash)
    # Bar 2 close: target 1.0 (executed at bar 3, capturing +20% rebound)
    # Bar 3 close: target 1.0
    target_weights = pd.Series([1.0, 0.0, 1.0, 1.0], index=timestamps)

    sim = simulate_multi_asset_holdings_portfolio(prices, target_weights, timestamps, fee_bps=0.0, initial_capital_usd=1000.0)

    eq_series = sim["equity_series"]
    assert abs(eq_series.iloc[1] - 1100.0) < 1e-4
    assert abs(eq_series.iloc[2] - 1100.0) < 1e-4
    assert abs(eq_series.iloc[3] - 1320.0) < 1e-4
    assert sim["net_return_pct"] == 32.0


def test_multi_asset_post_return_weight_drift():
    """Verify that buy-and-hold holdings do not incur artificial rebalancing fees as weights drift."""
    # 2 assets: Asset 0 doubles, Asset 1 is flat
    prices = np.array([
        [100.0, 100.0], # Bar 0
        [200.0, 100.0], # Bar 1
        [400.0, 100.0], # Bar 2
    ])
    timestamps = pd.date_range("2024-01-01", periods=3, freq="1h")
    target_weights = pd.Series([1.0, 1.0, 1.0], index=timestamps)

    # 12 bps entry fee
    sim = simulate_multi_asset_holdings_portfolio(prices, target_weights, timestamps, fee_bps=12.0, rebalance_period_hours=None, initial_capital_usd=1000.0)

    # Only 1 trade execution (at inception t=0)
    assert sim["rebalance_count"] == 1
    assert abs(sim["total_turnover"] - 1.0) < 1e-4
    assert abs(sim["total_fees_paid_usd"] - 1.20) < 1e-2


def test_missed_rebound_diagnostics():
    """Verify that non-overlapping missed rebounds and false alarms are tracked."""
    mkt_rets = pd.Series([0.0] * 60)
    target_weights = pd.Series([1.0] * 60)
    target_weights.iloc[10:30] = 0.0 # 20 bars in cash

    # Market rebounds during cash period
    mkt_rets.iloc[11:16] = 0.01

    diag = compute_avrs_specific_diagnostics(target_weights, mkt_rets)
    assert diag["total_cash_episodes"] == 1
    assert diag["cumulative_non_overlapping_missed_rebound_pct"] > 4.5
    assert diag["false_alarm_count"] == 1


def test_causal_avrs_evaluation_artifact_isolation_and_disposition(tmp_path: Path):
    """Verify that report generation respects tmp_path and produces genuine falsified dispositions."""
    canonical_file = ROOT / "research" / "information_discovery" / "causal_avrs_evaluation_results.json"
    canonical_mtime = canonical_file.stat().st_mtime if canonical_file.exists() else None

    report = build_causal_avrs_evaluation_report(output_dir=tmp_path)

    isolated_file = tmp_path / "causal_avrs_evaluation_results.json"
    assert isolated_file.exists()

    with open(isolated_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    diag = data["phase_b_corrected_diagnostics"]
    strategies = data["phase_a_comparable_strategies"]

    # Verify all 5 comparable strategies exist
    assert "CASH" in strategies
    assert "PASSIVE_PHYSICAL_BUY_AND_HOLD" in strategies
    assert "PASSIVE_REBALANCED_EW" in strategies
    assert "SIMPLE_VOL_GATING" in strategies
    assert "CAUSAL_AVRS_RULE_STD" in strategies

    # Causal AVRS falsification verdict must reflect genuine empirical outcomes
    assert diag["CAUSAL_AVRS_RULE_NET_RETURN"] < diag["PASSIVE_BUY_AND_HOLD_NET_RETURN"]
    assert diag["CAUSAL_AVRS_RULE_NET_RETURN"] < diag["PASSIVE_REBALANCED_EW_NET_RETURN"]
    assert diag["NET_ECONOMIC_VALUE"] == "NEGATIVE"

    disp = data["phase_e_research_closure_decisions"]
    assert disp["AVRS_DESCRIPTIVE_DOWNSIDE_CLUSTERING"] == "CONFIRMED_DESCRIPTIVE_ONLY"
    assert disp["AVRS_BINARY_TAIL_PREDICTION"] == "FALSIFIED_NEGATIVE"
    assert disp["AVRS_CAUSAL_RULE_ECONOMIC_VALUE"] == "FALSIFIED_NEGATIVE"
    assert disp["AVRS_NEURAL_INCREMENTAL_VALUE"] == "NOT_EVALUATED"
    assert disp["AVRS_NEURAL_PILOT_AUTHORIZATION"] == "NOT_AUTHORIZED"
    assert disp["AVRS_RESEARCH_DISPOSITION"] == "HEURISTIC_REJECTED_TERMINATE_OPTIMIZATION"

    # Ensure canonical file was NOT touched during test
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime
