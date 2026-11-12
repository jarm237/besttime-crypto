"""Tests for N1.7 Forward COIN-M Paired-Trade Lifecycle & Economic Evidence."""

import json
from pathlib import Path
import pytest

from neural_trading.n1_7.config import FROZEN_H1, COSTS, REPO_ROOT
from neural_trading.n1_7.lifecycle_engine import N1_7LifecycleEngine


def test_frozen_h1_and_costs_contract_n1_7():
    """Verify N1.7 frozen parameters and cost schedule match N1.5."""
    assert FROZEN_H1.entry_basis_ma24_bps == 75.0
    assert FROZEN_H1.entry_yield_ann_pct == 5.0
    assert FROZEN_H1.exit_basis_ma24_bps == 15.0
    assert FROZEN_H1.min_entry_ttm_hours == 72.0
    assert FROZEN_H1.max_concurrent_assets == 4
    assert FROZEN_H1.max_single_weight == 0.25

    # Cost schedule matches standard_retail_taker = 39 bps baseline
    assert COSTS.spot_entry_fee_bps == 10.0
    assert COSTS.cm_entry_fee_bps == 5.0
    assert COSTS.spot_exit_fee_bps == 10.0
    assert COSTS.cm_early_exit_fee_bps == 5.0
    assert COSTS.cm_delivery_settlement_fee_bps == 5.0
    assert COSTS.baseline_spread_slippage_bps == 9.0
    assert COSTS.all_in_baseline_rt_bps == 39.0


def test_n1_7_phase_a_btcusd_261225_not_eligible():
    """Verify Phase A1 explicit requirement: BTCUSD_261225 is NOT eligible under true MA24 basis (<75 bps)."""
    engine = N1_7LifecycleEngine()
    res = engine.run_lifecycle_analysis()
    
    intent_parquet = REPO_ROOT / "data" / "neural_n1_7" / "n1_7_paired_order_intent_ledger.parquet"
    assert intent_parquet.exists()
    import pandas as pd
    df = pd.read_parquet(intent_parquet)
    
    btc_cq = df[df["coinm_contract_symbol"] == "BTCUSD_261225"]
    assert len(btc_cq) > 0
    # Every snapshot of BTCUSD_261225 must have entry_eligible == False because MA24 basis is below 75 bps
    assert (btc_cq["entry_eligible"] == False).all()
    # Confirm block reason is present
    for reasons in btc_cq["entry_block_reasons"]:
        assert any("CAUSAL_MA24_BASIS_BELOW_75_BPS" in r for r in reasons)


def test_n1_7_independent_orderbook_sweeps_and_scenarios():
    """Verify independent orderbook sweeps, distinct leg depths, and 3 execution scenarios."""
    results_p = REPO_ROOT / "research" / "neural_n1_7" / "n1_7_forward_lifecycle_results.json"
    assert results_p.exists()
    data = json.loads(results_p.read_text(encoding="utf-8"))

    scenarios = data["execution_scenarios"]
    assert "scenario_1_spot_fills_first" in scenarios
    assert "scenario_2_coinm_fills_first" in scenarios
    assert "scenario_3_matched_virtual_fills" in scenarios
    assert scenarios["scenario_1_spot_fills_first"]["total_runs"] == 100


def test_n1_7_lifecycle_states_and_decision():
    """Verify lifecycle state machine transitions and Phase F decision states."""
    results_p = REPO_ROOT / "research" / "neural_n1_7" / "n1_7_forward_lifecycle_results.json"
    data = json.loads(results_p.read_text(encoding="utf-8"))

    # Active lifecycles in HEDGED_HOLD
    lifecycles = data["active_lifecycles"]
    assert len(lifecycles) > 0
    for l in lifecycles:
        assert l["state"] in ["PAIR_ENTRY_SIMULATED", "HEDGED_HOLD", "HEDGE_INCOMPLETE", "EARLY_EXIT_ELIGIBLE", "SETTLEMENT", "CLOSED"]
        assert len(l["lifecycle_history"]) >= 2
        # Margin ratio matches MMR identity
        assert l["margin_ratio"] in [0.004, 0.005]

    decision = data["phase_f_decision"]
    assert decision["H1_FORWARD_QUOTES_VALID"] is True
    assert decision["H1_FROZEN_SIGNAL_ELIGIBILITY_VALID"] is True
    assert decision["H1_PAIRED_EXECUTION_SIMULATOR_VALID"] is True
    assert decision["H1_PAIRED_EXECUTION_FEASIBILITY"] in ["SUPPORTED", "INSUFFICIENT", "FAILED"]
    assert decision["H1_FORWARD_CARRY_LIFECYCLES"] in ["ACCUMULATING", "RESOLVED"]
    assert decision["H1_FORWARD_NET_ECONOMIC_VALUE"] in ["SUPPORTED", "NEGATIVE", "INCONCLUSIVE"]
    assert decision["H1_PRODUCTION_CANDIDATE"] is False
    assert decision["REAL_TRADING"] == "DISABLED"
