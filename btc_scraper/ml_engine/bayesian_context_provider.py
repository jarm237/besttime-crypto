"""
BayesianContextProvider - Probabilistic context adjustment using Bayesian inference.

Phase 3.0 of the Causal World Model integration.

Instead of hard rules like "if DXY > threshold → impact -0.15", this provider
computes a posterior probability adjustment by combining:
  - Prior belief derived from causal_graph.json edge weights
  - Likelihood of the observed WorldState under each market hypothesis

Architecture:
    P(BTC_UP | evidence) ∝ P(evidence | BTC_UP) * P(BTC_UP)
    
    evidence = {DXY, VIX, Funding_Z, Sentiment, RealYield, ...}

Designed to complement (not replace) RuleContextProvider.
Use HybridContextProvider to blend both approaches.
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from btc_scraper.ml_engine.context_provider import (
    ContextAdjustment,
    ContextProvider,
    ContextReport,
    RiskLevel,
)
from btc_scraper.core.world_state import WorldState

logger = logging.getLogger(__name__)


# ─── Feature Specifications ───────────────────────────────────────────────────

@dataclass
class FeatureSpec:
    """Defines how a WorldState feature contributes to the Bayesian model."""
    name: str
    # Expected value distribution under BULLISH hypothesis (mean, std)
    bullish_mean: float
    bullish_std: float
    # Expected value distribution under BEARISH hypothesis
    bearish_mean: float
    bearish_std: float
    # Weight in the final score (from causal graph edge confidence)
    weight: float
    # Human-readable description
    description: str = ""


# Default feature specifications derived from causal_graph.json knowledge
DEFAULT_FEATURE_SPECS: List[FeatureSpec] = [
    FeatureSpec(
        name="DXY",
        bullish_mean=100.0,   # Low DXY = risk-on, good for BTC
        bullish_std=3.0,
        bearish_mean=107.0,   # High DXY = risk-off, bad for BTC
        bearish_std=3.0,
        weight=0.85,
        description="US Dollar Index (negative causal link to BTC)",
    ),
    FeatureSpec(
        name="VIX",
        bullish_mean=16.0,    # Low VIX = calm markets
        bullish_std=4.0,
        bearish_mean=28.0,    # High VIX = fear
        bearish_std=6.0,
        weight=0.70,
        description="Volatility Index (negative sentiment indicator)",
    ),
    FeatureSpec(
        name="Funding_Z",
        bullish_mean=0.2,     # Slight long bias = healthy
        bullish_std=0.8,
        bearish_mean=2.5,     # Extreme longs = overheated, correction risk
        bearish_std=0.7,
        weight=0.60,
        description="Funding Rate Z-score (extreme values = mean reversion risk)",
    ),
    FeatureSpec(
        name="FearGreed",
        bullish_mean=60.0,    # Moderate greed = trend continuation
        bullish_std=12.0,
        bearish_mean=25.0,    # Extreme fear = capitulation or continuation
        bearish_std=10.0,
        weight=0.55,
        description="Fear & Greed Index (0=extreme fear, 100=extreme greed)",
    ),
    FeatureSpec(
        name="RealYield",
        bullish_mean=0.5,     # Low/negative real yields = good for hard assets
        bullish_std=0.8,
        bearish_mean=2.2,     # High real yields = competition for BTC
        bearish_std=0.6,
        weight=0.80,
        description="10Y Real Yield (negative causal link to BTC)",
    ),
    FeatureSpec(
        name="OI_Delta",
        bullish_mean=3.0,     # Modest OI growth = healthy
        bullish_std=5.0,
        bearish_mean=22.0,    # OI surge = overheated, unwind risk
        bearish_std=8.0,
        weight=0.50,
        description="Open Interest Delta % (extreme = liquidation risk)",
    ),
]


# ─── Core Bayesian Engine ─────────────────────────────────────────────────────

def _gaussian_log_likelihood(x: float, mean: float, std: float) -> float:
    """Compute log-likelihood of observation x under Gaussian(mean, std)."""
    if std <= 0:
        return 0.0
    z = (x - mean) / std
    return -0.5 * z * z - math.log(std * math.sqrt(2 * math.pi))


def _has_macro_data(world_state: WorldState) -> bool:
    """Return True when macro defaults have been replaced by collected data."""
    m = world_state.macro
    return bool(
        m.updated_at
        or m.DXY > 0.0
        or m.BondYield > 0.0
        or m.FedRate > 0.0
        or m.RealYield != 0.0
        or m.VIX != 20.0
    )


def _has_liquidity_data(world_state: WorldState) -> bool:
    """Return True when liquidity defaults have been replaced by collected data."""
    l = world_state.liquidity
    return bool(
        l.updated_at
        or l.BTC_Funding != 0.0
        or l.ETH_Funding != 0.0
        or l.BTC_OI > 0.0
        or l.ETH_OI > 0.0
        or l.BTC_LongShortRatio != 1.0
        or l.ETH_LongShortRatio != 1.0
        or l.Funding_Z != 0.0
        or l.OI_Delta != 0.0
    )


def _has_sentiment_data(world_state: WorldState) -> bool:
    """Return True when sentiment defaults have been replaced by collected data."""
    s = world_state.sentiment
    return bool(
        s.updated_at
        or s.FearGreed != 50.0
        or s.SocialVolume > 0.0
        or s.LongTermHolders > 0.0
        or s.NewAddresses > 0.0
    )


def _has_risk_data(world_state: WorldState) -> bool:
    """Return True when risk defaults have been replaced by collected data."""
    r = world_state.risk
    return bool(
        r.updated_at
        or r.CurrentDrawdown != 0.0
        or r.MaxDrawdown != 0.0
        or r.Volatility != 0.0
        or r.VaR95 != 0.0
        or r.Sharpe != 0.0
    )


def _extract_feature_value(name: str, world_state: WorldState) -> Optional[float]:
    """Extract a named feature value from WorldState when its layer has data."""
    m = world_state.macro
    l = world_state.liquidity
    s = world_state.sentiment
    r = world_state.risk

    if name in world_state.custom_indicators:
        return float(world_state.custom_indicators[name])

    macro_features = {
        "DXY": m.DXY,
        "VIX": m.VIX,
        "RealYield": m.RealYield,
        "BondYield": m.BondYield,
        "FedRate": m.FedRate,
    }
    liquidity_features = {
        "Funding_Z": l.Funding_Z,
        "OI_Delta": l.OI_Delta,
    }
    sentiment_features = {
        "FearGreed": s.FearGreed,
    }
    risk_features = {
        "Drawdown": r.CurrentDrawdown,
        "Volatility": r.Volatility,
    }

    mapping = {
        **macro_features,
        **liquidity_features,
        **sentiment_features,
        **risk_features,
    }

    if name in macro_features and not _has_macro_data(world_state):
        return None
    if name in liquidity_features and not _has_liquidity_data(world_state):
        return None
    if name in sentiment_features and not _has_sentiment_data(world_state):
        return None
    if name in risk_features and not _has_risk_data(world_state):
        return None

    val = mapping.get(name)
    return float(val) if val is not None else None


@dataclass
class BayesianFeatureEvidence:
    """Evidence from a single feature in the Bayesian update."""
    feature_name: str
    observed_value: float
    log_likelihood_bullish: float
    log_likelihood_bearish: float
    weight: float
    posterior_contribution: float  # Positive = bullish, negative = bearish
    description: str = ""


class BayesianContextProvider(ContextProvider):
    """
    Probabilistic context provider using Bayesian inference.

    Computes a posterior probability that current conditions are bullish
    by combining likelihoods from multiple market features via log-sum.

    This provider:
    - Does NOT use hard rules or thresholds
    - Produces a smooth, continuous score adjustment
    - Is robust to missing features (skips gracefully)
    - Can incorporate learned feature distributions from historical data

    Score adjustment formula:
        posterior_log_odds = sum(weight_i * (logL_bullish_i - logL_bearish_i))
        posterior_probability = sigmoid(posterior_log_odds)
        adjustment = (posterior_probability - 0.5) * max_adjustment_range
    """

    # Maximum total score adjustment in either direction
    MAX_ADJUSTMENT = 0.30

    def __init__(
        self,
        feature_specs: Optional[List[FeatureSpec]] = None,
        prior_bullish: float = 0.50,
        max_adjustment: float = 0.30,
        name: str = "BayesianContextProvider",
    ):
        """
        Args:
            feature_specs: Feature distribution specifications. Uses defaults if None.
            prior_bullish: Prior probability of bullish conditions (0.5 = agnostic).
            max_adjustment: Maximum score adjustment range in either direction.
            name: Provider name.
        """
        super().__init__(name)
        self.feature_specs = feature_specs or DEFAULT_FEATURE_SPECS
        self.prior_log_odds = math.log(prior_bullish / (1.0 - prior_bullish + 1e-9) + 1e-9)
        self.max_adjustment = max_adjustment

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Numerically stable sigmoid."""
        if x >= 0:
            return 1.0 / (1.0 + math.exp(-x))
        else:
            e = math.exp(x)
            return e / (1.0 + e)

    def _compute_evidence(
        self, world_state: WorldState
    ) -> List[BayesianFeatureEvidence]:
        """Compute Bayesian evidence from each feature in WorldState."""
        evidence_list = []

        for spec in self.feature_specs:
            value = _extract_feature_value(spec.name, world_state)
            if value is None:
                continue  # Skip missing features gracefully

            log_l_bull = _gaussian_log_likelihood(value, spec.bullish_mean, spec.bullish_std)
            log_l_bear = _gaussian_log_likelihood(value, spec.bearish_mean, spec.bearish_std)

            # Positive contribution = evidence favors bullish
            contribution = spec.weight * (log_l_bull - log_l_bear)

            evidence_list.append(BayesianFeatureEvidence(
                feature_name=spec.name,
                observed_value=value,
                log_likelihood_bullish=log_l_bull,
                log_likelihood_bearish=log_l_bear,
                weight=spec.weight,
                posterior_contribution=contribution,
                description=spec.description,
            ))

        return evidence_list

    def _risk_level_from_posterior(self, posterior: float) -> RiskLevel:
        """Map posterior probability to RiskLevel."""
        if posterior < 0.25:
            return RiskLevel.CRITICAL
        elif posterior < 0.40:
            return RiskLevel.HIGH
        elif posterior < 0.55:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def validate(self) -> tuple[bool, str]:
        """Validate feature specifications."""
        if not self.feature_specs:
            return False, "No feature specifications defined"
        for spec in self.feature_specs:
            if spec.bullish_std <= 0 or spec.bearish_std <= 0:
                return False, f"Feature '{spec.name}' has invalid std (<= 0)"
            if not (0.0 <= spec.weight <= 1.0):
                return False, f"Feature '{spec.name}' weight must be in [0,1]"
        return True, "BayesianContextProvider is valid"

    def should_apply_context(self, world_state: WorldState) -> bool:
        """Apply when at least 2 features are available."""
        available = sum(
            1 for s in self.feature_specs
            if _extract_feature_value(s.name, world_state) is not None
        )
        return available >= 2

    def generate_context_report(
        self, original_score: float, world_state: WorldState
    ) -> ContextReport:
        """
        Generate ContextReport via Bayesian inference.

        Computes posterior probability of bullish conditions given current market
        state, then maps that into a score adjustment.
        """
        evidence_list = self._compute_evidence(world_state)

        if not evidence_list:
            logger.warning("[BayesianContextProvider] No features available, passthrough")
            return ContextReport(
                timestamp=datetime.now(timezone.utc),
                provider_name=self.name,
                world_state=world_state.to_dict(),
                original_score=original_score,
                adjusted_score=original_score,
                risk_level=RiskLevel.LOW,
                explanation="No market features available for Bayesian inference",
            )

        # Compute posterior log-odds
        total_log_odds = self.prior_log_odds + sum(e.posterior_contribution for e in evidence_list)
        posterior_bullish = self._sigmoid(total_log_odds)

        # Map posterior → score adjustment
        # posterior = 0.5 → no adjustment
        # posterior > 0.5 → positive adjustment (bullish)
        # posterior < 0.5 → negative adjustment (bearish)
        raw_adjustment = (posterior_bullish - 0.5) * 2 * self.max_adjustment
        adjusted_score = max(0.0, min(1.0, original_score + raw_adjustment))

        # Build ContextAdjustment objects (top 5 features by |contribution|)
        sorted_evidence = sorted(evidence_list, key=lambda e: abs(e.posterior_contribution), reverse=True)
        adjustments = []
        for ev in sorted_evidence[:5]:
            # Scale individual contribution to fractional score impact
            feature_score_impact = (
                (self._sigmoid(ev.posterior_contribution) - 0.5)
                * 2 * self.max_adjustment
                * (ev.weight / sum(s.weight for s in self.feature_specs))
            )
            direction = "bullish" if ev.posterior_contribution > 0 else "bearish"
            adj = ContextAdjustment(
                provider_name=self.name,
                factor_name=ev.feature_name,
                original_score=original_score,
                adjustment=feature_score_impact,
                adjusted_score=original_score + feature_score_impact,
                confidence=abs(self._sigmoid(ev.posterior_contribution * 2) - 0.5) * 2,
                reason=(
                    f"{ev.feature_name}={ev.observed_value:.2f} — {direction} signal "
                    f"(contribution={ev.posterior_contribution:+.3f})"
                ),
                metadata={
                    "log_l_bull": round(ev.log_likelihood_bullish, 4),
                    "log_l_bear": round(ev.log_likelihood_bearish, 4),
                    "feature_description": ev.description,
                },
            )
            adjustments.append(adj)

        # Breakdown by category
        macro_features = {"DXY", "VIX", "RealYield", "BondYield", "FedRate"}
        crypto_features = {"Funding_Z", "OI_Delta"}
        sentiment_features = {"FearGreed"}

        def _sum_contributions(names: set) -> float:
            return sum(
                (self._sigmoid(e.posterior_contribution) - 0.5)
                * 2 * self.max_adjustment
                * (e.weight / max(sum(s.weight for s in self.feature_specs), 1e-9))
                for e in evidence_list
                if e.feature_name in names
            )

        breakdown = {
            "macro":     round(_sum_contributions(macro_features), 4),
            "market":    round(_sum_contributions(crypto_features), 4),
            "sentiment": round(_sum_contributions(sentiment_features), 4),
        }

        risk_level = self._risk_level_from_posterior(posterior_bullish)

        top_factor = sorted_evidence[0] if sorted_evidence else None
        explanation = (
            f"Bayesian posterior: {posterior_bullish:.1%} bullish "
            f"(prior=50%, {len(evidence_list)} features). "
            f"Score: {original_score:.3f} → {adjusted_score:.3f}. "
            + (
                f"Dominant: {top_factor.feature_name}={top_factor.observed_value:.2f}"
                if top_factor else ""
            )
        )

        return ContextReport(
            timestamp=datetime.now(timezone.utc),
            provider_name=self.name,
            world_state=world_state.to_dict(),
            original_score=original_score,
            adjusted_score=adjusted_score,
            risk_level=risk_level,
            adjustments=adjustments,
            explanation=explanation,
            breakdown=breakdown,
        )

    @classmethod
    def from_causal_graph(cls, graph_path: str, **kwargs) -> "BayesianContextProvider":
        """
        Build a BayesianContextProvider with weights derived from causal_graph.json.

        Reads edge confidences for edges targeting BTC and uses them as feature weights,
        overriding the defaults.

        Args:
            graph_path: Path to causal_graph.json.
            **kwargs: Additional args forwarded to __init__.

        Returns:
            Configured BayesianContextProvider.
        """
        try:
            with open(graph_path) as f:
                graph = json.load(f)
        except Exception as exc:
            logger.warning(f"[BayesianContextProvider] Cannot load graph '{graph_path}': {exc}")
            return cls(**kwargs)

        # Build weight override map from edges targeting BTC
        weight_overrides: Dict[str, float] = {}
        node_to_feature = {
            "DXY": "DXY",
            "VIX": "VIX",
            "RealYield": "RealYield",
            "Funding": "Funding_Z",
            "OI": "OI_Delta",
            "Sentiment": "FearGreed",
            "BondYield": "BondYield",
            "FedRate": "FedRate",
        }

        for edge in graph.get("edges", []):
            if edge.get("to") == "BTC" and edge.get("is_active", True):
                node = edge.get("from", "")
                feat = node_to_feature.get(node)
                if feat:
                    # Use edge confidence as Bayesian weight
                    weight_overrides[feat] = float(edge.get("confidence", 0.7))

        # Apply overrides to default specs
        updated_specs = []
        for spec in DEFAULT_FEATURE_SPECS:
            if spec.name in weight_overrides:
                updated_spec = FeatureSpec(
                    name=spec.name,
                    bullish_mean=spec.bullish_mean,
                    bullish_std=spec.bullish_std,
                    bearish_mean=spec.bearish_mean,
                    bearish_std=spec.bearish_std,
                    weight=weight_overrides[spec.name],
                    description=spec.description + " [weight from graph]",
                )
                updated_specs.append(updated_spec)
                logger.debug(f"[BayesianContextProvider] Weight override: {spec.name} → {weight_overrides[spec.name]:.2f}")
            else:
                updated_specs.append(spec)

        logger.info(
            f"[BayesianContextProvider] Loaded from graph '{graph_path}' — "
            f"{len(weight_overrides)} weight overrides applied"
        )
        return cls(feature_specs=updated_specs, **kwargs)


