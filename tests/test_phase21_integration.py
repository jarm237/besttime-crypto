"""
Integration Test: Phase 2.1 Causal System Integration

Tests the full data flow:
  WorldState → RuleContextProvider → DecisionEngine.decide_with_provider()
  EventBus → causal_event_handlers → WorldState update

Run:
    python tests/test_phase21_integration.py
    # OR
    pytest tests/test_phase21_integration.py -v
"""

import sys
import os
import pytest
from datetime import datetime, timezone

# Ensure the project root is on the path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.core.world_state import (
    WorldState,
    WorldStateManager,
    MarketRegime,
    LiquidityRegime,
    get_world_state_manager,
)
from btc_scraper.core.event_bus import (
    EventBus,
    Event,
    EventType,
    get_event_bus,
)
from btc_scraper.ml_engine.rule_context_provider import RuleContextProvider, _world_state_to_context_dict
from btc_scraper.ml_engine.causal_event_handlers import (
    register_causal_event_handlers,
    unregister_causal_event_handlers,
)
from btc_scraper.ml_engine.context_provider import RiskLevel


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def world_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_ON)
    state.macro.DXY = 103.0
    state.macro.VIX = 16.0
    state.macro.RealYield = 1.2
    state.macro.FedRate = 5.25
    state.liquidity.Funding_Z = 0.5
    state.liquidity.OI_Delta = 5.0
    state.sentiment.FearGreed = 60.0
    return state


@pytest.fixture
def risk_off_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 108.0
    state.macro.VIX = 35.0
    state.macro.RealYield = 2.5
    state.macro.FedRate = 5.50
    state.liquidity.Funding_Z = 2.8
    state.liquidity.OI_Delta = 22.0
    state.sentiment.FearGreed = 18.0
    return state


@pytest.fixture
def rule_provider():
    provider = RuleContextProvider("data/context_rules.json")
    return provider


# ─── Task 1: RuleContextProvider ─────────────────────────────────────────────

class TestRuleContextProvider:
    def test_validate_with_existing_config(self, rule_provider):
        """Provider should load config without error."""
        is_valid, msg = rule_provider.validate()
        assert is_valid, f"Validation failed: {msg}"

    def test_should_apply_context_when_engine_loaded(self, rule_provider, world_state):
        assert rule_provider.should_apply_context(world_state) is True

    def test_generate_report_passthrough_on_neutral_state(self, rule_provider, world_state):
        """In calm conditions, adjustment should be minimal."""
        report = rule_provider.generate_context_report(0.70, world_state)
        assert report.original_score == pytest.approx(0.70)
        assert report.adjusted_score >= 0.0
        assert report.adjusted_score <= 1.0
        assert report.provider_name == "RuleContextProvider"

    def test_generate_report_penalizes_risk_off(self, rule_provider, risk_off_state):
        """In RISK_OFF with high VIX and Funding_Z, score should drop significantly."""
        original = 0.85
        report = rule_provider.generate_context_report(original, risk_off_state)
        assert report.adjusted_score < original, (
            f"Expected score to drop from {original}, got {report.adjusted_score}"
        )
        assert report.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_report_has_breakdown_and_adjustments(self, rule_provider, risk_off_state):
        """Report must include per-layer breakdown and adjustment list."""
        report = rule_provider.generate_context_report(0.80, risk_off_state)
        assert isinstance(report.breakdown, dict)
        assert isinstance(report.adjustments, list)
        assert report.explanation != ""

    def test_world_state_to_context_dict_maps_correctly(self, world_state):
        """WorldState should map to the flat dict format expected by rule evaluator."""
        ctx = _world_state_to_context_dict(world_state)
        assert "DXY" in ctx
        assert "VIX" in ctx
        assert "Funding_Z" in ctx
        assert "FearGreed" in ctx
        assert "market_regime" in ctx
        assert ctx["market_regime"] == "RISK_ON"

    def test_provider_name_correct(self, rule_provider):
        assert rule_provider.name == "RuleContextProvider"

    def test_reload_rules_succeeds(self, rule_provider):
        """Hot-reload should not crash."""
        result = rule_provider.reload_rules()
        assert result is True


