"""Tests for State-Aware Temporal Policy & Expanded Benchmark Experiment.

Verifies:
1. Training/evaluation label boundary purge (0% future label leakage across 2023/2024).
2. Spot cost parity semantics (traded notional on assets only, zero fee on cash changes).
3. Portfolio equity conservation and initial capital reconciliation.
4. State-aware temporal model architecture capacity (<= 50,000 parameters) and drift-hold mechanism.
5. Strict artifact isolation (tmp_path injection preserving canonical files).
6. Research stop rule disposition (truthfully records hypothesis falsification and search termination).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd
import torch

from scripts.run_state_aware_temporal_experiment import (
    load_causal_spot_data,
    extract_causal_features,
    purge_boundary_crossing_labels,
    simulate_spot_portfolio_policy,
    StateAwareTemporalPolicy,
    SharedMLP,
    build_state_aware_temporal_experiment_report,
    ROOT,
)


def test_training_boundary_purge_integrity():
    """Verify that training steps whose 168h future label extends into 2024 are purged."""
    piv_close, _, _, timestamps = load_causal_spot_data()
    dt = pd.to_datetime(timestamps, unit="ms")
    T = len(piv_close)
    step_indices = np.arange(168, T - 168, 168)

    train_purged, eval_steps, purge_info = purge_boundary_crossing_labels(step_indices, timestamps)

    # Must purge exactly the step whose label end reaches into 2024
    assert purge_info["purged_steps_count"] == 1
    assert purge_info["train_steps_before_purge"] == 104
    assert purge_info["train_steps_after_purge"] == 103
    assert purge_info["eval_steps_count"] == 103

    # Verify no purged step is in train_purged
    for s in train_purged:
        label_end_dt = dt[s + 168]
        assert label_end_dt < pd.Timestamp("2024-01-01 00:00:00")

    # Verify first eval step is in 2024
    assert dt[eval_steps[0]] >= pd.Timestamp("2024-01-01 00:00:00")


def test_spot_cost_parity_and_no_cash_fee():
    """Verify that Spot rebalancing fee applies strictly to traded assets, with zero fee on cash."""
    piv_close, symbols, prices, timestamps = load_causal_spot_data()
    N = len(symbols)
    fee_rate_bps = 12.0
    initial_cap = 10000.0

    # Test 1: 100% Cash -> 100% BTC at t=0
    btc_idx = symbols.index("BTCUSDT")
    target_w = np.zeros(N + 1)
    target_w[1 + btc_idx] = 1.0  # target: 0% cash, 100% BTC

    sub_prices = prices[:10]
    sub_ts = timestamps[:10]

    sim = simulate_spot_portfolio_policy(
        {0: target_w}, sub_prices, sub_ts, symbols, fee_bps=fee_rate_bps, initial_capital_usd=initial_cap
    )

    # Traded asset notional is $10,000. Fee must be exactly 12 bps = $12.00
    # NOT $24.00 (which would occur if cash was double-charged)
    assert abs(sim["total_fees_paid_usd"] - 12.00) < 1e-4
    assert abs(sim["total_turnover"] - 1.0) < 1e-4

    # Post-trade equity must equal initial_capital - fee
    assert abs(sim["equity_series"].iloc[0] - (initial_cap - 12.00)) < 1e-4

    # Initial capital exact reconciliation: Net return = (final_equity / 10000) - 1
    expected_net_ret = round(((sim["final_equity_usd"] / initial_cap) - 1.0) * 100.0, 2)
    assert abs(sim["net_return_pct"] - expected_net_ret) < 1e-4


def test_state_aware_temporal_model_capacity_and_hold_mechanism():
    """Verify that model capacity is <= 50,000 parameters and drift-hold stops unnecessary turnover."""
    policy = StateAwareTemporalPolicy(in_features=4, gru_hidden=24, n_assets=8, head_hidden=64)
    param_count = sum(p.numel() for p in policy.parameters())

    assert param_count <= 50000
    assert param_count == 15801  # Exact architecture capacity

    # Test forward pass with sequence tensor and current portfolio state
    x_seq = torch.randn(8, 24, 4)
    w_curr = torch.tensor([0.5, 0.1, 0.1, 0.1, 0.1, 0.05, 0.02, 0.02, 0.01])
    out_w = policy(x_seq, w_curr)

    assert out_w.shape == (9,)
    assert abs(float(out_w.detach().sum()) - 1.0) < 1e-5
    assert (out_w >= 0.0).all()

    # Test drift-hold mechanism in simulation with controlled prices
    N = 8
    dummy_prices = np.ones((10, N)) * 100.0
    dummy_ts = pd.date_range("2024-01-01", periods=10, freq="h")
    dummy_symbols = [f"SYM{i}" for i in range(N)]

    w_base = np.zeros(N + 1)
    w_base[1:] = 1.0 / N

    w_slight_drift = np.zeros(N + 1)
    w_slight_drift[1:] = 1.0 / N
    w_slight_drift[1] += 0.005
    w_slight_drift[2] -= 0.005  # displacement = 0.010 < 0.020 -> HOLD

    w_large_shift = np.zeros(N + 1)
    w_large_shift[1] = 1.0  # displacement = 0.875 > 0.020 -> REBALANCE

    target_dict = {
        0: w_base,         # Initial trade: rebalance_count = 1
        1: w_slight_drift, # Displacement = 0.010 < 0.020 -> HOLD (hold_count = 1)
        2: w_large_shift,  # Displacement > 0.020 -> REBALANCE (rebalance_count = 2)
    }

    sim = simulate_spot_portfolio_policy(
        target_dict, dummy_prices, dummy_ts, dummy_symbols, fee_bps=12.0, drift_hold_threshold=0.02
    )

    # Initial rebalance at t=0 and large shift at t=2 executed, but t=1 was held
    assert sim["rebalance_count"] == 2
    assert sim["hold_count"] == 1


def test_artifact_isolation_and_stop_rule_disposition(tmp_path: Path):
    """Verify tmp_path injection isolates test output and faithfully records hypothesis falsification."""
    canonical_file = ROOT / "research" / "information_discovery" / "state_aware_temporal_experiment_results.json"
    canonical_mtime = canonical_file.stat().st_mtime if canonical_file.exists() else None

    report = build_state_aware_temporal_experiment_report(output_dir=tmp_path)

    isolated_file = tmp_path / "state_aware_temporal_experiment_results.json"
    assert isolated_file.exists()

    # Verify canonical file was untouched
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime

    with open(isolated_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify metadata & guardrails
    meta = data["metadata"]
    assert meta["production_candidate"] is False
    assert meta["real_trading"] == "DISABLED"
    assert meta["sealed_holdouts_accessed"] is False

    # Verify purge summary
    purge = data["phase_0_parity_and_boundary_purge"]["purge_summary"]
    assert purge["purged_steps_count"] == 1
    assert purge["train_steps_after_purge"] == 103

    # Verify benchmarks present
    benchmarks = data["phase_2_expanded_benchmarks_summary_table"]
    expected_benchmarks = [
        "CASH",
        "BTC_PHYSICAL_BUY_AND_HOLD",
        "ETH_PHYSICAL_BUY_AND_HOLD",
        "EW_8ASSET_PHYSICAL_BUY_AND_HOLD",
        "EW_8ASSET_WEEKLY_REBALANCED",
        "CARM_WEEKLY_ONLY",
        "CORRECTED_SHARED_MLP",
        "STATE_AWARE_TEMPORAL_POLICY",
    ]
    for b in expected_benchmarks:
        assert b in benchmarks

    # Verify Stop Rule: both neural policies failed to beat CARM out of sample
    disp = data["phase_3_research_stop_rule_disposition"]
    assert disp["current_neural_information_hypothesis"] == "NOT_SUPPORTED"
    assert disp["current_model_family_search"] == "STOPPED"
    assert disp["disposition"] == "HYPOTHESIS_FALSIFIED_SEARCH_TERMINATED"
    assert disp["temporal_incremental_value_vs_carm_pct"] < 0.0
    assert disp["mlp_incremental_value_vs_carm_pct"] < 0.0
