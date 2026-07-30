from enum import Enum
from typing import Dict, Optional, TYPE_CHECKING
import uuid

from .meta_model import predict_meta_confidence
from btc_scraper.regime.config import (
    regime_decision_weight_enabled,
    regime_effect_metadata,
)
from btc_scraper.regime.contract import (
    RegimeDirection,
    RegimeFamily,
    RegimeSnapshot,
    map_legacy_regime,
)

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

REGIME_DIRECTION_SUPPORT = {
    (RegimeFamily.TREND, RegimeDirection.BULL): {"BUY": 0.9, "SELL": 0.1},
    (RegimeFamily.TREND, RegimeDirection.BEAR): {"BUY": 0.1, "SELL": 0.9},
    (RegimeFamily.BREAKOUT, RegimeDirection.BULL): {"BUY": 0.9, "SELL": 0.1},
    (RegimeFamily.BREAKOUT, RegimeDirection.BEAR): {"BUY": 0.1, "SELL": 0.9},
    (RegimeFamily.RANGE, RegimeDirection.NEUTRAL): {"BUY": 0.5, "SELL": 0.5},
    (RegimeFamily.COMPRESSION, RegimeDirection.NEUTRAL): {"BUY": 0.5, "SELL": 0.5},
    # Explicit risk policy: panic/pump never strongly encourage a fresh entry.
    (RegimeFamily.EXTREME, RegimeDirection.BEAR): {"BUY": 0.05, "SELL": 0.75},
    (RegimeFamily.EXTREME, RegimeDirection.BULL): {"BUY": 0.1, "SELL": 0.6},
}


class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    IGNORE = "IGNORE"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    NEUTRAL = "NEUTRAL"
    BLOCK_ENTRY = "BLOCK_ENTRY"
    ALLOW_REDUCE_ONLY = "ALLOW_REDUCE_ONLY"
    ALLOW_EXIT_ONLY = "ALLOW_EXIT_ONLY"


