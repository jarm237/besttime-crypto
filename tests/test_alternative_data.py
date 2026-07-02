import json
from datetime import datetime

from btc_scraper.collectors.alternative_data import collect_alternative_data, load_alternative_data
from btc_scraper.core.world_state import WorldState, MarketRegime, LiquidityRegime


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
    state = WorldState(timestamp=datetime.utcnow(), regime=MarketRegime.RISK_ON, liquidity_regime=LiquidityRegime.HIGH)
    state.alternative.exchange_netflow = -125000.0
    state.alternative.whale_score = 0.82
    state.alternative.options_iv = 0.31

    payload = state.to_dict()
    restored = WorldState.from_dict(payload)

    assert restored.alternative.exchange_netflow == -125000.0
    assert restored.alternative.whale_score == 0.82
    assert restored.alternative.options_iv == 0.31


def test_load_alternative_data_returns_defaults_when_missing(tmp_path):
    missing_path = tmp_path / "missing.json"
    data = load_alternative_data(str(missing_path))

    assert data["exchange_netflow"] == 0.0
    assert data["whale_score"] == 0.0
