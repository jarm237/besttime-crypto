"""Counterfactual analysis helpers for Phase 4.0."""

from __future__ import annotations

from typing import Any, Dict, Optional

from btc_scraper.core.world_state import WorldState
from btc_scraper.ml_engine.causal_simulator import CausalSimulator, SimulatedWorldState
from btc_scraper.ml_engine.scenario_interface import Intervention, InterventionType


class CounterfactualEngine:
    """Compare actual trade outcomes with intervention-based counterfactuals."""

    def __init__(self, simulator: Optional[CausalSimulator] = None):
        self.simulator = simulator or CausalSimulator()

    def analyze_trade(
        self,
        trade: Dict[str, Any],
        base_state: WorldState,
        intervention: Optional[Intervention] = None,
    ) -> Dict[str, Any]:
        actual_pnl = float(trade.get("pnl", 0.0))
        entry_price = float(trade.get("entry_price", 0.0))
        exit_price = float(trade.get("exit_price", 0.0))
        size = float(trade.get("size", 1.0))

        if intervention is None:
            intervention = Intervention(
                type=InterventionType.CUSTOM,
                target_node="DXY",
                value=5.0,
                description="default counterfactual shock",
            )

        simulated: SimulatedWorldState = self.simulator.simulate_intervention(base_state, intervention)
        btc_delta = simulated.simulated_state.crypto.BTC_Price - base_state.crypto.BTC_Price
        counterfactual_exit = exit_price + btc_delta
        counterfactual_pnl = (counterfactual_exit - entry_price) * size

        return {
            "trade": trade,
            "actual_pnl": actual_pnl,
            "counterfactual_pnl": counterfactual_pnl,
            "delta_pnl": counterfactual_pnl - actual_pnl,
            "intervention": intervention.to_dict(),
            "simulated_state": simulated.to_dict(),
        }
