from __future__ import annotations

from types import SimpleNamespace

import pytest

from btc_scraper.core.config import (
    DEFAULT_ANALYSIS_UNIVERSE,
    analysis_universe_hash,
    get_analysis_universe,
    get_runtime_universe,
    parse_runtime_symbols,
)
from btc_scraper.ml_engine.multi_agent import MarketAnalystAgent, SignalGeneratorAgent
from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator


def test_analysis_universe_parses_normalized_symbols(monkeypatch):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", " btc, ETH ,bnb ")
    assert get_analysis_universe() == ("BTC", "ETH", "BNB")


@pytest.mark.parametrize("raw,match", [
    ("BTC,,ETH", "empty symbol"),
    ("BTC,btc", "duplicate"),
    ("BTC,NOTREAL", "unsupported"),
])
def test_analysis_universe_rejects_invalid_values(raw, match):
    with pytest.raises(ValueError, match=match):
        parse_runtime_symbols(raw, field_name="BTC_ANALYSIS_UNIVERSE")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_analysis_universe_falls_back_to_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BTC_ANALYSIS_UNIVERSE", raising=False)
    else:
        monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", value)
    assert get_analysis_universe() == DEFAULT_ANALYSIS_UNIVERSE


def test_execution_universe_must_be_analysis_subset(monkeypatch):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,BNB")
    with pytest.raises(ValueError, match="subset"):
        get_runtime_universe()


def test_execution_universe_accepts_strict_subset(monkeypatch):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH")
    universe = get_runtime_universe()
    assert universe.execution_symbols == ("BTC", "ETH")
    assert universe.analysis_hash == analysis_universe_hash(("BTC", "ETH", "BNB"))


def test_analysis_and_inference_run_only_for_configured_universe(monkeypatch):
    symbols = ("BTC", "ETH", "BNB")
    analysis_calls: list[str] = []
    inference_calls: list[str] = []

    def fake_analysis(candles, symbol):
        analysis_calls.append(symbol)
        return {
            "signal": "NEUTRAL",
            "close": candles[-1]["close"],
            "ema9": 1.0,
            "ema21": 1.0,
            "sma50": 1.0,
            "chandelier": "NEUTRAL",
        }

    class FakeCoordinator:
        def predict_once(self, analysis, *, symbol, **kwargs):
            inference_calls.append(symbol)
            return SimpleNamespace(to_dict=lambda: {})

    monkeypatch.setattr(
        "btc_scraper.ml_engine.multi_agent.analyze_market", fake_analysis
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator",
        lambda: FakeCoordinator(),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
        lambda analysis, meta_prediction=None: {
            "action": "NEUTRAL",
            "meta_confidence": 0.5,
            "kelly_fraction": 0.0,
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: {},
    )

    all_symbols = (*symbols, "SOL")
    candles = {
        symbol: [{"close": 100.0}]
        for symbol in all_symbols
    }
    mtf = {
        symbol: {
            timeframe: [{"close": 100.0}]
            for timeframe in ("1h", "4h", "1d")
        }
        for symbol in all_symbols
    }
    context = MarketAnalystAgent(symbols).run({
        "raw_candles": candles,
        "mtf_candles": mtf,
    })
    SignalGeneratorAgent().run(context)

    assert len(analysis_calls) == len(symbols) * 4
    assert set(analysis_calls) == set(symbols)
    assert inference_calls == list(symbols)
    assert set(context["analysis"]) == {
        "BTC:Binance", "ETH:Binance", "BNB:Binance",
    }


def test_inference_boundary_rejects_symbol_outside_runtime_universe(monkeypatch):
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    with pytest.raises(ValueError, match="inference_symbol_unsupported"):
        InferenceCoordinator().predict_once(
            {"observed_at": "2026-07-30T08:00:00+00:00", "signal": "BUY"},
            symbol="WLD",
        )
