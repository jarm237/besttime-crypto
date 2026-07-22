"""
Integration Test: Phase C/D — CausalContextBridge + CounterfactualEngine hook
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.ml_engine.causal_context_bridge import (
    build_world_state_from_ana,
    enhance_signal_with_causal_context,
    get_decision_engine,
    get_hybrid_provider,
)


@pytest.fixture
def buy_ana():
    return {
        "signal": "STRONG BUY (Breakout)",
        "close": 65000.0,
        "rsi": 62.0,
        "ema9": 64800.0,
        "ema21": 64200.0,
        "regime": "TRENDING_BULL",
        "fear_greed": 72.0,
        "funding_rate": 0.01,
        "oi_delta": 5.0,
        "atr": 800.0,
        "htf_trend": "BULLISH",
    }


@pytest.fixture
def sell_ana():
    return {
        "signal": "STRONG SELL (Confirmed Reversal)",
        "close": 60000.0,
        "rsi": 28.0,
        "ema9": 60200.0,
        "ema21": 61000.0,
        "regime": "RANGING",
        "fear_greed": 25.0,
        "funding_rate": -0.02,
        "oi_delta": -8.0,
        "atr": 1200.0,
        "htf_trend": "BEARISH",
    }


# ─── build_world_state_from_ana ───────────────────────────────────────────────

class TestBuildWorldState:
    def test_buy_signal_sets_risk_on(self, buy_ana):
        from btc_scraper.core.world_state import MarketRegime
        state = build_world_state_from_ana(buy_ana)
        assert state is not None
        assert state.regime == MarketRegime.RISK_ON

    def test_sell_signal_sets_risk_off(self, sell_ana):
        from btc_scraper.core.world_state import MarketRegime
        state = build_world_state_from_ana(sell_ana)
        assert state is not None
        assert state.regime == MarketRegime.RISK_OFF

    def test_fear_greed_populated(self, buy_ana):
        state = build_world_state_from_ana(buy_ana)
        assert state.sentiment.FearGreed == 72.0

    def test_btc_price_populated(self, buy_ana):
        state = build_world_state_from_ana(buy_ana)
        assert state.crypto.BTC_Price == 65000.0

    def test_graceful_on_empty_dict(self):
        state = build_world_state_from_ana({})
        assert state is not None  # should not raise

    def test_alternative_data_is_not_loaded_into_decision_state(self, buy_ana, monkeypatch):
        def fail_if_loaded(*args, **kwargs):
            raise AssertionError("decision path must not load Alternative Data")

        monkeypatch.setattr(
            "btc_scraper.collectors.alternative_data.load_alternative_data",
            fail_if_loaded,
        )
        state = build_world_state_from_ana(buy_ana)
        assert state is not None
        assert state.alternative.decision_eligible is False
        assert state.alternative.risk_on_score is None


# ─── get_hybrid_provider (singleton) ─────────────────────────────────────────

class TestHybridProviderSingleton:
    def test_returns_provider(self):
        provider = get_hybrid_provider(alpha=0.0)
        assert provider is not None

    def test_singleton_same_object(self):
        p1 = get_hybrid_provider(alpha=0.0)
        p2 = get_hybrid_provider(alpha=0.0)
        assert p1 is p2

    def test_provider_has_name(self):
        provider = get_hybrid_provider(alpha=0.0)
        assert hasattr(provider, "name")


# ─── enhance_signal_with_causal_context ──────────────────────────────────────

class TestEnhanceSignal:
    def test_returns_dict(self, buy_ana):
        result = enhance_signal_with_causal_context(
            ana=buy_ana,
            analysis_info={**buy_ana},
            alpha=0.0,
        )
        assert isinstance(result, dict)

    def test_graceful_on_bad_input(self):
        result = enhance_signal_with_causal_context(
            ana={},
            analysis_info={},
            alpha=0.0,
        )
        assert isinstance(result, dict)  # should not raise

    def test_no_error_key_on_success(self, buy_ana):
        result = enhance_signal_with_causal_context(
            ana=buy_ana,
            analysis_info={**buy_ana},
            alpha=0.0,
        )
        # If provider succeeds, result should not contain top-level error
        if result:
            assert "action" in result or "context_skipped" in result

    def test_reference_payload_is_removed_from_decision_input(self, buy_ana, monkeypatch):
        captured = {}

        class FakeProvider:
            def should_apply_context(self, world_state):
                return False

        class FakeEngine:
            def decide_with_provider(self, analysis_info, provider, state):
                captured.update(analysis_info)
                return {"action": "HOLD"}

        monkeypatch.setattr(
            "btc_scraper.ml_engine.causal_context_bridge.get_hybrid_provider",
            lambda alpha=None: FakeProvider(),
        )
        monkeypatch.setattr(
            "btc_scraper.ml_engine.causal_context_bridge.get_decision_engine",
            lambda: FakeEngine(),
        )

        result = enhance_signal_with_causal_context(
            ana=buy_ana,
            analysis_info={
                **buy_ana,
                "alternative_data_reference": {
                    "mode": "reference_only",
                    "values": {"risk_on_score": -1.0},
                },
            },
            alpha=0.0,
        )

        assert result["action"] == "HOLD"
        assert "alternative_data_reference" not in captured


# ─── CounterfactualEngine integration via bridge ──────────────────────────────

class TestCounterfactualBridge:
    def test_counterfactual_on_losing_trade(self, sell_ana):
        from btc_scraper.ml_engine.counterfactual_engine import CounterfactualEngine

        trade = {
            "coin": "BTC",
            "pnl_pct": -1.2,
            "pnl": -120.0,
            "entry_price": 61000.0,
            "exit_price": 60000.0,
            "size": 0.1,
        }
        state = build_world_state_from_ana(sell_ana)
        engine = CounterfactualEngine()
        result = engine.analyze_trade(trade, state)

        assert isinstance(result, dict)
        assert "actual_pnl" in result
        assert "counterfactual_pnl" in result
        assert "delta_pnl" in result