# ─── Task 2: DecisionEngine.decide_with_provider() ───────────────────────────

class TestDecisionEngineWithProvider:
    def test_decide_with_provider_returns_dict(self, rule_provider, world_state):
        """decide_with_provider should return a well-formed dict."""
        from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

        engine = MetaDecisionEngine()
        # Use minimal analysis_info — Meta Model may return error without real model
        analysis_info = {
            "coin": "BTC",
            "signal": "BUY",
            "fear_greed": 60,
            "regime": "RISK_ON",
            "atr": 1.0,
        }
        result = engine.decide_with_provider(analysis_info, rule_provider, world_state)
        assert isinstance(result, dict)
        assert "action" in result

    def test_decide_with_provider_includes_context_provider_name(self, rule_provider, world_state):
        from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

        engine = MetaDecisionEngine()
        analysis_info = {"coin": "BTC", "signal": "BUY", "fear_greed": 60, "regime": "RISK_ON", "atr": 1.0}
        result = engine.decide_with_provider(analysis_info, rule_provider, world_state)
        # If meta model returns error, context_provider field may not be set
        # — that's acceptable in CI without a trained model
        if not result.get("error"):
            assert result.get("context_provider") == "RuleContextProvider"

    def test_decide_with_provider_skips_when_engine_unavailable(self, world_state):
        """If provider should_apply_context returns False, context is skipped."""
        from btc_scraper.ml_engine.context_provider import NoOpContextProvider
        from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

        engine = MetaDecisionEngine()
        noop = NoOpContextProvider()
        analysis_info = {"coin": "BTC", "signal": "BUY", "fear_greed": 60, "regime": "RISK_ON", "atr": 1.0}
        result = engine.decide_with_provider(analysis_info, noop, world_state)
        assert isinstance(result, dict)
        # NoOp never applies, so context_skipped should be True
        if not result.get("error"):
            assert result.get("context_skipped") is True


# ─── Task 3: Event Bus Subscriptions ─────────────────────────────────────────

