"""
Causal Event Handlers - Subscribes to Event Bus for MACRO_EVENT and REGIME_CHANGE.

This is Phase 2.1 of the Causal World Model integration.

When relevant market events occur (Fed pivot, funding spike, regime change), 
this module reacts by:
1. Updating the WorldState accordingly.
2. Logging the event for CausalMonitoring.
3. Optionally triggering a re-evaluation of the context rules.

Usage:
    from btc_scraper.ml_engine.causal_event_handlers import register_causal_event_handlers
    register_causal_event_handlers(event_bus, world_state_manager, rule_provider)
"""

import logging
from datetime import datetime
from typing import Optional

from btc_scraper.core.event_bus import EventBus, Event, EventType
from btc_scraper.core.world_state import WorldStateManager, MarketRegime, LiquidityRegime
from btc_scraper.ml_engine.rule_context_provider import RuleContextProvider

logger = logging.getLogger(__name__)


# ─── Handler Callbacks ────────────────────────────────────────────────────────

def _on_macro_event(
    event: Event,
    world_state_manager: WorldStateManager,
) -> None:
    """
    React to MACRO_EVENT (CPI, NFP, FOMC, etc.).

    Updates the WorldState macro layer with event data.
    High-importance events (priority >= 8) trigger additional warnings.
    """
    data = event.data
    indicator = data.get("indicator", "UNKNOWN")
    value = data.get("value")
    priority = event.priority

    logger.info(
        f"[CausalEvent] MACRO_EVENT received: {indicator}={value} "
        f"(priority={priority}, source={event.source})"
    )

    state = world_state_manager.get_state()
    if state is None:
        logger.warning("[CausalEvent] WorldState not initialized — skipping macro update")
        return

    # Update relevant macro fields from the event payload
    if indicator == "CPI" and value is not None:
        state.macro.CPI = float(value)
    elif indicator == "NFP" and value is not None:
        state.macro.NFP = float(value)
    elif indicator in ("FedRate", "FED_RATE") and value is not None:
        state.macro.FedRate = float(value)
    elif indicator == "DXY" and value is not None:
        state.macro.DXY = float(value)
    elif indicator == "VIX" and value is not None:
        state.macro.VIX = float(value)
    elif indicator in ("BondYield", "US10Y") and value is not None:
        state.macro.BondYield = float(value)

    state.macro.updated_at = datetime.utcnow()
    world_state_manager.update_state(state)

    if priority >= 8:
        logger.warning(
            f"[CausalEvent] HIGH PRIORITY macro event: {indicator}={value} — "
            f"Context Engine should re-evaluate signal scores."
        )


def _on_regime_change(
    event: Event,
    world_state_manager: WorldStateManager,
) -> None:
    """
    React to MARKET_REGIME_CHANGE events.

    Updates WorldState.regime and liquidity_regime. This causes Context Engine
    to re-evaluate conditional rules (e.g., edges with condition='market_regime == BEAR').
    """
    data = event.data
    new_regime_str = data.get("new_regime", "unknown").lower()
    new_liquidity_str = data.get("liquidity_regime", "normal").lower()

    logger.info(
        f"[CausalEvent] REGIME_CHANGE: regime={new_regime_str}, "
        f"liquidity={new_liquidity_str} (source={event.source})"
    )

    state = world_state_manager.get_state()
    if state is None:
        logger.warning("[CausalEvent] WorldState not initialized — skipping regime update")
        return

    # Map string → enum
    regime_map = {
        "risk_on": MarketRegime.RISK_ON,
        "risk_off": MarketRegime.RISK_OFF,
        "transitioning": MarketRegime.TRANSITIONING,
    }
    liquidity_map = {
        "high": LiquidityRegime.HIGH,
        "normal": LiquidityRegime.NORMAL,
        "low": LiquidityRegime.LOW,
        "extreme": LiquidityRegime.EXTREME,
    }

    state.regime = regime_map.get(new_regime_str, MarketRegime.UNKNOWN)
    state.liquidity_regime = liquidity_map.get(new_liquidity_str, LiquidityRegime.NORMAL)
    world_state_manager.update_state(state)

    logger.info(
        f"[CausalEvent] WorldState updated: regime={state.regime.value}, "
        f"liquidity_regime={state.liquidity_regime.value}"
    )


def _on_funding_spike(
    event: Event,
    world_state_manager: WorldStateManager,
) -> None:
    """
    React to FUNDING_SPIKE events.

    Updates liquidity layer in WorldState so Context Engine can immediately
    apply funding rules without waiting for the next polling cycle.
    """
    data = event.data
    funding_z = data.get("funding_z")
    oi_delta = data.get("oi_delta")
    asset = data.get("asset", "BTC")

    logger.info(
        f"[CausalEvent] FUNDING_SPIKE: {asset} Funding_Z={funding_z}, "
        f"OI_Delta={oi_delta} (source={event.source})"
    )

    state = world_state_manager.get_state()
    if state is None:
        return

    if funding_z is not None:
        state.liquidity.Funding_Z = float(funding_z)
    if oi_delta is not None:
        state.liquidity.OI_Delta = float(oi_delta)

    state.liquidity.updated_at = datetime.utcnow()
    world_state_manager.update_state(state)


