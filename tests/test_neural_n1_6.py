"""Tests for N1.6 COIN-M Forward Market Evidence & Execution Feasibility."""

import json
from pathlib import Path
import pytest

from neural_trading.n1_6.config import FROZEN_H1, PAIR_TO_SPOT, REPO_ROOT
from neural_trading.n1_6.phase_a_closure import main as run_phase_a_closure
from neural_trading.n1_6.paired_evaluator import ForwardMarketEvaluator, compute_vwap_ask, compute_vwap_cm_bid


def test_frozen_h1_contract_invariants():
    """Verify H-1 thresholds remain strictly frozen from N1.5."""
    assert FROZEN_H1.entry_basis_ma24_bps == 75.0
    assert FROZEN_H1.entry_yield_ma24_ann_pct == 5.0
    assert FROZEN_H1.exit_basis_ma24_bps == 15.0
    assert FROZEN_H1.min_entry_ttm_hours == 72.0
    assert FROZEN_H1.max_single_weight == 0.25
    assert FROZEN_H1.max_concurrent_assets == 4


def test_vwap_orderbook_math():
    """Test order book walking VWAP logic for Spot ask and COIN-M bid."""
    # Spot asks: [[price, qty]]
    asks = [["100.0", "10.0"], ["101.0", "20.0"]]  # lvl 1 = $1000, lvl 2 = $2020
    # Buy $500 -> all at $100
    p, filled, full = compute_vwap_ask(asks, 500.0)
    assert full is True
    assert round(p, 4) == 100.0
    assert round(filled, 4) == 500.0

    # Buy $1500 -> $1000 @ 100, $500 @ 101 -> 10 base + 4.950495 base = 14.950495 base
    p2, filled2, full2 = compute_vwap_ask(asks, 1500.0)
    assert full2 is True
    assert round(filled2, 4) == 1500.0
    assert 100.0 < p2 < 101.0

    # COIN-M bids: [[price, contracts]]
    bids = [["100.0", "10"], ["99.0", "20"]]  # c_size = $10
    p_cm, filled_c, full_cm = compute_vwap_cm_bid(bids, 10.0, 15)
    assert full_cm is True
    assert filled_c == 15
    # 10 @ 100 + 5 @ 99 = 1000 + 495 = 1495 / 15 = 99.6667
    assert round(p_cm, 4) == round(1495.0 / 15.0, 4)


def test_phase_a_closure_contract():
    """Verify Phase A closure outputs and results contract."""
    res = run_phase_a_closure()
    assert "label_map" in res
    assert res["label_map"]["EXECUTABLE_NET_CARRY"] == "LIQUIDITY_CONSTRAINED_SIMULATED_NET_CARRY"
    assert "settlement_official_vs_approximation" in res
    assert res["settlement_official_vs_approximation"]["events_in_n1_5_cache"] == 128
    assert res["settlement_official_vs_approximation"]["events_matched_to_official"] == 115
    assert res["verdict_change_required"] is False


def test_forward_evaluation_deliverables():
    """Verify N1.6 forward evaluation produces valid deliverables and adhering to states."""
    res_path = REPO_ROOT / "research" / "neural_n1_6" / "n1_6_forward_carry_evidence_results.json"
    assert res_path.exists(), f"Missing {res_path}"
    data = json.loads(res_path.read_text(encoding="utf-8"))

    assert data["total_paired_observations"] > 0
    decision = data["phase_f_decision"]
    assert decision["source_readiness"] in ("H1_FORWARD_SOURCE_READY", "H1_FORWARD_SOURCE_INSUFFICIENT")
    assert decision["observed_executable_quotes"] in ("H1_OBSERVED_EXECUTABLE_QUOTES_SUPPORTED", "H1_OBSERVED_EXECUTABLE_QUOTES_NOT_SUPPORTED")
    assert decision["paired_execution_feasibility"] in ("H1_PAIRED_EXECUTION_FEASIBLE", "H1_PAIRED_EXECUTION_NOT_FEASIBLE")
    assert decision["forward_economic_evidence"] in ("H1_FORWARD_ECONOMIC_EVIDENCE_ACCUMULATING", "H1_FORWARD_NET_EDGE_NOT_YET_CONFIRMED")
    assert decision["production_candidate"] is False
    assert decision["real_trading"] == "DISABLED"
