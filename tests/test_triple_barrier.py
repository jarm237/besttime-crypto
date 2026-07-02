from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.triple_barrier import TripleBarrierConfig, TripleBarrierLabeler


def _base_signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "signal_raw": "BUY", "atr": 1.0},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "signal_raw": "SELL", "atr": 1.0},
        ]
    )


def _base_candles() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"time": "2026-01-01 00:00", "open": 100.0, "high": 101.2, "low": 99.7, "close": 100.5},
            {"time": "2026-01-01 00:15", "open": 100.5, "high": 103.0, "low": 100.4, "close": 102.8},
            {"time": "2026-01-01 00:30", "open": 102.8, "high": 103.1, "low": 98.0, "close": 98.3},
            {"time": "2026-01-01 00:45", "open": 98.3, "high": 99.0, "low": 97.8, "close": 98.1},
        ]
    )


def test_triple_barrier_labels_long_and_short_paths():
    labeler = TripleBarrierLabeler(
        TripleBarrierConfig(
            max_holding_bars=3,
            tp_atr_mult=2.0,
            sl_atr_mult=1.0,
            min_rr=1.0,
        )
    )

    out = labeler.label(signals=_base_signals(), candles=_base_candles())

    # First row BUY at 100.5 with TP distance 2.0 -> TP should hit on second bar.
    assert out.iloc[0]["triple_barrier_label"] == 1
    assert out.iloc[0]["triple_barrier_reason"] == "take_profit"

    # Second row SELL at 102.8 with TP distance 2.0 -> low 98.0 hits TP for short.
    assert out.iloc[1]["triple_barrier_label"] == 1
    assert out.iloc[1]["triple_barrier_reason"] == "take_profit"


def test_triple_barrier_handles_neutral_signal():
    signals = pd.DataFrame(
        [{"coin": "BTC", "entry_time": "2026-01-01 00:00", "signal_raw": "NEUTRAL", "atr": 1.0}]
    )
    candles = _base_candles()

    labeler = TripleBarrierLabeler(TripleBarrierConfig(max_holding_bars=2, min_rr=1.0))
    out = labeler.label(signals=signals, candles=candles)

    assert out.iloc[0]["triple_barrier_label"] == 0
    assert out.iloc[0]["triple_barrier_reason"] == "neutral_signal"
