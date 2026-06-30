"""
Causal Reasoning Engine - Explain decisions through causal pathways.

Finds causal paths from macro drivers to BTC/ETH price impacts,
generates explainable reasoning trees for UI and LLM integration.
"""

import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

from .causal_graph import CausalGraph, CausalPath, CausalEdge


@dataclass
class CausalExplanation:
    """Structured causal explanation for a price move or signal."""
    signal_direction: str  # "BUY", "SELL", "HOLD"
    primary_drivers: List[str]  # Top causal nodes
    paths: List[Dict]  # Causal pathways
    confidence: float
    summary: str
    root_cause: Optional[str]


@dataclass
class CausalReasoning:
    """Full reasoning tree from root causes to prediction."""
    target: str  # "BTC", "ETH"
    root_causes: List[Tuple[str, float]]  # (node, confidence) tuples
    primary_path: Optional[CausalPath]
    alternative_paths: List[CausalPath]
    explanation: str
    timestamp: str

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "target": self.target,
            "root_causes": self.root_causes,
            "primary_path": self._path_to_dict(self.primary_path) if self.primary_path else None,
            "alternative_paths": [self._path_to_dict(p) for p in self.alternative_paths],
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def _path_to_dict(path: CausalPath) -> Dict:
        """Convert CausalPath to dictionary."""
        return {
            "source": path.source,
            "target": path.target,
            "path": path.path,
            "confidence": path.confidence,
            "effect_direction": path.effect_direction,
            "total_lag": path.total_lag,
            "num_hops": len(path.path) - 1,
        }


