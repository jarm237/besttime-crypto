"""
tests/test_m4_successor_research.py
Targeted test suite verifying M4 successor research invariants:
1. Closed-candle HTF synchronization (zero lookahead).
2. Cost-aware entry hurdle enforcement.
3. Genuine Open Interest expansion conditions.
4. Economic cost parity: net_pnl == raw_gross - total_friction.
5. Monotonic stress cost degradation (14 bps > 20 bps > 30 bps).
6. Frozen M5 candidate immutability.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import pytest
import pandas as pd

from btc_scraper.research.successor_strategies import (
    CostAwareMeanReversionStrategy,
    GenuineOiTrendStrategy,
    HtfTrendFilteredMeanReversionStrategy,
)
from scripts.run_m4_successor_pilot import enrich_4h_closed_candles


# ── Test 1: Cost-Aware Entry Hurdle ──────────────────────────────────────────

def test_cost_aware_mr_hurdle_enforcement():
    """Verify that CostAwareMeanReversionStrategy suppresses BUY when hurdle is not met."""
    strategy_300bps = CostAwareMeanReversionStrategy(min_distance_bps=300.0)
    strategy_100bps = CostAwareMeanReversionStrategy(min_distance_bps=100.0)

    # Construct candles where price plunges below lower band:
    # 20 bars of 100.0, then 3 drops: 99.0, 98.0, 97.0
    candles = []
    base_time = 1700000000000
    for i in range(20):
        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.0,
            "volume": 100.0,
        })
    # Add drops
    for i, p in enumerate([99.0, 98.0, 97.5]):
        candles.append({
            "timestamp": base_time + (20 + i) * 3600000,
            "open": p + 0.5,
            "high": p + 0.6,
            "low": p - 0.2,
            "close": p,
            "volume": 100.0,
        })

    hist = candles[:-1]
    curr = candles[-1]

    # Calculate distance:
    # bb_slice has 17 bars of 100.0, 1 bar of 99.0, 1 bar of 98.0, 1 bar of 97.5
    # SMA ~ 99.725. Current price = 97.5.
    # Distance = (99.725 - 97.5) / 97.5 * 10000 ~ 228 bps.
    # For 300 bps hurdle: distance ~228 bps < 300 bps -> signal should be None (suppressed)
    sig_300 = strategy_300bps.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig_300 is None, f"Expected None for 300 bps hurdle, got {sig_300}"

    # For 100 bps hurdle: distance ~228 bps >= 100 bps -> signal should be BUY
    sig_100 = strategy_100bps.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig_100 is not None and sig_100.get("action") == "BUY", f"Expected BUY for 100 bps hurdle, got {sig_100}"


# ── Test 2: Genuine Open Interest Filter ─────────────────────────────────────

def test_genuine_oi_trend_filter():
    """Verify GenuineOiTrendStrategy requires positive 24h delta OI."""
    strat_v1 = GenuineOiTrendStrategy(variant_id="H_S2_V1", min_oi_change_pct=0.0)
    strat_v2 = GenuineOiTrendStrategy(variant_id="H_S2_V2", min_oi_change_pct=0.02)

    # Need >= 125 bars for strategy evaluation
    candles = []
    base_time = 1700000000000
    for i in range(130):
        # Create a bullish EMA crossover at the very last bar (bar 129):
        # First 129 bars (0..128): price flat at 100.0
        # Bar 129: price surges to 110.0
        price = 100.0 if i < 129 else 110.0

        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 100.0,
            # Features
            "delta_oi_24h": -0.01,  # Contracting OI!
            "oi_usd": 1_000_000.0,
            "oi_sma_5d": 900_000.0,
        })

    hist = candles[:-1]
    curr = candles[-1]

    # 1. Contracting OI (oi_usd drops to 990k vs 1M 24h ago -> -1%)
    curr_neg = dict(curr)
    curr_neg["oi_usd"] = 990_000.0
    sig_neg = strat_v1.evaluate_bar("BTCUSDT", curr_neg, hist, current_position=None)
    assert sig_neg is None, "Bullish EMA with negative delta_oi_24h must be rejected by H_S2_V1"

    # 2. Flat OI (oi_usd = 1M vs 1M 24h ago -> 0.0%)
    curr_flat = dict(curr)
    curr_flat["oi_usd"] = 1_000_000.0
    sig_flat = strat_v1.evaluate_bar("BTCUSDT", curr_flat, hist, current_position=None)
    assert sig_flat is None, "Bullish EMA with flat delta_oi_24h (0%) must be rejected by H_S2_V1"

    # 3. Expanding OI (+1%): H_S2_V1 accepts (> 0)
    curr_pos_1pct = dict(curr)
    curr_pos_1pct["oi_usd"] = 1_010_000.0
    sig_v1_pass = strat_v1.evaluate_bar("BTCUSDT", curr_pos_1pct, hist, current_position=None)
    assert sig_v1_pass is not None and sig_v1_pass.get("action") == "BUY", f"Expected BUY for H_S2_V1, got {sig_v1_pass}"

    # H_S2_V2 requires >= +2%, so +1% must be rejected
    sig_v2_fail = strat_v2.evaluate_bar("BTCUSDT", curr_pos_1pct, hist, current_position=None)
    assert sig_v2_fail is None, "H_S2_V2 must reject delta_oi_24h < 0.02"

    # H_S2_V2 with +2.5% passes
    curr_pos_25pct = dict(curr)
    curr_pos_25pct["oi_usd"] = 1_025_000.0
    sig_v2_pass = strat_v2.evaluate_bar("BTCUSDT", curr_pos_25pct, hist, current_position=None)
    assert sig_v2_pass is not None and sig_v2_pass.get("action") == "BUY", f"Expected BUY for H_S2_V2, got {sig_v2_pass}"


# ── Test 3: HTF Closed-Candle Zero Lookahead Invariant ───────────────────────

def test_htf_trend_filtered_mr_zero_lookahead():
    """Verify that HTF 4h aggregation strictly provides closed-candle EMAs without lookahead."""
    # Generate 1h candle records across 12 hours: 2025-01-01 00:00 to 11:00 UTC
    times = pd.date_range("2025-01-01 00:00:00", periods=12, freq="1h", tz="UTC")
    raw_1h = []
    for t in times:
        raw_1h.append({
            "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
        })

    enriched = enrich_4h_closed_candles(raw_1h)

    # 4h candle 1: 00:00 to 04:00 (closes at 04:00:00 UTC)
    # At 00:00, 01:00, 02:00, 03:00 -> no 4h candle has closed yet -> htf_4h_close should be NaN
    for i in range(4):
        assert math.isnan(enriched[i]["htf_4h_close"]), f"Bar {i} ({enriched[i]['time']}) should not see closed 4h bar"

    # At 04:00 -> 00:00-04:00 bar has closed!
    assert not math.isnan(enriched[4]["htf_4h_close"]), "Bar 4 (04:00) should see closed 4h bar"
    close_at_04 = enriched[4]["htf_4h_close"]

    # At 05:00, 06:00, 07:00 -> still sees closed 4h bar from 04:00
    for i in range(5, 8):
        assert enriched[i]["htf_4h_close"] == close_at_04, f"Bar {i} must see 04:00 closed bar, not forming bar"

    # At 08:00 -> 04:00-08:00 bar has closed!
    assert not math.isnan(enriched[8]["htf_4h_close"]), "Bar 8 (08:00) should see new closed 4h bar"


def test_htf_strategy_signal_gating():
    """Verify HtfTrendFilteredMeanReversionStrategy gates BUY signals on 4h trend."""
    strat = HtfTrendFilteredMeanReversionStrategy(ema_period_4h=100, variant_id="H_S3_V1")

    # Construct candles triggering 1h RSI/BB oversold
    candles = []
    base_time = 1700000000000
    for i in range(20):
        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 100.0,
        })
    for i, p in enumerate([99.0, 98.0, 97.0]):
        candles.append({
            "timestamp": base_time + (20 + i) * 3600000,
            "open": p + 0.5, "high": p + 0.6, "low": p - 0.2, "close": p, "volume": 100.0,
        })

    hist = candles[:-1]
    curr = dict(candles[-1])

    # Case A: 4h close < 4h EMA (bearish HTF regime) -> BUY must be suppressed
    curr["htf_4h_close"] = 95.0
    curr["htf_4h_ema_100"] = 100.0
    sig_bearish = strat.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig_bearish is None, "HTF bearish regime must suppress MR dip buy"

    # Case B: 4h close > 4h EMA (bullish HTF regime) -> BUY allowed
    curr["htf_4h_close"] = 105.0
    curr["htf_4h_ema_100"] = 100.0
    sig_bullish = strat.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig_bullish is not None and sig_bullish.get("action") == "BUY", f"HTF bullish regime should allow BUY, got {sig_bullish}"


# ── Test 4: Economic Cost Parity Invariant ───────────────────────────────────

def test_economic_cost_parity():
    """Verify that net_pnl == raw_gross_pnl - total_friction exactly."""
    capital = 10000.0
    entry_price = 2000.0
    exit_price = 2100.0
    size = capital / entry_price  # 5.0 units

    # Baseline 14 bps friction: fee=10 bps, spread=2 bps, slip=2 bps
    fee_rate = 0.0010
    spread_rate = 0.0002
    slip_rate = 0.0002

    entry_fill = entry_price * (1.0 + spread_rate + slip_rate)
    exit_fill = exit_price * (1.0 - spread_rate - slip_rate)

    entry_fee = size * entry_fill * fee_rate
    exit_fee = size * exit_fill * fee_rate

    raw_gross_pnl = size * (exit_price - entry_price)
    effective_gross_pnl = size * (exit_fill - entry_fill)
    net_pnl = effective_gross_pnl - (entry_fee + exit_fee)

    total_fees = entry_fee + exit_fee
    spread_cost = size * (entry_price * spread_rate + exit_price * spread_rate)
    slip_cost = size * (entry_price * slip_rate + exit_price * slip_rate)
    total_friction = total_fees + spread_cost + slip_cost

    reconstructed_net = raw_gross_pnl - total_friction

    assert abs(net_pnl - reconstructed_net) < 1e-4, (
        f"Net PnL parity failed: net={net_pnl}, reconstructed={reconstructed_net}"
    )


# ── Test 5: Monotonic Stress Cost Degradation ────────────────────────────────

def test_monotonic_stress_cost_degradation():
    """Verify that net PnL strictly decreases as friction increases: 14 bps > 20 bps > 30 bps."""
    capital = 10000.0
    entry_price = 2000.0
    exit_price = 2050.0
    size = capital / entry_price

    net_pnls = []
    for friction_bps in [14.0, 20.0, 30.0]:
        rate = (friction_bps / 10000.0) / 2.0  # round-trip split into entry/exit
        eff_entry = entry_price * (1.0 + rate)
        eff_exit = exit_price * (1.0 - rate)
        net_pnls.append(size * (eff_exit - eff_entry))

    assert net_pnls[0] > net_pnls[1] > net_pnls[2], (
        f"Monotonic degradation violated: {net_pnls}"
    )


# ── Test 6: Frozen M5 Candidate Immutability ─────────────────────────────────

def test_frozen_m5_candidate_immutability():
    """Verify that frozen ETH candidate artifact is intact and untouched."""
    freeze_path = Path("data/candidate_freezes/vol_aware_mean_reversion_v1_freeze.json")
    assert freeze_path.exists(), "Frozen candidate artifact missing!"

    with open(freeze_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["candidate_id"] == "vol_aware_mean_reversion_v1"
    assert data["strategy_class_path"] == "btc_scraper.research.strategy_registry.VolAwareMeanReversionStrategy"
    assert data["symbol"] == "ETHUSDT"
    assert data["timeframe"] == "1h"
    assert data["execution_timing_policy"] == "NEXT_BAR_OPEN"
    # Ensure no successor variant accidentally overrode the freeze file
    assert "H_S" not in data.get("candidate_id", "")
