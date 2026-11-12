"""Targeted regression tests for N1.8-R1 Material Invariants.

Verifies:
1. Multiple assets updated in an interleaved quote batch.
2. Same asset across different quarterly expiries.
3. Cross-symbol quote contamination strictly prevented.
4. Aggregate underlying cap rejection.
5. Duplicate collateral consumption blocked.
6. Deterministic replay and restart idempotency.
7. Missing or stale quote handling.
8. Correctly separated original and compliant portfolio populations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from neural_trading.n1_7.lifecycle_engine import N1_7LifecycleEngine
from neural_trading.n1_8.allocation_engine import (
    AccountMarginLedger,
    AccountUnderlyingAllocationLedger,
)
from neural_trading.n1_8.config import (
    COSTS,
    DATA_ROOT_N1_7,
    FROZEN_H1,
    PORTFOLIO_CONFIG,
    RESEARCH_DIR_N1_7,
    RESEARCH_DIR_N1_8,
)


@pytest.fixture(scope="module")
def engine_results():
    engine = N1_7LifecycleEngine()
    return engine.run_lifecycle_analysis()


def test_invariant_1_interleaved_quote_batch_updates(engine_results):
    """Invariant 1: Multiple assets updated in an interleaved quote batch update only matching positions."""
    populations = engine_results.get("populations", {})
    compliant = populations.get("N1_8_POLICY_COMPLIANT_REPLAY", {})
    active = compliant.get("active_lifecycles", [])

    assert len(active) == 2
    symbols = {p["contract_symbol"] for p in active}
    assert symbols == {"BNBUSD_270326", "BTCUSD_270326"}

    # Each position's spot price must match its own coin's range, not another coin
    bnb_pos = next(p for p in active if p["contract_symbol"] == "BNBUSD_270326")
    btc_pos = next(p for p in active if p["contract_symbol"] == "BTCUSD_270326")

    # BNB spot price should be ~680 USD, BTC spot price ~73,500 - 74,000 USD
    assert 600.0 < bnb_pos["current_spot_price"] < 800.0
    assert 70_000.0 < btc_pos["current_spot_price"] < 80_000.0


def test_invariant_2_multi_expiry_underlying_aggregation():
    """Invariant 2: Same asset across different quarterly expiries shares risk bucket and collateral budget."""
    ledger = AccountUnderlyingAllocationLedger(portfolio_capital_usd=20_000.0)

    # Leg 1: BNB Dec expiry ($5,000 notional)
    ok1, pos1, reason1 = ledger.allocate_position(
        contract_symbol="BNBUSD_261225",
        contracts=500,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=685.0,
        timestamp_ms=1000,
    )
    assert ok1 is True
    assert pos1.status == "HEDGED_HOLD"

    # Leg 2: BNB Mar expiry ($2,370 notional) shares the same underlying 'BNB'
    ok2, pos2, reason2 = ledger.allocate_position(
        contract_symbol="BNBUSD_270326",
        contracts=237,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=695.0,
        timestamp_ms=2000,
        allow_over_allocation_recording=True,
    )
    assert ok2 is False
    assert pos2.status == "RISK_ACTION_REQUIRED"

    bucket = ledger.get_or_create_bucket("BNB")
    assert bucket.underlying_asset == "BNB"
    assert len(bucket.active_contracts) == 2
    assert bucket.aggregate_committed_capital_usd == 7370.0
    assert bucket.defect_detected is True


def test_invariant_3_cross_symbol_quote_contamination_prevented():
    """Invariant 3: Extreme price movements on unrelated symbols do not mutate BNB or BTC positions."""
    engine = N1_7LifecycleEngine()
    # Mock observation dictionary with extreme XRP shock
    xrp_shock = {
        "coinm_contract_symbol": "XRPUSD_270326",
        "spot_ask_vwap": 0.0001,  # 99.99% crash
        "coinm_bid_vwap": 10.0,   # 1000% spike
        "decision_timestamp": 1794412000000,
        "quote_valid_pit": True,
        "contract_multiplier_usd": 10.0,
    }

    # Position state before shock
    bnb_pos = {
        "symbol": "BNBUSD_261225",
        "contract_symbol": "BNBUSD_261225",
        "cur_spot_vwap": 683.7082,
        "cur_fut_vwap": 689.6821,
        "last_valid_observation_timestamp": 1794411927000,
        "last_update_ms": 1794411927000,
        "entry_timestamp": 1794409639026,
    }

    # Updating with XRP shock must strictly be rejected by engine.process_observation
    ok, reason = engine.process_observation(bnb_pos, xrp_shock)
    assert ok is False
    assert reason == "CROSS_SYMBOL_IGNORED"

    # State must remain untouched
    assert bnb_pos["cur_spot_vwap"] == 683.7082
    assert bnb_pos["cur_fut_vwap"] == 689.6821


def test_invariant_4_aggregate_underlying_cap_rejection():
    """Invariant 4: Aggregate underlying cap strictly rejects over-allocation."""
    ledger = AccountUnderlyingAllocationLedger(portfolio_capital_usd=20_000.0)

    # Commit full $5,000 cap to BNB
    ok, pos, _ = ledger.allocate_position(
        contract_symbol="BNBUSD_261225",
        contracts=500,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=685.0,
        timestamp_ms=1000,
    )
    assert ok is True

    # Next BNB contract must be strictly rejected
    ok2, pos2, reason2 = ledger.allocate_position(
        contract_symbol="BNBUSD_270326",
        contracts=10,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=695.0,
        timestamp_ms=2000,
        allow_over_allocation_recording=False,
    )
    assert ok2 is False
    assert pos2 is None
    assert "EXCEEDS_AGGREGATE_UNDERLYING_CAP" in reason2


def test_invariant_5_duplicate_collateral_consumption_blocked():
    """Invariant 5: Collateral allocated to one position cannot be credited to another position."""
    ledger = AccountUnderlyingAllocationLedger(portfolio_capital_usd=20_000.0)
    ledger.allocate_position(
        contract_symbol="BNBUSD_261225",
        contracts=500,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=685.0,
        timestamp_ms=1000,
    )
    ledger.allocate_position(
        contract_symbol="BNBUSD_270326",
        contracts=237,
        contract_size_usd=10.0,
        spot_price=680.0,
        fut_price=695.0,
        timestamp_ms=2000,
        allow_over_allocation_recording=True,
    )

    bucket = ledger.get_or_create_bucket("BNB")
    pos1 = bucket.active_contracts[0]
    pos2 = bucket.active_contracts[1]

    # Each contract tracks its own distinct coin collateral requirement
    assert pos1.allocated_coin_collateral > 0
    assert pos2.allocated_coin_collateral > 0
    # Sum of collateral must equal aggregate, not shared
    assert abs((pos1.allocated_coin_collateral + pos2.allocated_coin_collateral) - bucket.aggregate_collateral_coin) < 1e-9


def test_invariant_6_deterministic_replay_and_restart_idempotency():
    """Invariant 6: Consecutive replays over the same forward dataset produce identical results."""
    engine1 = N1_7LifecycleEngine()
    res1 = engine1.run_lifecycle_analysis()

    engine2 = N1_7LifecycleEngine()
    res2 = engine2.run_lifecycle_analysis()

    # Compare scorecards and position counts
    sc1 = res1["scorecard"]
    sc2 = res2["scorecard"]
    assert sc1["actively_tracked_lifecycles_count"] == sc2["actively_tracked_lifecycles_count"]
    assert sc1["total_open_unrealized_pnl_usd"] == sc2["total_open_unrealized_pnl_usd"]
    assert sc1["capital_utilization_pct"] == sc2["capital_utilization_pct"]

    # Active lifecycles bitwise match
    act1 = res1["active_lifecycles"]
    act2 = res2["active_lifecycles"]
    assert len(act1) == len(act2)
    for p1, p2 in zip(act1, act2):
        assert p1["contract_symbol"] == p2["contract_symbol"]
        assert p1["current_unrealized_pnl_usd"] == p2["current_unrealized_pnl_usd"]
        assert p1["current_mtm_equity_usd"] == p2["current_mtm_equity_usd"]


def test_invariant_7_missing_or_stale_quote_handling():
    """Invariant 7: Stale quotes are blocked from updating valuation timestamps."""
    engine = N1_7LifecycleEngine()
    pos = {
        "symbol": "BTCUSD_270326",
        "contract_symbol": "BTCUSD_270326",
        "last_valid_observation_timestamp": 1000,
        "entry_timestamp": 1000,
        "last_update_ms": 1000,
        "cur_spot_vwap": 73500.0,
    }

    # Stale observation with quote_valid_pit = False
    stale_quote = {
        "coinm_contract_symbol": "BTCUSD_270326",
        "decision_timestamp": 5000,
        "quote_valid_pit": False,  # age or skew exceeded
        "spot_ask_vwap": 74000.0,
    }

    ok, reason = engine.process_observation(pos, stale_quote)
    assert ok is False
    assert reason == "STALE_QUOTE_IGNORED"

    # Position must NOT have updated from stale quote
    assert pos["last_valid_observation_timestamp"] == 1000
    assert pos["cur_spot_vwap"] == 73500.0


def test_invariant_8_separated_original_and_compliant_populations(engine_results):
    """Invariant 8: Two explicitly identified populations exist with correct ledgers and defect auditability."""
    populations = engine_results.get("populations", {})
    assert "N1_7_AS_RECORDED" in populations
    assert "N1_8_POLICY_COMPLIANT_REPLAY" in populations

    # 1. Original Population
    orig = populations["N1_7_AS_RECORDED"]
    assert len(orig["active_lifecycles"]) == 3
    assert orig["deployed_capital_usd"] == 12370.0
    assert orig["total_unrealized_pnl_usd"] == -167.96
    assert len(orig["defect_notes"]) >= 2

    # 2. Compliant Population
    comp = populations["N1_8_POLICY_COMPLIANT_REPLAY"]
    assert len(comp["active_lifecycles"]) == 2
    assert len(comp["quarantined_lifecycles"]) == 1
    assert comp["deployed_capital_usd"] == 7370.0
    assert comp["capital_utilization_pct"] == 36.85
    assert comp["disposition"] == "VERIFIED_ACCUMULATING"

    # Quarantined lifecycle is preserved without silent erasure
    quarantined = comp["quarantined_lifecycles"][0]
    assert quarantined["contract_symbol"] == "BNBUSD_261225"
    assert quarantined["state"] in ("RISK_ACTION_REQUIRED", "INVALIDATED")
    assert quarantined["lifecycle_status"] == "QUARANTINED"
    assert "EXCEEDS_AGGREGATE_UNDERLYING_CAP" in quarantined["quarantine_reason"]
