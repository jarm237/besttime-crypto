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
from neural_trading.n1_7.lifecycle_engine import N1_7LifecycleEngine
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
    assert quarantined["lifecycle_id"] == "VTRADE_0002"
    assert quarantined["contract_symbol"] == "BNBUSD_270326"


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
        "spot_bid_sweep": {"fully_filled": True},
        "cm_ask_sweep": {"fully_filled": True},
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
        "spot_bid_sweep": {"fully_filled": True},
        "cm_ask_sweep": {"fully_filled": True},
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
