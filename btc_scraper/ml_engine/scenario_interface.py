"""
Scenario Interface - Foundation for Phase 5 (Scenario Simulator & Digital Twin).

Defines abstract interfaces for:
- Scenario simulation and counterfactual analysis
- Digital twin / world model experimentation
- Intervention effects computation
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import json


class InterventionType(Enum):
    """Types of interventions for scenario simulation."""
    FED_POLICY = "fed_policy_change"
    RATE_SHOCK = "interest_rate_shock"
    CURRENCY_SHOCK = "currency_shock"
    VOLATILITY_SHOCK = "volatility_shock"
    ON_CHAIN_SHOCK = "on_chain_shock"
    SENTIMENT_SHOCK = "sentiment_shock"
    CUSTOM = "custom_intervention"


@dataclass
class Intervention:
    """Represents an intervention in causal model."""
    type: InterventionType
    target_node: str
    value: float
    duration_hours: int = 1
    confidence: float = 0.8
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "target_node": self.target_node,
            "value": self.value,
            "duration_hours": self.duration_hours,
            "confidence": self.confidence,
            "description": self.description,
        }


@dataclass
class ScenarioOutcome:
    """Output of scenario simulation."""
    scenario_name: str
    initial_state: Dict[str, float]
    final_state: Dict[str, float]
    target_impact: float  # Expected impact on BTC/ETH
    confidence: float
    reasoning: str
    affected_nodes: List[str]
    timestamp: str

    def to_dict(self) -> Dict:
        return {
            "scenario_name": self.scenario_name,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "target_impact": self.target_impact,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "affected_nodes": self.affected_nodes,
            "timestamp": self.timestamp,
        }


class Scenario(ABC):
    """Abstract base class for simulation scenarios."""

    def __init__(self, name: str, description: str):
        """Initialize scenario."""
        self.name = name
        self.description = description
        self.interventions: List[Intervention] = []
        self.created_at = datetime.utcnow().isoformat()

    @abstractmethod
    def simulate(
        self,
        current_state: Dict[str, float],
        horizon_hours: int = 24,
    ) -> ScenarioOutcome:
        """
        Simulate scenario and return expected outcome.
        
        Args:
            current_state: Current market state dict
            horizon_hours: Simulation horizon
            
        Returns:
            ScenarioOutcome with projected state and impacts
        """
        pass

    def add_intervention(self, intervention: Intervention) -> None:
        """Add intervention to scenario."""
        self.interventions.append(intervention)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "interventions": [i.to_dict() for i in self.interventions],
            "created_at": self.created_at,
        }


class CounterfactualAnalyzer(ABC):
    """Abstract base for counterfactual analysis."""

    @abstractmethod
    def analyze(
        self,
        actual_outcome: Dict[str, Any],
        alternative_scenario: Scenario,
    ) -> Dict[str, Any]:
        """
        Compare actual outcome with alternative scenario.
        
        Returns analysis of "what would have happened if..."
        """
        pass


class DigitalTwin(ABC):
    """Abstract base for digital twin / world model."""

    @abstractmethod
    def step(self, state: Dict[str, float], actions: Dict[str, float]) -> Dict[str, float]:
        """
        Step forward in simulated world.
        
        Args:
            state: Current world state
            actions: Market actions/interventions
            
        Returns:
            Next world state
        """
        pass

    @abstractmethod
    def predict(
        self,
        initial_state: Dict[str, float],
        horizon_hours: int = 24,
    ) -> List[Dict[str, float]]:
        """
        Generate trajectory of world state.
        
        Returns trajectory of states at each time step.
        """
        pass


class ScenarioLibrary:
    """Manages collection of predefined scenarios."""

    SCENARIO_DEFS = {
        "RealYieldShock": {
            "description": "Real yields spike due to unexpected Fed tightening",
            "interventions": [
                {"type": "rate_shock", "target": "RealYield", "value": 0.5},
                {"type": "rate_shock", "target": "BondYield", "value": 0.3},
            ],
            "expected_impact": -0.25,
        },
        "VIXSpike": {
            "description": "Equity volatility spike spills into crypto",
            "interventions": [
                {"type": "volatility_shock", "target": "VIX", "value": 15},
                {"type": "sentiment_shock", "target": "Sentiment", "value": -20},
            ],
            "expected_impact": -0.20,
        },
        "FedPivot": {
            "description": "Fed signals policy pivot / rate cuts",
            "interventions": [
                {"type": "fed_policy", "target": "FedRate", "value": -0.25},
                {"type": "rate_shock", "target": "RealYield", "value": -0.5},
            ],
            "expected_impact": 0.30,
        },
        "DXYCollapse": {
            "description": "US Dollar index falls sharply",
            "interventions": [
                {"type": "currency_shock", "target": "DXY", "value": -5.0},
                {"type": "rate_shock", "target": "BondYield", "value": -0.3},
            ],
            "expected_impact": 0.25,
        },
        "FundingSpike": {
            "description": "Extreme funding rates signal over-leveraged longs",
            "interventions": [
                {"type": "on_chain_shock", "target": "Funding", "value": 0.15},
                {"type": "on_chain_shock", "target": "OI", "value": 30},
            ],
            "expected_impact": -0.18,
        },
        "BTC_Halving": {
            "description": "Bitcoin halving cycle dynamics",
            "interventions": [
                {"type": "on_chain_shock", "target": "Sentiment", "value": 15},
                {"type": "custom", "target": "BTC", "value": 0.0},
            ],
            "expected_impact": 0.35,
        },
    }

    @classmethod
    def get_scenario_def(cls, name: str) -> Optional[Dict]:
        """Get predefined scenario definition."""
        return cls.SCENARIO_DEFS.get(name)

    @classmethod
    def list_scenarios(cls) -> List[str]:
        """List all available scenarios."""
        return list(cls.SCENARIO_DEFS.keys())

    @classmethod
    def create_scenario_config(cls, name: str) -> Optional[Dict]:
        """Create full scenario configuration."""
        if name not in cls.SCENARIO_DEFS:
            return None

        scenario_def = cls.SCENARIO_DEFS[name]
        return {
            "scenario_name": name,
            "description": scenario_def["description"],
            "interventions": scenario_def["interventions"],
            "expected_impact": scenario_def["expected_impact"],
            "created_at": datetime.utcnow().isoformat(),
        }


class ScenarioSimulator:
    """
    High-level scenario simulation interface.
    
    Provides convenient methods for running scenarios without needing
    to implement full DigitalTwin / Scenario classes.
    """

    def __init__(self, causal_graph):
        """Initialize simulator with causal graph."""
        self.causal_graph = causal_graph

    def simulate_scenario(
        self,
        scenario_name: str,
        current_state: Dict[str, float],
        horizon_hours: int = 24,
    ) -> ScenarioOutcome:
        """
        Run a predefined scenario.
        
        Args:
            scenario_name: Name of scenario from ScenarioLibrary
            current_state: Current market state
            horizon_hours: Simulation horizon
            
        Returns:
            ScenarioOutcome
        """
        scenario_config = ScenarioLibrary.create_scenario_config(scenario_name)
        if not scenario_config:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        # Simple propagation: apply interventions through causal graph
        final_state = current_state.copy()
        affected_nodes = set()

        for intervention_def in scenario_config["interventions"]:
            target = intervention_def["target"]
            value = intervention_def["value"]

            # Apply intervention
            if target in final_state:
                final_state[target] = value
                affected_nodes.add(target)

            # Propagate through graph (simplified)
            descendants = self.causal_graph.get_descendants(target, max_depth=2)
            for desc_node, confidence in descendants:
                if desc_node in final_state:
                    # Rough heuristic: apply portion of intervention
                    final_state[desc_node] += value * confidence * 0.1

        return ScenarioOutcome(
            scenario_name=scenario_name,
            initial_state=current_state,
            final_state=final_state,
            target_impact=scenario_config["expected_impact"],
            confidence=0.7,  # Placeholder confidence
            reasoning=scenario_config["description"],
            affected_nodes=list(affected_nodes),
            timestamp=datetime.utcnow().isoformat(),
        )

    def sensitivity_analysis(
        self,
        node: str,
        shocks: List[float],
        current_state: Dict[str, float],
    ) -> Dict:
        """
        Analyze sensitivity of BTC to shocks in a particular node.
        
        Args:
            node: Node to shock
            shocks: List of shock magnitudes to test
            current_state: Current state
            
        Returns:
            Sensitivity analysis results
        """
        results = []

        for shock in shocks:
            test_state = current_state.copy()
            test_state[node] = shock

            # Find impact on BTC through causal graph
            paths = self.causal_graph.find_all_paths(node, "BTC", max_depth=3)

            if paths:
                primary_path = max(paths, key=lambda p: p.confidence)
                impact = primary_path.confidence * (1 if primary_path.effect_direction == "positive" else -1)
            else:
                impact = 0.0

            results.append({
                "shock_magnitude": shock,
                "expected_btc_impact": impact,
                "confidence": paths[0].confidence if paths else 0.0,
            })

        return {
            "node": node,
            "sensitivity_results": results,
            "timestamp": datetime.utcnow().isoformat(),
        }


if __name__ == "__main__":
    print("\n=== Scenario Library ===")
    print("Available scenarios:")
    for scenario in ScenarioLibrary.list_scenarios():
        print(f"  - {scenario}")

    print("\n=== Example Scenario Config ===")
    config = ScenarioLibrary.create_scenario_config("FedPivot")
    print(json.dumps(config, indent=2))
