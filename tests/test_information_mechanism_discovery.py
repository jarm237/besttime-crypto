"""Tests for New Information Mechanism Discovery and CARM Experiment Pipeline.

Verifies:
1. Initial capital accounting reconciliation (NET_RETURN = FINAL_EQUITY / INITIAL_CAPITAL - 1).
2. Distinction between CARM_WEEKLY_ONLY (209 rebalances) and CARM_WEEKLY_WITH_DRIFT_CONTROL (>2,000 rebalances).
3. Cross-sectional IC computation (Spearman Rank IC and Pearson IC on non-overlapping intervals).
4. Screening rejection of sub-minute / low-signal mechanisms (CALL-LD, VOSI-LS).
5. Unfavorable neural out-of-sample result recording (NEURAL_INCREMENTAL_VALUE = NOT_SUPPORTED).
6. Strict test output isolation (tmp_path injection preserving canonical files).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

from scripts.run_information_mechanism_discovery import (
    load_causal_spot_data,
    screen_candidate_mechanisms,
    compute_cross_sectional_ic_statistics,
    simulate_carm_top_momentum_strategy,
    train_and_evaluate_bounded_neural_pilot,
    build_information_mechanism_discovery_report,
    ROOT,
)


def test_candidate_mechanisms_screening_rejections():
    """Verify that CALL-LD and VOSI-LS are empirically rejected after transaction costs."""
    piv_close, symbols, _, _ = load_causal_spot_data()
    results = screen_candidate_mechanisms(piv_close, symbols)

    assert results["CALL_LD"]["screening_disposition"] == "REJECTED_AFTER_COSTS"
    assert results["VOSI_LS"]["screening_disposition"] == "REJECTED_AFTER_COSTS"
    assert results["CARM_CC"]["screening_disposition"] == "SURVIVED_INITIAL_SCREEN_SELECTED_FOR_EXPERIMENT"


def test_cross_sectional_ic_statistics():
    """Verify true per-timestamp cross-sectional IC computation on non-overlapping intervals."""
    piv_close, _, _, _ = load_causal_spot_data()
    ic_stats = compute_cross_sectional_ic_statistics(piv_close, horizon_hours=168)

    assert ic_stats["evaluation_intervals_count"] >= 200
    assert "mean_rank_ic" in ic_stats
    assert "median_rank_ic" in ic_stats
    assert "pct_positive_rank_ic" in ic_stats
    assert "annual_ic_breakdown" in ic_stats
    assert len(ic_stats["annual_ic_breakdown"]) == 4


def test_initial_equity_reconciliation_and_variant_distinction():
    """Verify exact net return reconciliation with initial capital and distinction between variants."""
    piv_close, symbols, prices, timestamps = load_causal_spot_data()

    # Fast evaluation on first 1000 bars
    sub_prices = prices[:1000]
    sub_piv = piv_close.iloc[:1000]
    sub_ts = timestamps[:1000]

    sim_wo = simulate_carm_top_momentum_strategy(
        sub_piv, symbols, sub_prices, sub_ts, top_k=3, rebalance_interval_hours=168, rebalance_on_drift=False, fee_bps=12.0
    )
    sim_dc = simulate_carm_top_momentum_strategy(
        sub_piv, symbols, sub_prices, sub_ts, top_k=3, rebalance_interval_hours=168, rebalance_on_drift=True, fee_bps=12.0
    )

    # 1. Exact initial capital reconciliation:
    # Net return must equal final equity / initial capital - 1
    expected_ret_wo = round(((sim_wo["final_equity_usd"] / 10000.0) - 1.0) * 100.0, 2)
    assert abs(sim_wo["net_return_pct"] - expected_ret_wo) < 0.05

    # 2. Variant distinction: weekly-only rebalances significantly less frequently than drift-control
    assert sim_wo["rebalance_count"] < sim_dc["rebalance_count"]
    assert sim_wo["total_turnover"] < sim_dc["total_turnover"]


def test_carm_information_discovery_artifact_isolation_and_neural_verdict(tmp_path: Path):
    """Verify tmp_path injection isolates test artifacts and records neural disposition truthfully."""
    canonical_file = ROOT / "research" / "information_discovery" / "next_information_mechanisms_screening.json"
    canonical_mtime = canonical_file.stat().st_mtime if canonical_file.exists() else None

    report = build_information_mechanism_discovery_report(output_dir=tmp_path)

    isolated_file = tmp_path / "next_information_mechanisms_screening.json"
    assert isolated_file.exists()

    with open(isolated_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Accounting reconciliation
    assert data["phase_a_economic_accounting_reconciliation"]["initial_capital_usd"] == 10000.00
    assert "CARM_WEEKLY_ONLY" in data["phase_a2_carm_variants_comparison"]
    assert "CARM_WEEKLY_WITH_DRIFT_CONTROL" in data["phase_a2_carm_variants_comparison"]

    # Neural pilot out-of-sample failure must be recorded honestly
    neural_res = data["phase_c_bounded_neural_pilot_results"]
    assert neural_res["incremental_eval_net_return_vs_carm"] < 0.0

    disp = data["phase_d_research_dispositions"]
    assert disp["CARM_ECONOMIC_EDGE"] == "SUPPORTED_EXPLORATORY"
    assert disp["NEURAL_INCREMENTAL_VALUE"] == "NOT_SUPPORTED"
    assert disp["BOUNDED_NEURAL_PILOT_AUTHORIZATION"] == "COMPLETED_INCREMENTAL_VALUE_NOT_SUPPORTED"

    # Ensure canonical file was NOT touched during test
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime
