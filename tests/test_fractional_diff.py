from __future__ import annotations

import numpy as np
import pandas as pd

from btc_scraper.feature_engineering.fractional_diff import FractionalDiffBuilder, FractionalDiffConfig


def test_fractional_diff_generates_features_and_report():
    rows = []
    for i in range(60):
        rows.append({"entry_time": f"2026-01-01 {i // 4:02d}:{(i % 4) * 15:02d}", "coin": "BTC", "close": 100 + i * 0.5})
        rows.append({"entry_time": f"2026-01-01 {i // 4:02d}:{(i % 4) * 15:02d}", "coin": "ETH", "close": 80 + i * 0.3})

    df = pd.DataFrame(rows)
    builder = FractionalDiffBuilder(
        FractionalDiffConfig(d_candidates=[0.0, 0.2, 0.4], min_valid_ratio=0.05, max_weight_size=64)
    )
    out = builder.build(df, timeframe="15m")
    report = builder.get_report()

    assert "fracdiff_price" in out.columns
    assert "fracdiff_return_1" in out.columns
    assert "fracdiff_d_selected" in out.columns
    assert out["fracdiff_d_selected"].notna().all()
    assert report["enabled"] is True
    assert len(report["coins"]) == 2


def test_fractional_diff_can_be_disabled_via_config():
    df = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:00:00Z", "coin": "BTC", "close": 100.0},
            {"timestamp": "2026-01-01T00:15:00Z", "coin": "BTC", "close": 101.0},
        ]
    )
    builder = FractionalDiffBuilder(FractionalDiffConfig(enabled=False))
    out = builder.build(df, timeframe="15m")
    report = builder.get_report()

    assert "fracdiff_price" not in out.columns
    assert report["enabled"] is False
