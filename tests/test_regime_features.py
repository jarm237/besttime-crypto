from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.regime_features import RegimeFeatureBuilder


def test_regime_feature_builder_duration_and_one_hot():
    df = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "regime": "BULLISH", "rsi": 60.0, "atr_pct": 1.0},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "regime": "BULLISH", "rsi": 62.0, "atr_pct": 1.1},
            {"coin": "BTC", "entry_time": "2026-01-01 00:30", "regime": "BEARISH", "rsi": 45.0, "atr_pct": 2.5},
        ]
    )

    out = RegimeFeatureBuilder().build(df)

    assert list(out["regime_duration_bars"]) == [1, 2, 1]
    assert out.iloc[0]["regime_bull_trend"] == 1
    assert out.iloc[2]["regime_bear_trend"] == 1
    assert out.iloc[2]["regime_high_vol"] == 1


def test_regime_interaction_features_exist():
    df = pd.DataFrame(
        [
            {
                "coin": "ETH",
                "entry_time": "2026-01-01 00:00",
                "regime": "BULLISH",
                "rsi": 55.0,
                "funding_rate": 0.01,
                "dxy": 104.0,
                "oi_delta": 12.0,
                "orderbook_imbalance": 0.2,
                "atr_pct": 2.3,
            }
        ]
    )

    out = RegimeFeatureBuilder().build(df)

    for col in [
        "rsi_x_regime_bull",
        "funding_x_regime_risk_on",
        "dxy_x_regime_risk_off",
        "oi_delta_x_high_vol",
        "orderbook_imbalance_x_trend",
    ]:
        assert col in out.columns
