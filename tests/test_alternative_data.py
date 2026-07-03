import json
import unittest
from datetime import datetime, timezone

from btc_scraper.collectors.alternative_data import (
    collect_alternative_data,
    load_alternative_data,
    normalize_alternative_payload,
)
from btc_scraper.core.world_state import WorldState, MarketRegime, LiquidityRegime
from btc_scraper.core.feature_snapshot import FeatureSnapshot


def test_collect_alternative_data_writes_defaults(tmp_path):
    output_path = tmp_path / "alternative_data.json"

    payload = collect_alternative_data(output_path=str(output_path), force=True)

    assert payload["timestamp"]
    assert payload["exchange_netflow"] == 0.0
    assert payload["whale_score"] == 0.0
    assert payload["stablecoin_supply"] == 0.0
    assert output_path.exists()

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["exchange_netflow"] == 0.0


def test_world_state_roundtrip_preserves_alternative_layer():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_ON, liquidity_regime=LiquidityRegime.HIGH)
    state.alternative.exchange_netflow = -125000.0
    state.alternative.whale_score = 0.82
    state.alternative.options_iv = 0.31

    payload = state.to_dict()
    restored = WorldState.from_dict(payload)

    assert restored.alternative.exchange_netflow == -125000.0
    assert restored.alternative.whale_score == 0.82
    assert restored.alternative.options_iv == 0.31
    assert restored.alternative.stablecoin_supply_total == 0.0
    assert restored.alternative.open_interest_pressure == 0.0


def test_load_alternative_data_returns_defaults_when_missing(tmp_path):
    missing_path = tmp_path / "missing.json"
    data = load_alternative_data(str(missing_path))

    assert data["exchange_netflow"] == 0.0
    assert data["whale_score"] == 0.0


def test_normalize_alternative_payload_builds_derived_features(tmp_path):
    payload = {
        "timestamp": "2026-07-02T00:00:00+00:00",
        "exchange_netflow": -120000.0,
        "whale_score": 0.72,
        "stablecoin_supply": 1000000000.0,
        "etf_flow": 2500000.0,
        "options_iv": 0.35,
        "funding_rate": 0.012,
        "open_interest": 1000000.0,
        "dxy": 104.0,
        "vix": 25.0,
        "us10y": 4.2,
        "gold": 2000.0,
    }

    normalized = normalize_alternative_payload(
        payload,
        previous_payload={
            "stablecoin_supply": 900000000.0,
            "etf_flow": 1000000.0,
            "exchange_netflow": -100000.0,
            "funding_rate": 0.004,
            "open_interest": 900000.0,
        },
        raw_store_dir=str(tmp_path / "raw_alternative"),
    )

    assert normalized["liquidity_pressure"] >= 0.0
    assert normalized["macro_pressure"] >= 0.0
    assert normalized["risk_on_score"] >= 0.0
    assert normalized["stablecoin_momentum"] != 0.0
    assert normalized["etf_momentum"] != 0.0
    assert normalized["stablecoin_supply_total"] == 0.0
    assert normalized["chain_tvl"] == 0.0
    assert normalized["defi_liquidity_score"] == 0.0
    assert normalized["macro_risk_score"] == 0.0
    assert normalized["open_interest_pressure"] == 0.0
    assert normalized["large_tx_proxy_score"] == 0.0
    assert normalized["options_iv_rank"] == 0.0
    assert normalized["options_skew"] == 0.0
    assert (tmp_path / "raw_alternative").exists()


def test_collect_alternative_data_exports_snapshot(tmp_path):
    output_path = tmp_path / "alternative_data.json"
    snapshot_path = tmp_path / "alternative_feature_snapshot.json"

    payload = collect_alternative_data(
        output_path=str(output_path),
        force=True,
        raw_store_dir=str(tmp_path / "raw_alternative"),
        feature_snapshot_path=str(snapshot_path),
    )

    assert output_path.exists()
    assert snapshot_path.exists()
    assert payload["timestamp"]
    assert payload["stablecoin_supply_total"] == 0.0
    assert payload["chain_tvl"] == 0.0
    assert payload["defi_liquidity_score"] == 0.0
    assert payload["macro_risk_score"] == 0.0
    assert payload["open_interest_pressure"] == 0.0
    assert payload["large_tx_proxy_score"] == 0.0
    assert payload["options_iv_rank"] == 0.0
    assert payload["options_skew"] == 0.0


class AlternativeSnapshotSchemaTest(unittest.TestCase):
    def test_feature_snapshot_includes_alternative_layer(self):
        state = WorldState(timestamp=datetime.utcnow(), regime=MarketRegime.RISK_ON, liquidity_regime=LiquidityRegime.HIGH)
        snapshot = FeatureSnapshot(
            snapshot_id="test_alt_snapshot",
            timestamp=state.timestamp,
            world_state=state.to_dict(),
        )

        self.assertIn("alternative", snapshot.world_state)
        self.assertEqual(snapshot.world_state["alternative"]["stablecoin_supply_total"], 0.0)
        self.assertIn("chain_tvl", snapshot.world_state["alternative"])
