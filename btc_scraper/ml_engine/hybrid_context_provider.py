"""
HybridContextProvider - Combines Rule-based and Bayesian context adjustment.

Phase 3.0 of the Causal World Model integration.

Blends RuleContextProvider (hard rules, high recall) with BayesianContextProvider
(probabilistic inference, smooth adjustments) into a single composite score.

This enables:
  - Manual rules to catch extreme, well-known conditions (FOMC risk, funding spike)
  - Bayesian inference to provide nuanced adjustments for ambiguous conditions
  - A/B testing between pure-rule and hybrid approaches
  - Gradual migration: start at alpha=0 (rules only), tune alpha upward as Bayesian
    proves its value in shadow mode

Reads enable_learned_rules from context_rules.json metadata to conditionally
include Bayesian adjustments (safe flag for production rollout).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from btc_scraper.ml_engine.context_provider import (
    ContextAdjustment,
    ContextProvider,
    ContextReport,
    RiskLevel,
    CompositeContextProvider,
)
from btc_scraper.ml_engine.rule_context_provider import RuleContextProvider
from btc_scraper.ml_engine.bayesian_context_provider import BayesianContextProvider
from btc_scraper.core.world_state import WorldState

logger = logging.getLogger(__name__)


class HybridContextProvider(ContextProvider):
    """
    Combines Rule-based and Bayesian context adjustment.

    Blending formula:
        hybrid_adjustment = (1 - alpha) * rule_adjustment + alpha * bayes_adjustment
        final_score = original_score + hybrid_adjustment

    where alpha ∈ [0.0, 1.0]:
        alpha = 0.0 → pure rule-based (same as RuleContextProvider)
        alpha = 0.5 → equal blend
        alpha = 1.0 → pure Bayesian

    The alpha is loaded from config and can be updated without a bot restart.
    """

    def __init__(
        self,
        rule_provider: RuleContextProvider,
        bayesian_provider: BayesianContextProvider,
        alpha: float = 0.0,
        rules_config_path: str = "data/context_rules.json",
        name: str = "HybridContextProvider",
    ):
        """
        Args:
            rule_provider: Configured RuleContextProvider.
            bayesian_provider: Configured BayesianContextProvider.
            alpha: Bayesian blend weight (0.0 = rules only, 1.0 = Bayes only).
            rules_config_path: Path to context_rules.json for reading enable_learned_rules.
            name: Provider name.
        """
        super().__init__(name)
        self.rule_provider = rule_provider
        self.bayesian_provider = bayesian_provider
        self.alpha = max(0.0, min(1.0, alpha))
        self.rules_config_path = rules_config_path
        self._enable_learned_rules: Optional[bool] = None
        self._load_config()

    def _load_config(self) -> None:
        """Read enable_learned_rules flag from context_rules.json."""
        try:
            with open(self.rules_config_path) as f:
                config = json.load(f)
            self._enable_learned_rules = (
                config.get("metadata", {}).get("enable_learned_rules", False)
                or config.get("global_parameters", {}).get("enable_learned_rules", False)
            )
            logger.info(
                f"[HybridContextProvider] enable_learned_rules={self._enable_learned_rules}, "
                f"alpha={self.alpha:.2f}"
            )
        except Exception as exc:
            logger.warning(f"[HybridContextProvider] Cannot load config: {exc}, defaulting to rules-only")
            self._enable_learned_rules = False

    def set_alpha(self, alpha: float) -> None:
        """Dynamically update blend weight (useful for A/B testing)."""
        old = self.alpha
        self.alpha = max(0.0, min(1.0, alpha))
        logger.info(f"[HybridContextProvider] alpha updated: {old:.2f} → {self.alpha:.2f}")

    def enable_bayesian(self, enabled: bool = True) -> None:
        """Enable or disable Bayesian component at runtime."""
        self._enable_learned_rules = enabled
        logger.info(f"[HybridContextProvider] enable_learned_rules={enabled}")

    def validate(self) -> tuple[bool, str]:
        """Validate both sub-providers."""
        r_valid, r_msg = self.rule_provider.validate()
        if not r_valid:
            return False, f"RuleContextProvider: {r_msg}"

        b_valid, b_msg = self.bayesian_provider.validate()
        if not b_valid:
            return False, f"BayesianContextProvider: {b_msg}"

        if not 0.0 <= self.alpha <= 1.0:
            return False, f"alpha must be in [0.0, 1.0], got {self.alpha}"

        return True, (
            f"HybridContextProvider valid (alpha={self.alpha:.2f}, "
            f"learned={self._enable_learned_rules})"
        )

    def should_apply_context(self, world_state: WorldState) -> bool:
        """Apply if at least the rule provider is ready."""
        return self.rule_provider.should_apply_context(world_state)

    def generate_context_report(
        self, original_score: float, world_state: WorldState
    ) -> ContextReport:
        """
        Generate hybrid context report.

        When enable_learned_rules=False (or alpha=0), behaves identically to
        RuleContextProvider — safe for production use before Bayesian validation.

        When enable_learned_rules=True, blends both reports.
        """
        # Always run rule-based provider
        rule_report = self.rule_provider.generate_context_report(original_score, world_state)

        use_bayes = (
            self._enable_learned_rules
            and self.alpha > 0.0
            and self.bayesian_provider.should_apply_context(world_state)
        )

        if not use_bayes or self.alpha == 0.0:
            # Pure rules mode — add provider metadata and return
            rule_report.provider_name = self.name
            rule_report.explanation = f"[Hybrid/rules-only] " + rule_report.explanation
            return rule_report

        # Run Bayesian provider
        bayes_report = self.bayesian_provider.generate_context_report(original_score, world_state)

        # Blend adjustments
        rule_adj = rule_report.adjusted_score - original_score
        bayes_adj = bayes_report.adjusted_score - original_score
        hybrid_adj = (1.0 - self.alpha) * rule_adj + self.alpha * bayes_adj
        hybrid_score = max(0.0, min(1.0, original_score + hybrid_adj))

        # Merge adjustments list (rule first, then Bayesian)
        merged_adjustments = list(rule_report.adjustments) + list(bayes_report.adjustments)

        # Merge breakdown
        merged_breakdown: Dict[str, float] = {}
        for layer, val in (rule_report.breakdown or {}).items():
            merged_breakdown[layer] = merged_breakdown.get(layer, 0.0) + (1.0 - self.alpha) * val
        for layer, val in (bayes_report.breakdown or {}).items():
            merged_breakdown[layer] = merged_breakdown.get(layer, 0.0) + self.alpha * val

        # Take the higher (more conservative) risk level
        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        max_risk = max(rule_report.risk_level, bayes_report.risk_level, key=risk_order.index)

        # Stop processing if either provider requests it
        stop = rule_report.stop_processing

        explanation = (
            f"[Hybrid α={self.alpha:.2f}] "
            f"Rule adj={rule_adj:+.3f} | Bayes adj={bayes_adj:+.3f} | "
            f"Hybrid adj={hybrid_adj:+.3f}. "
            f"{original_score:.3f} → {hybrid_score:.3f}"
        )

        return ContextReport(
            timestamp=datetime.now(timezone.utc),
            provider_name=self.name,
            world_state=world_state.to_dict(),
            original_score=original_score,
            adjusted_score=hybrid_score,
            risk_level=max_risk,
            adjustments=merged_adjustments,
            explanation=explanation,
            breakdown=merged_breakdown,
            stop_processing=stop,
        )

    @classmethod
    def build(
        cls,
        rules_path: str = "data/context_rules.json",
        graph_path: str = "data/causal_graph.json",
        alpha: float = 0.0,
    ) -> "HybridContextProvider":
        """
        Factory method to build a fully configured HybridContextProvider.

        Loads rule weights from context_rules.json and Bayesian weights from
        causal_graph.json edge confidences.

        Args:
            rules_path: Path to context_rules.json.
            graph_path: Path to causal_graph.json.
            alpha: Bayesian blend weight (start at 0.0 for shadow mode).

        Returns:
            Configured HybridContextProvider.
        """
        rule_provider = RuleContextProvider(rules_path)
        bayes_provider = BayesianContextProvider.from_causal_graph(graph_path)
        return cls(
            rule_provider=rule_provider,
            bayesian_provider=bayes_provider,
            alpha=alpha,
            rules_config_path=rules_path,
        )


if __name__ == "__main__":
    from btc_scraper.core.world_state import WorldState, MarketRegime

    print("Building HybridContextProvider...")
    provider = HybridContextProvider.build(
        rules_path="data/context_rules.json",
        graph_path="data/causal_graph.json",
        alpha=0.30,
    )

    is_valid, msg = provider.validate()
    print(f"✓ Valid: {is_valid} — {msg}")

    # Test with risk-off state
    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 108.0
    state.macro.VIX = 30.0
    state.macro.RealYield = 2.1
    state.liquidity.Funding_Z = 2.6
    state.sentiment.FearGreed = 20.0

    print("\n--- Hybrid (alpha=0.30) RISK-OFF ---")
    report = provider.generate_context_report(0.82, state)
    print(f"Score: {report.original_score:.3f} → {report.adjusted_score:.3f}")
    print(f"Risk: {report.risk_level.value}")
    print(f"Adjustments: {len(report.adjustments)}")
    print(f"Explanation: {report.explanation}")

    print("\n--- Alpha=0.0 (rules only) ---")
    provider.set_alpha(0.0)
    report2 = provider.generate_context_report(0.82, state)
    print(f"Score: {report2.original_score:.3f} → {report2.adjusted_score:.3f}")
    print(f"Explanation: {report2.explanation}")

    print("\n--- Enable Bayesian ---")
    provider.set_alpha(0.30)
    provider.enable_bayesian(True)
    report3 = provider.generate_context_report(0.82, state)
    print(f"Score: {report3.original_score:.3f} → {report3.adjusted_score:.3f}")
    print(f"Breakdown: {report3.breakdown}")
