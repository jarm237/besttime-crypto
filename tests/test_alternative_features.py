from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.alternative_features import AlternativeFeatureBuilder


def test_alternative_features_preserve_missing_values_and_add_flags():
    df = pd.DataFrame(
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "coin": "BTC",
                "exchange_netflow": 1200.0,
                "funding_rate": 0.01,
                "open_interest": 1000.0,
                "dxy": 104.0,
                "vix": 18.0,
                "us10y": 4.0,
                "sentiment_score": 0.2,
                "social_sentiment": 0.1,
            },
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "coin": "ETH",
                "exchange_netflow": None,
                "funding_rate": 0.02,
                "open_interest": 800.0,
                "dxy": 104.0,
                "vix": 19.0,
                "us10y": 4.1,
                "sentiment_score": 0.3,
                "social_sentiment": 0.15,
            },
            {
                "timestamp": "2026-01-01T00:15:00Z",
                "coin": "BTC",
                "exchange_netflow": 900.0,
                "funding_rate": 0.015,
                "open_interest": 1050.0,
                "dxy": 104.3,
                "vix": 20.0,
                "us10y": 4.2,
                "sentiment_score": 0.25,
                "social_sentiment": 0.18,
            },
        ]
    )

    builder = AlternativeFeatureBuilder()
    out = builder.build(df)

    generated = [col for col in out.columns if col.startswith("alt_")]
    assert len(generated) >= 20
    assert out.loc[out["coin"] == "ETH", "exchange_netflow"].isna().all()
    assert out.loc[out["coin"] == "ETH", "exchange_netflow__missing"].eq(1).all()
    assert out[generated].isna().sum().sum() > 0


def test_alternative_features_quality_report_contains_missing_metrics():
    df = pd.DataFrame(
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "coin": "BTC",
                "funding_rate": 0.01,
                "open_interest": None,
            },
            {
                "timestamp": "2026-01-01T00:15:00Z",
                "coin": "BTC",
                "funding_rate": None,
                "open_interest": 1100.0,
            },
        ]
    )

    builder = AlternativeFeatureBuilder()
    out = builder.build(df)
    report = builder.get_quality_report()

    assert report["input_rows"] == 2
    assert report["output_rows"] == len(out)
    assert report["generated_feature_count"] >= 20
    assert "missing_before" in report
    assert "funding_rate" in report["missing_before"]
    assert "open_interest" in report["missing_before"]