class CausalReasoningEngine:
    """Generate causal explanations for market movements."""

    def __init__(self, graph_path: str):
        """Initialize with causal graph."""
        self.graph = CausalGraph(graph_path)
        self.macro_nodes = {"DXY", "FedRate", "BondYield", "VIX", "RealYield"}
        self.crypto_nodes = {"BTC", "ETH"}
        self.on_chain_nodes = {"Funding", "OI", "LongShortRatio"}

    def find_root_causes(
        self, target: str = "BTC", max_depth: int = 4
    ) -> List[Tuple[str, float]]:
        """
        Find nodes that can influence the target.
        
        Returns list of (node_id, aggregated_confidence) sorted by confidence.
        """
        if target not in self.graph.nodes:
            return []

        return self.graph.get_influencers(target, max_depth=max_depth)

    def generate_reasoning_tree(
        self,
        target: str = "BTC",
        signal_direction: str = "BUY",
        current_values: Optional[Dict] = None,
    ) -> CausalReasoning:
        """
        Generate full causal reasoning tree from root causes to target.
        
        Args:
            target: Target asset ("BTC", "ETH")
            signal_direction: Trading signal direction
            current_values: Current market values for filtering
            
        Returns:
            CausalReasoning with full explanation tree
        """
        # Find root causes
        root_causes = self.find_root_causes(target)

        if not root_causes:
            return CausalReasoning(
                target=target,
                root_causes=[],
                primary_path=None,
                alternative_paths=[],
                explanation=f"No causal paths found to {target}",
                timestamp=datetime.utcnow().isoformat(),
            )

        # Find paths from top root causes to target
        primary_path = None
        alternative_paths = []

        for root_cause, confidence in root_causes[:3]:  # Top 3 root causes
            path = self.graph.find_shortest_path(root_cause, target, use_confidence=True)

            if path:
                if primary_path is None or path.confidence > primary_path.confidence:
                    if primary_path:
                        alternative_paths.append(primary_path)
                    primary_path = path
                else:
                    alternative_paths.append(path)

        # Generate explanation
        explanation = self._generate_explanation(
            target, signal_direction, primary_path, root_causes, current_values
        )

        return CausalReasoning(
            target=target,
            root_causes=root_causes[:5],  # Top 5 root causes
            primary_path=primary_path,
            alternative_paths=alternative_paths,
            explanation=explanation,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _generate_explanation(
        self,
        target: str,
        signal_direction: str,
        primary_path: Optional[CausalPath],
        root_causes: List[Tuple[str, float]],
        current_values: Optional[Dict] = None,
    ) -> str:
        """Generate human-readable explanation."""
        if not root_causes or not primary_path:
            return f"Insufficient causal evidence for {signal_direction} signal on {target}."

        top_roots = [r[0] for r in root_causes[:2]]
        path_str = " → ".join(primary_path.path)

        effect_verb = "strengthen" if primary_path.effect_direction == "positive" else "pressure"

        explanation = (
            f"{signal_direction} signal on {target} driven by: "
            f"{', '.join(top_roots)}. "
            f"Primary causal path: {path_str}. "
            f"Current conditions {effect_verb} the case for {signal_direction}. "
            f"Confidence: {primary_path.confidence:.0%}."
        )

        return explanation

    def explain_decision(
        self,
        decision_dict: Dict,
        target: str = "BTC",
        context_report: Optional[Dict] = None,
    ) -> Dict:
        """
        Generate causal explanation for a trading decision.
        
        Args:
            decision_dict: Output from decision_engine.decide()
            target: Target asset
            context_report: ContextReport from context_engine
            
        Returns:
            Decision with causal explanation
        """
        action = decision_dict.get("action", "HOLD")
        posterior = decision_dict.get("posterior_probability", 0.5)

        # Map action to direction
        if action in ["BUY", "INCREASE"]:
            direction = "BUY"
        elif action in ["SELL", "REDUCE"]:
            direction = "SELL"
        else:
            direction = "HOLD"

        reasoning = self.generate_reasoning_tree(target, direction)

        return {
            **decision_dict,
            "causal_reasoning": reasoning.to_dict(),
            "causal_explanation": reasoning.explanation,
            "context_report": context_report,
        }

    def build_scenario_tree(
        self,
        target: str = "BTC",
        scenarios: Optional[List[str]] = None,
    ) -> Dict:
        """
        Build intervention scenarios for digital twin / counterfactual analysis.
        
        This prepares ground for Phase 5 (Scenario Simulator).
        
        Args:
            target: Target asset
            scenarios: List of intervention scenarios (e.g., ["FedRateCut", "DXYDrops"])
            
        Returns:
            Scenario tree for simulation
        """
        if not scenarios:
            scenarios = ["RealYieldDrops", "VIXSpikes", "DXYRises"]

        scenario_tree = {}

        for scenario in scenarios:
            # Find causal path for this scenario
            causal_nodes = self._scenario_to_nodes(scenario)

            paths = []
            for node in causal_nodes:
                path = self.graph.find_shortest_path(node, target)
                if path:
                    paths.append(path)

            scenario_tree[scenario] = {
                "trigger_nodes": causal_nodes,
                "paths_to_target": [
                    {
                        "path": p.path,
                        "confidence": p.confidence,
                        "effect": p.effect_direction,
                    }
                    for p in paths
                ],
                "expected_impact": self._estimate_scenario_impact(paths),
            }

        return scenario_tree

    def _scenario_to_nodes(self, scenario: str) -> List[str]:
        """Map scenario name to causal nodes."""
        scenarios = {
            "FedRateCut": ["FedRate"],
            "RealYieldDrops": ["RealYield", "BondYield"],
            "VIXSpikes": ["VIX"],
            "DXYRises": ["DXY"],
            "FundingExtreme": ["Funding"],
            "OICollapse": ["OI"],
        }
        return scenarios.get(scenario, [])

    def _estimate_scenario_impact(self, paths: List[CausalPath]) -> str:
        """Estimate impact direction for scenario."""
        if not paths:
            return "NEUTRAL"

        # Simple heuristic: if most paths are negative, estimate bearish
        negative_count = sum(1 for p in paths if p.effect_direction == "negative")
        if negative_count > len(paths) / 2:
            return "BEARISH"
        elif negative_count < len(paths) / 2:
            return "BULLISH"
        return "MIXED"

    def get_summary(self) -> Dict:
        """Get summary of reasoning engine capabilities."""
        graph_summary = self.graph.get_summary()
        return {
            **graph_summary,
            "engine": "CausalReasoningEngine",
            "version": "1.0.0",
            "capabilities": [
                "root_cause_analysis",
                "causal_path_finding",
                "decision_explanation",
                "scenario_simulation_prep",
            ],
        }


if __name__ == "__main__":
    engine = CausalReasoningEngine("data/causal_graph.json")

    print("\nCausal Reasoning Engine Summary:")
    print(json.dumps(engine.get_summary(), indent=2))

    print("\nExample: BUY reasoning for BTC:")
    reasoning = engine.generate_reasoning_tree("BTC", "BUY")
    print(json.dumps(reasoning.to_dict(), indent=2))

    print("\nScenario Tree for RealYieldDrops:")
    scenario_tree = engine.build_scenario_tree("BTC", ["RealYieldDrops"])
    print(json.dumps(scenario_tree, indent=2))
