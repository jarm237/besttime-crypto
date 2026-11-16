"""Tests for CarmMarketDataProvider read-only market data adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from btc_scraper.research.carm_market_data import (
    CANONICAL_UNIVERSE,
    CarmMarketDataProvider,
    MarketDataObservation,
)


def test_market_data_provider_offline_mock():
    """Verify parsing and validation of ticker observations."""
    provider = CarmMarketDataProvider()
    mock_payload = [
        {"symbol": "BTCUSDT", "price": "65000.50"},
        {"symbol": "ETHUSDT", "price": "3500.00"},
        {"symbol": "SOLUSDT", "price": "140.25"},
        {"symbol": "ADAUSDT", "price": "-1.0"},  # invalid negative
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        prices, observations = provider.fetch_live_ticker_snapshot(universe=["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"])

    assert "BTCUSDT" in prices
    assert prices["BTCUSDT"] == 65000.50
    assert "ADAUSDT" not in prices  # negative price excluded from valid prices

    obs_map = {o.symbol: o for o in observations}
    assert obs_map["BTCUSDT"].data_quality == "VALID"
    assert obs_map["ADAUSDT"].data_quality == "INVALID_PRICE"
    assert obs_map["BTCUSDT"].is_forward is True
    assert obs_map["BTCUSDT"].source == "BINANCE_PUBLIC_REST"


def test_create_warmup_observations():
    """Verify historical warmup observations are strictly tagged is_forward=False."""
    prices = {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}
    warmup_obs = CarmMarketDataProvider.create_warmup_observations(prices, "2026-01-01T00:00:00Z")

    assert len(warmup_obs) == 2
    for o in warmup_obs:
        assert o.is_forward is False
        assert o.data_quality == "VALID"
        assert o.price_type == "SPOT_HISTORICAL_CLOSE"
