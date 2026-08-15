from enum import Enum
from typing import Dict, Optional, TYPE_CHECKING
import uuid

from .meta_model import predict_meta_confidence
from btc_scraper.core.paths import (
    runtime_evidence_eligible,
    runtime_paper_run_id,
)
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


# ──────────────────────────────────────────────────────────────────────
# Unit contract for expected return values
# CONTRACT: All expected_return values in this engine are *fractional returns*
# (not percentage points). Scale reference:
#   0.0001 =  1 bp   (0.01%)
#   0.0005 =  5 bps  (0.05%)   ← MIN_EV_PCT_DEFAULT
#   0.005  = 50 bps  (0.5%)
#   0.05   = 500 bps (5.0%)
# ──────────────────────────────────────────────────────────────────────
_EXPECTED_RETURN_UNIT = "FRACTION"  # confirms unit; do not change without updating all callers
MIN_EV_PCT_DEFAULT = 0.0005  # 5 bps — minimum net expected value per trade


class MetaDecisionEngine:
    """Central decision engine combining EV meta model and contextual evidence."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        buy_threshold: float = 0.50,
        sell_threshold: float = 0.50,
        hold_threshold: float = 0.45,
        min_ev_pct: float = MIN_EV_PCT_DEFAULT,  # see _EXPECTED_RETURN_UNIT: FRACTION (0.0005 = 5 bps)
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

    @staticmethod
    def _terminal_fields(action: str) -> dict:
        normalized = str(action or "").upper()
        if normalized in {"BUY", "SELL"}:
            terminal_status = "TRADE"
            eligible = True
        elif normalized in {"BLOCK_ENTRY", "ALLOW_EXIT_ONLY", "ERROR"}:
            terminal_status = "ERROR" if normalized == "ERROR" else "REJECTED"
            eligible = False
        else:
            terminal_status = "HOLD"
            eligible = False
        return {
            "terminal_status": terminal_status,
            "eligible": eligible,
            "superseded": False,
        }

    def _signal_direction(self, info: Dict) -> str:
        text = str(info.get("signal") or info.get("action") or "").upper()
        if "SELL" in text or "SHORT" in text or "BEAR" in text:
            return "SELL"
        if "BUY" in text or "LONG" in text or "BULL" in text:
            return "BUY"
        return "NEUTRAL"

    @staticmethod
    def _entry_action(info: Dict) -> str:
        """Return the structured pre-final action, never a display label."""
        action = str(info.get("action") or "").upper()
        return action if action in {"BUY", "SELL"} else "NEUTRAL"

    @staticmethod
    def _execution_probability(action: str, meta_probability: float) -> float:
        probability = max(0.0, min(1.0, float(meta_probability)))
        return 1.0 - probability if str(action).upper() == "SELL" else probability

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

    @staticmethod
    def _existing_final_decision(payload: Dict) -> Optional[Dict]:
        meta = payload.get("_meta_prediction")
        prediction_id = (
            meta.get("prediction_id")
            if isinstance(meta, dict)
            else payload.get("prediction_id")
        )
        if not prediction_id:
            return None
        from .runtime_evidence_store import get_runtime_evidence_store
        return get_runtime_evidence_store().get_final_decision_for_prediction(
            str(prediction_id)
        )

    def decide(self, analysis_info: Dict, *, persist_final: bool = True) -> Dict:
        meta = analysis_info.get("_meta_prediction")
        existing = self._existing_final_decision(analysis_info)
        if existing is not None:
            return existing
        if not isinstance(meta, dict):
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

        proposed_side = self._entry_action(analysis_info)
        signal_side = proposed_side if proposed_side in {"BUY", "SELL"} else self._signal_direction(analysis_info)
        probability_semantics = str(meta.get("probability_semantics") or "P(up)")
        if meta.get("model_probability_up") is not None:
            model_probability_up = self._clamp01(meta["model_probability_up"])
        elif probability_semantics == "P(win_given_proposed_trade)":
            side_value = self._clamp01(meta["probability"])
            model_probability_up = 1.0 - side_value if signal_side == "SELL" else side_value
        else:
            model_probability_up = self._clamp01(meta["probability"])
        meta_prob = (
            self._clamp01(meta.get("execution_probability"))
            if meta.get("execution_probability") is not None
            else self._execution_probability(signal_side, model_probability_up)
        )
        sentiment_prob = self._sentiment_support(analysis_info)
        proposed_regime_prob = self._regime_support(analysis_info)
        applied_regime_prob = proposed_regime_prob if self.regime_decision_effect_enabled else 0.5
        volatility_prob = self._volatility_support(analysis_info)
        side_probability = self.compute_posterior(
            meta_prob, sentiment_prob, applied_regime_prob, volatility_prob
        )
        posterior = (
            1.0 - side_probability if signal_side == "SELL" else side_probability
        )

        expected_return = meta.get("expected_return")
        if expected_return is None:
            expected_return = 0.0
        try:
            expected_return = float(expected_return)
        except Exception:
            expected_return = 0.0

        action = "HOLD"
        if signal_side == "BUY":
            if expected_return >= self.min_ev_pct and side_probability >= self.buy_threshold:
                action = "BUY"
            elif side_probability >= self.buy_threshold:
                action = "INCREASE"
        elif signal_side == "SELL":
            if expected_return >= self.min_ev_pct and side_probability >= self.sell_threshold:
                action = "SELL"
            elif side_probability >= self.sell_threshold:
                action = "REDUCE"

        if expected_return < self.min_ev_pct:
            action = "IGNORE"

        risk_status = str(analysis_info.get("risk_status") or "HEALTHY").upper()
        risk_failure_reason = analysis_info.get("risk_failure_reason")
        risk_blocked = bool(analysis_info.get("risk_blocked", False))
        if risk_blocked or risk_status == "UNAVAILABLE":
            action = "BLOCK_ENTRY"
            risk_failure_reason = risk_failure_reason or "risk_data_unavailable"

        # A meta/context layer may filter a structured entry action, but it may
        # not manufacture a physical BUY/SELL from a neutral pre-final intent.
        # Display text is deliberately not consulted here.
        if action in {"BUY", "SELL"} and self._entry_action(analysis_info) != action:
            action = "HOLD"
            risk_failure_reason = "canonical_action_not_supported_by_entry_signal"

        reason = [
            f"model_probability_up={model_probability_up:.3f}",
            f"meta_side_probability={meta_prob:.3f}",
            f"meta_prob={meta_prob:.3f}",
            f"sentiment={sentiment_prob:.3f}",
            f"regime_proposed={proposed_regime_prob:.3f}",
            f"regime_applied={applied_regime_prob:.3f}",
            f"volatility={volatility_prob:.3f}",
            f"posterior={posterior:.3f}",
            f"side_probability={side_probability:.3f}",
            f"ev={expected_return:.4f}",
        ]
        if risk_blocked or risk_status == "UNAVAILABLE":
            reason.append(f"risk_failure={risk_failure_reason}")

        final_decision = {
            "action": action,
            "posterior_probability": posterior,
            "posterior_probability_semantics": "P(up)",
            "side_probability": side_probability,
            "side_probability_semantics": "P(win_given_proposed_trade)",
            "meta_probability": meta_prob,
            "meta_probability_semantics": "P(win_given_proposed_trade)",
            "model_probability_up": model_probability_up,
            "model_probability_semantics": "P(up)",
            "execution_probability": meta_prob,
            "execution_probability_semantics": "P(win_given_proposed_trade)",
            "decision_contract_version": "side-probability-v2",
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
            "model_artifact_sha256": meta.get("artifact_sha256"),
            "feature_schema_version": meta.get("feature_schema_version"),
            "deployment_id": meta.get("deployment_id"),
            "paper_run_id": (
                meta.get("paper_run_id") or runtime_paper_run_id()
            ),
            "cycle_id": meta.get("cycle_id"),
            "decision_context": meta.get("decision_context"),
            "caller_context": meta.get("caller_context"),
            "feature_hash": meta.get("feature_hash"),
            "risk_status": risk_status,
            "risk_failure_reason": risk_failure_reason,
            "risk_blocked": risk_blocked or risk_status == "UNAVAILABLE",
            "evidence_eligible": runtime_evidence_eligible(),
            "decision_id": str(uuid.uuid4()),
            "context_snapshot_id": None,
            **regime_effect_metadata(self.regime_decision_effect_enabled),
            **self._terminal_fields(action),
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

        proposed_side = self._entry_action(analysis_info or {})
        signal_side = proposed_side if proposed_side in {"BUY", "SELL"} else self._signal_direction(analysis_info or {})
        adjusted_side_prob = (
            1.0 - adjusted_posterior if signal_side == "SELL" else adjusted_posterior
        )

        proposed_action = "HOLD"
        if signal_side == "BUY":
            if expected_return >= self.min_ev_pct and adjusted_side_prob >= self.buy_threshold:
                proposed_action = "BUY"
            elif adjusted_side_prob >= self.buy_threshold:
                proposed_action = "INCREASE"
        elif signal_side == "SELL":
            if expected_return >= self.min_ev_pct and adjusted_side_prob >= self.sell_threshold:
                proposed_action = "SELL"
            elif adjusted_side_prob >= self.sell_threshold:
                proposed_action = "REDUCE"

        if expected_return < self.min_ev_pct:
            proposed_action = "IGNORE"

        final_action, risk_reasons = apply_final_risk_gate(proposed_action, risk_level, stop_processing)
        if (
            bool(base_decision.get("risk_blocked"))
            or str(base_decision.get("risk_status") or "").upper() == "UNAVAILABLE"
        ):
            final_action = DecisionAction.BLOCK_ENTRY
            risk_reasons = tuple(risk_reasons) + ("risk_failure_entry_block",)
        if (
            final_action.value in {"BUY", "SELL"}
            and self._entry_action(analysis_info or {}) != final_action.value
        ):
            final_action = DecisionAction.HOLD
            risk_reasons = tuple(risk_reasons) + (
                "canonical_action_not_supported_by_entry_signal",
            )
        reason_parts = [base_decision.get("reason", "")]
        for adj in sorted(adjustments, key=lambda x: abs(x.get("impact", 0)), reverse=True)[:2]:
            reason_parts.append(f"[{adj.get('layer', 'context')}] {adj.get('reason', '')}")
        reason_parts.extend(risk_reasons)
        context_snapshot_id = context_report.get("context_snapshot_id") or str(uuid.uuid4())

        meta_probability = float(base_decision.get("meta_probability") or 0.5)
        if base_decision.get("meta_probability_semantics") != "P(win_given_proposed_trade)":
            meta_probability = self._execution_probability(
                final_action.value, meta_probability
            )
        adjusted_side_probability = (
            1.0 - adjusted_posterior
            if final_action.value == "SELL"
            else adjusted_posterior
        )
        final_decision = {
            **base_decision,
            "action": final_action.value,
            "execution_probability": meta_probability,
            "execution_probability_semantics": "P(win_given_proposed_trade)",
            "side_probability": adjusted_side_probability,
            "side_probability_semantics": "P(win_given_proposed_trade)",
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
            **self._terminal_fields(final_action.value),
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
        existing = self._existing_final_decision(base_decision)
        if existing is not None:
            return existing
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
        existing = self._existing_final_decision(base_decision)
        if existing is not None:
            return existing
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
