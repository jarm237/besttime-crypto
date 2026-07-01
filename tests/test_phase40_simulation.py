"""
Integration Test: Phase 4.0 Scenario Simulation & Counterfactual Analysis

Run:
    .venv/bin/pytest tests/test_phase40_simulation.py -v
"""

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.core.world_state import WorldState, MarketRegime
from btc_scraper.ml_engine.causal_simulator import CausalSimulator, Intervention, InterventionType
from btc_scraper.ml_engine.counterfactual_engine import CounterfactualEngine


@pytest.fixture
def base_state():
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 104.0
    state.macro.VIX = 20.0
    state.macro.RealYield = 1.2
    state.macro.BondYield = 4.0
    state.liquidity.BTC_Funding = 0.01
    state.liquidity.OI_Delta = 5.0
    state.crypto.BTC_Price = 50000.0
    state.crypto.ETH_Price = 3000.0
    state.sentiment.FearGreed = 45.0
    return state


def test_simulator_applies_intervention_and_propagates_to_btc(base_state):
    simulator = CausalSimulator(graph_path="data/causal_graph.json")

    intervention = Intervention(
        type=InterventionType.CUSTOM,
        target_node="DXY",
        value=5.0,
        description="USD strength shock",
    )

    simulated = simulator.simulate_intervention(base_state, intervention)

    assert simulated.intervention.target_node == "DXY"
    assert simulated.simulated_state.macro.DXY == pytest.approx(109.0)
    assert simulated.simulated_state.crypto.BTC_Price < base_state.crypto.BTC_Price
    assert "BTC" in simulated.propagated_changes


def test_counterfactual_engine_computes_delta_pnl(base_state):
    simulator = CausalSimulator(graph_path="data/causal_graph.json")
    engine = CounterfactualEngine(simulator=simulator)

    trade = {
        "symbol": "BTC",
        "entry_price": 50000.0,
        "exit_price": 51000.0,
        "size": 0.5,
        "pnl": 500.0,
    }

    intervention = Intervention(
        type=InterventionType.CUSTOM,
        target_node="DXY",
        value=5.0,
        description="USD strength shock",
    )

    result = engine.analyze_trade(trade, base_state, intervention=intervention)

    assert result["actual_pnl"] == pytest.approx(500.0)
    assert result["counterfactual_pnl"] != pytest.approx(result["actual_pnl"])
    assert "delta_pnl" in result
    assert result["delta_pnl"] != 0.0


def test_cli_intervention_parsing_supports_percentages():
    from btc_scraper.ml_engine.simulator import parse_intervention

    parsed = parse_intervention("DXY=+5%")

    assert parsed.target_node == "DXY"
    assert parsed.value == pytest.approx(5.0)
    assert parsed.description == "Intervention from CLI"
