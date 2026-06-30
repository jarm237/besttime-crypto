from typing import Dict, Optional, TYPE_CHECKING

from .meta_model import predict_meta_confidence

if TYPE_CHECKING:
    from .context_engine import ContextReport
    from .context_provider import ContextProvider
    from btc_scraper.core.world_state import WorldState

DEFAULT_EVIDENCE_WEIGHTS = {
    "meta": 0.55,
    "sentiment": 0.15,
    "regime": 0.15,
    "volatility": 0.15,
}


class MetaDecisionEngine:
    """Central decision engine combining EV meta model and contextual evidence."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        buy_threshold: float = 0.65,
        sell_threshold: float = 0.35,
        hold_threshold: float = 0.45,
        min_ev_pct: float = 0.05,
    ):
        self.weights = weights if weights is not None else DEFAULT_EVIDENCE_WEIGHTS.copy()
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.hold_threshold = hold_threshold
        self.min_ev_pct = min_ev_pct

    def _clamp01(self, value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.5

    def _signal_direction(self, info: Dict) -> str:
        text = str(info.get("signal") or info.get("action") or "").upper()
        if "SELL" in text or "SHORT" in text or "BEAR" in text:
            return "SELL"
        if "BUY" in text or "LONG" in text or "BULL" in text:
            return "BUY"
        return "NEUTRAL"

    def _sentiment_support(self, info: Dict) -> float:
        fg = info.get("fear_greed")
        try:
            fg = float(fg) if fg is not None else 50.0
        except Exception:
            fg = 50.0
        fg_score = self._clamp01(fg / 100.0)

        momentum = info.get("sentiment_momentum")
        try:
            momentum = float(momentum)
        except Exception:
            momentum = 0.0
        momentum = self._clamp01((momentum + 1.0) / 2.0)

        direction = self._signal_direction(info)
        if direction == "BUY":
            return self._clamp01(0.55 * fg_score + 0.45 * momentum)
        if direction == "SELL":
            return self._clamp01(0.55 * (1.0 - fg_score) + 0.45 * (1.0 - momentum))
        return 0.5

    def _regime_support(self, info: Dict) -> float:
        regime = str(info.get("regime") or info.get("market_regime") or "").upper()
        direction = self._signal_direction(info)
        if "TRENDING_BULL" in regime or "STRONG_TREND" in regime:
            return 0.9 if direction == "BUY" else 0.1
        if "TRENDING_BEAR" in regime or "BEAR" in regime:
            return 0.1 if direction == "BUY" else 0.9
        if "RANGING" in regime or "COMPRESSION" in regime:
            return 0.5
        return 0.5

    def _volatility_support(self, info: Dict) -> float:
        atr_pct = info.get("atr_pct") or info.get("atr")
        vol_index = info.get("atr_percentile") or info.get("hv20") or info.get("volatility_regime_panic_sell")
        try:
            vol = float(vol_index) if vol_index is not None else 50.0
        except Exception:
            vol = 50.0
        try:
            atr = float(atr_pct) if atr_pct is not None else 1.0
        except Exception:
            atr = 1.0

        if vol >= 80 or atr >= 3.0:
            return 0.25
        if vol >= 60 or atr >= 2.0:
            return 0.5
        if vol >= 40 or atr >= 1.2:
            return 0.75
        return 0.9

    def compute_posterior(
        self,
        meta_prob: float,
        sentiment_prob: float,
        regime_prob: float,
        volatility_prob: float,
    ) -> float:
        evidence = {
            "meta": self._clamp01(meta_prob),
            "sentiment": self._clamp01(sentiment_prob),
            "regime": self._clamp01(regime_prob),
            "volatility": self._clamp01(volatility_prob),
        }
        total_weight = sum(self.weights.get(k, 0.0) for k in evidence)
        if total_weight <= 0:
            return 0.5
        weighted = 0.0
        for key, value in evidence.items():
            weight = self.weights.get(key, 0.0)
            weighted += value * weight
        return self._clamp01(weighted / total_weight)

    def decide(self, analysis_info: Dict) -> Dict:
        meta = predict_meta_confidence(analysis_info)
        if not isinstance(meta, dict) or meta.get("probability") is None:
            return {
                "error": meta.get("error", "no_model"),
                "action": "NEUTRAL",
                "posterior_probability": None,
                "meta_probability": None,
                "meta_ev": None,
            }

        meta_prob = float(meta["probability"])
        sentiment_prob = self._sentiment_support(analysis_info)
        regime_prob = self._regime_support(analysis_info)
        volatility_prob = self._volatility_support(analysis_info)
        posterior = self.compute_posterior(meta_prob, sentiment_prob, regime_prob, volatility_prob)

        expected_return = meta.get("expected_return")
        if expected_return is None:
            expected_return = 0.0
        try:
            expected_return = float(expected_return)
        except Exception:
            expected_return = 0.0

        action = "HOLD"
        if expected_return >= self.min_ev_pct and posterior >= self.buy_threshold:
            action = "BUY"
        elif expected_return <= -self.min_ev_pct and posterior <= self.sell_threshold:
            action = "SELL"
        elif posterior >= self.buy_threshold:
            action = "INCREASE"
        elif posterior <= self.sell_threshold:
            action = "REDUCE"
        elif self.hold_threshold <= posterior <= 1.0 - self.hold_threshold:
            action = "HOLD"

        if abs(expected_return) < self.min_ev_pct:
            action = "IGNORE"

        reason = [
            f"meta_prob={meta_prob:.3f}",
            f"sentiment={sentiment_prob:.3f}",
            f"regime={regime_prob:.3f}",
            f"volatility={volatility_prob:.3f}",
            f"posterior={posterior:.3f}",
            f"ev={expected_return:.4f}",
        ]

        return {
            "action": action,
            "posterior_probability": posterior,
            "meta_probability": meta_prob,
            "sentiment_support": sentiment_prob,
            "regime_support": regime_prob,
            "volatility_support": volatility_prob,
            "expected_return": expected_return,
            "expected_drawdown": meta.get("expected_drawdown"),
            "expected_hold_time": meta.get("expected_hold_time"),
            "prob_tp1": meta.get("prob_tp1"),
            "prob_tp2": meta.get("prob_tp2"),
            "prob_sl": meta.get("prob_sl"),
            "meta_ev": meta.get("expected_return"),
            "reason": " | ".join(reason),
        }

    def decide_with_context(
        self,
        analysis_info: Dict,
        context_report: Optional[Dict] = None,
    ) -> Dict:
        """
        Make decision incorporating causal context adjustment.
        
        Args:
            analysis_info: Base analysis information
            context_report: ContextReport dict (from ContextEngine)
            
        Returns:
            Enhanced decision dict with context adjustments
        """
        # Get base decision
        base_decision = self.decide(analysis_info)

        if not context_report or base_decision.get("error"):
            return base_decision

        # Extract context adjustments
        original_posterior = base_decision.get("posterior_probability", 0.5)
        adjusted_posterior = context_report.get("adjusted_score", original_posterior)
        adjustments = context_report.get("adjustments", [])
        stop_processing = context_report.get("stop_processing", False)
        risk_level = context_report.get("risk_level", "LOW")

        # Check if we should override decision due to stop_processing
        if stop_processing and risk_level in ["CRITICAL", "HIGH"]:
            base_decision["action"] = "REDUCE" if base_decision["action"] in ["BUY", "INCREASE"] else base_decision["action"]
            base_decision["action"] = "HOLD" if base_decision["action"] == "NEUTRAL" else base_decision["action"]

        # Recalculate action based on adjusted posterior
        action = base_decision["action"]
        if adjusted_posterior >= self.buy_threshold:
            action = "BUY" if base_decision.get("expected_return", 0) >= self.min_ev_pct else "INCREASE"
        elif adjusted_posterior <= self.sell_threshold:
            action = "SELL" if base_decision.get("expected_return", 0) <= -self.min_ev_pct else "REDUCE"
        elif self.hold_threshold <= adjusted_posterior <= 1.0 - self.hold_threshold:
            action = "HOLD"

        # Build enhanced reason
        reason_parts = [base_decision.get("reason", "")]
        if adjustments:
            top_adjustments = sorted(adjustments, key=lambda x: abs(x.get("impact", 0)), reverse=True)[:2]
            for adj in top_adjustments:
                reason_parts.append(f"[{adj['layer']}] {adj['reason']}")

        return {
            **base_decision,
            "action": action,
            "posterior_probability": original_posterior,
            "adjusted_posterior": adjusted_posterior,
            "context_adjustment": adjusted_posterior - original_posterior,
            "context_risk_level": risk_level,
            "context_adjustments": adjustments,
            "stop_processing": stop_processing,
            "reason": " | ".join(reason_parts),
        }

    def decide_with_provider(
        self,
        analysis_info: Dict,
        context_provider: "ContextProvider",
        world_state: "WorldState",
    ) -> Dict:
        """
        Make decision using the ContextProvider interface (Phase 2.1).

        This is the preferred entry point in the v2.0 architecture.
        DecisionEngine is fully decoupled from the concrete implementation
        — it only depends on the ContextProvider interface and WorldState.

        Args:
            analysis_info: Base analysis dict (same as decide()).
            context_provider: Any ContextProvider implementation
                              (RuleContextProvider, BayesianContextProvider, etc.).
            world_state: Current unified WorldState.

        Returns:
            Enhanced decision dict, same shape as decide_with_context().
        """
        # Get base decision
        base_decision = self.decide(analysis_info)
        if base_decision.get("error") or base_decision.get("posterior_probability") is None:
            return base_decision

        # Check if provider wants to apply context in current market conditions
        if not context_provider.should_apply_context(world_state):
            base_decision["context_provider"] = context_provider.name
            base_decision["context_skipped"] = True
            return base_decision

        original_posterior = base_decision.get("posterior_probability", 0.5)

        # Generate context report via provider
        try:
            report = context_provider.generate_context_report(original_posterior, world_state)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                f"[DecisionEngine] ContextProvider '{context_provider.name}' failed: {exc}"
            )
            return base_decision

        # Delegate to decide_with_context using serialized report
        return {
            **self.decide_with_context(analysis_info, report.to_dict()),
            "context_provider": context_provider.name,
            "context_skipped": False,
        }