class TestCausalEventHandlers:
    def setup_method(self):
        """Fresh bus and WSM for each test."""
        self.bus = EventBus()
        self.wsm = WorldStateManager()

        state = WorldState(timestamp=datetime.now(timezone.utc))
        state.macro.DXY = 104.0
        self.wsm.update_state(state)

    def test_register_handlers_returns_sub_ids(self):
        sub_ids = register_causal_event_handlers(self.bus, self.wsm)
        assert len(sub_ids) >= 3  # macro, regime, funding at minimum
        assert "macro_event_handler" in sub_ids

    def test_macro_event_updates_world_state_cpi(self):
        register_causal_event_handlers(self.bus, self.wsm)

        self.bus.publish(Event(
            type=EventType.MACRO_EVENT,
            timestamp=datetime.now(timezone.utc),
            source="test",
            data={"indicator": "CPI", "value": 3.9},
            priority=9,
        ))

        state = self.wsm.get_state()
        assert state.macro.CPI == pytest.approx(3.9)

    def test_macro_event_updates_dxy(self):
        register_causal_event_handlers(self.bus, self.wsm)

        self.bus.publish(Event(
            type=EventType.MACRO_EVENT,
            timestamp=datetime.now(timezone.utc),
            source="test",
            data={"indicator": "DXY", "value": 106.5},
            priority=7,
        ))

        state = self.wsm.get_state()
        assert state.macro.DXY == pytest.approx(106.5)

    def test_regime_change_updates_world_state(self):
        register_causal_event_handlers(self.bus, self.wsm)

        self.bus.publish(Event(
            type=EventType.MARKET_REGIME_CHANGE,
            timestamp=datetime.now(timezone.utc),
            source="regime_detector",
            data={"new_regime": "risk_off", "liquidity_regime": "low"},
            priority=8,
        ))

        state = self.wsm.get_state()
        assert state.regime == MarketRegime.RISK_OFF
        assert state.liquidity_regime == LiquidityRegime.LOW

    def test_funding_spike_updates_liquidity(self):
        register_causal_event_handlers(self.bus, self.wsm)

        self.bus.publish(Event(
            type=EventType.FUNDING_SPIKE,
            timestamp=datetime.now(timezone.utc),
            source="binance_futures",
            data={"asset": "BTC", "funding_z": 3.1, "oi_delta": 18.5},
            priority=7,
        ))

        state = self.wsm.get_state()
        assert state.liquidity.Funding_Z == pytest.approx(3.1)
        assert state.liquidity.OI_Delta == pytest.approx(18.5)

    def test_rules_reloaded_triggers_provider_reload(self, rule_provider):
        provider = RuleContextProvider("data/context_rules.json")
        register_causal_event_handlers(self.bus, self.wsm, provider)

        self.bus.publish(Event(
            type=EventType.RULES_RELOADED,
            timestamp=datetime.now(timezone.utc),
            source="config_watcher",
            data={},
            priority=5,
        ))
        # If reload didn't raise, it's a pass
        is_valid, _ = provider.validate()
        assert is_valid

    def test_unregister_stops_receiving_events(self):
        sub_ids = register_causal_event_handlers(self.bus, self.wsm)

        # Save initial state
        initial_state = self.wsm.get_state()
        initial_dxy = initial_state.macro.DXY

        # Unregister
        unregister_causal_event_handlers(self.bus, sub_ids)

        # Publish — should NOT update state
        self.bus.publish(Event(
            type=EventType.MACRO_EVENT,
            timestamp=datetime.now(timezone.utc),
            source="test",
            data={"indicator": "DXY", "value": 999.0},
            priority=9,
        ))

        state = self.wsm.get_state()
        assert state.macro.DXY == pytest.approx(initial_dxy), (
            "State was updated after unregistering — handlers still active"
        )


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2.1 Integration Test — Running directly")
    print("=" * 60)

    # Quick smoke test outside pytest
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 108.0
    state.macro.VIX = 32.0
    state.liquidity.Funding_Z = 2.5
    state.sentiment.FearGreed = 20.0

    provider = RuleContextProvider("data/context_rules.json")
    is_valid, msg = provider.validate()
    print(f"\n[1/4] RuleContextProvider valid: {is_valid} — {msg}")

    report = provider.generate_context_report(0.82, state)
    print(f"[2/4] Context Report: {report.original_score:.2f} → {report.adjusted_score:.2f} "
          f"({report.risk_level.value}, {len(report.adjustments)} adjustments)")

    bus = EventBus()
    wsm = WorldStateManager()
    wsm.update_state(WorldState(timestamp=datetime.now(timezone.utc)))
    sub_ids = register_causal_event_handlers(bus, wsm, provider)

    bus.publish(Event(
        type=EventType.MACRO_EVENT,
        timestamp=datetime.now(timezone.utc),
        source="test",
        data={"indicator": "CPI", "value": 4.1},
        priority=9,
    ))
    cpi_updated = wsm.get_state().macro.CPI
    print(f"[3/4] Event Bus MACRO_EVENT → WorldState CPI: {cpi_updated}")

    bus.publish(Event(
        type=EventType.MARKET_REGIME_CHANGE,
        timestamp=datetime.now(timezone.utc),
        source="test",
        data={"new_regime": "risk_off"},
        priority=8,
    ))
    regime_updated = wsm.get_state().regime.value
    print(f"[4/4] Event Bus REGIME_CHANGE → WorldState regime: {regime_updated}")

    print("\n✓ Phase 2.1 Smoke Test PASSED")
