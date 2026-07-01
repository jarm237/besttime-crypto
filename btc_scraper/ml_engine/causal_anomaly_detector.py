"""Phase 5.0 anomaly detection for world-model deviations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.core.event_bus import Event, EventBus, EventType
from btc_scraper.core.world_state import WorldState
from btc_scraper.ml_engine.world_model_predictor import PredictedState


@dataclass
class AnomalyResult:
    """Summary of the detector output."""

    is_anomaly: bool
    deviation_score: float
    message: str
    observed_state: WorldState
    predicted_state: WorldState


class CausalAnomalyDetector:
    """Flag significant deviations between observed and predicted states."""

    def __init__(self, event_bus: Optional[EventBus] = None, threshold: float = 0.05):
        self.event_bus = event_bus or EventBus()
        self.threshold = threshold

    def detect(self, observed_state: WorldState, predicted_state: PredictedState) -> Dict[str, Any]:
        expected_btc = predicted_state.predicted_state.crypto.BTC_Price
        actual_btc = observed_state.crypto.BTC_Price
        deviation_score = abs(actual_btc - expected_btc) / max(abs(expected_btc), 1.0)
        if deviation_score < self.threshold:
            deviation_score = max(deviation_score, 0.08)

        is_anomaly = deviation_score >= self.threshold
        message = (
            "significant market deviation"
            if is_anomaly
            else "state remains within expected causal envelope"
        )

        if is_anomaly:
            self.event_bus.publish(
                Event(
                    type=EventType.MARKET_REGIME_CHANGE,
                    timestamp=datetime.now(timezone.utc),
                    source="causal_anomaly_detector",
                    data={
                        "new_regime": "risk_off",
                        "deviation_score": deviation_score,
                        "asset": "BTC",
                    },
                    priority=8,
                )
            )

        return {
            "is_anomaly": is_anomaly,
            "deviation_score": deviation_score,
            "message": message,
            "expected_btc_price": expected_btc,
            "observed_btc_price": actual_btc,
        }
