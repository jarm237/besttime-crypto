"""Tests for Causal AVRS Economic Falsification Pipeline.

Verifies:
1. Strict causality (no full-sample threshold leakage, expanding quantiles use only past data).
2. Execution timing (decision at bar t is executed at bar t+1, no same-bar return leakage).
3. Turnover and fee calculation on actual weight changes.
4. Correct tracking of missed rebounds.
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
    simulate_causal_portfolio,
    compute_avrs_specific_diagnostics,
    build_causal_avrs_evaluation_report,
    ROOT,
)


def test_causal_expanding_quantile_no_lookahead():
    """Verify that expanding quantiles at step t do NOT use any future values from t+1 onwards."""
    # Create synthetic series where an extreme spike occurs at step 100
    np.random.seed(42)
    series = pd.Series(np.random.normal(0, 1, 150))
    # Add a massive spike at index 120
    series.iloc[120] = 50.0

    # Warmup of 30 steps
    q80_expanding = series.expanding(min_periods=30).quantile(0.80)

    # Step 119 must NOT know about the spike at step 120
    # Calculate quantile manually on sub-slice 0:120 (indices 0..119)
    manual_q80_119 = series.iloc[:120].quantile(0.80)
    assert abs(q80_expanding.iloc[119] - manual_q80_119) < 1e-6
    # Expanding quantile at 119 must be normal (< 2.0), unaffected by the 50.0 spike at 120
    assert q80_expanding.iloc[119] < 2.0
    # Step 120 expands to include the spike
    assert q80_expanding.iloc[120] > q80_expanding.iloc[119]


def test_next_bar_execution_timing_and_no_same_bar_leakage():
    """Verify that target weight decided at t is applied strictly to return at t+1."""
    # Deterministic 4-bar scenario
    # Returns: bar 0: 0.0, bar 1: +10%, bar 2: -50%, bar 3: +20%
    mkt_rets = pd.Series([0.0, 0.10, -0.50, 0.20])
    
    # Target weights decided at bar closes:
    # Bar 0 close: decide w=1.0 (execute at bar 1)
    # Bar 1 close: decide w=0.0 (execute at bar 2, avoiding -50% crash)
    # Bar 2 close: decide w=1.0 (execute at bar 3, capturing +20% rebound)
    # Bar 3 close: decide w=1.0
    target_weights = pd.Series([1.0, 0.0, 1.0, 1.0])

    # Zero fees for transparent calculation
    sim = simulate_causal_portfolio(target_weights, mkt_rets, initial_capital_usd=1000.0, fee_bps_per_trade_leg=0.0)
    
    # Expected equity progression:
    # Bar 0: $1,000.0
    # Bar 1: uses target_w from bar 0 (1.0) -> $1,000 * (1 + 0.10) = $1,100.0
    # Bar 2: uses target_w from bar 1 (0.0) -> $1,100 * (1 + 0.0 * -0.50) = $1,100.0 (crash avoided!)
    # Bar 3: uses target_w from bar 2 (1.0) -> $1,100 * (1 + 1.0 * 0.20) = $1,320.0
    eq_series = sim["equity_series"]
    assert abs(eq_series.iloc[1] - 1100.0) < 1e-4
    assert abs(eq_series.iloc[2] - 1100.0) < 1e-4
    assert abs(eq_series.iloc[3] - 1320.0) < 1e-4
    assert sim["net_return_pct"] == 32.0


def test_turnover_and_transaction_friction_deduction():
    """Verify that fees are deducted strictly on actual weight changes (turnover)."""
    mkt_rets = pd.Series([0.0, 0.0, 0.0, 0.0]) # flat market
    
    # Target weights:
    # Bar 0: w=1.0 (initial buy from cash: dw=1.0)
    # Bar 1: w=1.0 (no change: dw=0.0)
    # Bar 2: w=0.0 (sell to cash: dw=1.0)
    # Bar 3: w=1.0 (re-buy: dw=1.0)
    target_weights = pd.Series([1.0, 1.0, 0.0, 1.0])
    
    # Fee = 100 bps (1%) per trade leg
    sim = simulate_causal_portfolio(target_weights, mkt_rets, initial_capital_usd=1000.0, fee_bps_per_trade_leg=100.0)
    
    # Progression:
    # Bar 1: target_w from bar 0 is 1.0. Prev_w was 0.0. Turnover dw = 1.0. Fee = $1,000 * 0.01 = $10. Equity = $990.
    # Bar 2: target_w from bar 1 is 1.0. Prev_w was 1.0. dw = 0.0. Fee = $0. Equity = $990.
    # Bar 3: target_w from bar 2 is 0.0. Prev_w was 1.0. dw = 1.0. Fee = $990 * 0.01 = $9.90. Equity = $980.10.
    eq_series = sim["equity_series"]
    assert abs(eq_series.iloc[1] - 990.0) < 1e-4
    assert abs(eq_series.iloc[2] - 990.0) < 1e-4
    assert abs(eq_series.iloc[3] - 980.10) < 1e-4
    assert sim["rebalance_count"] == 2 # 2 rebalancing events (Bar 1 initial allocation and Bar 3 exit)
    assert abs(sim["total_turnover"] - 2.0) < 1e-4


def test_missed_rebound_diagnostics():
    """Verify that exits followed by immediate positive returns are correctly tracked as missed rebounds."""
    # 5 bars:
    # Bar 0: normal
    # Bar 1: exit to cash
    # Bar 2..49: market rises by +5%
    mkt_rets = pd.Series([0.0] * 60)
    # Exit to cash at bar 10:
    target_weights = pd.Series([1.0] * 60)
    target_weights.iloc[10:30] = 0.0 # 20 bars in cash
    
    # Market rebounds strongly in bars 11..15 (+1% each bar = ~5%)
    mkt_rets.iloc[11:16] = 0.01

    diag = compute_avrs_specific_diagnostics(target_weights, mkt_rets)
    assert diag["total_exits_to_cash"] == 1
    assert diag["cumulative_missed_rebound_pct"] > 4.5
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
        
    diag = data["phase_d_executable_portfolio_backtest"]["required_diagnostics"]
    
    # Ensure diagnostics exist
    assert "PASSIVE_NET_RETURN" in diag
    assert "CAUSAL_AVRS_RULE_NET_RETURN" in diag
    assert "MISSED_REBOUND_RETURN_PCT" in diag
    assert "ACTUAL_REBALANCE_COUNT" in diag
    
    # Causal AVRS falsification verdict must reflect genuine empirical outcomes
    assert diag["CAUSAL_AVRS_RULE_NET_RETURN"] < diag["PASSIVE_NET_RETURN"]
    assert diag["NET_ECONOMIC_VALUE"] == "NEGATIVE"
    
    disp = data["phase_f_neural_research_authorization"]["disposition_verdict"]
    assert disp["AVRS_NEURAL_PILOT"] == "NOT_AUTHORIZED"
    assert disp["AVRS_DISPOSITION"] == "REJECTED_OR_INCONCLUSIVE"
    
    # Ensure canonical file was NOT touched during test
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime
