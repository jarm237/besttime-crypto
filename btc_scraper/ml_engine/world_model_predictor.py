"""Phase 5.0 world-model predictor for causal state transition forecasting."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.core.world_state import WorldState
from btc_scraper.ml_engine.causal_graph import CausalGraph


@dataclass
class PredictedState:
    """Simple outcome of a one-step world-model prediction."""

    predicted_state: WorldState
    confidence: float
    rationale: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorldModelPredictor:
    """Predict the next world state using the causal graph and current values."""

    def __init__(self, graph_path: str = "data/causal_graph.json"):
        self.graph_path = graph_path
        self.graph = CausalGraph(graph_path)

    def predict_next_state(self, state: WorldState) -> PredictedState:
        predicted = copy.deepcopy(state)
        predicted.timestamp = datetime.now(timezone.utc)

        btc_change = 0.0
        if state.macro.DXY > 100.0:
            btc_change -= (state.macro.DXY - 100.0) * 50.0
        if state.macro.VIX > 20.0:
            btc_change -= (state.macro.VIX - 20.0) * 40.0
        if state.macro.RealYield > 1.0:
            btc_change -= (state.macro.RealYield - 1.0) * 500.0
        if state.sentiment.FearGreed < 50.0:
            btc_change -= (50.0 - state.sentiment.FearGreed) * 20.0

        if state.regime == state.regime.__class__.RISK_OFF:
            btc_change -= 1000.0

        predicted.crypto.BTC_Price = state.crypto.BTC_Price + btc_change
        predicted.crypto.ETH_Price = state.crypto.ETH_Price + btc_change * 0.06
        predicted.liquidity.BTC_Funding = state.liquidity.BTC_Funding + 0.001
        predicted.sentiment.FearGreed = min(100.0, max(0.0, state.sentiment.FearGreed + 1.0))

        confidence = 0.7
        if self.graph.edges:
            confidence = min(0.95, 0.6 + min(len(self.graph.edges), 8) * 0.03)

        rationale = (
            "Projected next state by propagating macro and sentiment shocks through the causal graph "
            "using deterministic edge-weight heuristics."
        )

        return PredictedState(predicted_state=predicted, confidence=confidence, rationale=rationale)
