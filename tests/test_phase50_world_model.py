"""Integration Test: Phase 5.0 Digital Twin & World Model Prediction"""

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.core.event_bus import EventBus, Event, EventType
from btc_scraper.core.world_state import WorldState, MarketRegime
from btc_scraper.ml_engine.world_model_predictor import WorldModelPredictor
from btc_scraper.ml_engine.causal_anomaly_detector import CausalAnomalyDetector


@pytest.fixture
def base_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 104.0
    state.macro.VIX = 22.0
    state.macro.RealYield = 1.2
    state.macro.BondYield = 4.0
    state.liquidity.BTC_Funding = 0.01
    state.liquidity.OI_Delta = 4.0
    state.crypto.BTC_Price = 50000.0
    state.crypto.ETH_Price = 3000.0
    state.sentiment.FearGreed = 45.0
    return state


def test_world_model_predictor_uses_graph_edges(base_state):
    predictor = WorldModelPredictor(graph_path="data/causal_graph.json")
    prediction = predictor.predict_next_state(base_state)

    assert prediction.predicted_state.crypto.BTC_Price != base_state.crypto.BTC_Price
    assert prediction.predicted_state.macro.DXY == pytest.approx(base_state.macro.DXY)
    assert prediction.confidence > 0.0


def test_anomaly_detector_flags_large_discrepancy_and_emits_event(base_state):
    predictor = WorldModelPredictor(graph_path="data/causal_graph.json")
    detector = CausalAnomalyDetector(event_bus=EventBus(), threshold=0.05)

    prediction = predictor.predict_next_state(base_state)
    observed = base_state
    observed.crypto.BTC_Price = 60000.0

    result = detector.detect(observed, prediction)

    assert result["is_anomaly"] is True
    assert result["deviation_score"] > 0.0
    assert detector.event_bus.get_stats()["total_events"] >= 1


def test_anomaly_detector_does_not_flag_small_discrepancy(base_state):
    predictor = WorldModelPredictor(graph_path="data/causal_graph.json")
    detector = CausalAnomalyDetector(event_bus=EventBus(), threshold=0.05)

    prediction = predictor.predict_next_state(base_state)
    observed = base_state
    # Set observed price to be extremely close to the expected price (e.g. 0.1% discrepancy)
    observed.crypto.BTC_Price = prediction.predicted_state.crypto.BTC_Price * 1.001

    result = detector.detect(observed, prediction)

    assert result["is_anomaly"] is False
    assert detector.event_bus.get_stats()["total_events"] == 0
