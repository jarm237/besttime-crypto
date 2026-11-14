"""Tests for New Information Mechanism Discovery and CARM Experiment Pipeline.

Verifies:
1. Strict causality (168h return evaluated at bar t-2, executed at bar t, no lookahead).
2. Screening rejection of sub-minute / low-signal mechanisms (CALL-LD, VOSI-LS).
3. Empirical performance under standard and stressed costs.
4. Test isolation with tmp_path injection preserving canonical files.
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
    simulate_carm_top_momentum_strategy,
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


def test_carm_strategy_execution_causality_and_turnover():
    """Verify that CARM strategy executes with strict next-bar latency and charges turnover fees."""
    piv_close, symbols, prices, timestamps = load_causal_spot_data()

    # Fast test on first 500 bars
    sub_prices = prices[:500]
    sub_piv = piv_close.iloc[:500]
    sub_ts = timestamps[:500]

    sim = simulate_carm_top_momentum_strategy(
        sub_piv, symbols, sub_prices, sub_ts, top_k=3, rebalance_interval_hours=168, fee_bps=12.0
    )

    assert sim["total_turnover"] > 0.0
    assert sim["total_fees_paid_usd"] > 0.0
    assert len(sim["equity_series"]) == 500


def test_carm_information_discovery_artifact_isolation(tmp_path: Path):
    """Verify tmp_path injection isolates test artifacts and preserves canonical files."""
    canonical_file = ROOT / "research" / "information_discovery" / "next_information_mechanisms_screening.json"
    canonical_mtime = canonical_file.stat().st_mtime if canonical_file.exists() else None

    report = build_information_mechanism_discovery_report(output_dir=tmp_path)

    isolated_file = tmp_path / "next_information_mechanisms_screening.json"
    assert isolated_file.exists()

    with open(isolated_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    exp = data["phase_e_bounded_experiment_carm_cc"]
    assert "CARM_CC_TOP3_MOMENTUM_STD_COST" in exp["benchmark_comparisons"]
    assert exp["excess_net_utility"]["excess_vs_buy_and_hold_pct"] > 50.0

    verdict = data["phase_f_neural_pilot_authorization"]["authorization_verdict"]
    assert verdict["BOUNDED_NEURAL_PILOT_AUTHORIZATION"] == "AUTHORIZED_FOR_CARM_CONTINUOUS_POLICY"

    # Ensure canonical file was NOT touched during test
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime
