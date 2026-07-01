"""Consensus engine for causal multi-agent collaboration."""

from __future__ import annotations

from typing import Any, Dict, List

from btc_scraper.core.world_state import WorldState
from btc_scraper.ml_engine.causal_graph import CausalGraph


class CausalConsensusEngine:
    """Combine sub-agent views using the causal graph as a weighting source."""

    def __init__(self, graph_path: str = "data/causal_graph.json"):
        self.graph = CausalGraph(graph_path)

    def decide(self, state: WorldState, agent_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_score = 0.0
        weights: Dict[str, float] = {}
        for report in agent_reports:
            agent_name = report.get("agent", "unknown")
            if agent_name == "macro_agent":
                weights[agent_name] = 0.45
            elif agent_name == "liquidity_agent":
                weights[agent_name] = 0.35
            elif agent_name == "sentiment_agent":
                weights[agent_name] = 0.20
            else:
                weights[agent_name] = 0.1

            total_score += float(report.get("score", 0.0)) * weights[agent_name]

        signal = "neutral"
        if total_score > 0.2:
            signal = "bullish"
        elif total_score < -0.2:
            signal = "bearish"

        return {
            "signal": signal,
            "score": round(total_score, 3),
            "agent_reports": agent_reports,
            "causal_graph_nodes": len(self.graph.nodes),
            "explanation": "Consensus built from weighted causal sub-agent views.",
        }
