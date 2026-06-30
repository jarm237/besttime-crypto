"""
Context Engine - Multi-layered context adjustment with explainability.

Processes rules across Macro, Crypto, Sentiment, and Risk layers to generate
ContextReport with confidence breakdown and adjustment justification.
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


@dataclass
class ContextAdjustment:
    """Represents a single adjustment to the signal."""
    layer: str
    feature: str
    impact: float
    reason: str
    rule_id: str
    confidence: float = 0.8


@dataclass
class ContextReport:
    """Output of context engine with full explainability."""
    original_score: float
    adjusted_score: float
    breakdown: Dict[str, float]  # layer -> cumulative impact
    adjustments: List[ContextAdjustment]
    timestamp: str
    total_confidence: float
    risk_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    stop_processing: bool = False
    warning_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "original_score": self.original_score,
            "adjusted_score": self.adjusted_score,
            "breakdown": self.breakdown,
            "adjustments": [asdict(a) for a in self.adjustments],
            "timestamp": self.timestamp,
            "total_confidence": self.total_confidence,
            "risk_level": self.risk_level,
            "stop_processing": self.stop_processing,
            "warning_message": self.warning_message,
        }


class ExpressionEvaluator:
    """Evaluates conditional expressions in context rules."""

    def __init__(self, context_data: Dict):
        """Initialize evaluator with market context data."""
        self.context = context_data

    def _flatten_context(self) -> Dict:
        """Flatten nested context dict for expression evaluation."""
        flat = {}
        for key, value in self.context.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    flat[f"{key}.{subkey}"] = subvalue
            else:
                flat[key] = value
        return flat

    def evaluate(self, expression: str) -> bool:
        """
        Evaluate conditional expression.
        
        Supports: AND, OR, comparison operators (>, <, ==, >=, <=), boolean logic.
        """
        if expression.lower() == "always":
            return True

        try:
            flat = self._flatten_context()

            # Replace context variables in expression
            for key, value in flat.items():
                # Handle string values
                if isinstance(value, str):
                    expression = re.sub(rf'\b{key}\b', f"'{value}'", expression)
                else:
                    expression = re.sub(rf'\b{key}\b', str(value), expression)

            # Evaluate the expression
            result = eval(expression, {"__builtins__": {}}, {})
            return bool(result)

        except Exception as e:
            logger.warning(f"Failed to evaluate expression '{expression}': {str(e)}")
            return False


class ContextEngine:
    """Multi-layered context adjustment engine."""

    def __init__(self, rules_path: str):
        """Initialize context engine with rules configuration."""
        self.rules_path = rules_path
        self.rules = self._load_rules()
        self.layers = ["macro", "market", "sentiment", "risk"]

    def _load_rules(self) -> Dict:
        """Load context rules from JSON."""
        try:
            with open(self.rules_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load context rules: {str(e)}")
            return {}

    def _get_rules_by_layer(self, layer: str) -> List[Dict]:
        """Get rules for a specific layer."""
        key = f"{layer}_context_rules"
        if key in self.rules:
            return self.rules[key]

        # Fallback for time_based_rules
        if layer == "time" and "time_based_rules" in self.rules:
            return self.rules["time_based_rules"]

        return []

    def _evaluate_rule(self, rule: Dict, context_data: Dict) -> Tuple[bool, bool]:
        """
        Evaluate if a rule applies to current context.
        
        Returns: (applies, stop_processing)
        """
        condition = rule.get("condition", "always")
        evaluator = ExpressionEvaluator(context_data)

        applies = evaluator.evaluate(condition)
        stop = rule.get("stop_processing", False) and applies

        return applies, stop

    def process_layer(
        self,
        layer: str,
        original_score: float,
        context_data: Dict,
        cumulative_impact: float = 0.0,
    ) -> Tuple[List[ContextAdjustment], float, bool]:
        """
        Process all rules for a specific layer.
        
        Returns: (adjustments, cumulative_impact, stop_processing)
        """
        adjustments = []
        rules = self._get_rules_by_layer(layer)

        # Sort by priority (descending)
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

        stop_processing = False

        for rule in sorted_rules:
            applies, stop = self._evaluate_rule(rule, context_data)

            if applies:
                impact = float(rule.get("impact", 0.0))
                adjustment = ContextAdjustment(
                    layer=layer,
                    feature=rule.get("id", "unknown"),
                    impact=impact,
                    reason=rule.get("reason", ""),
                    rule_id=rule.get("id", "unknown"),
                    confidence=0.8,
                )
                adjustments.append(adjustment)
                cumulative_impact += impact

                if stop:
                    stop_processing = True
                    break

        return adjustments, cumulative_impact, stop_processing

    def generate_context_report(
        self,
        original_score: float,
        context_data: Dict,
    ) -> ContextReport:
        """
        Generate comprehensive context report with adjustments.
        
        Args:
            original_score: Original signal score [0, 1]
            context_data: Market context information
            
        Returns:
            ContextReport with adjustments and explainability
        """
        all_adjustments: List[ContextAdjustment] = []
        cumulative_impact = 0.0
        breakdown: Dict[str, float] = {}
        stop_processing = False

        # Process each layer in order
        for layer in self.layers:
            layer_adjustments, layer_impact, layer_stop = self.process_layer(
                layer,
                original_score,
                context_data,
                cumulative_impact,
            )

            all_adjustments.extend(layer_adjustments)
            cumulative_impact += layer_impact
            breakdown[layer] = layer_impact

            if layer_stop:
                stop_processing = True
                break

        # Apply global impact limits
        global_params = self.rules.get("global_parameters", {})
        max_negative = global_params.get("max_cumulative_negative_impact", -0.75)
        cumulative_impact = max(cumulative_impact, max_negative)

        # Calculate adjusted score
        adjusted_score = max(0.0, min(1.0, original_score + cumulative_impact))

        # Calculate total confidence
        total_confidence = 1.0
        for adj in all_adjustments:
            total_confidence *= adj.confidence
        total_confidence = max(0.5, total_confidence)  # Floor at 0.5

        # Determine risk level
        risk_level = self._calculate_risk_level(adjusted_score, cumulative_impact, len(all_adjustments))

        warning_message = None
        if stop_processing:
            warning_message = "Context engine triggered stop_processing - critical conditions detected"

        report = ContextReport(
            original_score=original_score,
            adjusted_score=adjusted_score,
            breakdown=breakdown,
            adjustments=all_adjustments,
            timestamp=datetime.utcnow().isoformat(),
            total_confidence=total_confidence,
            risk_level=risk_level,
            stop_processing=stop_processing,
            warning_message=warning_message,
        )

        return report

    def _calculate_risk_level(self, adjusted_score: float, cumulative_impact: float, num_adjustments: int) -> str:
        """Calculate risk level based on adjustments."""
        if adjusted_score < 0.2 or cumulative_impact < -0.5:
            return "CRITICAL"
        elif adjusted_score < 0.35 or cumulative_impact < -0.3:
            return "HIGH"
        elif adjusted_score < 0.5 or num_adjustments > 3:
            return "MEDIUM"
        else:
            return "LOW"

    def analyze_context(self, context_data: Dict) -> Dict:
        """
        Analyze market context without adjusting a score.
        
        Useful for standalone context analysis.
        """
        all_adjustments: List[ContextAdjustment] = []

        for layer in self.layers:
            layer_adjustments, _, _ = self.process_layer(layer, 0.5, context_data)
            all_adjustments.extend(layer_adjustments)

        return {
            "total_active_rules": len(all_adjustments),
            "breakdown_by_layer": {
                layer: len([a for a in all_adjustments if a.layer == layer])
                for layer in self.layers
            },
            "adjustments": [asdict(a) for a in all_adjustments],
            "timestamp": datetime.utcnow().isoformat(),
        }


if __name__ == "__main__":
    # Example usage
    engine = ContextEngine("data/context_rules.json")

    # Sample context data
    sample_context = {
        "MacroEvent": {
            "FOMC": {"HoursToEvent": 2, "Importance": "HIGH"}
        },
        "Funding_Z": 1.5,
        "OI_Delta": 10,
        "BTC_Trend": "UP",
        "FearGreed": 30,
        "Trend": "DOWN",
        "DXY": 104.5,
        "DXY_52w_high": 106.0,
    }

    original_score = 0.75
    report = engine.generate_context_report(original_score, sample_context)

    print("\nContext Report:")
    print(json.dumps(report.to_dict(), indent=2))