if __name__ == "__main__":
    from btc_scraper.core.world_state import WorldState, MarketRegime

    # Risk-off conditions: High DXY, High VIX, High Real Yield, Fear sentiment
    risk_off = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_OFF)
    risk_off.macro.DXY = 108.5
    risk_off.macro.VIX = 32.0
    risk_off.macro.RealYield = 2.3
    risk_off.liquidity.Funding_Z = 2.8
    risk_off.sentiment.FearGreed = 18.0

    # Risk-on conditions: Low DXY, Low VIX, Moderate Greed
    risk_on = WorldState(timestamp=datetime.now(timezone.utc), regime=MarketRegime.RISK_ON)
    risk_on.macro.DXY = 100.5
    risk_on.macro.VIX = 14.0
    risk_on.macro.RealYield = 0.4
    risk_on.liquidity.Funding_Z = 0.3
    risk_on.sentiment.FearGreed = 62.0

    provider = BayesianContextProvider.from_causal_graph("data/causal_graph.json")
    is_valid, msg = provider.validate()
    print(f"✓ Valid: {is_valid} — {msg}")

    print("\n--- RISK-OFF CONDITIONS ---")
    report = provider.generate_context_report(0.82, risk_off)
    print(f"Score: {report.original_score:.3f} → {report.adjusted_score:.3f}")
    print(f"Risk: {report.risk_level.value}")
    print(f"Explanation: {report.explanation}")

    print("\n--- RISK-ON CONDITIONS ---")
    report2 = provider.generate_context_report(0.70, risk_on)
    print(f"Score: {report2.original_score:.3f} → {report2.adjusted_score:.3f}")
    print(f"Risk: {report2.risk_level.value}")
    print(f"Explanation: {report2.explanation}")