def _on_rules_reloaded(
    event: Event,
    rule_provider: Optional[RuleContextProvider],
) -> None:
    """
    React to RULES_RELOADED system events.

    Triggers a hot-reload of context_rules.json in the RuleContextProvider
    without requiring a bot restart.
    """
    logger.info(f"[CausalEvent] RULES_RELOADED event received from '{event.source}'")
    if rule_provider is not None:
        success = rule_provider.reload_rules()
        if success:
            logger.info("[CausalEvent] ✓ RuleContextProvider rules reloaded successfully")
        else:
            logger.error("[CausalEvent] ✗ Failed to reload RuleContextProvider rules")


# ─── Registration ─────────────────────────────────────────────────────────────

def register_causal_event_handlers(
    event_bus: EventBus,
    world_state_manager: WorldStateManager,
    rule_provider: Optional[RuleContextProvider] = None,
) -> dict[str, str]:
    """
    Register all causal system callbacks on the event bus.

    Call this once at bot startup after initializing the causal system.

    Args:
        event_bus: The global EventBus singleton.
        world_state_manager: The global WorldStateManager singleton.
        rule_provider: Optional RuleContextProvider for hot-reload support.

    Returns:
        Dict mapping subscriber name → subscription ID (for deregistration).
    """
    sub_ids: dict[str, str] = {}

    # 1. Subscribe to MACRO_EVENT (CPI, NFP, FOMC, etc.)
    sub_ids["macro_event_handler"] = event_bus.subscribe(
        name="causal_macro_handler",
        callback=lambda e: _on_macro_event(e, world_state_manager),
        event_types=[EventType.MACRO_EVENT, EventType.FED_PIVOT, EventType.ECONOMIC_SHOCK],
        min_priority=5,
    )

    # 2. Subscribe to MARKET_REGIME_CHANGE
    sub_ids["regime_change_handler"] = event_bus.subscribe(
        name="causal_regime_handler",
        callback=lambda e: _on_regime_change(e, world_state_manager),
        event_types=[EventType.MARKET_REGIME_CHANGE],
        min_priority=5,
    )

    # 3. Subscribe to FUNDING_SPIKE (crypto market micro-events)
    sub_ids["funding_spike_handler"] = event_bus.subscribe(
        name="causal_funding_handler",
        callback=lambda e: _on_funding_spike(e, world_state_manager),
        event_types=[EventType.FUNDING_SPIKE, EventType.OI_SPIKE],
        min_priority=6,
    )

    # 4. Subscribe to RULES_RELOADED (hot-reload system events)
    if rule_provider is not None:
        sub_ids["rules_reload_handler"] = event_bus.subscribe(
            name="causal_rules_reload_handler",
            callback=lambda e: _on_rules_reloaded(e, rule_provider),
            event_types=[EventType.RULES_RELOADED],
            min_priority=0,
        )

    logger.info(
        f"[CausalEvent] ✓ Registered {len(sub_ids)} causal event handlers on the bus: "
        + ", ".join(sub_ids.keys())
    )

    return sub_ids


def unregister_causal_event_handlers(
    event_bus: EventBus,
    sub_ids: dict[str, str],
) -> None:
    """
    Unregister all causal event handlers (e.g., during graceful shutdown).

    Args:
        event_bus: The global EventBus singleton.
        sub_ids: Dict returned by register_causal_event_handlers().
    """
    for name, sub_id in sub_ids.items():
        event_bus.unsubscribe(sub_id)
        logger.debug(f"[CausalEvent] Unregistered handler '{name}'")

    logger.info(f"[CausalEvent] ✓ Unregistered {len(sub_ids)} causal event handlers")


if __name__ == "__main__":
    from datetime import datetime
    from btc_scraper.core.event_bus import get_event_bus
    from btc_scraper.core.world_state import get_world_state_manager, WorldState

    # Initialize
    bus = get_event_bus()
    wsm = get_world_state_manager()

    # Create initial world state
    state = WorldState(timestamp=datetime.utcnow())
    state.macro.DXY = 104.0
    wsm.update_state(state)

    provider = RuleContextProvider("data/context_rules.json")
    sub_ids = register_causal_event_handlers(bus, wsm, provider)

    # Publish test events
    bus.publish(Event(
        type=EventType.MACRO_EVENT,
        timestamp=datetime.utcnow(),
        source="test",
        data={"indicator": "CPI", "value": 3.7},
        priority=9,
    ))

    bus.publish(Event(
        type=EventType.MARKET_REGIME_CHANGE,
        timestamp=datetime.utcnow(),
        source="regime_detector",
        data={"new_regime": "risk_off", "liquidity_regime": "low"},
        priority=8,
    ))

    updated_state = wsm.get_state()
    print(f"✓ CPI updated to: {updated_state.macro.CPI}")
    print(f"✓ Regime updated to: {updated_state.regime.value}")
    print(f"\n✓ Bus stats: {bus.get_stats()}")
