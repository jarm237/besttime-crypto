from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2


def test_feature_store_creates_layers_and_metadata(tmp_path):
    store = FeatureStoreV2(root=tmp_path / "feature_store")
    store.ensure_structure()

    table = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "BTC", "feature_x": 1.0},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "BTC", "feature_x": 2.0},
        ]
    )

    out_path = store.save_table(table, layer="clean", name="unit_test_features", fmt="csv")
    assert out_path.exists()

    loaded = store.load_table(layer="clean", name="unit_test_features")
    assert len(loaded) == 2
    assert set(loaded.columns) == {"timestamp", "coin", "feature_x"}

    meta = store.register_feature_metadata(
        {
            "feature_name": "feature_x",
            "group": "technical",
            "source": "unit_test",
            "is_point_in_time_safe": True,
            "requires_lag": True,
            "lag_bars": 1,
        }
    )
    assert meta["feature_name"] == "feature_x"

    all_meta = store.load_feature_metadata()
    assert "feature_x" in all_meta


def test_dataset_version_written(tmp_path):
    store = FeatureStoreV2(root=tmp_path / "feature_store")
    store.ensure_structure()

    dataset = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "BTC", "f1": 1.0, "label": 1},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "ETH", "f1": 0.5, "label": -1},
        ]
    )

    version = store.write_dataset_version(
        dataset,
        label_type="triple_barrier_meta",
        lookahead_bars=48,
        timeframe="15m",
        feature_groups=["technical", "regime"],
    )

    assert version.row_count == 2
    assert version.feature_count == 4
    assert version.source_hash
    assert store.dataset_version_index.exists()
