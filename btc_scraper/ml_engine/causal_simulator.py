"""Phase 4.0 causal simulator for interventions and counterfactual propagation."""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from btc_scraper.core.world_state import WorldState
from btc_scraper.ml_engine.causal_graph import CausalGraph
from btc_scraper.ml_engine.scenario_interface import Intervention, InterventionType


@dataclass
class SimulatedWorldState:
    """Result of a causal intervention simulation."""

    original_state: WorldState
    simulated_state: WorldState
    intervention: Intervention
    propagated_changes: Dict[str, float] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "intervention": self.intervention.to_dict(),
            "propagated_changes": self.propagated_changes,
            "summary": self.summary,
            "simulated_state": self.simulated_state.to_dict(),
        }


class CausalSimulator:
    """Apply interventions to a WorldState using the causal graph."""

    def __init__(self, graph_path: str = "data/causal_graph.json"):
        self.graph_path = graph_path
        self.graph = CausalGraph(graph_path)

    def simulate_intervention(
        self,
        state: WorldState,
        intervention: Intervention,
    ) -> SimulatedWorldState:
        """Apply a single intervention and propagate its effect through the graph."""
        simulated_state = copy.deepcopy(state)
        propagated_changes: Dict[str, float] = {}
        summary: Dict[str, Any] = {
            "target_node": intervention.target_node,
            "affected_nodes": [],
            "propagation_depth": 0,
        }

        self._apply_direct_change(simulated_state, intervention.target_node, intervention.value)
        propagated_changes[intervention.target_node] = intervention.value
        summary["affected_nodes"].append(intervention.target_node)

        queue: deque[Tuple[str, float, int]] = deque([(intervention.target_node, intervention.value, 0)])
        visited: set[str] = {intervention.target_node}
        max_depth = 0

        while queue:
            node, parent_impact, depth = queue.popleft()
            max_depth = max(max_depth, depth)
            for edge in self.graph.get_edges_from(node):
                if edge.to_node in visited:
                    continue
                delta = self._compute_edge_delta(parent_impact, edge)
                if self._apply_propagated_change(simulated_state, edge.to_node, delta):
                    propagated_changes[edge.to_node] = delta
                    summary["affected_nodes"].append(edge.to_node)
                    visited.add(edge.to_node)
                    queue.append((edge.to_node, delta, depth + 1))

        summary["propagation_depth"] = max_depth
        summary["propagated_nodes"] = list(propagated_changes.keys())
        return SimulatedWorldState(
            original_state=state,
            simulated_state=simulated_state,
            intervention=intervention,
            propagated_changes=propagated_changes,
            summary=summary,
        )

    def _apply_direct_change(self, state: WorldState, node: str, value: float) -> None:
        target_value = self._get_state_value(state, node)
        if target_value is None:
            state.custom_indicators[node] = value
            return

        new_value = target_value + value
        self._set_state_value(state, node, new_value)

    def _apply_propagated_change(self, state: WorldState, node: str, delta: float) -> bool:
        current_value = self._get_state_value(state, node)
        if current_value is None:
            return False
        new_value = current_value + delta
        self._set_state_value(state, node, new_value)
        return True

    def _get_state_value(self, state: WorldState, node: str) -> Optional[float]:
        mapping = {
            "DXY": state.macro.DXY,
            "FedRate": state.macro.FedRate,
            "BondYield": state.macro.BondYield,
            "RealYield": state.macro.RealYield,
            "VIX": state.macro.VIX,
            "BTC": state.crypto.BTC_Price,
            "BTC_Price": state.crypto.BTC_Price,
            "ETH": state.crypto.ETH_Price,
            "ETH_Price": state.crypto.ETH_Price,
            "Funding": state.liquidity.BTC_Funding,
            "OI": state.liquidity.BTC_OI,
            "Sentiment": state.sentiment.FearGreed,
            "FearGreed": state.sentiment.FearGreed,
        }
        return mapping.get(node)

    def _set_state_value(self, state: WorldState, node: str, value: float) -> None:
        if node in {"DXY"}:
            state.macro.DXY = value
        elif node in {"FedRate"}:
            state.macro.FedRate = value
        elif node in {"BondYield"}:
            state.macro.BondYield = value
        elif node in {"RealYield"}:
            state.macro.RealYield = value
        elif node in {"VIX"}:
            state.macro.VIX = value
        elif node in {"BTC", "BTC_Price"}:
            state.crypto.BTC_Price = value
        elif node in {"ETH", "ETH_Price"}:
            state.crypto.ETH_Price = value
        elif node in {"Funding"}:
            state.liquidity.BTC_Funding = value
        elif node in {"OI"}:
            state.liquidity.BTC_OI = value
        elif node in {"Sentiment", "FearGreed"}:
            state.sentiment.FearGreed = value
        else:
            state.custom_indicators[node] = value

    def _compute_edge_delta(self, parent_impact: float, edge: Any) -> float:
        direction = -1.0 if edge.effect == "negative" else 1.0
        if edge.to_node in {"BTC", "BTC_Price", "ETH", "ETH_Price"}:
            magnitude = abs(parent_impact) * edge.weight * 100.0
        elif edge.to_node in {"Sentiment", "FearGreed"}:
            magnitude = abs(parent_impact) * edge.weight * 1.0
        elif edge.to_node in {"Funding"}:
            magnitude = abs(parent_impact) * edge.weight * 0.2
        else:
            magnitude = abs(parent_impact) * edge.weight * 0.25
        return direction * magnitude
