from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.dataset_builder_v3 import DatasetBuilderV3, DatasetBuilderV3Config


def test_dataset_builder_v3_builds_dataset_with_labels_and_features(tmp_path):
    base = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "result": "WIN", "pnl_pct": 1.2},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "result": "LOSS", "pnl_pct": -0.7},
            {"coin": "ETH", "entry_time": "2026-01-01 00:15", "result": "WIN", "pnl_pct": 0.5},
        ]
    )

    regime = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "regime_bull_trend": 1},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "regime_bull_trend": 0},
            {"coin": "ETH", "entry_time": "2026-01-01 00:15", "regime_bull_trend": 1},
        ]
    )

    alt = pd.DataFrame(
        [
            {"timestamp": "2026-01-01 00:00", "alt_macro_stress_composite": 0.3},
            {"timestamp": "2026-01-01 00:15", "alt_macro_stress_composite": 0.5},
        ]
    )

    builder = DatasetBuilderV3(DatasetBuilderV3Config(timeframe="15m", lookahead_bars=48, label_type="tb_meta"))
    dataset = builder.build(base, {"regime": regime, "alternative": alt})

    assert len(dataset) == 3
    assert "result" in dataset.columns
    assert "pnl_pct" in dataset.columns
    assert "regime_bull_trend" in dataset.columns
    assert "alt_macro_stress_composite" in dataset.columns

    out_path = tmp_path / "ml_dataset_v3.parquet"
    dataset_path, metadata_path, metadata = builder.persist(dataset, out_path, output_format="parquet")
    assert dataset_path.exists()
    assert metadata_path.exists()
    assert metadata["dataset_version"]["row_count"] == 3


def test_dataset_builder_v3_point_in_time_backward_join():
    base = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:10", "result": "WIN"},
            {"coin": "BTC", "entry_time": "2026-01-01 00:20", "result": "LOSS"},
        ]
    )
    feat = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "f_regime": 1},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "f_regime": 2},
        ]
    )

    builder = DatasetBuilderV3()
    ds = builder.build(base, {"regime": feat})

    assert list(ds["f_regime"]) == [1, 2]
