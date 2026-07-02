from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.cross_sectional_features import CrossSectionalFeatureBuilder


def test_cross_sectional_ranks_and_relative_strength_vs_btc_eth():
    df = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "BTC", "close": 100.0, "sector": "L1"},
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "ETH", "close": 50.0, "sector": "L1"},
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "ADA", "close": 25.0, "sector": "L2"},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "BTC", "close": 110.0, "sector": "L1"},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "ETH", "close": 49.0, "sector": "L1"},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "ADA", "close": 26.0, "sector": "L2"},
        ]
    )

    out = CrossSectionalFeatureBuilder().build(df)
    t2 = out[out["timestamp"] == pd.Timestamp("2026-01-01T00:15:00Z")].set_index("coin")

    assert t2.loc["BTC", "cs_rank_return_1"] == 1.0
    assert t2.loc["ETH", "cs_rank_return_1"] < t2.loc["ADA", "cs_rank_return_1"]
    assert t2.loc["ADA", "cs_rel_strength_btc"] < 0.0
    assert t2.loc["ADA", "cs_rel_strength_eth"] > 0.0
    assert t2.loc["BTC", "cs_group_rank_return_1"] == 1.0


def test_cross_sectional_builder_works_without_sector_column():
    df = pd.DataFrame(
        [
            {"entry_time": "2026-01-01 00:00", "symbol": "BTCUSDT", "return_15m": 0.1},
            {"entry_time": "2026-01-01 00:00", "symbol": "ETHUSDT", "return_15m": -0.2},
        ]
    )

    out = CrossSectionalFeatureBuilder().build(df)

    for col in [
        "cs_rank_return_1",
        "cs_rel_strength_btc",
        "cs_rel_strength_eth",
        "cs_group_rank_return_1",
        "cs_group_excess_return_1",
    ]:
        assert col in out.columns
    assert out[col].isna().sum() == 0
