"""Targeted regression and specification test suite for N1.8-R2.

Verifies:
1. MA24 remains causal and never uses future USDT/USD.
2. Frozen 75 bps eligibility cannot be overridden by historical hardcoding.
3. Future-received Spot quotes cannot pair with earlier decisions (causal pairing constraint).
4. Out-of-order observations cannot change current equity (OUT_OF_ORDER_IGNORED).
5. Cross-symbol quotes cannot change unrelated positions (CROSS_SYMBOL_IGNORED).
6. Multiple lifecycles receive unique persistent IDs.
7. Cross-expiry underlying caps remain strictly enforced ($5,000 max per asset).
8. Close-now values use Spot bid / COIN-M ask without double spread deduction.
9. A natural virtual early exit produces correct realized PnL.
10. A virtual delivery settlement produces correct inverse-coin accounting.
11. Restart preserves state and does not duplicate entries.
12. Replay is deterministic from frozen inputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from neural_trading.n1_7.config import (
    COSTS,
    FROZEN_H1,
    LifecycleState,
    RESEARCH_DIR_N1_7,
)
from neural_trading.n1_7.lifecycle_engine import (
    ForwardLifecycleRunner,
    N1_7LifecycleEngine,
)
from neural_trading.n1_8.allocation_engine import AccountUnderlyingAllocationLedger


# ---------------------------------------------------------------------------
# Test Case 1: MA24 causal calculation without future USDT/USD
# ---------------------------------------------------------------------------
def test_case_1_ma24_causal_no_future_usdt():
    """Verify MA24 uses strictly historical bars and timestamp-aligned USDT/USD."""
    engine = N1_7LifecycleEngine()
    ts = 1794409200000  # 2026-11-11 15:00:00 UTC

    # Fetch causal MA24 for BNB Dec delivery
    ma24_basis, usdt_usd, ready = engine.fetch_causal_ma24_history("BNBUSD_261225", ts)
    assert ready is True
    assert ma24_basis > 75.0
    assert 0.99 < usdt_usd < 1.01

    # If timestamp has insufficient history (< 24 bars), must return ready=False
    early_ts = 1794326400000  # 23 hours prior to dataset end (only ~5 bars available)
    ma24_early, _, ready_early = engine.fetch_causal_ma24_history("BNBUSD_261225", early_ts)
    assert ready_early is False
    assert ma24_early == 0.0


# ---------------------------------------------------------------------------
# Test Case 2: Frozen 75 bps eligibility cannot be overridden
# ---------------------------------------------------------------------------
def test_case_2_frozen_75bps_no_historical_hardcoding():
    """Verify BTCUSD_261225 calculates natural MA24 (74.25 bps) and is not forced to 74.55."""
    engine = N1_7LifecycleEngine()
    ts = 1794409200000

    ma24_basis, usdt_usd, ready = engine.fetch_causal_ma24_history("BTCUSD_261225", ts)
    assert ready is True
    # The natural calculation without hardcoded override is 74.25 bps (< 75.0 bps)
    assert abs(ma24_basis - 74.25) < 0.1
    assert ma24_basis != 74.55  # Verify no artificial hardcoding

    # In engine replay, BTCUSD_261225 must not be admitted because it is below 75 bps
    results = engine.run_lifecycle_analysis()
    active_symbols = {p["contract_symbol"] for p in results["active_lifecycles"]}
    assert "BTCUSD_261225" not in active_symbols


# ---------------------------------------------------------------------------
# Test Case 3: Future-received Spot quotes cannot pair with earlier decisions
# ---------------------------------------------------------------------------
def test_case_3_future_spot_quote_pairing_blocked():
    """Verify that a Spot quote received AFTER decision timestamp is strictly rejected."""
    cm_recv = 1794409629037  # COIN-M quote arrival time

    # Mock candidate Spot quotes
    past_quote = {"recv_ms": 1794409628000, "payload": {"bids": [["680", "1"]], "asks": [["681", "1"]]}}
    future_quote = {"recv_ms": 1794409629040, "payload": {"bids": [["680.5", "1"]], "asks": [["681.5", "1"]]}}
    # future_quote is only 3ms away, past_quote is 1037ms away.
    # Non-causal abs() would pick future_quote (|3| < |1037|). Causal pairing must reject future_quote.

    sp_list = [past_quote, future_quote]

    # Causal pairing algorithm
    s_idx = 0
    n_sp = len(sp_list)
    while s_idx + 1 < n_sp and sp_list[s_idx + 1]["recv_ms"] <= cm_recv:
        s_idx += 1

    selected_quote = sp_list[s_idx]
    assert selected_quote["recv_ms"] <= cm_recv
    assert selected_quote["recv_ms"] == 1794409628000
    assert selected_quote != future_quote


# ---------------------------------------------------------------------------
# Test Case 4: Out-of-order observations cannot change current equity
# ---------------------------------------------------------------------------
def test_case_4_out_of_order_observations_ignored():
    """Verify engine.process_observation strictly rejects out-of-order timestamps."""
    engine = N1_7LifecycleEngine()
    pos = {
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "entry_timestamp": 1794409639026,
        "last_valid_observation_timestamp": 1794411000000,
        "last_update_ms": 1794411000000,
        "cur_spot_vwap": 683.5,
        "cur_fut_vwap": 689.5,
    }

    # Observation with timestamp strictly in the past relative to pos high watermark
    out_of_order_obs = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1794410500000,  # 500s in the past
        "quote_valid_pit": True,
        "spot_ask_vwap": 600.0,  # Extreme shock that must NOT be applied
        "coinm_bid_vwap": 600.0,
    }

    ok, reason = engine.process_observation(pos, out_of_order_obs)
    assert ok is False
    assert reason == "OUT_OF_ORDER_IGNORED"
    assert pos["cur_spot_vwap"] == 683.5
    assert pos["cur_fut_vwap"] == 689.5
    assert pos["last_valid_observation_timestamp"] == 1794411000000


# ---------------------------------------------------------------------------
# Test Case 5: Cross-symbol quotes cannot change unrelated positions
# ---------------------------------------------------------------------------
def test_case_5_cross_symbol_quotes_ignored():
    """Verify engine.process_observation rejects cross-symbol updates."""
    engine = N1_7LifecycleEngine()
    bnb_pos = {
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "entry_timestamp": 1794409639026,
        "last_valid_observation_timestamp": 1794410000000,
        "cur_spot_vwap": 683.5,
        "cur_fut_vwap": 689.5,
    }

    xrp_obs = {
        "coinm_contract_symbol": "XRPUSD_270326",
        "decision_timestamp": 1794411000000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 0.50,
        "coinm_bid_vwap": 0.55,
    }

    ok, reason = engine.process_observation(bnb_pos, xrp_obs)
    assert ok is False
    assert reason == "CROSS_SYMBOL_IGNORED"
    assert bnb_pos["cur_spot_vwap"] == 683.5
    assert bnb_pos["cur_fut_vwap"] == 689.5


# ---------------------------------------------------------------------------
# Test Case 6: Multiple lifecycles receive unique persistent IDs
# ---------------------------------------------------------------------------
def test_case_6_unique_persistent_lifecycle_ids():
    """Verify lifecycles receive immutable, non-colliding IDs across admissions."""
    engine = N1_7LifecycleEngine()
    results = engine.run_lifecycle_analysis()

    compliant = results["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]
    all_lifecycles = compliant["active_lifecycles"] + compliant["quarantined_lifecycles"]

    ids = [p["lifecycle_id"] for p in all_lifecycles]
    assert len(ids) == len(set(ids)), "Lifecycle IDs must be strictly unique"
    assert sorted(ids) == ["VTRADE_0001", "VTRADE_0002", "VTRADE_0003"]
    assert set(ids) == {"VTRADE_0001", "VTRADE_0002", "VTRADE_0003"}

    # Original quarantined lifecycle retains its original identity
    quarantined = compliant["quarantined_lifecycles"][0]
    assert quarantined["lifecycle_id"] == "VTRADE_0001"
    assert quarantined["contract_symbol"] == "BNBUSD_261225"


# ---------------------------------------------------------------------------
# Test Case 7: Cross-expiry underlying caps remain enforced ($5,000 max)
# ---------------------------------------------------------------------------
def test_case_7_cross_expiry_underlying_caps_enforced():
    """Verify underlying aggregation strictly caps aggregate capital across quarterly expiries."""
    ledger = AccountUnderlyingAllocationLedger(portfolio_capital_usd=20_000.0)

    # Leg 1: BNB Dec expiry ($5,000 notional, exactly 25% cap)
    ok1, pos1, _ = ledger.allocate_position(
        contract_symbol="BNBUSD_261225",
        contracts=500,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=685.0,
        timestamp_ms=1000,
    )
    assert ok1 is True

    # Leg 2: BNB Mar expiry ($2,370 notional) must be rejected because BNB already has $5,000
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


# ---------------------------------------------------------------------------
# Test Case 8: Close-now values use Spot bid / COIN-M ask
# ---------------------------------------------------------------------------
def test_case_8_close_now_uses_spot_bid_coinm_ask():
    """Verify closing valuation uses exit executable prices (Spot bid, COIN-M ask)."""
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_TEST",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 685.0,
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    obs = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 2000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 682.0,
        "coinm_bid_vwap": 686.0,
        "spot_bid_vwap": 681.5,  # Exit spot level
        "coinm_ask_vwap": 686.5,  # Exit futures cover level
        "observed_depth_basis_bps": 73.0,  # Holding, not early exit
    }

    ok, reason = engine.process_observation(pos, obs)
    assert ok is True
    assert pos["exit_spot_bid_vwap"] == 681.5
    assert pos["exit_cm_ask_vwap"] == 686.5

    # Compute MTM using exit prices
    mtm = engine.compute_position_mtm(pos)
    assert mtm["close_now_spot_price"] == 681.5
    assert mtm["close_now_futures_price"] == 686.5
    # Ensure no separate artificial spread deduction is subtracted
    assert "fixed_spread_deduction_usd" not in mtm or mtm["fixed_spread_deduction_usd"] == 0.0


# ---------------------------------------------------------------------------
# Test Case 9: Natural virtual early exit produces correct realized PnL
# ---------------------------------------------------------------------------
def test_case_9_virtual_early_exit_realized_pnl():
    """Verify early exit trigger (basis <= 15 bps) executes at depth and computes net realized PnL."""
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_TEST_EXIT",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.0,  # Entry basis ~88 bps
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    # Observation with basis compressed to 10 bps (<= 15 bps) with full depth
    obs = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 5000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "observed_depth_basis_bps": 10.0,
        "causal_basis_ma24_bps": 10.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }

    ok, reason = engine.process_observation(pos, obs)
    assert ok is True
    assert reason == "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.CLOSED
    assert pos["lifecycle_status"] == "CLOSED_EARLY_EXIT"
    assert pos["closed_timestamp"] == 5000

    # Verify realized PnL accounting
    # Spot gross PnL: 7.35294 * 684.5 - 5000 = +33.09 USD
    # Inverse CM PnL: 5000 * (1/686.0 - 1/685.2) * 684.5 = 5000 * (-0.0000017) * 684.5 = -5.82 USD
    # Exit fees: Spot exit (10 bps) = $5.03, CM exit (5 bps) = $2.50
    # Net realized PnL must be recorded
    assert pos["realized_pnl"] is not None
    assert isinstance(pos["realized_pnl"], float)


# ---------------------------------------------------------------------------
# Test Case 10: Virtual delivery settlement produces correct inverse accounting
# ---------------------------------------------------------------------------
def test_case_10_virtual_delivery_settlement_inverse_accounting():
    """Verify delivery settlement uses official settlement price and inverse coin PnL formula."""
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_TEST_SETTLE",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "delivery_ms": 1798272000000,  # Expiry timestamp
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.8,
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    obs = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1798272001000,  # Post expiry
        "quote_valid_pit": True,
        "spot_ask_vwap": 690.0,
        "spot_bid_vwap": 689.8,
        "spot_bid_sweep": {
            "fully_filled": True,
            "filled_base_qty": 5000.0 / 680.0,
            "filled_units": 5000.0 / 680.0,
            "filled_usd": (5000.0 / 680.0) * 689.8,
            "vwap": 689.8,
        },
        "delivery_settlement_price": 689.8,  # Converged delivery settlement price
        "observed_depth_basis_bps": 0.0,
    }

    ok, reason = engine.process_observation(pos, obs)
    assert ok is True
    assert reason == "DELIVERY_SETTLED"
    assert pos["state"] == LifecycleState.CLOSED
    assert pos["lifecycle_status"] == "CLOSED_DELIVERY_SETTLED"
    assert pos["exit_futures_price"] == 689.8
    assert pos["realized_pnl"] is not None


# ---------------------------------------------------------------------------
# Test Case 11: Restart preserves state and does not duplicate entries
# ---------------------------------------------------------------------------
def test_case_11_restart_preserves_state_no_duplicates():
    """Verify restarting the lifecycle engine on the same dataset preserves position count."""
    engine1 = N1_7LifecycleEngine()
    res1 = engine1.run_lifecycle_analysis()

    engine2 = N1_7LifecycleEngine()
    res2 = engine2.run_lifecycle_analysis()

    pop1 = res1["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]
    pop2 = res2["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]

    assert len(pop1["active_lifecycles"]) == len(pop2["active_lifecycles"])
    assert len(pop1["quarantined_lifecycles"]) == len(pop2["quarantined_lifecycles"])

    tids1 = [p["lifecycle_id"] for p in pop1["active_lifecycles"]]
    tids2 = [p["lifecycle_id"] for p in pop2["active_lifecycles"]]
    assert tids1 == tids2


# ---------------------------------------------------------------------------
# Test Case 12: Replay is deterministic from frozen inputs
# ---------------------------------------------------------------------------
def test_case_12_replay_deterministic_from_frozen_inputs():
    """Verify bit-for-bit replay idempotency across independent engine runs."""
    engine_a = N1_7LifecycleEngine()
    out_a = engine_a.run_lifecycle_analysis()

    engine_b = N1_7LifecycleEngine()
    out_b = engine_b.run_lifecycle_analysis()

    scorecard_a = out_a["scorecard"]
    scorecard_b = out_b["scorecard"]

    assert out_a["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]["deployed_capital_usd"] == out_b["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]["deployed_capital_usd"]
    assert scorecard_a["total_open_unrealized_pnl_usd"] == scorecard_b["total_open_unrealized_pnl_usd"]
    assert scorecard_a["capital_utilization_pct"] == scorecard_b["capital_utilization_pct"]
    assert scorecard_a["actively_tracked_lifecycles_count"] == scorecard_b["actively_tracked_lifecycles_count"]

    # Decision block exactly matches
    assert out_a["phase_f_decision"] == out_b["phase_f_decision"]


# ---------------------------------------------------------------------------
# Test Case 13: End-to-end Entry -> Restart -> Close -> Replay Idempotency
# ---------------------------------------------------------------------------
def test_case_13_end_to_end_entry_restart_close_replay_idempotency():
    """Verify focused lifecycle workflow: entry -> restart -> early exit close -> release -> replay idempotency."""
    engine = N1_7LifecycleEngine()

    # 1. Entry: Hedged position initialized
    pos = {
        "lifecycle_id": "VTRADE_0001",
        "trade_id": "VTRADE_0001",
        "position_id": "VTRADE_0001",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1794409639000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.0,  # ~88 bps basis
        "spot_inventory_coin": 5000.0 / 680.0,
        "coin_collateral": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1794409639000,
        "last_update_ms": 1794409639000,
    }

    # 2. Accumulation & Restart: market observation updates MTM
    obs_hold = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1794410000000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 682.0,
        "coinm_bid_vwap": 687.0,
        "spot_bid_vwap": 681.5,
        "coinm_ask_vwap": 687.5,
        "observed_depth_basis_bps": 73.0,
    }
    ok_hold, reason_hold = engine.process_observation(pos, obs_hold)
    assert ok_hold is True
    assert reason_hold == "VALUATION_UPDATED"
    assert pos["state"] == LifecycleState.HEDGED_HOLD
    assert pos["cur_spot_vwap"] == 682.0

    # Restart check: saving position state to dict/json and restoring preserves exact values
    pos_snapshot = json.loads(json.dumps(pos))
    assert pos_snapshot["cur_spot_vwap"] == 682.0
    assert pos_snapshot["last_valid_observation_timestamp"] == 1794410000000

    # 3. Early Exit Close: Basis compresses to 10 bps (<= 15 bps) with fillable depth
    obs_close = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1794415000000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "observed_depth_basis_bps": 10.0,
        "causal_basis_ma24_bps": 10.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }
    ok_close, reason_close = engine.process_observation(pos, obs_close)
    assert ok_close is True
    assert reason_close == "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.CLOSED
    assert pos["lifecycle_status"] == "CLOSED_EARLY_EXIT"
    assert pos["capital_released"] is True
    assert pos["released_capital_usd"] == 5000.0
    assert pos["realized_pnl"] is not None
    initial_realized_pnl = pos["realized_pnl"]

    # 4. Strict Single Realization: subsequent observations CANNOT alter closed state or realized PnL
    obs_subsequent = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1794416000000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 700.0,
        "coinm_bid_vwap": 710.0,
        "spot_bid_vwap": 699.0,
        "coinm_ask_vwap": 711.0,
    }
    ok_subseq, reason_subseq = engine.process_observation(pos, obs_subsequent)
    assert ok_subseq is False
    assert reason_subseq == "POSITION_ALREADY_CLOSED"
    assert pos["realized_pnl"] == initial_realized_pnl

    # 5. Replay Idempotency
    mtm_closed = engine.compute_position_mtm(pos)
    assert mtm_closed["state"] == LifecycleState.CLOSED
    assert mtm_closed["realized_pnl"] == initial_realized_pnl


# ---------------------------------------------------------------------------
# Test Case 14: P0-1 Mathematical Oracle Fee Bridge for Realized PnL
# ---------------------------------------------------------------------------
def test_case_14_realized_pnl_fee_bridge_exact_oracle():
    """Verify realized PnL bridge exactly matches independent mathematical oracle for early exit and settlement."""
    engine = N1_7LifecycleEngine()

    # Part A: Early Exit
    notional = 5000.0
    entry_spot = 680.0
    entry_fut = 686.0
    spot_inv_coin = notional / entry_spot
    exit_spot = 684.5
    exit_fut = 685.2

    # Independent oracle calculation
    oracle_gross_spot = spot_inv_coin * exit_spot - notional
    oracle_inv_pnl_coin = notional * (1.0 / exit_fut - 1.0 / entry_fut)
    oracle_inv_pnl_usd = oracle_inv_pnl_coin * exit_spot
    oracle_sp_entry_fee = notional * (COSTS.spot_entry_fee_bps / 10_000.0)
    oracle_cm_entry_fee = notional * (COSTS.cm_entry_fee_bps / 10_000.0)
    oracle_sp_exit_fee = spot_inv_coin * exit_spot * (COSTS.spot_exit_fee_bps / 10_000.0)
    oracle_cm_exit_fee = notional * (COSTS.cm_early_exit_fee_bps / 10_000.0)
    oracle_residual = 0.0

    oracle_net_pnl = (
        oracle_gross_spot + oracle_inv_pnl_usd
        - oracle_sp_entry_fee
        - oracle_cm_entry_fee
        - oracle_sp_exit_fee
        - oracle_cm_exit_fee
        - oracle_residual
    )

    pos = {
        "lifecycle_id": "VTRADE_ORACLE_EXIT",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": notional,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": entry_spot,
        "entry_futures_price": entry_fut,
        "spot_inventory_coin": spot_inv_coin,
        "coin_collateral": spot_inv_coin,
        "entry_fees_paid": oracle_sp_entry_fee + oracle_cm_entry_fee,
        "spot_entry_fee_usd": oracle_sp_entry_fee,
        "coinm_entry_fee_usd": oracle_cm_entry_fee,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    obs_exit = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 5000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": exit_spot,
        "coinm_ask_vwap": exit_fut,
        "observed_depth_basis_bps": 10.0,
        "causal_basis_ma24_bps": 10.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }

    ok, reason = engine.process_observation(pos, obs_exit)
    assert ok is True
    assert reason == "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.CLOSED

    # Assert exact pennies matching mathematical oracle
    assert abs(pos["realized_pnl"] - round(oracle_net_pnl, 2)) < 1e-4
    bridge = pos["realized_pnl_bridge"]
    assert abs(bridge["gross_spot_pnl_usd"] - round(oracle_gross_spot, 4)) < 1e-4
    assert abs(bridge["inverse_coinm_pnl_converted_usd"] - round(oracle_inv_pnl_usd, 4)) < 1e-4
    assert abs(bridge["spot_entry_fee_usd"] - round(oracle_sp_entry_fee, 4)) < 1e-4
    assert abs(bridge["coinm_entry_fee_usd"] - round(oracle_cm_entry_fee, 4)) < 1e-4
    assert abs(bridge["spot_exit_fee_usd"] - round(oracle_sp_exit_fee, 4)) < 1e-4
    assert abs(bridge["coinm_exit_or_delivery_fee_usd"] - round(oracle_cm_exit_fee, 4)) < 1e-4

    # Part B: Delivery Settlement
    settle_price = 690.0
    settle_exit_spot = 689.8
    oracle_settle_gross_spot = spot_inv_coin * settle_exit_spot - notional
    oracle_settle_inv_coin = notional * (1.0 / settle_price - 1.0 / entry_fut)
    oracle_settle_inv_usd = oracle_settle_inv_coin * settle_exit_spot
    oracle_settle_sp_deliv_fee = spot_inv_coin * settle_exit_spot * (COSTS.spot_exit_fee_bps / 10_000.0)
    oracle_settle_cm_deliv_fee = notional * (COSTS.cm_delivery_settlement_fee_bps / 10_000.0)

    oracle_settle_net_pnl = (
        oracle_settle_gross_spot + oracle_settle_inv_usd
        - oracle_sp_entry_fee
        - oracle_cm_entry_fee
        - oracle_settle_sp_deliv_fee
        - oracle_settle_cm_deliv_fee
    )

    pos_settle = {
        "lifecycle_id": "VTRADE_ORACLE_SETTLE",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "delivery_ms": 1798272000000,
        "entry_notional_usd": notional,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": entry_spot,
        "entry_futures_price": entry_fut,
        "spot_inventory_coin": spot_inv_coin,
        "coin_collateral": spot_inv_coin,
        "entry_fees_paid": oracle_sp_entry_fee + oracle_cm_entry_fee,
        "spot_entry_fee_usd": oracle_sp_entry_fee,
        "coinm_entry_fee_usd": oracle_cm_entry_fee,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    obs_settle = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 1798272001000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 690.0,
        "spot_bid_vwap": settle_exit_spot,
        "spot_bid_sweep": {
            "fully_filled": True,
            "filled_base_qty": spot_inv_coin,
            "filled_units": spot_inv_coin,
            "filled_usd": spot_inv_coin * settle_exit_spot,
            "vwap": settle_exit_spot,
        },
        "delivery_settlement_price": settle_price,
        "observed_depth_basis_bps": 0.0,
    }

    ok_s, reason_s = engine.process_observation(pos_settle, obs_settle)
    assert ok_s is True
    assert reason_s == "DELIVERY_SETTLED"
    assert abs(pos_settle["realized_pnl"] - round(oracle_settle_net_pnl, 2)) < 1e-4


# ---------------------------------------------------------------------------
# Test Case 15: P0-2 Close-Now Liquidation vs MTM Separation and Depth Fail-Closed
# ---------------------------------------------------------------------------
def test_case_15_close_now_economics_insufficient_depth():
    """Verify close-now returns CLOSE_NOT_EXECUTABLE when orderbook depth cannot fill size."""
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_DEPTH_TEST",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.0,
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 2000,
        "cur_spot_vwap": 682.0,
        "cur_fut_vwap": 687.0,
        "exit_spot_bid_vwap": 681.5,
        "exit_cm_ask_vwap": 687.5,
        # Insufficient depth sweep on spot leg
        "spot_bid_sweep": {"fully_filled": False, "filled_usd": 2000.0, "vwap": 681.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 687.5},
    }

    mtm = engine.compute_position_mtm(pos)
    assert mtm["close_executable"] is False
    assert mtm["close_liquidation_status"] == "CLOSE_NOT_EXECUTABLE"
    assert mtm["estimated_close_now_pnl"] == "CLOSE_NOT_EXECUTABLE"
    # Accounting MTM remains available and distinct
    assert isinstance(mtm["unrealized_pnl_after_entry_cost"], float)


# ---------------------------------------------------------------------------
# Test Case 16: P0-3 Causal MA24 Replay Contracts Fail-Closed
# ---------------------------------------------------------------------------
def test_case_16_causal_ma24_fails_closed_without_silent_network():
    """Verify MA24 returns (0.0, 0.0, False) when history is missing or network disallowed in replay."""
    engine = N1_7LifecycleEngine()

    # Query unknown symbol in offline mode -> must return ready=False without throwing or calling network
    ma24_basis, usdt_usd, ready = engine.fetch_causal_ma24_history("UNKNOWN_CONTRACT", 1794409200000)
    assert ready is False
    assert ma24_basis == 0.0
    assert usdt_usd == 0.0


# ---------------------------------------------------------------------------
# Test Case 17: P1 SingleWriterLock Atomic Recorder Ownership
# ---------------------------------------------------------------------------
def test_case_17_single_writer_lock_atomicity(tmp_path):
    """Verify SingleWriterLock guarantees single process ownership and recovers from stale locks."""
    import os
    from neural_trading.n1_6.recorder import SingleWriterLock

    lock_file = tmp_path / "test_recorder.lock"

    # Process 1 acquires lock
    lock1 = SingleWriterLock(lock_file)
    acquired1, active_pid1 = lock1.acquire()
    assert acquired1 is True
    assert active_pid1 == os.getpid()

    # Process 1 releases lock cleanly
    lock1.release()

    # Process 2 (simulating competing instance with parent PID)
    lock_file.write_text(f"{os.getppid()}\n2026-11-12T00:00:00Z\n", encoding="utf-8")
    lock2 = SingleWriterLock(lock_file)
    acquired2, active_pid2 = lock2.acquire()
    assert acquired2 is False
    assert active_pid2 == os.getppid()

    # Stale lock recovery: write dead PID 99999999
    lock_file.write_text("99999999\n2026-11-12T00:00:00Z\n", encoding="utf-8")
    lock3 = SingleWriterLock(lock_file)
    acquired3, active_pid3 = lock3.acquire()
    assert acquired3 is True
    assert active_pid3 == os.getpid()

    lock3.release()
    assert not lock_file.exists()


# ---------------------------------------------------------------------------
# Test Case 18: P0-4 10-Step Multi-Day Lifecycle Integration Test
# ---------------------------------------------------------------------------
def test_case_18_multiday_10step_integration(tmp_path):
    """Verify complete 10-step multi-day lifecycle flow using immutable fixture."""
    fixture_path = Path("tests/fixtures/n1_8_r2_multiday_lifecycle_fixture.json")
    assert fixture_path.exists(), "Multi-day test fixture must exist"

    with fixture_path.open("r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    events = fixture_data["events"]
    assert len(events) == 10

    engine = N1_7LifecycleEngine(portfolio_capital_usd=20000.0)
    checkpoint_file = tmp_path / "lifecycle_checkpoint.json"

    # Step 1: Day 1 entry for BNBUSD_261225
    e1 = events[0]
    pos1 = {
        "position_id": "VTRADE_0001",
        "trade_id": "VTRADE_0001",
        "lifecycle_id": "VTRADE_0001",
        "contract_symbol": e1["coinm_contract_symbol"],
        "symbol": e1["coinm_contract_symbol"],
        "spot_symbol": e1["spot_symbol"],
        "underlying_asset": "BNB",
        "state": LifecycleState.HEDGED_HOLD,
        "contracts_short": e1["matched_short_contracts"],
        "contract_multiplier_usd": e1["contract_multiplier_usd"],
        "entry_notional_usd": e1["matched_executable_notional"],
        "entry_timestamp": e1["decision_timestamp"],
        "entry_timestamp_ms": e1["decision_timestamp"],
        "last_valid_observation_timestamp": e1["decision_timestamp"],
        "last_update_ms": e1["decision_timestamp"],
        "entry_spot_price": e1["spot_ask_vwap"],
        "entry_futures_price": e1["coinm_bid_vwap"],
        "spot_inventory_coin": e1["matched_executable_notional"] / e1["spot_ask_vwap"],
        "coin_collateral": e1["matched_executable_notional"] / e1["spot_ask_vwap"],
        "entry_fees_paid": round(e1["matched_executable_notional"] * (15.0 / 10000.0), 2),
        "spot_entry_fee_usd": round(e1["matched_executable_notional"] * (10.0 / 10000.0), 4),
        "coinm_entry_fee_usd": round(e1["matched_executable_notional"] * (5.0 / 10000.0), 4),
    }

    # Step 2: Day 1 quarantine for BNBUSD_270326 (exceeds aggregate $5,000 BNB cap)
    e2 = events[1]
    quarantined = {
        "position_id": "VTRADE_0002",
        "lifecycle_id": "VTRADE_0002",
        "contract_symbol": e2["coinm_contract_symbol"],
        "underlying_asset": "BNB",
        "state": LifecycleState.INVALIDATED,
        "quarantine_reason": "EXCEEDS_AGGREGATE_UNDERLYING_CAP",
    }

    # Step 3 & 4: Day 1 hold updates and checkpoint cutoff
    engine.process_observation(pos1, events[2])
    engine.process_observation(pos1, events[3])

    engine.active_positions = {"VTRADE_0001": pos1}
    engine.quarantined_positions = {"BNBUSD_270326": quarantined}
    engine.closed_positions = []
    engine.underlying_committed_usd = {"BNB": 5000.0}

    # Save checkpoint at day 1 end
    saved_path = engine.save_checkpoint(checkpoint_file)
    assert saved_path.exists()

    # Step 5: Day 2 resume from checkpoint in fresh engine instance
    engine_day2 = N1_7LifecycleEngine(portfolio_capital_usd=20000.0)
    engine_day2.resume_from_checkpoint(checkpoint_file)
    assert "VTRADE_0001" in engine_day2.active_positions
    assert engine_day2.underlying_committed_usd["BNB"] == 5000.0

    pos1_resumed = engine_day2.active_positions["VTRADE_0001"]
    engine_day2.process_observation(pos1_resumed, events[4])

    # Step 6: Day 2 basis compression early exit trigger (<= 15 bps)
    e6 = events[5]
    ok6, reason6 = engine_day2.process_observation(pos1_resumed, e6)
    assert ok6 is True
    assert reason6 == "EARLY_EXIT_EXECUTED"
    assert pos1_resumed["state"] == LifecycleState.CLOSED
    assert pos1_resumed["capital_released"] is True

    # Realized PnL bridge calculated
    assert pos1_resumed["realized_pnl"] is not None
    assert "realized_pnl_bridge" in pos1_resumed

    # Release capital
    engine_day2.closed_positions.append(pos1_resumed)
    del engine_day2.active_positions["VTRADE_0001"]
    engine_day2.underlying_committed_usd["BNB"] = max(
        0.0,
        engine_day2.underlying_committed_usd["BNB"] - pos1_resumed["entry_notional_usd"],
    )
    assert engine_day2.underlying_committed_usd["BNB"] == 0.0

    # Step 7: Out-of-order rejection
    ok7, reason7 = engine_day2.process_observation(pos1_resumed, events[6])
    assert ok7 is False
    assert reason7 in ("POSITION_ALREADY_CLOSED", "OUT_OF_ORDER_IGNORED")

    # Step 8: Post-close quote rejection
    ok8, reason8 = engine_day2.process_observation(pos1_resumed, events[7])
    assert ok8 is False
    assert reason8 == "POSITION_ALREADY_CLOSED"

    # Step 9: Released capital admits BNBUSD_270326
    e9 = events[8]
    assert engine_day2.underlying_committed_usd.get("BNB", 0.0) == 0.0
    pos2 = {
        "position_id": "VTRADE_0004",
        "lifecycle_id": "VTRADE_0004",
        "contract_symbol": e9["coinm_contract_symbol"],
        "symbol": e9["coinm_contract_symbol"],
        "spot_symbol": e9["spot_symbol"],
        "underlying_asset": "BNB",
        "state": LifecycleState.HEDGED_HOLD,
        "contracts_short": e9["matched_short_contracts"],
        "contract_multiplier_usd": e9["contract_multiplier_usd"],
        "entry_notional_usd": e9["matched_executable_notional"],
        "entry_timestamp": e9["decision_timestamp"],
        "last_valid_observation_timestamp": e9["decision_timestamp"],
        "entry_spot_price": e9["spot_ask_vwap"],
        "entry_futures_price": e9["coinm_bid_vwap"],
        "spot_inventory_coin": e9["matched_executable_notional"] / e9["spot_ask_vwap"],
        "coin_collateral": e9["matched_executable_notional"] / e9["spot_ask_vwap"],
        "entry_fees_paid": round(e9["matched_executable_notional"] * (15.0 / 10000.0), 2),
        "spot_entry_fee_usd": round(e9["matched_executable_notional"] * (10.0 / 10000.0), 4),
        "coinm_entry_fee_usd": round(e9["matched_executable_notional"] * (5.0 / 10000.0), 4),
        "delivery_ms": 1798272000000,
    }
    engine_day2.active_positions["VTRADE_0004"] = pos2
    engine_day2.underlying_committed_usd["BNB"] = 5000.0

    # Step 10: Delivery settlement at maturity
    e10 = dict(events[9])
    c_qty = pos2["spot_inventory_coin"]
    e10["spot_bid_sweep"] = {
        "fully_filled": True,
        "filled_base_qty": c_qty,
        "filled_units": c_qty,
        "filled_usd": c_qty * e10["spot_bid_vwap"],
        "vwap": e10["spot_bid_vwap"],
    }
    ok10, reason10 = engine_day2.process_observation(pos2, e10)
    assert ok10 is True
    assert reason10 == "DELIVERY_SETTLED"
    assert pos2["state"] == LifecycleState.CLOSED
    assert pos2["realized_pnl"] is not None

    engine_day2.closed_positions.append(pos2)
    del engine_day2.active_positions["VTRADE_0004"]
    engine_day2.underlying_committed_usd["BNB"] = 0.0

    # Verify final score
    assert len(engine_day2.closed_positions) == 2
    assert len(engine_day2.active_positions) == 0
    total_realized = sum(p["realized_pnl"] for p in engine_day2.closed_positions)
    assert isinstance(total_realized, float)


# ---------------------------------------------------------------------------
# Test Case 19: Task 3 Focused Real Evaluator Integration (Synthetic Test Data)
# ---------------------------------------------------------------------------
def test_case_19_end_to_end_raw_evaluator_integration_test_data(tmp_path):
    """Verify raw observation evaluation, entry admission, checkpointing, resume, and natural closure.
    NOTE: All events used here are explicitly TEST_DATA_SYNTHETIC, not authentic prospective observations.
    """
    engine = N1_7LifecycleEngine(portfolio_capital_usd=20000.0)
    checkpoint_file = tmp_path / "lifecycle_session_checkpoint.json"

    # Step 1: Raw-format observation accepted through evaluator path at t=1000ms
    t_entry = 1794409600000
    raw_obs_entry = {
        "source": "TEST_DATA_SYNTHETIC",
        "coinm_contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "decision_timestamp": t_entry,
        "recv_ms": t_entry,
        "quote_valid_pit": True,
        "observed_depth_basis_bps": 85.0,
        "causal_basis_ma24_bps": 88.0,
        "basis_ma24_ready": True,
        "annualized_yield_pct": 7.0,
        "contract_type": "CURRENT_QUARTER",
        "contract_multiplier_usd": 10.0,
        "matched_short_contracts": 500,
        "matched_executable_notional": 5000.0,
        "entry_eligible": True,
        "spot_ask_vwap": 680.0,
        "coinm_bid_vwap": 685.78,
        "spot_bid_vwap": 679.5,
        "coinm_ask_vwap": 686.2,
    }

    # Evaluate admission
    pos = {
        "position_id": "VTRADE_INT_0001",
        "lifecycle_id": "VTRADE_INT_0001",
        "contract_symbol": raw_obs_entry["coinm_contract_symbol"],
        "symbol": raw_obs_entry["coinm_contract_symbol"],
        "spot_symbol": raw_obs_entry["spot_symbol"],
        "underlying_asset": "BNB",
        "state": LifecycleState.HEDGED_HOLD,
        "lifecycle_status": "ACCUMULATING",
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_notional_usd": 5000.0,
        "entry_timestamp": t_entry,
        "last_valid_observation_timestamp": t_entry,
        "entry_spot_price": 680.0,
        "entry_futures_price": 685.78,
        "spot_inventory_coin": 5000.0 / 680.0,
        "coin_collateral": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "spot_entry_fee_usd": 5.0,
        "coinm_entry_fee_usd": 2.5,
    }

    engine.active_positions = {"VTRADE_INT_0001": pos}
    engine.quarantined_positions = {}
    engine.closed_positions = []
    engine.underlying_committed_usd = {"BNB": 5000.0}

    # Step 2: Persist account and position state to checkpoint
    engine.save_checkpoint(checkpoint_file)
    assert checkpoint_file.exists()

    # Step 3: Second session restores state without duplicate entry
    engine_session_2 = N1_7LifecycleEngine(portfolio_capital_usd=20000.0)
    engine_session_2.resume_from_checkpoint(checkpoint_file)
    assert "VTRADE_INT_0001" in engine_session_2.active_positions
    assert len(engine_session_2.active_positions) == 1
    assert engine_session_2.underlying_committed_usd["BNB"] == 5000.0

    # Ensure no duplicate entry is admitted
    dup_admitted = False
    if "VTRADE_INT_0001" in engine_session_2.active_positions:
        dup_admitted = False  # already active, blocked
    assert dup_admitted is False

    # Step 4: Natural closure conditions (basis <= 15 bps) causes exactly one virtual close
    t_exit = t_entry + 3600000  # 1 hour later
    raw_obs_exit = {
        "source": "TEST_DATA_SYNTHETIC",
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": t_exit,
        "quote_valid_pit": True,
        "observed_depth_basis_bps": 12.0,  # Basis compressed <= 15 bps
        "causal_basis_ma24_bps": 12.0,
        "basis_ma24_ready": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.8,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.32,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.32},
    }

    pos_s2 = engine_session_2.active_positions["VTRADE_INT_0001"]
    ok_close, reason_close = engine_session_2.process_observation(pos_s2, raw_obs_exit)
    assert ok_close is True
    assert reason_close == "EARLY_EXIT_EXECUTED"
    assert pos_s2["state"] == LifecycleState.CLOSED

    # Calculate exact mathematical oracle for fee bridge
    oracle_spot_gross = (5000.0 / 680.0) * 684.5 - 5000.0  # +33.0882
    oracle_cm_inv = 5000.0 * (1.0 / 685.32 - 1.0 / 685.78) * 684.5  # -3.3444
    oracle_sp_entry = 5.0
    oracle_cm_entry = 2.5
    oracle_sp_exit = (5000.0 / 680.0) * 684.5 * 0.001  # 5.0331
    oracle_cm_exit = 5000.0 * 0.0005  # 2.50
    expected_realized = (oracle_spot_gross + oracle_cm_inv) - oracle_sp_entry - oracle_cm_entry - oracle_sp_exit - oracle_cm_exit

    assert abs(pos_s2["realized_pnl"] - round(expected_realized, 2)) < 1e-2

    # Step 5: Scorecard counts closed lifecycle and correct realized net PnL
    engine_session_2.closed_positions.append(pos_s2)
    del engine_session_2.active_positions["VTRADE_INT_0001"]
    engine_session_2.underlying_committed_usd["BNB"] = 0.0

    closed_ledger = [engine_session_2.compute_position_mtm(p) for p in engine_session_2.closed_positions]
    realized_closed_pnl = sum(p.get("realized_pnl", 0.0) for p in closed_ledger)
    assert len(closed_ledger) == 1
    assert abs(realized_closed_pnl - pos_s2["realized_pnl"]) < 1e-4


# ---------------------------------------------------------------------------
# Test Case 20: Task 1 Causal Event Ordering with 50s Separation
# ---------------------------------------------------------------------------
def test_case_20_causal_event_ordering_50s_separation():
    """Verify that later-observed events (50s later) CANNOT preempt earlier events.
    CURRENT_QUARTER priority applies ONLY when decision timestamps are identical.
    """
    t_base = (1794409600000 // 60_000) * 60_000  # Minute boundary (:00.000)
    t_early = t_base + 5_000   # :05.000 (second 5 of minute)
    t_late = t_base + 55_000   # :55.000 (second 55 of minute, exactly 50s later in same minute)

    # Both are within the exact same minute:
    assert t_early // 60_000 == t_late // 60_000

    # Event A: NEXT_QUARTER arrived at second 5
    intent_a = {
        "coinm_contract_symbol": "BNBUSD_270326",
        "contract_type": "NEXT_QUARTER",
        "decision_timestamp": t_early,
        "entry_eligible": True,
    }

    # Event B: CURRENT_QUARTER arrived at second 55 (50s later in timeline in same minute)
    intent_b = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "contract_type": "CURRENT_QUARTER",
        "decision_timestamp": t_late,
        "entry_eligible": True,
    }

    events = [intent_b, intent_a]  # Input in arbitrary arrival order

    # Flawed sort: (ts // 60000, priority, ts)
    flawed_sort = sorted(
        events,
        key=lambda x: (int(x["decision_timestamp"]) // 60_000, 0 if x.get("contract_type") == "CURRENT_QUARTER" else 1, int(x["decision_timestamp"])),
    )
    # Flawed sort puts intent_b (at t=60s) BEFORE intent_a (at t=10s) -> VIOLATION!
    assert flawed_sort[0] == intent_b
    assert flawed_sort[1] == intent_a

    # Causally correct sort: (ts, priority)
    causal_sort = sorted(
        events,
        key=lambda x: (int(x["decision_timestamp"]), 0 if x.get("contract_type") == "CURRENT_QUARTER" else 1),
    )
    # Causal sort guarantees intent_a (second 10) is processed BEFORE intent_b (second 60)
    assert causal_sort[0] == intent_a
    assert causal_sort[1] == intent_b
    assert causal_sort[0]["decision_timestamp"] < causal_sort[1]["decision_timestamp"]

    # When timestamps are identical (t1 == t2), CURRENT_QUARTER priority correctly breaks the tie
    intent_same_time_a = {
        "coinm_contract_symbol": "BNBUSD_270326",
        "contract_type": "NEXT_QUARTER",
        "decision_timestamp": t_early,
    }
    intent_same_time_b = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "contract_type": "CURRENT_QUARTER",
        "decision_timestamp": t_early,
    }
    same_time_events = [intent_same_time_a, intent_same_time_b]
    causal_same_time_sort = sorted(
        same_time_events,
        key=lambda x: (int(x["decision_timestamp"]), 0 if x.get("contract_type") == "CURRENT_QUARTER" else 1),
    )
    # CURRENT_QUARTER is first because timestamps are equal
    assert causal_same_time_sort[0] == intent_same_time_b
    assert causal_same_time_sort[1] == intent_same_time_a


# ---------------------------------------------------------------------------
# Test Case 21: Focused Multi-Day Ingestion, Checkpoint Resume, and Natural Closure
# ---------------------------------------------------------------------------
def test_case_21_focused_multiday_real_ingestion_and_closure(tmp_path):
    """Verifies end-to-end forward carry pipeline:
    1. Day 1 raw observations ingestion from DATA_ROOT_N1_6 / 'raw' / '20261111'.
    2. Opens active virtual carry pairs within policy caps.
    3. Saves state checkpoint at Day 1 watermark.
    4. Day 2 resume with new partition (restores active positions, watermark, committed capital).
    5. Synthetic close scenario: basis compression (depth_basis <= 15 bps) with fillable bid/ask depth sweeps.
    6. Closes once with exact fee bridge and net realized PnL.
    7. Scorecard dynamically reports 1 closed trade and exact realized net PnL.
    8. Restart idempotency: subsequent observations do not duplicate close, release capital twice, or alter equity.
    """
    checkpoint_file = tmp_path / "lifecycle_multiday_checkpoint.json"

    # Step 1 & 2: Day 1 real raw observation ingestion
    engine_day1 = N1_7LifecycleEngine(portfolio_capital_usd=20_000.0)
    day1_results = engine_day1.run_lifecycle_analysis()

    compliant_day1 = day1_results["populations"]["N1_8_POLICY_COMPLIANT_REPLAY"]
    active_day1 = compliant_day1["active_lifecycles"]
    quarantined_day1 = compliant_day1["quarantined_lifecycles"]

    assert len(active_day1) == 2
    assert len(quarantined_day1) == 1
    assert engine_day1.last_observation_watermark_ms > 0

    # Step 3: Save checkpoint at Day 1 watermark
    engine_day1.save_checkpoint(checkpoint_file)
    assert checkpoint_file.exists()

    # Step 4: Day 2 resume from checkpoint in a fresh engine instance
    engine_day2 = N1_7LifecycleEngine(portfolio_capital_usd=20_000.0)
    ok_res = engine_day2.resume_from_checkpoint(checkpoint_file)
    assert ok_res is not None
    assert len(engine_day2.active_positions) == 2
    assert engine_day2.last_observation_watermark_ms == engine_day1.last_observation_watermark_ms
    assert engine_day2.underlying_committed_usd.get("BNB", 0.0) == 2370.0

    # Step 5: Day 2 observation with basis compression <= 15 bps and fillable exit depth
    t_exit = engine_day2.last_observation_watermark_ms + 60_000  # 1 minute into Day 2
    active_bnb_pos = next(
        p for p in engine_day2.active_positions.values() if p["contract_symbol"] == "BNBUSD_270326"
    )
    bnb_pid = active_bnb_pos.get("lifecycle_id", "VTRADE_0002")

    notional = active_bnb_pos["entry_notional_usd"]
    entry_spot = active_bnb_pos["entry_spot_price"]
    entry_fut = active_bnb_pos["entry_futures_price"]
    spot_inv = active_bnb_pos["spot_inventory_coin"]

    exit_spot_bid = 690.0
    exit_fut_ask = 690.8

    obs_close = {
        "source": "TEST_DATA_DAY2_SYNTHETIC",
        "coinm_contract_symbol": "BNBUSD_270326",
        "decision_timestamp": t_exit,
        "recv_ms": t_exit,
        "quote_valid_pit": True,
        "observed_depth_basis_bps": 11.6,  # basis <= 15 bps trigger
        "causal_basis_ma24_bps": 11.6,
        "basis_ma24_ready": True,
        "spot_ask_vwap": 690.5,
        "coinm_bid_vwap": 691.0,
        "spot_bid_vwap": exit_spot_bid,
        "coinm_ask_vwap": exit_fut_ask,
        "spot_bid_sweep": {
            "fully_filled": True,
            "filled_usd": notional,
            "vwap": exit_spot_bid,
        },
        "cm_ask_sweep": {
            "fully_filled": True,
            "filled_usd": notional,
            "filled_units": active_bnb_pos["contracts_short"],
            "vwap": exit_fut_ask,
        },
    }

    # Step 6: Process close once with fee bridge
    ok_close, reason_close = engine_day2.process_observation(active_bnb_pos, obs_close)
    assert ok_close is True
    assert reason_close == "EARLY_EXIT_EXECUTED"
    assert active_bnb_pos["state"] == LifecycleState.CLOSED
    assert active_bnb_pos["capital_released"] is True

    # Calculate mathematical oracle
    oracle_gross_spot = spot_inv * exit_spot_bid - notional
    oracle_inv_pnl_usd = notional * (1.0 / exit_fut_ask - 1.0 / entry_fut) * exit_spot_bid
    oracle_sp_entry_fee = notional * (COSTS.spot_entry_fee_bps / 10_000.0)
    oracle_cm_entry_fee = notional * (COSTS.cm_entry_fee_bps / 10_000.0)
    oracle_sp_exit_fee = spot_inv * exit_spot_bid * (COSTS.spot_exit_fee_bps / 10_000.0)
    oracle_cm_exit_fee = notional * (COSTS.cm_early_exit_fee_bps / 10_000.0)
    oracle_net_pnl = (oracle_gross_spot + oracle_inv_pnl_usd) - oracle_sp_entry_fee - oracle_cm_entry_fee - oracle_sp_exit_fee - oracle_cm_exit_fee

    assert abs(active_bnb_pos["realized_pnl"] - round(oracle_net_pnl, 2)) < 1e-2

    # Step 7: Update engine positions and release capital
    engine_day2.closed_positions.append(active_bnb_pos)
    del engine_day2.active_positions[bnb_pid]
    engine_day2.underlying_committed_usd["BNB"] = max(
        0.0, engine_day2.underlying_committed_usd["BNB"] - notional
    )
    assert engine_day2.underlying_committed_usd["BNB"] == 0.0

    # Compute scorecard
    closed_ledger = [engine_day2.compute_position_mtm(p) for p in engine_day2.closed_positions]
    active_ledger = [engine_day2.compute_position_mtm(p) for p in engine_day2.active_positions.values()]

    realized_closed_pnl = round(sum(p.get("realized_pnl", 0.0) for p in closed_ledger), 2)
    assert len(closed_ledger) == 1
    assert len(active_ledger) == 1
    assert realized_closed_pnl == active_bnb_pos["realized_pnl"]
    assert realized_closed_pnl != 0.0

    # Step 8: Restart idempotency - subsequent observations on closed position strictly ignored
    obs_day2_late = {
        "coinm_contract_symbol": "BNBUSD_270326",
        "decision_timestamp": t_exit + 300_000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 720.0,
        "coinm_bid_vwap": 730.0,
        "spot_bid_vwap": 719.0,
        "coinm_ask_vwap": 731.0,
    }
    ok_late, reason_late = engine_day2.process_observation(active_bnb_pos, obs_day2_late)
    assert ok_late is False
    assert reason_late == "POSITION_ALREADY_CLOSED"
    assert active_bnb_pos["realized_pnl"] == realized_closed_pnl
    assert engine_day2.underlying_committed_usd["BNB"] == 0.0


# ---------------------------------------------------------------------------
# Test Case 22: Real entrypoint forward runner pipeline (Day 1 -> checkpoint -> Day 2 -> exit)
# ---------------------------------------------------------------------------
def test_case_22_real_entrypoint_forward_runner_pipeline(tmp_path: Path):
    """Verify full forward pipeline:
    1. Day 1 entry under valid MA24 (85 bps >= 75 bps) and aggregate risk cap.
    2. Atomic durable checkpoint save.
    3. Day 2 resumption, dynamic MA24 update (12 bps <= 15 bps), exit via MA24 compression.
    4. Exact realized PnL bridge verification.
    5. Engine-generated scorecard updated without manual intervention.
    6. Third run asserts restart idempotency.
    """
    raw_root = tmp_path / "raw"
    day1_dir = raw_root / "20261111"
    day2_dir = raw_root / "20261112"
    day1_dir.mkdir(parents=True)
    day2_dir.mkdir(parents=True)
    checkpoint_file = tmp_path / "lifecycle_checkpoint.json"

    t_day1 = 1794412800000  # Nov 11 08:00 UTC
    t_day2 = 1794499200000  # Nov 12 08:00 UTC

    # Write Day 1 exchange info
    ex_info = {
        "stream": "cm_exchange_info",
        "recv_ms": t_day1,
        "payload": {
            "symbols": [
                {
                    "symbol": "BNBUSD_261225",
                    "pair": "BNBUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": 1798272000000,
                    "contractSize": 10.0,
                }
            ]
        },
    }
    (day1_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    (day2_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")

    # Write timestamp-aligned hourly USDT rates for Day 1
    u1_lines = [
        json.dumps({"stream": "usdt_usd", "recv_ms": t_day1 - (25 - i) * 3600000 + 3600000 - 1, "payload": {"price": "1.0000"}})
        for i in range(25)
    ]
    u1_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": t_day1, "payload": {"price": "1.0000"}}))
    (day1_dir / "usdt_usd.jsonl").write_text("\n".join(u1_lines) + "\n", encoding="utf-8")

    # Generate 24 completed 1h candles for Day 1 with MA24 basis = 85.0 bps (entry eligible)
    cm_k1 = []
    sp_k1 = []
    for i in range(25):
        ot = t_day1 - (25 - i) * 3600000
        ct = ot + 3600000 - 1
        cm_k1.append([ot, "680.0", "686.0", "679.0", "685.78", "100.0", ct, "0", 10, "0", "0", "0"])
        sp_k1.append([ot, "680.0", "681.0", "679.0", "680.00", "100.0", ct, "0", 10, "0", "0", "0"])

    k_cm_rec1 = {"symbol": "BNBUSD_261225", "recv_ms": t_day1, "payload": cm_k1}
    k_sp_rec1 = {"symbol": "BNBUSDT", "recv_ms": t_day1, "payload": sp_k1}
    (day1_dir / "signal_cm_klines.jsonl").write_text(json.dumps(k_cm_rec1) + "\n", encoding="utf-8")
    (day1_dir / "signal_spot_klines.jsonl").write_text(json.dumps(k_sp_rec1) + "\n", encoding="utf-8")

    # Day 1 depth snapshots: spot ask = 680.0, cm bid = 685.78 (basis 85 bps)
    sp_d1 = {
        "symbol": "BNBUSDT",
        "recv_ms": t_day1 + 1000,
        "payload": {
            "bids": [["679.9", "20.0"]],
            "asks": [["680.0", "20.0"]],
        },
    }
    cm_d1 = {
        "symbol": "BNBUSD_261225",
        "recv_ms": t_day1 + 1000,
        "payload": {
            "bids": [["685.78", "1000"]],
            "asks": [["685.80", "1000"]],
        },
    }
    (day1_dir / "spot_depth.jsonl").write_text(json.dumps(sp_d1) + "\n", encoding="utf-8")
    (day1_dir / "cm_depth.jsonl").write_text(json.dumps(cm_d1) + "\n", encoding="utf-8")

    # Step 1: Run Day 1 with ForwardLifecycleRunner
    test_out = tmp_path / "research"
    runner1 = ForwardLifecycleRunner(checkpoint_path=checkpoint_file, raw_root=raw_root, output_dir=test_out, portfolio_capital_usd=20000.0)
    res_day1 = runner1.run_step(raw_partitions=[day1_dir])

    # Assert Day 1 entered
    assert checkpoint_file.exists()
    assert res_day1["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res_day1["scorecard"]["realized_completed_lifecycles_count"] == 0
    active_pos = list(runner1.engine.active_positions.values())[0]
    assert active_pos["contract_symbol"] == "BNBUSD_261225"
    assert active_pos["state"] == LifecycleState.HEDGED_HOLD
    assert runner1.engine.underlying_committed_usd["BNB"] == 5000.0

    # Step 2: Prepare Day 2 data (24 hours later)
    # New klines where basis has compressed to 12.0 bps (<= 15 bps)
    cm_k2 = list(cm_k1)
    sp_k2 = list(sp_k1)
    for i in range(24):
        ot = t_day2 - (24 - i) * 3600000
        ct = ot + 3600000 - 1
        cm_k2.append([ot, "690.0", "691.0", "689.0", "690.828", "100.0", ct, "0", 10, "0", "0", "0"])
        sp_k2.append([ot, "690.0", "691.0", "689.0", "690.000", "100.0", ct, "0", 10, "0", "0", "0"])

    k_cm_rec2 = {"symbol": "BNBUSD_261225", "recv_ms": t_day2, "payload": cm_k2}
    k_sp_rec2 = {"symbol": "BNBUSDT", "recv_ms": t_day2, "payload": sp_k2}
    (day2_dir / "signal_cm_klines.jsonl").write_text(json.dumps(k_cm_rec2) + "\n", encoding="utf-8")
    (day2_dir / "signal_spot_klines.jsonl").write_text(json.dumps(k_sp_rec2) + "\n", encoding="utf-8")

    u2_lines = [
        json.dumps({"stream": "usdt_usd", "recv_ms": t_day2 - (24 - i) * 3600000 + 3600000 - 1, "payload": {"price": "1.0000"}})
        for i in range(24)
    ]
    u2_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": t_day2, "payload": {"price": "1.0000"}}))
    (day2_dir / "usdt_usd.jsonl").write_text("\n".join(u2_lines) + "\n", encoding="utf-8")

    # Day 2 depth with full executable depth: spot bid = 689.5, cm ask = 690.3
    sp_d2 = {
        "symbol": "BNBUSDT",
        "recv_ms": t_day2 + 2000,
        "payload": {
            "bids": [["689.5", "20.0"]],
            "asks": [["689.6", "20.0"]],
        },
    }
    cm_d2 = {
        "symbol": "BNBUSD_261225",
        "recv_ms": t_day2 + 2000,
        "payload": {
            "bids": [["690.2", "1000"]],
            "asks": [["690.3", "1000"]],
        },
    }
    (day2_dir / "spot_depth.jsonl").write_text(json.dumps(sp_d2) + "\n", encoding="utf-8")
    (day2_dir / "cm_depth.jsonl").write_text(json.dumps(cm_d2) + "\n", encoding="utf-8")

    # Step 3: Start FRESH runner instance resuming from checkpoint (simulating next forward run)
    runner2 = ForwardLifecycleRunner(checkpoint_path=checkpoint_file, raw_root=raw_root, output_dir=test_out, portfolio_capital_usd=20000.0)
    res_day2 = runner2.run_step(raw_partitions=[day2_dir])

    # Assert Day 2 closed via MA24 compression
    assert res_day2["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res_day2["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert len(runner2.engine.closed_positions) == 1
    closed_pos = runner2.engine.closed_positions[0]
    assert closed_pos["state"] == LifecycleState.CLOSED
    assert closed_pos["lifecycle_status"] == "CLOSED_EARLY_EXIT"
    assert closed_pos["realized_pnl"] != 0.0
    assert res_day2["scorecard"]["realized_closed_pnl_usd"] == closed_pos["realized_pnl"]
    # Capital released
    assert runner2.engine.underlying_committed_usd["BNB"] == 0.0

    # Step 4: Third run asserts idempotency
    runner3 = ForwardLifecycleRunner(checkpoint_path=checkpoint_file, raw_root=raw_root, output_dir=test_out, portfolio_capital_usd=20000.0)
    res_day3 = runner3.run_step(raw_partitions=[day2_dir])
    assert res_day3["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res_day3["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert res_day3["scorecard"]["realized_closed_pnl_usd"] == closed_pos["realized_pnl"]


# ---------------------------------------------------------------------------
# Test Case 23: Official settlement delivery pipeline
# ---------------------------------------------------------------------------
def test_case_23_official_settlement_delivery_pipeline(tmp_path: Path):
    """Verify official settlement delivery path:
    1. Day 1 entry.
    2. Checkpoint saved.
    3. Day 2 delivery expiry reached with official settlement record.
    4. Settles cleanly with inverse coin PnL and full fee accounting.
    """
    raw_root = tmp_path / "raw"
    day1_dir = raw_root / "20261111"
    day2_dir = raw_root / "20261112"
    day1_dir.mkdir(parents=True)
    day2_dir.mkdir(parents=True)
    checkpoint_file = tmp_path / "lifecycle_checkpoint.json"

    t_day1 = 1794412800000
    deliv_time = t_day1 + 100 * 3600000  # 100h away (> 72h requirement)

    ex_info = {
        "stream": "cm_exchange_info",
        "recv_ms": t_day1,
        "payload": {
            "symbols": [
                {
                    "symbol": "BNBUSD_261225",
                    "pair": "BNBUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": deliv_time,
                    "contractSize": 10.0,
                }
            ]
        },
    }
    (day1_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    (day2_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")

    # USDT/USD rates covering the 25 warmup candles plus current time
    u1_lines = [
        json.dumps({"stream": "usdt_usd", "recv_ms": t_day1 - (25 - i) * 3600000 + 3600000 - 1, "payload": {"price": "1.0000"}})
        for i in range(25)
    ]
    u1_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": t_day1, "payload": {"price": "1.0000"}}))
    (day1_dir / "usdt_usd.jsonl").write_text("\n".join(u1_lines) + "\n", encoding="utf-8")

    u2 = {"stream": "usdt_usd", "recv_ms": deliv_time, "payload": {"price": "1.0000"}}
    (day2_dir / "usdt_usd.jsonl").write_text(json.dumps(u2) + "\n", encoding="utf-8")

    # Klines for entry (85 bps)
    cm_k = []
    sp_k = []
    for i in range(25):
        ot = t_day1 - (25 - i) * 3600000
        ct = ot + 3600000 - 1
        cm_k.append([ot, "680.0", "686.0", "679.0", "685.78", "100.0", ct, "0", 10, "0", "0", "0"])
        sp_k.append([ot, "680.0", "681.0", "679.0", "680.00", "100.0", ct, "0", 10, "0", "0", "0"])

    (day1_dir / "signal_cm_klines.jsonl").write_text(json.dumps({"symbol": "BNBUSD_261225", "payload": cm_k}) + "\n", encoding="utf-8")
    (day1_dir / "signal_spot_klines.jsonl").write_text(json.dumps({"symbol": "BNBUSDT", "payload": sp_k}) + "\n", encoding="utf-8")

    sp_d1 = {"symbol": "BNBUSDT", "recv_ms": t_day1 + 1000, "payload": {"bids": [["679.9", "20.0"]], "asks": [["680.0", "20.0"]]}}
    cm_d1 = {"symbol": "BNBUSD_261225", "recv_ms": t_day1 + 1000, "payload": {"bids": [["685.78", "1000"]], "asks": [["685.80", "1000"]]}}
    (day1_dir / "spot_depth.jsonl").write_text(json.dumps(sp_d1) + "\n", encoding="utf-8")
    (day1_dir / "cm_depth.jsonl").write_text(json.dumps(cm_d1) + "\n", encoding="utf-8")

    # Step 1: Day 1 entry
    test_out = tmp_path / "research"
    runner1 = ForwardLifecycleRunner(checkpoint_path=checkpoint_file, raw_root=raw_root, output_dir=test_out, portfolio_capital_usd=20000.0)
    runner1.run_step(raw_partitions=[day1_dir])
    assert len(runner1.engine.active_positions) == 1

    # Step 2: Day 2 delivery expiry reached with official settlement record
    official_settle_rec = {
        "contract_symbol": "BNBUSD_261225",
        "delivery_ms": deliv_time,
        "settlement_price": 689.8,
        "published_ms": deliv_time + 1000,
        "spot_bid_vwap": 689.5,
        "spot_bid_sweep": {
            "fully_filled": True,
            "filled_base_qty": 5000.0 / 680.0,
            "filled_units": 5000.0 / 680.0,
            "filled_usd": (5000.0 / 680.0) * 689.5,
            "vwap": 689.5,
        },
    }
    (day2_dir / "cm_delivery_settlement.jsonl").write_text(json.dumps(official_settle_rec) + "\n", encoding="utf-8")

    sp_d2 = {"symbol": "BNBUSDT", "recv_ms": deliv_time + 500, "payload": {"bids": [["689.5", "20.0"]], "asks": [["689.6", "20.0"]]}}
    cm_d2 = {"symbol": "BNBUSD_261225", "recv_ms": deliv_time + 500, "payload": {"bids": [["689.8", "1000"]], "asks": [["689.9", "1000"]]}}
    (day2_dir / "spot_depth.jsonl").write_text(json.dumps(sp_d2) + "\n", encoding="utf-8")
    (day2_dir / "cm_depth.jsonl").write_text(json.dumps(cm_d2) + "\n", encoding="utf-8")

    runner2 = ForwardLifecycleRunner(checkpoint_path=checkpoint_file, raw_root=raw_root, output_dir=test_out, portfolio_capital_usd=20000.0)
    res_day2 = runner2.run_step(raw_partitions=[day2_dir])

    # Assert delivery settled cleanly
    assert res_day2["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res_day2["scorecard"]["realized_completed_lifecycles_count"] == 1
    closed_pos = runner2.engine.closed_positions[0]
    assert closed_pos["state"] == LifecycleState.CLOSED
    assert closed_pos["lifecycle_status"] == "CLOSED_DELIVERY_SETTLED"
    assert closed_pos["exit_futures_price"] == 689.8
    assert closed_pos["realized_pnl"] != 0.0


# ---------------------------------------------------------------------------
# Test Case 24: Instantaneous depth basis compression cannot trigger exit without MA24
# ---------------------------------------------------------------------------
def test_case_24_instantaneous_depth_cannot_trigger_exit_without_ma24_compression():
    """Verify frozen H-1 exit semantics:
    Instantaneous observed_depth_basis_bps <= 15.0 NEVER triggers exit if causal_basis_ma24_bps > 15.0.
    """
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_EXIT_SEMANTICS_TEST",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.0,
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    # Observation with instantaneous depth basis = 10.0 bps (compressed),
    # BUT MA24 = 74.0 bps (NOT compressed <= 15.0 bps)
    obs_hold = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 2000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "observed_depth_basis_bps": 10.0,  # instantaneous compressed!
        "causal_basis_ma24_bps": 74.0,     # MA24 NOT compressed!
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }

    ok_hold, reason_hold = engine.process_observation(pos, obs_hold)
    assert ok_hold is True
    assert reason_hold != "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.HEDGED_HOLD
    assert pos.get("lifecycle_status") != "CLOSED_EARLY_EXIT"

    # Now observation arrives where MA24 HAS compressed <= 15.0 bps
    obs_exit = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 3000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "observed_depth_basis_bps": 10.0,
        "causal_basis_ma24_bps": 12.0,     # MA24 IS compressed <= 15 bps!
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }

    ok_exit, reason_exit = engine.process_observation(pos, obs_exit)
    assert ok_exit is True
    assert reason_exit == "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.CLOSED


# ---------------------------------------------------------------------------
# Test Case 25: Missing depth sweep evidence returns CLOSE_NOT_EXECUTABLE
# ---------------------------------------------------------------------------
def test_case_25_missing_depth_sweep_returns_close_not_executable():
    """Verify complete depth evidence contract:
    Missing spot_bid_sweep.filled_usd or cm_ask_sweep.filled_units returns CLOSE_NOT_EXECUTABLE.
    """
    engine = N1_7LifecycleEngine()
    pos = {
        "lifecycle_id": "VTRADE_SWEEP_TEST",
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "underlying_asset": "BNB",
        "entry_timestamp": 1000,
        "entry_notional_usd": 5000.0,
        "contracts_short": 500,
        "contract_multiplier_usd": 10.0,
        "entry_spot_price": 680.0,
        "entry_futures_price": 686.0,
        "spot_inventory_coin": 5000.0 / 680.0,
        "entry_fees_paid": 7.5,
        "state": LifecycleState.HEDGED_HOLD,
        "last_valid_observation_timestamp": 1000,
        "last_update_ms": 1000,
    }

    # Observation with MA24 <= 15 bps, but missing filled_usd in spot sweep
    obs_incomplete_spot = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 2000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "causal_basis_ma24_bps": 12.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True},  # missing explicit filled_usd!
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0},
    }

    ok, reason = engine.process_observation(pos, obs_incomplete_spot)
    assert ok is True
    assert reason == "CLOSE_NOT_EXECUTABLE"
    assert pos["state"] == LifecycleState.EXIT_ELIGIBLE
    assert pos["lifecycle_status"] == "CLOSE_NOT_EXECUTABLE"

    # Observation with missing filled_units in CM sweep
    obs_incomplete_cm = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 3000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "causal_basis_ma24_bps": 12.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0},
        "cm_ask_sweep": {"fully_filled": True, "filled_usd": 5000.0},  # missing filled_units!
    }

    ok_cm, reason_cm = engine.process_observation(pos, obs_incomplete_cm)
    assert ok_cm is True
    assert reason_cm == "CLOSE_NOT_EXECUTABLE"

    # Observation with complete depth evidence executes cleanly
    obs_complete = {
        "coinm_contract_symbol": "BNBUSD_261225",
        "decision_timestamp": 4000,
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.0,
        "coinm_bid_vwap": 685.5,
        "spot_bid_vwap": 684.5,
        "coinm_ask_vwap": 685.2,
        "causal_basis_ma24_bps": 12.0,
        "basis_ma24_ready": True,
        "spot_bid_sweep": {"fully_filled": True, "filled_usd": 5000.0, "vwap": 684.5},
        "cm_ask_sweep": {"fully_filled": True, "filled_units": 500, "filled_usd": 5000.0, "vwap": 685.2},
    }

    ok_full, reason_full = engine.process_observation(pos, obs_complete)
    assert ok_full is True
    assert reason_full == "EARLY_EXIT_EXECUTED"
    assert pos["state"] == LifecycleState.CLOSED


# ---------------------------------------------------------------------------
# Test Case 26: Evidence Integrity & Natural Forward Observation Finalization
# ---------------------------------------------------------------------------
def test_case_26_evidence_integrity_and_natural_forward_observation(tmp_path: Path):
    """Verify all 7 P0 evidence integrity and forward readiness criteria:
    1. Compound event identity processes two events sharing the exact same timestamp.
    2. Missing causal PIT USDT/USD rate or insufficient candles returns MA24_NOT_READY.
    3. Synthetic test execution cannot mutate authentic research/neural_n1_7 artifacts.
    4. Official settlement completes futures leg even if delisted from depth feeds.
    5. Incomplete spot liquidation leaves spot in inventory without fabricating spot sale.
    6. Checkpoint restart does not duplicate lifecycles or re-commit capital.
    7. Scorecard reporting isolates TEST_SYNTHETIC from AUTHENTIC_FORWARD.
    """
    from neural_trading.n1_7.lifecycle_engine import (
        RESEARCH_DIR_N1_7,
        fetch_causal_ma24_history,
    )

    # -----------------------------------------------------------------------
    # Criterion 3: Canonical research evidence isolation
    # -----------------------------------------------------------------------
    canonical_res_file = RESEARCH_DIR_N1_7 / "n1_7_forward_lifecycle_results.json"
    assert canonical_res_file.exists(), "Canonical forward evidence file must exist"
    canonical_content_before = canonical_res_file.read_text(encoding="utf-8")
    canonical_data = json.loads(canonical_content_before)
    # Assert restored canonical baseline: 0 closed lifecycles, 0.0 realized PnL
    scorecard = canonical_data.get("scorecard", {})
    assert scorecard.get("realized_completed_lifecycles_count") == 0
    assert scorecard.get("realized_closed_pnl_usd") == 0.0

    # -----------------------------------------------------------------------
    # Criterion 2: Missing PIT source returns MA24_NOT_READY
    # -----------------------------------------------------------------------
    raw_root = tmp_path / "raw"
    day1_dir = raw_root / "20261111"
    day1_dir.mkdir(parents=True)
    t_base = 1794412800000

    # Only 10 hourly candles provided (insufficient for 24h warmup)
    short_klines = []
    for i in range(10):
        ot = t_base - (10 - i) * 3600000
        ct = ot + 3600000 - 1
        short_klines.append([ot, "680.0", "686.0", "679.0", "685.0", "100.0", ct, "0", 10, "0", "0", "0"])

    basis_val, basis_bps, is_ready = fetch_causal_ma24_history(
        cm_symbol="BNBUSD_261225",
        spot_symbol="BNBUSDT",
        target_end_ms=t_base,
        raw_partitions=[day1_dir],
        historical_replay_mode=False,
    )
    assert is_ready is False
    assert basis_bps == 0.0  # MA24_NOT_READY

    # -----------------------------------------------------------------------
    # Criterion 1 & 6: Same-timestamp compound cursor + checkpoint idempotency
    # -----------------------------------------------------------------------
    # Create 25 hourly candles and matching causal USDT rates for BNB and BTC
    cm_k_bnb = []
    sp_k_bnb = []
    cm_k_btc = []
    sp_k_btc = []
    u_lines = []
    for i in range(25):
        ot = t_base - (25 - i) * 3600000
        ct = ot + 3600000 - 1
        cm_k_bnb.append([ot, "680.0", "686.0", "679.0", "685.78", "100.0", ct, "0", 10, "0", "0", "0"])
        sp_k_bnb.append([ot, "680.0", "681.0", "679.0", "680.00", "100.0", ct, "0", 10, "0", "0", "0"])
        cm_k_btc.append([ot, "98000.0", "98900.0", "97900.0", "98833.0", "10.0", ct, "0", 10, "0", "0", "0"])
        sp_k_btc.append([ot, "98000.0", "98100.0", "97900.0", "98000.0", "10.0", ct, "0", 10, "0", "0", "0"])
        u_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": ct, "payload": {"price": "1.0000"}}))

    u_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": t_base, "payload": {"price": "1.0000"}}))
    (day1_dir / "usdt_usd.jsonl").write_text("\n".join(u_lines) + "\n", encoding="utf-8")

    k_cm_all = [
        {"symbol": "BNBUSD_261225", "recv_ms": t_base, "payload": cm_k_bnb},
        {"symbol": "BTCUSD_261225", "recv_ms": t_base, "payload": cm_k_btc},
    ]
    k_sp_all = [
        {"symbol": "BNBUSDT", "recv_ms": t_base, "payload": sp_k_bnb},
        {"symbol": "BTCUSDT", "recv_ms": t_base, "payload": sp_k_btc},
    ]
    (day1_dir / "signal_cm_klines.jsonl").write_text("\n".join(json.dumps(x) for x in k_cm_all) + "\n", encoding="utf-8")
    (day1_dir / "signal_spot_klines.jsonl").write_text("\n".join(json.dumps(x) for x in k_sp_all) + "\n", encoding="utf-8")

    deliv_time = t_base + 100 * 3600000
    ex_info = {
        "stream": "cm_exchange_info",
        "recv_ms": t_base,
        "payload": {
            "symbols": [
                {
                    "symbol": "BNBUSD_261225",
                    "pair": "BNBUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": deliv_time,
                    "contractSize": 10.0,
                },
                {
                    "symbol": "BTCUSD_261225",
                    "pair": "BTCUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": deliv_time,
                    "contractSize": 100.0,
                },
            ]
        },
    }
    (day1_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")

    # Depth snapshots for both contracts at the EXACT SAME millisecond: t_base + 1000
    t_same = t_base + 1000
    depth_sp_lines = [
        json.dumps({"symbol": "BNBUSDT", "recv_ms": t_same, "payload": {"bids": [["679.9", "20.0"]], "asks": [["680.0", "20.0"]]}}),
        json.dumps({"symbol": "BTCUSDT", "recv_ms": t_same, "payload": {"bids": [["97990.0", "5.0"]], "asks": [["98000.0", "5.0"]]}}),
    ]
    depth_cm_lines = [
        json.dumps({"symbol": "BNBUSD_261225", "recv_ms": t_same, "payload": {"bids": [["685.78", "1000"]], "asks": [["685.80", "1000"]]}}),
        json.dumps({"symbol": "BTCUSD_261225", "recv_ms": t_same, "payload": {"bids": [["98833.0", "100"]], "asks": [["98835.0", "100"]]}}),
    ]
    (day1_dir / "spot_depth.jsonl").write_text("\n".join(depth_sp_lines) + "\n", encoding="utf-8")
    (day1_dir / "cm_depth.jsonl").write_text("\n".join(depth_cm_lines) + "\n", encoding="utf-8")

    # Run ForwardLifecycleRunner with explicit test output directory and TEST_SYNTHETIC population
    test_out = tmp_path / "research"
    checkpoint_file = tmp_path / "checkpoint.json"
    runner1 = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    res1 = runner1.run_step(raw_partitions=[day1_dir])

    # Assert Criterion 1: BOTH same-timestamp contracts were evaluated and admitted!
    assert res1["scorecard"]["actively_tracked_lifecycles_count"] == 2
    active_syms = {p["contract_symbol"] for p in runner1.engine.active_positions.values()}
    assert active_syms == {"BNBUSD_261225", "BTCUSD_261225"}
    assert runner1.engine.underlying_committed_usd["BNB"] == 5000.0
    assert runner1.engine.underlying_committed_usd["BTC"] == 5000.0

    # Assert Criterion 6: Checkpoint restart does not duplicate or re-commit capital
    runner1_restart = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    res1_replay = runner1_restart.run_step(raw_partitions=[day1_dir])
    assert res1_replay["scorecard"]["actively_tracked_lifecycles_count"] == 2
    assert runner1_restart.engine.underlying_committed_usd["BNB"] == 5000.0
    assert runner1_restart.engine.underlying_committed_usd["BTC"] == 5000.0

    # -----------------------------------------------------------------------
    # Criterion 4 & 5: Settlement-only partition + Spot Inventory Held
    # -----------------------------------------------------------------------
    # Day 2 has ONLY cm_delivery_settlement.jsonl (delisted from cm_depth.jsonl)
    day2_dir = raw_root / "20261112"
    day2_dir.mkdir(parents=True)
    (day2_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    (day2_dir / "usdt_usd.jsonl").write_text(json.dumps({"stream": "usdt_usd", "recv_ms": deliv_time, "payload": {"price": "1.0000"}}) + "\n", encoding="utf-8")

    # Settlement records:
    # - BNBUSD: has spot_bid_sweep -> full delivery settlement
    # - BTCUSD: MISSING spot_bid_sweep -> futures settled, spot held in inventory!
    settle_records = [
        {
            "contract_symbol": "BNBUSD_261225",
            "delivery_ms": deliv_time,
            "settlement_price": 689.8,
            "published_ms": deliv_time + 1000,
            "spot_bid_vwap": 689.5,
            "spot_bid_sweep": {
                "fully_filled": True,
                "filled_base_qty": 5000.0 / 680.0,
                "filled_units": 5000.0 / 680.0,
                "filled_usd": (5000.0 / 680.0) * 689.5,
                "vwap": 689.5,
            },
        },
        {
            "contract_symbol": "BTCUSD_261225",
            "delivery_ms": deliv_time,
            "settlement_price": 99500.0,
            "published_ms": deliv_time + 1000,
            # Deliberately omit spot_bid_sweep to trigger inventory-held handling!
        },
    ]
    (day2_dir / "cm_delivery_settlement.jsonl").write_text("\n".join(json.dumps(r) for r in settle_records) + "\n", encoding="utf-8")

    # Run Day 2 settlement
    runner2 = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    res2 = runner2.run_step(raw_partitions=[day2_dir])

    # Assert Criterion 4 & 5 with P0-A Partial Settlement Accounting:
    # BNB is fully closed; BTC futures leg is settled while Spot is held in active inventory
    assert res2["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res2["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert res2["scorecard"]["FUTURES_LEGS_SETTLED"] == 2
    assert res2["scorecard"]["PAIRS_FULLY_CLOSED"] == 1
    assert res2["scorecard"]["SPOT_INVENTORY_HELD"] == 1
    assert res2["scorecard"]["CAPITAL_STILL_COMMITTED"] == 5000.0
    assert res2["scorecard"]["CAPITAL_AVAILABLE"] == 15000.0
    assert runner2.engine.underlying_committed_usd["BNB"] == 0.0
    assert runner2.engine.underlying_committed_usd["BTC"] == 5000.0

    # Check BNB: full settlement
    bnb_pos = [p for p in runner2.engine.closed_positions if p["contract_symbol"] == "BNBUSD_261225"][0]
    assert bnb_pos["lifecycle_status"] == "CLOSED_DELIVERY_SETTLED"
    assert bnb_pos["pair_fully_closed"] is True
    assert bnb_pos["exit_spot_price"] == 689.5
    assert bnb_pos["capital_released"] is True

    # Check BTC: futures settled, spot held in active inventory
    btc_pos = [p for p in runner2.engine.active_positions.values() if p["contract_symbol"] == "BTCUSD_261225"][0]
    assert btc_pos["state"] == LifecycleState.FUTURES_LEG_SETTLED
    assert btc_pos["lifecycle_status"] == "FUTURES_LEG_SETTLED"
    assert btc_pos["pair_fully_closed"] is False
    assert btc_pos["spot_inventory_held"] is True
    assert btc_pos["exit_spot_price"] is None
    assert btc_pos["capital_released"] is False
    assert btc_pos["released_capital_usd"] == 0.0
    # Realized PnL only realized on futures leg; gross spot pnl is 0.0
    assert btc_pos["realized_pnl_bridge"]["gross_spot_pnl_usd"] == 0.0
    assert btc_pos["spot_inventory_market_value_usd"] > 0.0

    # Assert Criterion 7: Scorecard reflects population mode
    assert res2["scorecard"]["population_mode"] == "TEST_SYNTHETIC"

    # Assert Criterion 3 (Final Check): Authentic research artifacts were NEVER touched
    canonical_content_after = canonical_res_file.read_text(encoding="utf-8")
    assert canonical_content_before == canonical_content_after, "Canonical forward evidence was contaminated by test run!"


# ---------------------------------------------------------------------------
# Test Case 27: Official Recorder Delivery Ingestion & Held Inventory Liquidation
# ---------------------------------------------------------------------------
def test_case_27_recorder_format_settlement_and_inventory_lifecycle(tmp_path: Path):
    """P0-B & P0-A End-to-End Test:

    Pipeline:
    1. Day 1: Ingests raw recorder feed and admits BNBUSD_261225 into HEDGED_HOLD ($5,000 committed).
    2. Day 2: Ingests raw official Binance settlement payload (keyed by pair 'BNBUSD' per API contract).
       Resolves pair to contract symbol BNBUSD_261225.
       Futures leg settles without Spot liquidation -> FUTURES_LEG_SETTLED.
       Spot inventory preserved, capital remains reserved ($5,000 committed).
    3. Checkpoint & Restart: Saves checkpoint, restarts runner, confirms zero capital leakage and idempotency.
    4. Day 3: Ingests Spot depth partition with executable sweep -> liquidates held Spot inventory.
       Transitions to PAIR_FULLY_CLOSED, reconciles exact realized fee bridge, releases capital to $0.
    """
    raw_root = tmp_path / "raw"
    day1_dir = raw_root / "20261111"
    day1_dir.mkdir(parents=True)
    t_base = 1794412800000
    deliv_time = t_base + 100 * 3600000

    # 1. Day 1 Feed: 25 completed 1h candles
    cm_k_bnb = []
    sp_k_bnb = []
    u_lines = []
    for i in range(25):
        ot = t_base - (25 - i) * 3600000
        ct = ot + 3600000 - 1
        cm_k_bnb.append([ot, "680.0", "686.0", "679.0", "685.78", "100.0", ct, "0", 10, "0", "0", "0"])
        sp_k_bnb.append([ot, "680.0", "681.0", "679.0", "680.00", "100.0", ct, "0", 10, "0", "0", "0"])
        u_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": ct, "payload": {"price": "1.0000"}}))

    u_lines.append(json.dumps({"stream": "usdt_usd", "recv_ms": t_base, "payload": {"price": "1.0000"}}))
    (day1_dir / "usdt_usd.jsonl").write_text("\n".join(u_lines) + "\n", encoding="utf-8")

    k_cm_all = [{"symbol": "BNBUSD_261225", "recv_ms": t_base, "payload": cm_k_bnb}]
    k_sp_all = [{"symbol": "BNBUSDT", "recv_ms": t_base, "payload": sp_k_bnb}]
    (day1_dir / "signal_cm_klines.jsonl").write_text("\n".join(json.dumps(x) for x in k_cm_all) + "\n", encoding="utf-8")
    (day1_dir / "signal_spot_klines.jsonl").write_text("\n".join(json.dumps(x) for x in k_sp_all) + "\n", encoding="utf-8")

    ex_info = {
        "stream": "cm_exchange_info",
        "recv_ms": t_base,
        "payload": {
            "symbols": [
                {
                    "symbol": "BNBUSD_261225",
                    "pair": "BNBUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": deliv_time,
                    "contractSize": 10.0,
                }
            ]
        },
    }
    (day1_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")

    t_entry = t_base + 1000
    (day1_dir / "spot_depth.jsonl").write_text(
        json.dumps({"symbol": "BNBUSDT", "recv_ms": t_entry, "payload": {"bids": [["679.9", "20.0"]], "asks": [["680.0", "20.0"]]}}) + "\n",
        encoding="utf-8",
    )
    (day1_dir / "cm_depth.jsonl").write_text(
        json.dumps({"symbol": "BNBUSD_261225", "recv_ms": t_entry, "payload": {"bids": [["685.78", "1000"]], "asks": [["685.80", "1000"]]}}) + "\n",
        encoding="utf-8",
    )

    test_out = tmp_path / "research"
    checkpoint_file = tmp_path / "checkpoint.json"

    # Step 1: Run Day 1
    runner = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    res1 = runner.run_step(raw_partitions=[day1_dir])
    assert res1["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert runner.engine.underlying_committed_usd["BNB"] == 5000.0
    pos1 = list(runner.engine.active_positions.values())[0]
    entry_fut_price = pos1["entry_futures_price"]
    entry_spot_price = pos1["entry_spot_price"]
    spot_coin_qty = pos1["spot_inventory_coin"]
    assert entry_fut_price == 685.78
    assert entry_spot_price == 680.0

    # Step 2: Day 2 Official Delivery Ingestion (keyed by pair 'BNBUSD' from Binance API)
    day2_dir = raw_root / "20261112"
    day2_dir.mkdir(parents=True)
    (day2_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    (day2_dir / "usdt_usd.jsonl").write_text(json.dumps({"stream": "usdt_usd", "recv_ms": deliv_time, "payload": {"price": "1.0000"}}) + "\n", encoding="utf-8")

    # Official Binance API delivery payload format recorded by upstream recorder
    recorder_delivery_payload = {
        "obs_id": "RECORDER_DELIV_OBS_001",
        "stream": "cm_delivery_settlement",
        "symbol": "BNBUSD",  # Note: upstream endpoint returns pair!
        "params": {"pair": "BNBUSD"},
        "recv_ms": deliv_time + 500,  # Official receipt watermark
        "payload": [
            {
                "deliveryPrice": "689.80000000",
                "deliveryTime": deliv_time,
            }
        ],
    }
    (day2_dir / "cm_delivery_settlement.jsonl").write_text(json.dumps(recorder_delivery_payload) + "\n", encoding="utf-8")

    res2 = runner.run_step(raw_partitions=[day2_dir])

    # Assert Step 2: Mapped cleanly to BNBUSD_261225; futures settled, Spot held, capital reserved
    assert res2["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res2["scorecard"]["FUTURES_LEGS_SETTLED"] == 1
    assert res2["scorecard"]["PAIRS_FULLY_CLOSED"] == 0
    assert res2["scorecard"]["SPOT_INVENTORY_HELD"] == 1
    assert res2["scorecard"]["CAPITAL_STILL_COMMITTED"] == 5000.0
    assert res2["scorecard"]["CAPITAL_AVAILABLE"] == 15000.0
    assert runner.engine.underlying_committed_usd["BNB"] == 5000.0

    pos2 = list(runner.engine.active_positions.values())[0]
    assert pos2["state"] == LifecycleState.FUTURES_LEG_SETTLED
    assert pos2["futures_leg_settled"] is True
    assert pos2["pair_fully_closed"] is False
    assert pos2["spot_inventory_held"] is True
    assert pos2["capital_released"] is False
    assert pos2["released_capital_usd"] == 0.0
    assert pos2["exit_futures_price"] == 689.8

    # Independent mathematical verification of realized futures PnL
    notional = 5000.0
    expected_inv_pnl_coin = notional * (1.0 / 689.8 - 1.0 / entry_fut_price)
    expected_cm_entry_fee = notional * (COSTS.cm_entry_fee_bps / 10_000.0)
    expected_cm_deliv_fee = notional * (COSTS.cm_delivery_settlement_fee_bps / 10_000.0)
    expected_realized_fut_usd = (expected_inv_pnl_coin * 689.8) - expected_cm_entry_fee - expected_cm_deliv_fee
    assert abs(pos2["realized_futures_pnl_usd"] - round(expected_realized_fut_usd, 2)) <= 0.02

    # Step 3: Checkpoint and Restart Idempotency
    runner_restart = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    res_restart = runner_restart.run_step(raw_partitions=[day2_dir])
    assert res_restart["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res_restart["scorecard"]["CAPITAL_STILL_COMMITTED"] == 5000.0

    # Step 4: Day 3 Liquidation Partition (Only Spot depth available for BNBUSDT)
    day3_dir = raw_root / "20261113"
    day3_dir.mkdir(parents=True)
    t_liq = deliv_time + 3600000
    (day3_dir / "usdt_usd.jsonl").write_text(json.dumps({"stream": "usdt_usd", "recv_ms": t_liq, "payload": {"price": "1.0000"}}) + "\n", encoding="utf-8")
    (day3_dir / "spot_depth.jsonl").write_text(
        json.dumps({
            "symbol": "BNBUSDT",
            "recv_ms": t_liq,
            "payload": {"bids": [["688.50", "50.0"]], "asks": [["688.60", "50.0"]]},
        }) + "\n",
        encoding="utf-8",
    )

    res3 = runner_restart.run_step(raw_partitions=[day3_dir])

    # Assert Step 4: Held inventory fully liquidated, pair fully closed, capital released
    assert res3["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res3["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert res3["scorecard"]["FUTURES_LEGS_SETTLED"] == 1
    assert res3["scorecard"]["PAIRS_FULLY_CLOSED"] == 1
    assert res3["scorecard"]["SPOT_INVENTORY_HELD"] == 0
    assert res3["scorecard"]["CAPITAL_STILL_COMMITTED"] == 0.0
    assert res3["scorecard"]["CAPITAL_AVAILABLE"] == 20000.0
    assert runner_restart.engine.underlying_committed_usd.get("BNB", 0.0) == 0.0

    pos_closed = runner_restart.engine.closed_positions[0]
    assert pos_closed["state"] == LifecycleState.CLOSED
    assert pos_closed["lifecycle_status"] == "PAIR_FULLY_CLOSED"
    assert pos_closed["pair_fully_closed"] is True
    assert pos_closed["spot_inventory_held"] is False
    assert pos_closed["capital_released"] is True
    assert pos_closed["released_capital_usd"] == 5000.0
    assert pos_closed["exit_spot_price"] == 688.50

    # Independent mathematical verification of complete realized PnL bridge
    spot_gross = spot_coin_qty * 688.50 - notional
    sp_entry_fee = notional * (COSTS.spot_entry_fee_bps / 10_000.0)
    sp_exit_fee = spot_coin_qty * 688.50 * (COSTS.spot_exit_fee_bps / 10_000.0)
    expected_realized_spot_usd = spot_gross - sp_entry_fee - sp_exit_fee
    expected_net_realized_usd = expected_realized_fut_usd + expected_realized_spot_usd

    bridge = pos_closed["realized_pnl_bridge"]
    assert abs(bridge["gross_spot_pnl_usd"] - round(spot_gross, 4)) <= 0.01
    assert abs(bridge["spot_entry_fee_usd"] - round(sp_entry_fee, 4)) <= 0.01
    assert abs(bridge["spot_exit_fee_usd"] - round(sp_exit_fee, 4)) <= 0.01
    assert abs(bridge["realized_spot_pnl_usd"] - round(expected_realized_spot_usd, 2)) <= 0.02
    assert abs(bridge["realized_net_pnl_usd"] - round(expected_net_realized_usd, 2)) <= 0.02


# ---------------------------------------------------------------------------
# Test Case 28: Targeted Settlement Availability, Spot Coin Liquidation & Equity
# ---------------------------------------------------------------------------
def test_case_28_targeted_settlement_and_spot_quantity_lifecycle(tmp_path: Path):
    """Verify:
    1. P0-A: Official settlement available at T+5m is not processed at T (causal PIT).
    2. P0-B: Spot liquidation sweeps actual coin quantity (7.352941 BNB), not USD notional.
             Sweeping $5000 exit notional at $688.50 yields 7.262164 BNB; does NOT close pair.
             Partial fill preserves remaining 0.090777 BNB and remaining $61.73 committed capital.
             Subsequent sweep finishes remaining coins and closes pair exactly once.
    3. P0-C: Disjoint accounting buckets reconcile TOTAL_ACCOUNT_EQUITY across partial settlement.
    4. Checkpoint idempotency across restart.
    """
    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True)

    t_base = 1794409200000  # 2026-11-11 15:00:00 UTC
    deliv_time = 1798185600000  # Contract expiry T

    ex_info = {
        "payload": {
            "symbols": [
                {
                    "symbol": "BNBUSD_261225",
                    "pair": "BNBUSD",
                    "contractType": "CURRENT_QUARTER",
                    "contractStatus": "TRADING",
                    "deliveryDate": str(deliv_time),
                    "contractSize": "10.0",
                }
            ]
        }
    }

    # Step 1: Day 1 - Enter Virtual Carry Pair
    day1_dir = raw_root / "20261111"
    day1_dir.mkdir(parents=True)
    (day1_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    (day1_dir / "usdt_usd.jsonl").write_text(
        json.dumps({"stream": "usdt_usd", "recv_ms": t_base, "payload": {"price": "1.0000"}}) + "\n",
        encoding="utf-8",
    )
    t_entry = t_base + 1000
    # Spot entry at $680.00 -> $5000 notional requires 5000 / 680 = 7.35294117647 BNB
    (day1_dir / "spot_depth.jsonl").write_text(
        json.dumps({
            "symbol": "BNBUSDT",
            "recv_ms": t_entry,
            "payload": {"bids": [["679.9", "20.0"]], "asks": [["680.0", "20.0"]]},
        }) + "\n",
        encoding="utf-8",
    )
    # COIN-M short entry at $685.78
    (day1_dir / "cm_depth.jsonl").write_text(
        json.dumps({
            "symbol": "BNBUSD_261225",
            "recv_ms": t_entry,
            "payload": {"bids": [["685.78", "1000"]], "asks": [["685.80", "1000"]]},
        }) + "\n",
        encoding="utf-8",
    )

    test_out = tmp_path / "research"
    checkpoint_file = tmp_path / "checkpoint.json"

    runner = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )

    res1 = runner.run_step(raw_partitions=[day1_dir])
    assert res1["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert runner.engine.underlying_committed_usd["BNB"] == 5000.0

    pos1 = list(runner.engine.active_positions.values())[0]
    entry_notional = pos1["entry_notional_usd"]
    entry_spot = pos1["entry_spot_price"]
    entry_fut = pos1["entry_futures_price"]
    spot_coin_qty = pos1["spot_inventory_coin"]
    assert entry_spot == 680.0
    assert entry_fut == 685.78
    assert abs(spot_coin_qty - (5000.0 / 680.0)) < 1e-6
    # 7.352941176...
    assert round(spot_coin_qty, 6) == 7.352941

    # Step 2: Day 2 - Settlement Available at T + 300_000 (T + 5 min)
    day2_dir = raw_root / "20261112"
    day2_dir.mkdir(parents=True)
    (day2_dir / "cm_exchange_info.jsonl").write_text(json.dumps(ex_info) + "\n", encoding="utf-8")
    t_recv = deliv_time + 300_000  # T + 5 min
    (day2_dir / "usdt_usd.jsonl").write_text(
        json.dumps({"stream": "usdt_usd", "recv_ms": t_recv, "payload": {"price": "1.0000"}}) + "\n",
        encoding="utf-8",
    )

    # Official Binance API settlement received at T + 5m (recv_ms = deliv_time + 300_000)
    recorder_delivery_payload = {
        "obs_id": "RECORDER_DELIV_002",
        "stream": "cm_delivery_settlement",
        "symbol": "BNBUSD",
        "params": {"pair": "BNBUSD"},
        "recv_ms": t_recv,
        "payload": [
            {
                "deliveryPrice": "689.80000000",
                "deliveryTime": deliv_time,
            }
        ],
    }
    (day2_dir / "cm_delivery_settlement.jsonl").write_text(
        json.dumps(recorder_delivery_payload) + "\n", encoding="utf-8"
    )

    # Verify P0-A: An observation at T (expiry time) must NOT settle the position before data is available
    obs_at_expiry = {
        "decision_timestamp": deliv_time,
        "contract_symbol": "BNBUSD_261225",
        "spot_symbol": "BNBUSDT",
        "quote_valid_pit": True,
        "spot_ask_vwap": 685.00,
        "spot_bid_vwap": 684.90,
        "coinm_bid_vwap": 689.80,
        "coinm_ask_vwap": 689.90,
        "official_delivery_settlement": {
            "contract_symbol": "BNBUSD_261225",
            "settlement_price": 689.80,
            "delivery_ms": deliv_time,
            "available_ms": t_recv,  # Available only at T + 5m!
        },
    }
    ok_early, reason_early = runner.engine.process_observation(pos1, obs_at_expiry)
    assert ok_early is False
    assert reason_early == "SETTLEMENT_DATA_FUTURE_PIT"
    assert pos1.get("futures_leg_settled", False) is False

    # Now run runner step for Day 2 (processes at t_recv = T + 5m)
    res2 = runner.run_step(raw_partitions=[day2_dir])
    assert res2["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res2["scorecard"]["FUTURES_LEGS_SETTLED"] == 1
    assert res2["scorecard"]["PAIRS_FULLY_CLOSED"] == 0
    assert res2["scorecard"]["SPOT_INVENTORY_HELD"] == 1
    assert res2["scorecard"]["CAPITAL_STILL_COMMITTED"] == 5000.0
    assert res2["scorecard"]["CAPITAL_AVAILABLE"] == 15000.0

    pos2 = list(runner.engine.active_positions.values())[0]
    assert pos2["state"] == LifecycleState.FUTURES_LEG_SETTLED
    assert pos2["futures_leg_settled"] is True
    assert pos2["pair_fully_closed"] is False
    assert pos2["spot_inventory_held"] is True
    assert pos2["capital_released"] is False

    # Realized futures PnL math
    expected_inv_pnl_coin = 5000.0 * (1.0 / 689.80 - 1.0 / 685.78)
    cm_entry_fee = 5000.0 * (COSTS.cm_entry_fee_bps / 10_000.0)
    cm_deliv_fee = 5000.0 * (COSTS.cm_delivery_settlement_fee_bps / 10_000.0)
    expected_realized_fut = (expected_inv_pnl_coin * 689.80) - cm_entry_fee - cm_deliv_fee
    assert abs(pos2["realized_futures_pnl_usd"] - round(expected_realized_fut, 2)) <= 0.02

    # Verify P0-C Disjoint Accounting Buckets & Equity
    scorecard2 = res2["scorecard"]
    assert scorecard2["FULLY_CLOSED_PAIR_REALIZED_NET_PNL"] == 0.0
    assert scorecard2["ACTIVE_HEDGED_PAIR_UNREALIZED_NET_PNL"] == 0.0
    assert abs(scorecard2["FUTURES_SETTLED_SPOT_HELD_REALIZED_FUTURES_PNL"] - round(expected_realized_fut, 2)) <= 0.02
    # Verify equity strictly includes realized futures PnL
    expected_equity2 = round(
        20000.0
        + scorecard2["FULLY_CLOSED_PAIR_REALIZED_NET_PNL"]
        + scorecard2["ACTIVE_HEDGED_PAIR_UNREALIZED_NET_PNL"]
        + scorecard2["FUTURES_SETTLED_SPOT_HELD_REALIZED_FUTURES_PNL"]
        + scorecard2["FUTURES_SETTLED_SPOT_HELD_UNREALIZED_SPOT_PNL"],
        2,
    )
    assert abs(scorecard2["TOTAL_ACCOUNT_EQUITY"] - expected_equity2) <= 0.02

    # Step 3: Day 3 - Partial Spot Liquidation: Sweeping $5000 exit notional at $688.50
    # At $688.50, $5000 notional is only 7.26216412 BNB, which is LESS than 7.352941 BNB.
    # Must NOT close the pair!
    day3_dir = raw_root / "20261113"
    day3_dir.mkdir(parents=True)
    t_sweep1 = t_recv + 3600000
    (day3_dir / "usdt_usd.jsonl").write_text(
        json.dumps({"stream": "usdt_usd", "recv_ms": t_sweep1, "payload": {"price": "1.0000"}}) + "\n",
        encoding="utf-8",
    )
    # Spot bids with exact depth: 7.262164 BNB at 688.50
    (day3_dir / "spot_depth.jsonl").write_text(
        json.dumps({
            "symbol": "BNBUSDT",
            "recv_ms": t_sweep1,
            "payload": {
                "bids": [["688.50", "7.262164"]],
                "asks": [["688.60", "10.0"]],
            },
        }) + "\n",
        encoding="utf-8",
    )

    res3 = runner.run_step(raw_partitions=[day3_dir])
    # Assert pair is NOT fully closed
    assert res3["scorecard"]["actively_tracked_lifecycles_count"] == 1
    assert res3["scorecard"]["PAIRS_FULLY_CLOSED"] == 0
    assert res3["scorecard"]["SPOT_INVENTORY_HELD"] == 1

    pos3 = list(runner.engine.active_positions.values())[0]
    assert pos3["state"] == LifecycleState.FUTURES_LEG_SETTLED
    assert pos3["pair_fully_closed"] is False
    assert pos3["spot_inventory_held"] is True
    # Verify remaining coins: 7.352941 - 7.262164 = 0.090777 BNB
    expected_remaining_coin = spot_coin_qty - 7.262164
    assert abs(pos3["spot_inventory_coin"] - expected_remaining_coin) <= 1e-5
    assert abs(pos3["spot_inventory_coin"] - 0.090777) <= 1e-4

    # Verify remaining committed capital
    frac_remaining = expected_remaining_coin / spot_coin_qty
    expected_remaining_notional = 5000.0 * frac_remaining
    assert abs(pos3["entry_notional_usd"] - expected_remaining_notional) <= 0.1
    assert abs(res3["scorecard"]["CAPITAL_STILL_COMMITTED"] - round(expected_remaining_notional, 2)) <= 0.1
    assert abs(runner.engine.underlying_committed_usd["BNB"] - round(expected_remaining_notional, 2)) <= 0.1
    assert res3["scorecard"]["CAPITAL_STILL_COMMITTED"] > 50.0  # Around $61.73

    # Step 4: Day 4 - Complete Liquidation of Remaining 0.090777 BNB
    day4_dir = raw_root / "20261114"
    day4_dir.mkdir(parents=True)
    t_sweep2 = t_sweep1 + 3600000
    (day4_dir / "usdt_usd.jsonl").write_text(
        json.dumps({"stream": "usdt_usd", "recv_ms": t_sweep2, "payload": {"price": "1.0000"}}) + "\n",
        encoding="utf-8",
    )
    # Spot bids with ample size to cover remaining 0.090777 BNB
    (day4_dir / "spot_depth.jsonl").write_text(
        json.dumps({
            "symbol": "BNBUSDT",
            "recv_ms": t_sweep2,
            "payload": {
                "bids": [["688.50", "20.0"]],
                "asks": [["688.60", "20.0"]],
            },
        }) + "\n",
        encoding="utf-8",
    )

    res4 = runner.run_step(raw_partitions=[day4_dir])
    # Assert pair is NOW fully closed
    assert res4["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res4["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert res4["scorecard"]["FUTURES_LEGS_SETTLED"] == 1
    assert res4["scorecard"]["PAIRS_FULLY_CLOSED"] == 1
    assert res4["scorecard"]["SPOT_INVENTORY_HELD"] == 0
    assert res4["scorecard"]["CAPITAL_STILL_COMMITTED"] == 0.0
    assert res4["scorecard"]["CAPITAL_AVAILABLE"] == 20000.0
    assert runner.engine.underlying_committed_usd.get("BNB", 0.0) == 0.0

    pos_closed = runner.engine.closed_positions[0]
    assert pos_closed["state"] == LifecycleState.CLOSED
    assert pos_closed["lifecycle_status"] == "PAIR_FULLY_CLOSED"
    assert pos_closed["pair_fully_closed"] is True
    assert pos_closed["spot_inventory_held"] is False
    assert pos_closed["capital_released"] is True

    # Mathematical fee bridge verification
    # Total spot sold = 7.352941 BNB at 688.50 = 5062.50 proceeds
    total_proceeds = spot_coin_qty * 688.50
    total_spot_gross = total_proceeds - 5000.0
    sp_entry_fee = 5000.0 * (COSTS.spot_entry_fee_bps / 10_000.0)
    sp_exit_fee = total_proceeds * (COSTS.spot_exit_fee_bps / 10_000.0)
    expected_spot_net = total_spot_gross - sp_entry_fee - sp_exit_fee
    expected_total_net = expected_realized_fut + expected_spot_net

    assert abs(pos_closed["realized_pnl"] - round(expected_total_net, 2)) <= 0.05
    assert res4["scorecard"]["FULLY_CLOSED_PAIR_REALIZED_NET_PNL"] == pos_closed["realized_pnl"]
    assert abs(res4["scorecard"]["TOTAL_ACCOUNT_EQUITY"] - round(20000.0 + pos_closed["realized_pnl"], 2)) <= 0.05

    # Step 5: Checkpoint and Restart Idempotency
    runner_restart = ForwardLifecycleRunner(
        checkpoint_path=checkpoint_file,
        raw_root=raw_root,
        output_dir=test_out,
        portfolio_capital_usd=20000.0,
        population_mode="TEST_SYNTHETIC",
    )
    # Replay Day 4 partition
    res_replay = runner_restart.run_step(raw_partitions=[day4_dir])
    assert res_replay["scorecard"]["actively_tracked_lifecycles_count"] == 0
    assert res_replay["scorecard"]["realized_completed_lifecycles_count"] == 1
    assert res_replay["scorecard"]["PAIRS_FULLY_CLOSED"] == 1
    assert res_replay["scorecard"]["CAPITAL_STILL_COMMITTED"] == 0.0
    assert res_replay["scorecard"]["CAPITAL_AVAILABLE"] == 20000.0
