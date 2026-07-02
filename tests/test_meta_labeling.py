from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.meta_labeling import MetaLabeler, MetaLabelingConfig


def test_meta_labeling_marks_confirmed_direction_as_execute():
    df = pd.DataFrame(
        [
            {
                "coin": "BTC",
                "entry_time": "2026-01-01 00:00",
                "signal_raw": "BUY (Crossover)",
                "triple_barrier_label": 1,
                "barrier_return_pct": 2.0,
                "barrier_mae_pct": -0.8,
                "barrier_hold_bars": 6,
                "htf_trend": "BULLISH",
            }
        ]
    )

    out = MetaLabeler().label(df)
    assert out.iloc[0]["meta_label"] == 1.0
    assert out.iloc[0]["meta_label_reason"] == "direction_confirmed_by_triple_barrier"


def test_meta_labeling_marks_neutral_as_nan_when_excluded():
    df = pd.DataFrame(
        [
            {
                "coin": "ETH",
                "entry_time": "2026-01-01 00:15",
                "signal_raw": "NEUTRAL (BULLISH)",
                "triple_barrier_label": 0,
                "barrier_return_pct": 0.0,
                "barrier_mae_pct": -0.3,
                "barrier_hold_bars": 12,
            }
        ]
    )

    out = MetaLabeler(MetaLabelingConfig(exclude_neutral=True)).label(df)
    assert pd.isna(out.iloc[0]["meta_label"])
    assert out.iloc[0]["meta_label_reason"] == "neutral_or_non_executable"


def test_trade_quality_bucket_ordering():
    df = pd.DataFrame(
        [
            {
                "coin": "SOL",
                "entry_time": "2026-01-01 00:00",
                "signal_raw": "SELL (Reversal)",
                "triple_barrier_label": -1,
                "barrier_return_pct": 4.0,
                "barrier_mae_pct": -0.3,
                "barrier_hold_bars": 4,
                "htf_trend": "BEARISH",
            },
            {
                "coin": "SOL",
                "entry_time": "2026-01-01 00:15",
                "signal_raw": "SELL (Reversal)",
                "triple_barrier_label": 1,
                "barrier_return_pct": -2.5,
                "barrier_mae_pct": -3.5,
                "barrier_hold_bars": 48,
                "htf_trend": "BULLISH",
            },
        ]
    )

    out = MetaLabeler().label(df)
    assert out.iloc[0]["trade_quality_score"] > out.iloc[1]["trade_quality_score"]
    assert out.iloc[0]["trade_quality_bucket"] in {"A", "B", "C"}
    assert out.iloc[1]["trade_quality_bucket"] in {"C", "D"}
