from copy import deepcopy

import pytest

from btc_scraper.analysis import (
    SignalAction,
    analyze_all_market,
    analyze_market,
    calculate_tp_sl,
    signal_action,
)
from btc_scraper.analysis.indicators import calculate_rsi
from btc_scraper.analysis.structure import is_trend_following_allowed


def make_synthetic_candles(length: int = 260) -> list[dict]:
    candles = []
    price = 100.0
    for i in range(length):
        open_price = price
        close_price = price + (i % 5 - 2) * 0.3
        high_price = max(open_price, close_price) + 0.5
        low_price = min(open_price, close_price) - 0.5
        candles.append({
            "time": f"2024-01-01 00:{i:02d}",
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": 100.0 + i,
        })
        price += 0.1
    return candles


def test_analyze_all_market_runs_and_returns_signals():
    candles = make_synthetic_candles(260)
    results = analyze_all_market(candles)

    assert len(results) == 60
    assert all("signal" in item for item in results)
    assert all("tp_sl" in item for item in results)
    assert all("market_regime" in item for item in results)
    assert all("trend_following_allowed" in item for item in results)
    for item in results:
        if item["action"] == SignalAction.NEUTRAL.value:
            assert item["tp_sl"] == {}
            assert item["position_size"] == 0.0


def test_analyze_market_does_not_track_missed_signals():
    result = analyze_market(make_synthetic_candles(260), coin_name="BTC")

    assert "missed_signals" not in result


def test_analyze_market_preserves_producer_utc_timestamp_in_history():
    candles = make_synthetic_candles(260)
    candles[-1]["time_utc"] = "2026-08-13T10:45:00Z"

    result = analyze_market(candles, coin_name="BTC")

    assert result["history"][-1]["time_utc"] == "2026-08-13T10:45:00Z"


def test_calculate_tp_sl_directional_targets():
    long_tp = calculate_tp_sl(
        close=100.0,
        signal="BUY",
        atr=2.0,
        support=98.0,
        resistance=105.0,
        bb_upper=104.0,
        bb_middle=100.0,
        bb_lower=96.0,
    )
    short_tp = calculate_tp_sl(
        close=100.0,
        signal="SELL",
        atr=2.0,
        support=98.0,
        resistance=105.0,
        bb_upper=104.0,
        bb_middle=100.0,
        bb_lower=96.0,
    )

    assert long_tp["sl"] < 100.0
    assert long_tp["tp1"] > 100.0
    assert short_tp["sl"] > 100.0
    assert short_tp["tp1"] < 100.0


def test_trend_following_allowed_thresholds():
    assert is_trend_following_allowed(25.0, 50.0)
    assert not is_trend_following_allowed(15.0, 55.0)


@pytest.mark.parametrize("label", ["NEUTRAL", "NEUTRAL (BULLISH)", "NEUTRAL (BEARISH)"])
def test_neutral_bias_never_creates_risk_levels(label):
    assert signal_action(label) is SignalAction.NEUTRAL
    assert calculate_tp_sl(
        close=100.0,
        signal=label,
        atr=2.0,
        support=95.0,
        resistance=105.0,
        bb_upper=104.0,
        bb_middle=100.0,
        bb_lower=96.0,
    ) == {}


def test_flat_rsi_is_neutral():
    assert calculate_rsi([100.0] * 100, 14)[-1] == 50.0


def test_historical_analysis_does_not_fetch_current_sentiment(monkeypatch):
    def fail_if_called():
        raise AssertionError("historical analysis fetched current sentiment")

    monkeypatch.setattr("btc_scraper.analysis.core.get_market_sentiment", fail_if_called)
    results = analyze_all_market(make_synthetic_candles(260))

    assert results
    assert all(item["sentiment"]["score"] is None for item in results)
    assert all(item["sentiment"]["available"] is False for item in results)


def test_historical_regime_receives_atr_price_percentage(monkeypatch):
    observed_atr_pct = []

    def fake_regime(close, sma200, ema21, sma50, adx, atr_pct, cfg=None):
        observed_atr_pct.append(atr_pct)
        return {"regime": "RANGING", "confidence": 0.4}

    monkeypatch.setattr("btc_scraper.analysis.core.regime_from_values", fake_regime)
    analyze_all_market(make_synthetic_candles(260))

    # Synthetic candles have roughly 1% ATR; a percentile would commonly be 0-100.
    assert observed_atr_pct
    assert max(observed_atr_pct[200:]) < 10.0


def test_live_and_historical_latest_regime_match(monkeypatch):
    sentiment = {"normalized_score": None, "label": None, "raw_value": None}
    monkeypatch.setattr("btc_scraper.analysis.core.get_market_sentiment", lambda: sentiment)
    monkeypatch.setattr("btc_scraper.analysis.core.get_sentiment_trend", lambda **kwargs: {})
    monkeypatch.setattr("btc_scraper.analysis.core._save_sentiment_to_history", lambda value: None)
    candles = make_synthetic_candles(260)

    live = analyze_market(deepcopy(candles), coin_name="BTC")
    historical = analyze_all_market(deepcopy(candles))[-1]

    assert historical["regime"] == live["regime"]
    assert historical["regime_confidence"] == live["regime_confidence"]
