"""Tests for N1.8 COIN-M Forward Lifecycle Correctness & Natural Economic Accumulation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neural_trading.n1_8.allocation_engine import (
    AccountMarginLedger,
    AccountUnderlyingAllocationLedger,
    IndependentLegExecutionSimulator,
)
from neural_trading.n1_8.config import (
    COSTS,
    DATA_ROOT_N1_8,
    FROZEN_H1,
    PORTFOLIO_CONFIG,
    RESEARCH_DIR_N1_8,
)
from neural_trading.n1_8.lifecycle_reconciler import N1_8LifecycleReconciler


@pytest.fixture
def reconciler_output():
    reconciler = N1_8LifecycleReconciler()
    return reconciler.execute_all_phases()


def test_underlying_asset_risk_aggregation():
    """Verify that account-level allocation strictly aggregates by underlying asset."""
    ledger = AccountUnderlyingAllocationLedger(portfolio_capital_usd=20_000.0)

    # 1. Allocate BNBUSD_261225 ($5,000 notional)
    ok1, pos1, reason1 = ledger.allocate_position(
        contract_symbol="BNBUSD_261225",
        contracts=500,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=685.0,
        timestamp_ms=1000,
    )
    assert ok1 is True
    assert pos1 is not None
    assert pos1.status == "HEDGED_HOLD"

    # 2. Attempt to allocate BNBUSD_270326 ($2,370 notional) -> Should be rejected without flag
    ok2, pos2, reason2 = ledger.allocate_position(
        contract_symbol="BNBUSD_270326",
        contracts=237,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=695.0,
        timestamp_ms=2000,
        allow_over_allocation_recording=False,
    )
    assert ok2 is False
    assert pos2 is None
    assert "EXCEEDS_AGGREGATE_UNDERLYING_CAP" in reason2

    # 3. Allow recording defect for historical N1.7 audit
    ok3, pos3, reason3 = ledger.allocate_position(
        contract_symbol="BNBUSD_270326",
        contracts=237,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=695.0,
        timestamp_ms=2000,
        allow_over_allocation_recording=True,
    )
    assert ok3 is False
    assert pos3 is not None
    assert pos3.status == "RISK_ACTION_REQUIRED"
    assert "EXCEEDS_AGGREGATE_UNDERLYING_CAP" in pos3.disposition_note

    # 4. Allocate independent asset BTCUSD_270326 ($5,000 notional) -> Should succeed
    ok4, pos4, reason4 = ledger.allocate_position(
        contract_symbol="BTCUSD_270326",
        contracts=50,
        contract_size_usd=100.0,
        spot_price=74000.0,
        fut_price=75500.0,
        timestamp_ms=3000,
    )
    assert ok4 is True
    assert pos4 is not None
    assert pos4.status == "HEDGED_HOLD"


def test_coinm_initial_collateral_feasibility():
    """Verify that COIN-M-first is blocked without collateral and records prefunded delta if collateral exists."""
    sim = IndependentLegExecutionSimulator()

    # Unfunded COIN-M-first
    unfunded = sim.simulate_coinm_first(
        target_notional_usd=5000.0,
        spot_ask_vwap=680.0,
        spot_avail_usd=10000.0,
        cm_bid_vwap=685.0,
        cm_avail_usd=10000.0,
        contract_size_usd=10.0,
        has_prefunded_collateral=False,
    )
    assert unfunded["status"] == "BLOCKED_BY_EXCHANGE_MARGIN_RULE"
    assert unfunded["failure_reason"] == "COINM_FIRST_BLOCKED_INSUFFICIENT_COLLATERAL"
    assert unfunded["first_leg_fill"] == "NONE"

    # Prefunded COIN-M-first
    prefunded = sim.simulate_coinm_first(
        target_notional_usd=5000.0,
        spot_ask_vwap=680.0,
        spot_avail_usd=10000.0,
        cm_bid_vwap=685.0,
        cm_avail_usd=10000.0,
        contract_size_usd=10.0,
        has_prefunded_collateral=True,
    )
    assert prefunded["status"] == "HEDGE_COMPLETE_PREFUNDED"
    assert prefunded["maximum_unhedged_delta"] == 5000.0
    assert prefunded["initial_account_delta"] == 5000.0

    # Matched depth must be labeled BOOK_DEPTH_PAIRABLE
    matched = sim.simulate_matched_virtual_capacity(
        target_notional_usd=5000.0,
        spot_ask_vwap=680.0,
        spot_avail_usd=10000.0,
        cm_bid_vwap=685.0,
        cm_avail_usd=10000.0,
        contract_size_usd=10.0,
    )
    assert matched["status"] == "BOOK_DEPTH_PAIRABLE"
    assert matched["status"] != "TWO_LEG_EXECUTION_CONFIRMED"


def test_dynamic_margin_ratio_and_tier():
    """Verify cross-margin calculation, dynamic margin ratio, and non-zero liquidation risk."""
    ledger = AccountMarginLedger()

    positions = [
        {
            "contract_symbol": "BNBUSD_261225",
            "entry_notional_usd": 5000.0,
            "entry_futures_price": 685.0,
        }
    ]
    cur_spot = {"BNB": 684.0}
    cur_fut = {"BNBUSD_261225": 690.0}  # Futures price rose -> inverse short lost slightly

    wallet = ledger.update_coin_wallet(
        coin="BNB",
        wallet_balance_coin=7.35,
        active_positions=positions,
        current_spot_prices=cur_spot,
        current_futures_prices=cur_fut,
    )

    assert wallet["coin"] == "BNB"
    assert wallet["contract_tier"] == "Tier 1"
    assert wallet["unrealized_inverse_pnl_coin"] < 0.0
    assert wallet["margin_balance_coin"] < 7.35
    # Margin ratio must be calculated dynamically and be between 0.1% and 1.0% for fully collateralized
    assert 0.003 < wallet["margin_ratio"] < 0.007
    assert "NON_ZERO" in wallet["liquidation_risk_note"]


def test_n1_7_reconciliation_and_pricing_disentanglement(reconciler_output):
    """Verify that N1.7 MTM -$167.96 is fully explained and disentangled from true asset pricing."""
    rec = reconciler_output["reconciliation"]
    assert rec["n1_7_reported_total_unrealized_pnl_usd"] == -167.96
    # True gross basis MTM across positions is slightly positive (+1.74 USD under causal pairing, +3.63 USD under original)
    assert abs(rec["true_total_gross_basis_mtm_usd"] - 1.74) < 0.5 or abs(rec["true_total_gross_basis_mtm_usd"] - 3.63) < 0.5
    # True entry fees paid upfront
    assert abs(rec["true_total_entry_fees_paid_usd"] - 18.56) < 0.5
    # True net MTM
    assert abs(rec["true_total_net_mtm_usd"] - (-16.81)) < 0.5 or abs(rec["true_total_net_mtm_usd"] - (-14.92)) < 0.5
    # Cross-symbol pricing bug accounts for over -$150 of artificial drawdown
    assert rec["cross_symbol_pricing_defect_usd"] < -140.0


def test_recorder_health_and_paused_status(reconciler_output):
    """Verify recorder health detection and FORWARD_ACCUMULATION = PAUSED state."""
    rec_health = reconciler_output["recorder_health"]
    assert rec_health["pid_is_running"] is False
    assert rec_health["forward_accumulation_state"] == "PAUSED"
    assert len(rec_health["operational_spec_audit"]) == 7


def test_end_to_end_n1_8_reconciler_and_artifacts(reconciler_output):
    """Verify all machine-readable JSON artifacts and disposition verdicts."""
    expected_files = [
        "n1_8_underlying_allocation_ledger.json",
        "n1_8_account_margin_ledger.json",
        "n1_8_independent_leg_scenarios.json",
        "n1_8_position_reconciliation.json",
        "n1_8_recorder_health.json",
        "n1_8_lifecycle_state.json",
    ]
    for fn in expected_files:
        p = RESEARCH_DIR_N1_8 / fn
        assert p.exists()
        assert p.stat().st_size > 0

    disp = reconciler_output["lifecycle_state"]["disposition"]
    assert disp["N1_8_PORTFOLIO_RISK_AGGREGATION"] == "VERIFIED"
    assert disp["N1_8_COINM_COLLATERAL_FEASIBILITY"] == "VERIFIED"
    assert disp["N1_8_INDEPENDENT_LEG_ACCOUNTING"] == "VERIFIED"
    assert disp["N1_8_COST_ACCOUNTING"] == "RECONCILED"
    assert disp["H1_FORWARD_LIFECYCLES"] == "ACCUMULATING"
    assert disp["H1_FORWARD_NET_ECONOMIC_VALUE"] == "INCONCLUSIVE"
    assert disp["H1_PRODUCTION_CANDIDATE"] is False
    assert disp["REAL_TRADING"] == "DISABLED"
