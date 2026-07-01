"""Integration Test: Phase 6.0 Multi-Agent Causal Collaboration"""

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.core.world_state import WorldState, MarketRegime
from btc_scraper.ml_engine.agents.macro_agent import MacroAgent
from btc_scraper.ml_engine.agents.liquidity_agent import LiquidityAgent
from btc_scraper.ml_engine.agents.sentiment_agent import SentimentAgent
from btc_scraper.ml_engine.agents.consensus_engine import CausalConsensusEngine


@pytest.fixture
def state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 108.0
    state.macro.RealYield = 2.0
    state.liquidity.BTC_Funding = 0.04
    state.liquidity.OI_Delta = 25.0
    state.sentiment.FearGreed = 20.0
    return state


def test_agents_emit_coherent_views(state):
    macro = MacroAgent().assess(state)
    liquidity = LiquidityAgent().assess(state)
    sentiment = SentimentAgent().assess(state)

    assert macro["signal"] == "bearish"
    assert liquidity["signal"] == "bearish"
    assert sentiment["signal"] == "bullish"


def test_consensus_engine_blends_agent_signals(state):
    engine = CausalConsensusEngine(graph_path="data/causal_graph.json")
    reports = [
        MacroAgent().assess(state),
        LiquidityAgent().assess(state),
        SentimentAgent().assess(state),
    ]
    decision = engine.decide(state, reports)

    assert decision["signal"] == "bearish"
    assert decision["score"] < 0.0
