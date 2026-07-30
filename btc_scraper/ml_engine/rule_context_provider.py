"""
RuleContextProvider - Adapts the existing ContextEngine to the ContextProvider interface.

This is Phase 2.1 of the Causal World Model integration.
Bridges the old ContextEngine (rules-based) with the new ContextProvider abstract interface
so that DecisionEngine can be fully decoupled from the implementation.

Future providers (Bayesian, RL, LLM) will implement the same interface.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from btc_scraper.ml_engine.context_provider import (
    ContextProvider,
    ContextReport,
    ContextAdjustment,
    RiskLevel,
)
from btc_scraper.ml_engine.context_engine import ContextEngine
from btc_scraper.core.world_state import WorldState

logger = logging.getLogger(__name__)


def _world_state_to_context_dict(world_state: WorldState) -> Dict[str, Any]:
    """
    Convert WorldState into the flat dict format expected by ContextEngine's rule evaluator.

    Maps structured WorldState layers to the key names used in context_rules.json conditions.
    """
    macro = world_state.macro
    liquidity = world_state.liquidity
    sentiment = world_state.sentiment
    risk = world_state.risk

    ctx: Dict[str, Any] = {}

    # Macro layer
    ctx["DXY"] = macro.DXY
    ctx["FedRate"] = macro.FedRate
    ctx["RealYield"] = macro.RealYield
    ctx["BondYield"] = macro.BondYield
    ctx["VIX"] = macro.VIX
    if macro.CPI is not None:
        ctx["CPI"] = macro.CPI
    if macro.NFP is not None:
        ctx["NFP"] = macro.NFP

    # Liquidity / Crypto context
    ctx["Funding_Z"] = liquidity.Funding_Z
    ctx["OI_Delta"] = liquidity.OI_Delta
    ctx["BTC_LongShortRatio"] = liquidity.BTC_LongShortRatio
    ctx["ETH_LongShortRatio"] = liquidity.ETH_LongShortRatio

    # Sentiment
    ctx["FearGreed"] = sentiment.FearGreed
    ctx["SocialVolume"] = sentiment.SocialVolume

    # Risk
    ctx["CurrentDrawdown"] = risk.CurrentDrawdown
    ctx["Volatility"] = risk.Volatility

    # Market regime string (used in some rule conditions)
    ctx["market_regime"] = world_state.regime.value.upper()
    if isinstance(world_state.technical_regime, dict):
        ctx["technical_regime_family"] = world_state.technical_regime.get("family", "UNKNOWN")
        ctx["technical_regime_direction"] = world_state.technical_regime.get("direction", "UNKNOWN")
        ctx["technical_regime_volatility"] = world_state.technical_regime.get("volatility", "UNKNOWN")

    # Custom indicators pass-through (allows callers to inject ad-hoc features)
    for k, v in world_state.custom_indicators.items():
        ctx[k] = v

    return ctx


class RuleContextProvider(ContextProvider):
    """
    Rule-based context provider backed by ContextEngine + context_rules.json.

    This is the Phase 2.0 production provider. It wraps the existing multi-layer
    rule engine and translates its output into the standardized ContextReport format
    expected by DecisionEngine.

    Future providers (BayesianContextProvider, RLContextProvider) will implement
    the same ContextProvider interface without changing DecisionEngine.
    """

    def __init__(self, rules_path: str = "data/context_rules.json"):
        """
        Args:
            rules_path: Path to context_rules.json configuration file.
        """
        super().__init__("RuleContextProvider")
        self.rules_path = rules_path
        self._engine: ContextEngine | None = None
        self._load_engine()

    def _load_engine(self) -> None:
        """Load ContextEngine from rules file. Fails loudly if file is missing."""
        try:
            self._engine = ContextEngine(self.rules_path)
            rule_count = sum(
                len(v) for k, v in self._engine.rules.items() if isinstance(v, list)
            )
            logger.info(
                f"[RuleContextProvider] Loaded {rule_count} rules from '{self.rules_path}'"
            )
        except Exception as exc:
            logger.error(f"[RuleContextProvider] Failed to load rules: {exc}")
            self._engine = None

    def validate(self) -> tuple[bool, str]:
        """Validate that rules file loaded correctly and has content."""
        if self._engine is None:
            return False, f"ContextEngine failed to load from '{self.rules_path}'"
        if not self._engine.rules:
            return False, f"No rules found in '{self.rules_path}'"
        return True, "RuleContextProvider is valid"

    def should_apply_context(self, world_state: WorldState) -> bool:
        """
        Always apply context adjustments when engine is available.

        Can be overridden to skip adjustments during extreme conditions
        (e.g., flash crash where rules are unreliable).
        """
        return self._engine is not None

    def generate_context_report(
        self, original_score: float, world_state: WorldState
    ) -> ContextReport:
        """
        Generate ContextReport by running the rule engine against current WorldState.

        Translates ContextEngine's internal ContextReport into the standardized
        ContextProvider ContextReport format.

        Args:
            original_score: Signal score from Meta Model (0.0–1.0).
            world_state: Current unified market state.

        Returns:
            ContextReport with full explainability breakdown.
        """
        if self._engine is None:
            logger.warning("[RuleContextProvider] Engine not loaded, returning passthrough report")
            return ContextReport(
                timestamp=datetime.now(timezone.utc),
                provider_name=self.name,
                original_score=original_score,
                adjusted_score=original_score,
                risk_level=RiskLevel.LOW,
                explanation="Context engine unavailable — score unchanged",
            )

        # Convert WorldState → flat dict for rule evaluator
        context_data = _world_state_to_context_dict(world_state)

        # Run multi-layer rule engine
        engine_report = self._engine.generate_context_report(original_score, context_data)

        # Translate risk level string → RiskLevel enum
        risk_map = {
            "LOW": RiskLevel.LOW,
            "MEDIUM": RiskLevel.MEDIUM,
            "HIGH": RiskLevel.HIGH,
            "CRITICAL": RiskLevel.CRITICAL,
        }
        risk_level = risk_map.get(engine_report.risk_level.upper(), RiskLevel.MEDIUM)

        # Translate ContextEngine adjustments → ContextProvider ContextAdjustment format
        provider_adjustments = []
        for adj in engine_report.adjustments:
            provider_adj = ContextAdjustment(
                provider_name=self.name,
                factor_name=adj.feature,
                original_score=original_score,
                adjustment=adj.impact,
                adjusted_score=original_score + adj.impact,
                confidence=adj.confidence,
                reason=adj.reason,
                metadata={"layer": adj.layer, "rule_id": adj.rule_id},
            )
            provider_adjustments.append(provider_adj)

        # Build explanation summary
        top_reasons = [
            f"{a.reason} ({a.adjustment:+.2f})"
            for a in sorted(provider_adjustments, key=lambda x: abs(x.adjustment), reverse=True)[:3]
        ]
        explanation = (
            f"Rule-based adjustment: {original_score:.3f} → {engine_report.adjusted_score:.3f}. "
            + ("Reasons: " + "; ".join(top_reasons) if top_reasons else "No active rules.")
        )

        return ContextReport(
            timestamp=datetime.now(timezone.utc),
            provider_name=self.name,
            world_state=world_state.to_dict(),
            original_score=original_score,
            adjusted_score=engine_report.adjusted_score,
            risk_level=risk_level,
            adjustments=provider_adjustments,
            explanation=explanation,
            breakdown=engine_report.breakdown,
            stop_processing=engine_report.stop_processing,
        )

    def reload_rules(self) -> bool:
        """Hot-reload rules from disk without restarting the bot."""
        try:
            self._load_engine()
            return self._engine is not None
        except Exception as exc:
            logger.error(f"[RuleContextProvider] Reload failed: {exc}")
            return False


if __name__ == "__main__":
    from btc_scraper.core.world_state import WorldState, MarketRegime

    provider = RuleContextProvider("data/context_rules.json")
    is_valid, msg = provider.validate()
    print(f"✓ Validation: {is_valid} — {msg}")

    state = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    state.macro.DXY = 107.0
    state.macro.VIX = 28.0
    state.macro.RealYield = 2.1
    state.liquidity.Funding_Z = 2.5
    state.sentiment.FearGreed = 22

    report = provider.generate_context_report(0.82, state)
    print(f"\nOriginal:  {report.original_score:.3f}")
    print(f"Adjusted:  {report.adjusted_score:.3f}")
    print(f"Risk:      {report.risk_level.value}")
    print(f"Adjustments: {len(report.adjustments)}")
    for adj in report.adjustments:
        print(f"  [{adj.metadata.get('layer')}] {adj.factor_name}: {adj.adjustment:+.3f} — {adj.reason}")
    print(f"\nExplanation: {report.explanation}")
