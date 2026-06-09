from btc_scraper.filters import (
    atr_shock_filter,
    atr_used_for_chandelier,
    dynamic_sl_long,
    dynamic_sl_short,
    sentiment_modify,
)


def test_atr_shock_filter_detects_shock():
    assert atr_shock_filter(20.0, 10.0)
    assert not atr_shock_filter(16.0, 10.0)


def test_atr_used_for_chandelier_caps_spikes():
    assert atr_used_for_chandelier(30.0, 10.0) == 15.0
    assert atr_used_for_chandelier(8.0, 10.0) == 8.0


def test_dynamic_sl_long_and_short():
    long_sl = dynamic_sl_long(100.0, 6.0, 5.0)
    short_sl = dynamic_sl_short(110.0, 6.0, 5.0)

    assert long_sl < 100.0
    assert short_sl > 110.0
    assert isinstance(long_sl, float)
    assert isinstance(short_sl, float)


def test_sentiment_modify_limits_confidence():
    assert sentiment_modify(0.4, "BEAR", "SHORT", True) <= 0.4
    assert sentiment_modify(0.9, "BULL", "LONG", False) <= 1.0
    assert 0.0 <= sentiment_modify(0.0, "BULL", "LONG", False) <= 1.0