def apply_final_risk_gate(
    proposed_action: str | DecisionAction,
    risk_level: str,
    stop_processing: bool,
) -> tuple[DecisionAction, tuple[str, ...]]:
    """Apply immutable exposure constraints after every model/context adjustment."""
    try:
        action = DecisionAction(str(getattr(proposed_action, "value", proposed_action)).upper())
    except ValueError:
        action = DecisionAction.HOLD
    if not stop_processing:
        return action, ()
    risk = str(getattr(risk_level, "value", risk_level)).upper()
    if risk == "CRITICAL":
        return DecisionAction.ALLOW_EXIT_ONLY, ("critical_context_hard_stop",)
    if risk == "HIGH" and action in {
        DecisionAction.BUY,
        DecisionAction.SELL,
        DecisionAction.INCREASE,
    }:
        return DecisionAction.BLOCK_ENTRY, ("high_context_entry_block",)
    return action, ()


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
        self.proposed_weights = (weights if weights is not None else DEFAULT_EVIDENCE_WEIGHTS).copy()
        self.weights = self.proposed_weights.copy()
        self.regime_decision_effect_enabled = regime_decision_weight_enabled()
        if not self.regime_decision_effect_enabled:
            self.weights["regime"] = 0.0
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
        direction = self._signal_direction(info)
        if direction not in {"BUY", "SELL"}:
            return 0.5
        raw_snapshot = info.get("regime_snapshot")
        try:
            if isinstance(raw_snapshot, RegimeSnapshot):
                family = raw_snapshot.family
                regime_direction = raw_snapshot.direction
            elif isinstance(raw_snapshot, dict) and raw_snapshot.get("taxonomy_version"):
                snapshot = RegimeSnapshot.from_dict(raw_snapshot)
                family = snapshot.family
                regime_direction = snapshot.direction
            else:
                _, mapped = map_legacy_regime(info.get("regime") or info.get("market_regime"))
                family = mapped.family
                regime_direction = mapped.direction
        except (TypeError, ValueError):
            return 0.5
        return REGIME_DIRECTION_SUPPORT.get((family, regime_direction), {}).get(direction, 0.5)

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

    @staticmethod
    def _persist_final_decision(decision: Dict) -> None:
        if not decision.get("prediction_id"):
            return
        try:
            from .runtime_evidence_store import get_runtime_evidence_store
            get_runtime_evidence_store().append_final_decision(decision)
        except Exception as exc:
            from .operational_health import record_degradation
            record_degradation("prediction_audit", "prediction_audit_write_failure_total", exc)

    def decide(self, analysis_info: Dict, *, persist_final: bool = True) -> Dict:
        meta = predict_meta_confidence(analysis_info)
        if not isinstance(meta, dict) or meta.get("probability") is None:
            return {
                "error": meta.get("error", "no_model"),
                "action": "NEUTRAL",
                "posterior_probability": None,
                "meta_probability": None,
                "meta_ev": None,
                "signal_id": analysis_info.get("signal_id") or analysis_info.get("id"),
                "prediction_id": None,
                "decision_id": str(uuid.uuid4()),
                "context_snapshot_id": None,
                "model_version": None,
                "artifact_sha256": None,
            }

        meta_prob = float(meta["probability"])
        sentiment_prob = self._sentiment_support(analysis_info)
        proposed_regime_prob = self._regime_support(analysis_info)
        applied_regime_prob = proposed_regime_prob if self.regime_decision_effect_enabled else 0.5
        volatility_prob = self._volatility_support(analysis_info)
        posterior = self.compute_posterior(meta_prob, sentiment_prob, applied_regime_prob, volatility_prob)

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
            f"regime_proposed={proposed_regime_prob:.3f}",
            f"regime_applied={applied_regime_prob:.3f}",
            f"volatility={volatility_prob:.3f}",
            f"posterior={posterior:.3f}",
            f"ev={expected_return:.4f}",
        ]

        final_decision = {
            "action": action,
            "posterior_probability": posterior,
            "meta_probability": meta_prob,
            "sentiment_support": sentiment_prob,
            "regime_support": applied_regime_prob,
            "proposed_regime_support": proposed_regime_prob,
            "applied_regime_support": applied_regime_prob,
            "proposed_regime_weight": float(self.proposed_weights.get("regime", 0.0)),
            "applied_regime_weight": float(self.weights.get("regime", 0.0)),
            "regime_snapshot": analysis_info.get("regime_snapshot"),
            "volatility_support": volatility_prob,
            "expected_return": expected_return,
            "expected_drawdown": meta.get("expected_drawdown"),
            "expected_hold_time": meta.get("expected_hold_time"),
            "prob_tp1": meta.get("prob_tp1"),
            "prob_tp2": meta.get("prob_tp2"),
            "prob_sl": meta.get("prob_sl"),
            "meta_ev": meta.get("expected_return"),
            "reason": " | ".join(reason),
            "signal_id": analysis_info.get("signal_id") or analysis_info.get("id"),
            "prediction_id": meta.get("prediction_id"),
            "model_version": meta.get("model_version"),
            "artifact_sha256": meta.get("artifact_sha256"),
            "decision_id": str(uuid.uuid4()),
            "context_snapshot_id": None,
            **regime_effect_metadata(self.regime_decision_effect_enabled),
        }
        if persist_final:
            self._persist_final_decision(final_decision)
        return final_decision

    def apply_context(self, base_decision: Dict, context_report: Dict, *, analysis_info: Optional[Dict] = None) -> Dict:
        """Apply context to an existing inference and enforce the final hard-risk gate."""
        if not context_report or base_decision.get("error"):
            self._persist_final_decision(base_decision)
            return base_decision

        original_posterior = base_decision.get("posterior_probability", 0.5)
        adjusted_posterior = self._clamp01(context_report.get("adjusted_score", original_posterior))
        adjustments = context_report.get("adjustments", [])
        stop_processing = bool(context_report.get("stop_processing", False))
        risk_level = str(getattr(context_report.get("risk_level", "LOW"), "value", context_report.get("risk_level", "LOW"))).upper()
        expected_return = float(base_decision.get("expected_return") or 0.0)

        proposed_action = base_decision.get("action", "HOLD")
        if adjusted_posterior >= self.buy_threshold:
            proposed_action = "BUY" if expected_return >= self.min_ev_pct else "INCREASE"
        elif adjusted_posterior <= self.sell_threshold:
            proposed_action = "SELL" if expected_return <= -self.min_ev_pct else "REDUCE"
        elif self.hold_threshold <= adjusted_posterior <= 1.0 - self.hold_threshold:
            proposed_action = "HOLD"
        if abs(expected_return) < self.min_ev_pct:
            proposed_action = "IGNORE"

        final_action, risk_reasons = apply_final_risk_gate(proposed_action, risk_level, stop_processing)
        reason_parts = [base_decision.get("reason", "")]
        for adj in sorted(adjustments, key=lambda x: abs(x.get("impact", 0)), reverse=True)[:2]:
            reason_parts.append(f"[{adj.get('layer', 'context')}] {adj.get('reason', '')}")
        reason_parts.extend(risk_reasons)
        context_snapshot_id = context_report.get("context_snapshot_id") or str(uuid.uuid4())

        final_decision = {
            **base_decision,
            "action": final_action.value,
            "posterior_probability": original_posterior,
            "adjusted_posterior": adjusted_posterior,
            "context_adjustment": adjusted_posterior - original_posterior,
            "context_risk_level": risk_level,
            "context_adjustments": adjustments,
            "stop_processing": stop_processing,
            "risk_reason_codes": list(risk_reasons),
            "context_snapshot_id": context_snapshot_id,
            "decision_id": base_decision.get("decision_id") or str(uuid.uuid4()),
            "signal_id": base_decision.get("signal_id") or (analysis_info or {}).get("signal_id") or (analysis_info or {}).get("id"),
            "reason": " | ".join(part for part in reason_parts if part),
        }
        self._persist_final_decision(final_decision)
        return final_decision

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
        base_decision = self.decide(analysis_info, persist_final=False)
        return self.apply_context(base_decision, context_report or {}, analysis_info=analysis_info)

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
        base_decision = self.decide(analysis_info, persist_final=False)
        if base_decision.get("error") or base_decision.get("posterior_probability") is None:
            return base_decision

        # Check if provider wants to apply context in current market conditions
        try:
            should_apply = context_provider.should_apply_context(world_state)
        except Exception as exc:
            from .operational_health import record_degradation
            record_degradation("context_provider", "context_provider_failure_total", exc)
            self._persist_final_decision(base_decision)
            return base_decision
        if not should_apply:
            base_decision["context_provider"] = context_provider.name
            base_decision["context_skipped"] = True
            self._persist_final_decision(base_decision)
            return base_decision

        original_posterior = base_decision.get("posterior_probability", 0.5)

        # Generate context report via provider
        try:
            report = context_provider.generate_context_report(original_posterior, world_state)
        except Exception as exc:
            import logging
            from .operational_health import record_degradation
            record_degradation("context_provider", "context_provider_failure_total", exc)
            logging.getLogger(__name__).error(
                f"[DecisionEngine] ContextProvider '{context_provider.name}' failed: {exc}"
            )
            self._persist_final_decision(base_decision)
            return base_decision

        return {
            **self.apply_context(base_decision, report.to_dict(), analysis_info=analysis_info),
            "context_provider": context_provider.name,
            "context_skipped": False,
        }
