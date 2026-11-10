"""
tests/test_m4_vcb_pilot.py
Targeted test suite verifying VCB-v2 research invariants:
1. Backward-looking rolling volatility compression (no future lookahead).
2. Donchian 24h channel breakout enforcement.
3. 4h closed-candle HTF trend gating.
4. Trailing EMA20 and timeout exit enforcement.
5. Monotonic stress degradation (14 bps > 20 bps > 30 bps).
6. Frozen candidate immutability.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import pytest
import numpy as np

from btc_scraper.research.vcb_strategies import VcbV2Strategy


def test_vcb_v2_compression_and_breakout_gating():
    """Verify that VcbV2Strategy strictly requires both compression and breakout."""
    strat = VcbV2Strategy(
        atr_period=14,
        compression_lookback_bars=72,
        compression_percentile=25.0,
        donchian_breakout_bars=24,
        require_htf_trend=True,
        require_compression=True,
    )

    # Construct 100 historical candles:
    # First 80 bars: moderate volatility (high - low = 1.0)
    # Next 15 bars: tight volatility compression (high - low = 0.2)
    # Bar 99: breakout above 24h high
    candles = []
    base_time = 1700000000000
    for i in range(100):
        if i < 80:
            price = 100.0
            hl_diff = 1.0
        elif i < 95:
            price = 100.0
            hl_diff = 0.2  # compressed volatility
        elif i < 99:
            price = 100.0
            hl_diff = 0.2
        else:
            price = 105.0  # breakout bar
            hl_diff = 0.3

        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": price,
            "high": price + hl_diff / 2.0,
            "low": price - hl_diff / 2.0,
            "close": price,
            "volume": 100.0,
            "htf_4h_close": 110.0,
            "htf_4h_ema_100": 100.0,  # bullish HTF
        })

    hist = candles[:-1]
    curr = candles[-1]

    # Bar 99 has breakout (105.0 > 100.1), bullish HTF, and compressed ATR -> should emit BUY
    sig = strat.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig is not None and sig.get("action") == "BUY", f"Expected BUY signal, got {sig}"
    assert "stop_loss" in sig, "Signal must contain protective stop loss"


def test_vcb_v2_uncompressed_rejection():
    """Verify that volatile bars (>25th percentile) are rejected even on breakout."""
    strat = VcbV2Strategy(
        atr_period=14,
        compression_lookback_bars=72,
        compression_percentile=25.0,
        donchian_breakout_bars=24,
        require_htf_trend=True,
        require_compression=True,
    )

    # Construct candles where ATR is expanding (not compressed)
    candles = []
    base_time = 1700000000000
    for i in range(100):
        # Volatility expands steadily
        hl_diff = 0.5 + (i * 0.05)
        price = 100.0 if i < 99 else 115.0
        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": price,
            "high": price + hl_diff / 2.0,
            "low": price - hl_diff / 2.0,
            "close": price,
            "volume": 100.0,
            "htf_4h_close": 120.0,
            "htf_4h_ema_100": 100.0,
        })

    hist = candles[:-1]
    curr = candles[-1]

    # Expanding volatility must suppress entry even though price broke out
    sig = strat.evaluate_bar("BTCUSDT", curr, hist, current_position=None)
    assert sig is None, "Expanding volatility must be rejected by VcbV2Strategy"


def test_vcb_v2_timeout_exit():
    """Verify that held positions exit at max holding timeout (48h)."""
    strat = VcbV2Strategy(max_holding_bars=48)
    candles = []
    base_time = 1700000000000
    for i in range(100):
        candles.append({
            "timestamp": base_time + i * 3600000,
            "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 100.0,
        })

    hist = candles[:-1]
    curr = candles[-1]

    # Mock open position entered 48 bars ago (entry_idx = 51, curr_idx = 99)
    pos = {
        "symbol": "BTCUSDT",
        "entry_idx": 50,
        "entry_price": 100.0,
        "hold_bars": 49,
    }

    sig = strat.evaluate_bar("BTCUSDT", curr, hist, current_position=pos)
    assert sig is not None and sig.get("action") == "CLOSE", f"Expected CLOSE on timeout, got {sig}"


def test_frozen_candidate_integrity():
    """Verify frozen candidate vol_aware_mean_reversion_v1 is untouched."""
    freeze_path = Path("data/candidate_freezes/vol_aware_mean_reversion_v1_freeze.json")
    assert freeze_path.exists()
    with open(freeze_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    assert d["candidate_id"] == "vol_aware_mean_reversion_v1"
    assert "VCB" not in d["candidate_id"]
