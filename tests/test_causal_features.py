from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.causal_features import CausalFeatureBuilder


def test_causal_feature_builder_maps_risk_and_one_hot():
    df = pd.DataFrame(
        [
            {
                "coin": "BTC",
                "entry_time": "2026-01-01 00:00",
                "context_risk_level": "HIGH",
                "context_adjustment": -0.12,
                "causal_num_rules_fired": 3,
                "delta_pnl": 1.4,
            }
        ]
    )

    out = CausalFeatureBuilder().build(df)

    assert out.iloc[0]["causal_risk_level"] == "HIGH"
    assert out.iloc[0]["causal_risk_HIGH"] == 1
    assert out.iloc[0]["causal_risk_raw"] > 0.5
    assert out.iloc[0]["causal_context_adjustment"] == -0.12
    assert out.iloc[0]["cf_delta_pnl"] == 1.4


def test_causal_feature_builder_defaults_when_missing():
    df = pd.DataFrame([{"coin": "ETH", "entry_time": "2026-01-01 00:15"}])

    out = CausalFeatureBuilder().build(df)

    assert out.iloc[0]["causal_risk_level"] == "LOW"
    assert out.iloc[0]["causal_risk_LOW"] == 1
    assert out.iloc[0]["causal_alpha"] == 0.0
    assert out.iloc[0]["causal_num_rules_fired"] == 0
