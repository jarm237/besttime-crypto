from btc_scraper.analysis import analyze_all_market, calculate_tp_sl, is_trend_following_allowed


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
