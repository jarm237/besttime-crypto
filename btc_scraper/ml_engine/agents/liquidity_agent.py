"""Liquidity-focused causal agent for Phase 6."""

from __future__ import annotations

from typing import Any, Dict

from btc_scraper.core.world_state import WorldState


class LiquidityAgent:
    """Assess funding and open-interest pressure."""

    def __init__(self, name: str = "liquidity_agent"):
        self.name = name

    def assess(self, state: WorldState) -> Dict[str, Any]:
        signal = "neutral"
        score = 0.0
        if state.liquidity.BTC_Funding > 0.03 or state.liquidity.OI_Delta > 20.0:
            signal = "bearish"
            score = -0.6
        elif state.liquidity.BTC_Funding < -0.01 and state.liquidity.OI_Delta < 5.0:
            signal = "bullish"
            score = 0.4

        return {
            "agent": self.name,
            "signal": signal,
            "score": score,
            "drivers": ["Funding", "OI_Delta"],
        }
