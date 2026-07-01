"""Sentiment-focused causal agent for Phase 6."""

from __future__ import annotations

from typing import Any, Dict

from btc_scraper.core.world_state import WorldState


class SentimentAgent:
    """Assess crowd sentiment and social pressure."""

    def __init__(self, name: str = "sentiment_agent"):
        self.name = name

    def assess(self, state: WorldState) -> Dict[str, Any]:
        signal = "neutral"
        score = 0.0
        if state.sentiment.FearGreed < 30.0:
            signal = "bullish"
            score = 0.6
        elif state.sentiment.FearGreed > 75.0:
            signal = "bearish"
            score = -0.4

        return {
            "agent": self.name,
            "signal": signal,
            "score": score,
            "drivers": ["FearGreed"],
        }
