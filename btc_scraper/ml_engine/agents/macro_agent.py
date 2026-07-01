"""Macro-focused causal agent for Phase 6."""

from __future__ import annotations

from typing import Any, Dict

from btc_scraper.core.world_state import WorldState


class MacroAgent:
    """Assess macro regime pressure and emit a directional view."""

    def __init__(self, name: str = "macro_agent"):
        self.name = name

    def assess(self, state: WorldState) -> Dict[str, Any]:
        signal = "neutral"
        score = 0.0
        if state.macro.DXY > 105.0 or state.macro.RealYield > 1.5:
            signal = "bearish"
            score = -0.7
        elif state.macro.DXY < 100.0 and state.macro.RealYield < 1.0:
            signal = "bullish"
            score = 0.5

        return {
            "agent": self.name,
            "signal": signal,
            "score": score,
            "drivers": ["DXY", "RealYield", "BondYield"],
        }
