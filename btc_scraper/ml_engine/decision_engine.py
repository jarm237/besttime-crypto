import copy
import os
from enum import Enum
from typing import Any, Dict, Mapping, Optional, TYPE_CHECKING
import uuid

from .economic_contract import (
    COST_CONTRACT_VERSION,
    DEFAULT_ROUNDTRIP_COST_FRACTION,
    EV_CONTRACT_VERSION,
    EXPECTED_RETURN_UNIT,
    compute_net_expected_return,
    is_paper_shadow_policy,
    resolve_paper_economic_policy,
)
from .inference_contract import normalize_inference_symbol
from .meta_model import predict_meta_confidence
from .s3_thresholds import evaluate_s3_threshold
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
#   0.0005 =  5 bps  (0.05%)   ← MIN_EV_FRACTION_DEFAULT
#   0.005  = 50 bps  (0.5%)
#   0.05   = 500 bps (5.0%)
# ──────────────────────────────────────────────────────────────────────
MIN_EV_FRACTION_DEFAULT = 0.0005
# Backward-compatible alias. Despite the historical name, the value is a fraction.
MIN_EV_PCT_DEFAULT = MIN_EV_FRACTION_DEFAULT


def apply_economic_policy_to_final_decision(
    decision: Dict[str, Any],
    *,
    analysis_info: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Applies canonical runtime economic policy at finalization point.

    In paper environment with PAPER_ECONOMIC_POLICY in {NO_TRADE_SHADOW, NO_TRADE, SHADOW}:
    - Suppresses executable BUY/SELL to HOLD.
    - Sets eligible = False.
    - Sets terminal_status = HOLD and terminal_action = HOLD.
    - Preserves original active intent in shadow_action.
    - Sets rejection_reason = NO_VIABLE_ECONOMIC_CANDIDATE.
    - Sets economic_rejection_reason = NO_VIABLE_ECONOMIC_CANDIDATE.
    - Zero executable paper orders can be planned or executed.
    """
    if not isinstance(decision, dict):
        return decision

    env = os.getenv("BTC_RUNTIME_ENVIRONMENT", "").strip().lower()
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"
    is_paper_env = (
        not live_enabled
        or env in {"paper", "testnet", "local-paper"}
        or os.getenv("AUTO_TRADE_DRY_RUN", "true").lower() == "true"
        or (analysis_info or {}).get("is_paper") is True
    )

    policy = resolve_paper_economic_policy(analysis_info=analysis_info)
    decision["paper_economic_policy"] = policy
    current_action = str(decision.get("action") or "HOLD").upper()

    if is_paper_env and is_paper_shadow_policy(policy, analysis_info=analysis_info):
        if current_action in {"BUY", "SELL"}:
            decision["shadow_action"] = current_action
            decision["action"] = "HOLD"
            decision["eligible"] = False
            decision["terminal_status"] = "HOLD"
            decision["terminal_action"] = "HOLD"
            decision["economic_rejection_reason"] = "NO_VIABLE_ECONOMIC_CANDIDATE"
            decision["rejection_reason"] = "NO_VIABLE_ECONOMIC_CANDIDATE"
            reason_str = str(decision.get("reason") or "")
            if "economic_failure=NO_VIABLE_ECONOMIC_CANDIDATE" not in reason_str:
                decision["reason"] = f"{reason_str} | economic_failure=NO_VIABLE_ECONOMIC_CANDIDATE".strip(" |")
        elif "shadow_action" not in decision:
            decision["shadow_action"] = current_action

    return decision


class MetaDecisionEngine:
    """Central decision engine combining EV meta model and contextual evidence."""

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        buy_threshold: float = 0.50,
        sell_threshold: float = 0.50,
        hold_threshold: float = 0.45,
        min_ev_pct: float = MIN_EV_PCT_DEFAULT,  # see _EXPECTED_RETURN_UNIT: FRACTION (0.0005 = 5 bps)
        roundtrip_cost_fraction: float = DEFAULT_ROUNDTRIP_COST_FRACTION,
        min_net_ev_pct: float | None = None,
        net_ev_gating_enabled: bool = False,
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
        self.roundtrip_cost_fraction = roundtrip_cost_fraction
        self.min_net_ev_pct = min_net_ev_pct if min_net_ev_pct is not None else 0.0
        self.net_ev_gating_enabled = net_ev_gating_enabled or (
            os.getenv("PAPER_NET_EV_GATE_ENABLED", "").lower() in {"1", "true", "yes"}
        )

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
        _sent = info.get("sentiment")
        sentiment_stale = (
            str(info.get("sentiment_quality_status") or "").upper() == "STALE_NEUTRALIZED"
            or (isinstance(_sent, dict) and bool(_sent.get("stale") or _sent.get("status") == "stale"))
        )
        if sentiment_stale:
            fg = 50.0
            momentum = 0.0
        else:
            fg = info.get("fear_greed")
            try:
                fg = float(fg) if fg is not None else 50.0
            except Exception:
                fg = 50.0
            momentum = info.get("sentiment_momentum")
            try:
                momentum = float(momentum)
            except Exception:
                momentum = 0.0
        fg_score = self._clamp01(fg / 100.0)
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
    def _finalize_and_persist(
        decision: Dict,
        *,
        analysis_info: Optional[Mapping[str, Any]] = None,
        persist: bool = True,
    ) -> Dict:
        """Finalize the decision exactly once and persist the exact finalized object."""
        finalized = apply_economic_policy_to_final_decision(decision, analysis_info=analysis_info)
        if persist:
            MetaDecisionEngine._persist_final_decision(finalized)
        return finalized

    @staticmethod
    def _persist_final_decision(decision: Dict) -> None:
        """Persist a pre-finalized decision to the runtime evidence store.

        Does NOT alter, re-finalize, or duplicate finalization logic.
        """
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

    @staticmethod
    def _resolve_input_quality(
        analysis_info: Optional[Mapping[str, Any]],
        world_state: Any = None,
    ) -> tuple[str, str, Dict[str, Any]]:
        info = analysis_info if isinstance(analysis_info, Mapping) else {}
        sent_obj = info.get("sentiment") if isinstance(info.get("sentiment"), Mapping) else {}
        macro_obj = info.get("macro") if isinstance(info.get("macro"), Mapping) else {}

        ws_sent_status = str(getattr(world_state, "sentiment_quality_status", "") or "").upper()
        ws_macro_status = str(getattr(world_state, "macro_quality_status", "") or "").upper()

        sentiment_stale = bool(
            str(info.get("sentiment_quality_status") or "").upper() == "STALE_NEUTRALIZED"
            or ws_sent_status == "STALE_NEUTRALIZED"
            or info.get("sentiment_stale", False)
            or sent_obj.get("stale", False)
            or str(sent_obj.get("status") or "").lower() == "stale"
        )
        macro_stale = bool(
            str(info.get("macro_quality_status") or "").upper() == "STALE_NEUTRALIZED"
            or ws_macro_status == "STALE_NEUTRALIZED"
            or info.get("macro_stale", False)
            or macro_obj.get("stale", False)
            or str(macro_obj.get("status") or "").lower() == "stale"
        )

        macro_quality_status = "STALE_NEUTRALIZED" if macro_stale else str(info.get("macro_quality_status") or "FRESH")
        sentiment_quality_status = (
            "STALE_NEUTRALIZED" if sentiment_stale else str(info.get("sentiment_quality_status") or "FRESH")
        )

        obs: Dict[str, Any] = {}
        existing_obs = info.get("observability_only")
        if isinstance(existing_obs, Mapping):
            obs.update(copy.deepcopy(dict(existing_obs)))
        ws_obs = getattr(world_state, "observability_only", None)
        if isinstance(ws_obs, Mapping):
            for k, v in ws_obs.items():
                obs.setdefault(k, copy.deepcopy(v))

        if sentiment_stale and "raw_sentiment" not in obs:
            raw_sent_obs = sent_obj.get("raw_observability") if isinstance(sent_obj.get("raw_observability"), Mapping) else {}
            ws_sent_fg = getattr(getattr(world_state, "sentiment", None), "FearGreed", None)
            obs["raw_sentiment"] = {
                "fear_greed": (
                    raw_sent_obs.get("raw_value")
                    if raw_sent_obs.get("raw_value") is not None
                    else (
                        info.get("fear_greed")
                        if info.get("fear_greed") is not None
                        else (sent_obj.get("raw_value") if sent_obj.get("raw_value") is not None else ws_sent_fg)
                    )
                ),
                "sentiment_momentum": info.get("sentiment_momentum", sent_obj.get("momentum")),
                "score": raw_sent_obs.get("normalized_score", sent_obj.get("score")),
            }

        if macro_stale and "raw_macro" not in obs:
            ws_macro = getattr(world_state, "macro", None)
            obs["raw_macro"] = {
                "DXY": macro_obj.get("DXY", getattr(ws_macro, "DXY", None)),
                "VIX": macro_obj.get("VIX", getattr(ws_macro, "VIX", None)),
                "RealYield": macro_obj.get("RealYield", getattr(ws_macro, "RealYield", None)),
                "BondYield": macro_obj.get("BondYield", getattr(ws_macro, "BondYield", None)),
            }

        return macro_quality_status, sentiment_quality_status, obs

    @staticmethod
    def _neutralize_world_state(
        world_state: Any,
        *,
        macro_stale: bool,
        sentiment_stale: bool,
    ) -> Any:
        if world_state is None or (not macro_stale and not sentiment_stale):
            return world_state
        cloned = copy.copy(world_state)
        if macro_stale and hasattr(cloned, "macro") and cloned.macro is not None:
            cloned_macro = copy.copy(cloned.macro)
            cloned_macro.DXY = 100.0
            cloned_macro.VIX = 20.0
            cloned_macro.RealYield = 0.0
            cloned_macro.BondYield = 4.5
            cloned_macro.FedRate = 0.0
            cloned.macro = cloned_macro
            cloned.macro_quality_status = "STALE_NEUTRALIZED"
        if sentiment_stale and hasattr(cloned, "sentiment") and cloned.sentiment is not None:
            cloned_sent = copy.copy(cloned.sentiment)
            cloned_sent.FearGreed = 50.0
            cloned.sentiment = cloned_sent
            cloned.sentiment_quality_status = "STALE_NEUTRALIZED"
        return cloned

    def decide(self, analysis_info: Dict, *, persist_final: bool = True) -> Dict:
        macro_quality_status, sentiment_quality_status, observability_only = self._resolve_input_quality(analysis_info)
        meta = analysis_info.get("_meta_prediction")
        existing = self._existing_final_decision(analysis_info)
        if existing is not None:
            return existing
        if not isinstance(meta, dict):
            explicit_symbol = (
                analysis_info.get("symbol")
                or analysis_info.get("coin")
                or analysis_info.get("ticker")
            )
            effective_infer_info = dict(analysis_info)
            effective_infer_info["macro_quality_status"] = macro_quality_status
            effective_infer_info["sentiment_quality_status"] = sentiment_quality_status
            if sentiment_quality_status == "STALE_NEUTRALIZED":
                effective_infer_info["fear_greed"] = 50.0
                effective_infer_info["sentiment_raw"] = 50.0
                effective_infer_info["sentiment_score"] = 0.0
                effective_infer_info["sentiment_momentum"] = 0.0
            if macro_quality_status == "STALE_NEUTRALIZED" and isinstance(effective_infer_info.get("macro"), Mapping):
                effective_infer_info["macro"] = {
                    "DXY": 100.0,
                    "VIX": 20.0,
                    "RealYield": 0.0,
                    "BondYield": 4.5,
                    "stale": True,
                }
            meta = predict_meta_confidence(
                effective_infer_info,
                symbol=explicit_symbol,
            )
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
                "inference_contract_version": None,
                "model_family": None,
                "artifact_version": None,
                "artifact_hash": None,
                "feature_schema_hash": None,
            }

        explicit_analysis_symbol = (
            analysis_info.get("symbol")
            or analysis_info.get("coin")
            or analysis_info.get("ticker")
        )
        if meta.get("symbol") is not None and explicit_analysis_symbol is not None:
            try:
                if normalize_inference_symbol(meta["symbol"]) != normalize_inference_symbol(
                    explicit_analysis_symbol
                ):
                    return {
                        "error": "prediction_symbol_mismatch",
                        "action": "NEUTRAL",
                        "posterior_probability": None,
                        "meta_probability": None,
                        "prediction_id": meta.get("prediction_id"),
                        "decision_id": str(uuid.uuid4()),
                    }
            except ValueError as exc:
                return {
                    "error": str(exc),
                    "action": "NEUTRAL",
                    "posterior_probability": None,
                    "meta_probability": None,
                    "prediction_id": meta.get("prediction_id"),
                    "decision_id": str(uuid.uuid4()),
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
        s3_gate = evaluate_s3_threshold(
            meta.get("symbol")
            or analysis_info.get("coin")
            or analysis_info.get("symbol")
            or analysis_info.get("ticker"),
            meta_prob,
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

        net_ev_metrics = compute_net_expected_return(
            expected_return,
            roundtrip_cost_fraction=self.roundtrip_cost_fraction,
        )
        expected_gross_return = net_ev_metrics["expected_gross_return"]
        expected_cost = net_ev_metrics["expected_cost"]
        expected_net_return = net_ev_metrics["expected_net_return"]

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

        # S3 Threshold Gating
        s3_rejection_reason = None
        if not s3_gate.s3_pass:
            action = "IGNORE"
            s3_rejection_reason = s3_gate.error or "S3_THRESHOLD_NOT_MET"

        # Economic Gating
        economic_rejection_reason = None
        if expected_return < self.min_ev_pct:
            action = "IGNORE"
            economic_rejection_reason = "INSUFFICIENT_EXPECTED_VALUE"

        # Net EV Gate: Enforce cost-aware expected return threshold
        if self.net_ev_gating_enabled and expected_net_return < self.min_net_ev_pct:
            action = "HOLD"
            economic_rejection_reason = "NEGATIVE_NET_EXPECTED_VALUE"

        # PAPER_ECONOMIC_POLICY: Resolved canonical policy
        paper_economic_policy = resolve_paper_economic_policy(analysis_info=analysis_info)
        shadow_action = action

        # Risk Gating
        risk_status = str(analysis_info.get("risk_status") or "HEALTHY").upper()
        risk_blocked = bool(analysis_info.get("risk_blocked", False))
        risk_failure_reason = None
        if risk_blocked or risk_status == "UNAVAILABLE":
            action = "BLOCK_ENTRY"
            risk_failure_reason = analysis_info.get("risk_failure_reason") or "risk_data_unavailable"
        elif action in {"BUY", "SELL"} and self._entry_action(analysis_info) != action:
            action = "HOLD"
            risk_failure_reason = "canonical_action_not_supported_by_entry_signal"
        elif analysis_info.get("risk_failure_reason"):
            risk_failure_reason = str(analysis_info.get("risk_failure_reason"))

        # Composite rejection reason
        composite_rejection_reason = (
            risk_failure_reason
            or s3_rejection_reason
            or economic_rejection_reason
        ) if action in {"HOLD", "IGNORE", "BLOCK_ENTRY"} else None

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
            f"gross_ev={expected_gross_return:.4f}",
            f"cost={expected_cost:.4f}",
            f"net_ev={expected_net_return:.4f}",
            f"cost_contract={COST_CONTRACT_VERSION}",
            f"ev_unit={EXPECTED_RETURN_UNIT}",
            f"ev_contract={EV_CONTRACT_VERSION}",
            f"s3_threshold={s3_gate.s3_threshold}",
            f"s3_pass={str(s3_gate.s3_pass).lower()}",
            f"threshold_contract={s3_gate.threshold_contract_version}",
        ]
        if s3_gate.error:
            reason.append(f"s3_error={s3_gate.error}")
        if risk_blocked or risk_status == "UNAVAILABLE" or risk_failure_reason:
            reason.append(f"risk_failure={risk_failure_reason}")
        if economic_rejection_reason:
            reason.append(f"economic_failure={economic_rejection_reason}")
        if macro_quality_status != "FRESH":
            reason.append(f"macro_quality={macro_quality_status}")
        if sentiment_quality_status != "FRESH":
            reason.append(f"sentiment_quality={sentiment_quality_status}")

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
            "macro_quality_status": macro_quality_status,
            "sentiment_quality_status": sentiment_quality_status,
            "observability_only": observability_only,
            "regime_support": applied_regime_prob,
            "proposed_regime_support": proposed_regime_prob,
            "applied_regime_support": applied_regime_prob,
            "proposed_regime_weight": float(self.proposed_weights.get("regime", 0.0)),
            "applied_regime_weight": float(self.weights.get("regime", 0.0)),
            "regime_snapshot": analysis_info.get("regime_snapshot"),
            "volatility_support": volatility_prob,
            "expected_return": expected_return,
            "expected_gross_return": expected_gross_return,
            "expected_cost": expected_cost,
            "expected_net_return": expected_net_return,
            "cost_contract_version": COST_CONTRACT_VERSION,
            "rejection_reason": composite_rejection_reason,
            "risk_rejection_reason": risk_failure_reason,
            "economic_rejection_reason": economic_rejection_reason,
            "paper_economic_policy": paper_economic_policy,
            "shadow_action": shadow_action,
            "estimate_source": meta.get("estimate_source", "meta_confidence"),
            "calibration_identity": meta.get("calibration_identity", meta.get("calibration_method", "logistic")),
            "confidence": meta.get("confidence", meta_prob),
            "net_ev_status": "AVAILABLE" if net_ev_metrics is not None else "NET_EV_UNAVAILABLE",
            "expected_return_unit": EXPECTED_RETURN_UNIT,
            "ev_contract_version": EV_CONTRACT_VERSION,
            "expected_drawdown": meta.get("expected_drawdown"),
            "expected_hold_time": meta.get("expected_hold_time"),
            "prob_tp1": meta.get("prob_tp1"),
            "prob_tp2": meta.get("prob_tp2"),
            "prob_sl": meta.get("prob_sl"),
            "meta_ev": expected_return,
            "symbol": s3_gate.symbol,
            "s3_threshold": s3_gate.s3_threshold,
            "s3_pass": s3_gate.s3_pass,
            "s3_threshold_error": s3_gate.error,
            "threshold_contract_version": s3_gate.threshold_contract_version,
            "threshold_contract_sha256": s3_gate.threshold_contract_sha256,
            "reason": " | ".join(reason),
            "signal_id": analysis_info.get("signal_id") or analysis_info.get("id"),
            "prediction_id": meta.get("prediction_id"),
            "inference_contract_version": meta.get("inference_contract_version"),
            "model_family": meta.get("model_family"),
            "artifact_version": meta.get("artifact_version"),
            "artifact_hash": meta.get("artifact_hash") or meta.get("artifact_sha256"),
            "feature_schema_hash": meta.get("feature_schema_hash"),
            "prediction": meta.get("prediction", meta.get("probability")),
            "artifact_metadata_consistent": meta.get(
                "artifact_metadata_consistent"
            ),
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
            return self._finalize_and_persist(final_decision, analysis_info=analysis_info, persist=True)
        return final_decision

    def _build_context_decision(
        self,
        base_decision: Dict,
        context_report: Dict,
        *,
        analysis_info: Optional[Dict] = None,
    ) -> Dict:
        """Build raw context-adjusted decision dictionary without finalization or persistence."""
        if not context_report or base_decision.get("error"):
            return dict(base_decision)

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
        if not bool(base_decision.get("s3_pass")):
            proposed_action = "IGNORE"

        final_action, risk_reasons = apply_final_risk_gate(proposed_action, risk_level, stop_processing)
        if not bool(base_decision.get("s3_pass")) and not risk_reasons:
            risk_reasons = tuple(risk_reasons) + ("s3_threshold_failed",)
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
        macro_q, sent_q, obs_only = self._resolve_input_quality(analysis_info)
        if str(base_decision.get("macro_quality_status") or "").upper() == "STALE_NEUTRALIZED":
            macro_q = "STALE_NEUTRALIZED"
        if str(base_decision.get("sentiment_quality_status") or "").upper() == "STALE_NEUTRALIZED":
            sent_q = "STALE_NEUTRALIZED"
        merged_obs = {}
        if isinstance(base_decision.get("observability_only"), Mapping):
            merged_obs.update(copy.deepcopy(dict(base_decision["observability_only"])))
        merged_obs.update(obs_only)
        base_reason_str = base_decision.get("reason", "")
        if macro_q != "FRESH" and f"macro_quality={macro_q}" not in base_reason_str:
            reason_parts.append(f"macro_quality={macro_q}")
        if sent_q != "FRESH" and f"sentiment_quality={sent_q}" not in base_reason_str:
            reason_parts.append(f"sentiment_quality={sent_q}")

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
            "macro_quality_status": macro_q,
            "sentiment_quality_status": sent_q,
            "observability_only": merged_obs,
            "decision_id": base_decision.get("decision_id") or str(uuid.uuid4()),
            "signal_id": base_decision.get("signal_id") or (analysis_info or {}).get("signal_id") or (analysis_info or {}).get("id"),
            "reason": " | ".join(part for part in reason_parts if part),
            **self._terminal_fields(final_action.value),
        }
        return final_decision

    def apply_context(
        self,
        base_decision: Dict,
        context_report: Dict,
        *,
        analysis_info: Optional[Dict] = None,
        persist_final: bool = True,
    ) -> Dict:
        """Apply context to an existing inference and enforce the final hard-risk gate."""
        raw_decision = self._build_context_decision(
            base_decision, context_report, analysis_info=analysis_info
        )
        if persist_final:
            return self._finalize_and_persist(raw_decision, analysis_info=analysis_info, persist=True)
        return raw_decision

    def decide_with_context(
        self,
        analysis_info: Dict,
        context_report: Optional[Dict] = None,
        *,
        persist_final: bool = True,
    ) -> Dict:
        """
        Make decision incorporating causal context adjustment.

        Args:
            analysis_info: Base analysis information
            context_report: ContextReport dict (from ContextEngine)
            persist_final: Whether to persist the final decision (default True).

        Returns:
            Enhanced decision dict with context adjustments
        """
        base_decision = self.decide(analysis_info, persist_final=False)
        existing = self._existing_final_decision(base_decision)
        if existing is not None:
            return existing
        return self.apply_context(
            base_decision,
            context_report or {},
            analysis_info=analysis_info,
            persist_final=persist_final,
        )

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
        macro_q, sent_q, obs_only = self._resolve_input_quality(analysis_info, world_state=world_state)
        effective_info = dict(analysis_info)
        effective_info["macro_quality_status"] = macro_q
        effective_info["sentiment_quality_status"] = sent_q
        if obs_only:
            effective_info["observability_only"] = obs_only
        effective_world_state = self._neutralize_world_state(
            world_state,
            macro_stale=(macro_q == "STALE_NEUTRALIZED"),
            sentiment_stale=(sent_q == "STALE_NEUTRALIZED"),
        )

        # Get base decision
        base_decision = self.decide(effective_info, persist_final=False)
        existing = self._existing_final_decision(base_decision)
        if existing is not None:
            return existing
        if base_decision.get("error") or base_decision.get("posterior_probability") is None:
            return self._finalize_and_persist(base_decision, analysis_info=effective_info, persist=True)

        # Check if provider wants to apply context in current market conditions
        try:
            should_apply = context_provider.should_apply_context(effective_world_state)
        except Exception as exc:
            from .operational_health import record_degradation
            record_degradation("context_provider", "context_provider_failure_total", exc)
            return self._finalize_and_persist(base_decision, analysis_info=effective_info, persist=True)
        if not should_apply:
            base_decision["context_provider"] = context_provider.name
            base_decision["context_skipped"] = True
            return self._finalize_and_persist(base_decision, analysis_info=effective_info, persist=True)

        original_posterior = base_decision.get("posterior_probability", 0.5)

        # Generate context report via provider
        try:
            report = context_provider.generate_context_report(original_posterior, effective_world_state)
        except Exception as exc:
            import logging
            from .operational_health import record_degradation
            record_degradation("context_provider", "context_provider_failure_total", exc)
            logging.getLogger(__name__).error(
                f"[DecisionEngine] ContextProvider '{context_provider.name}' failed: {exc}"
            )
            return self._finalize_and_persist(base_decision, analysis_info=effective_info, persist=True)

        raw_applied = self._build_context_decision(
            base_decision,
            report.to_dict(),
            analysis_info=effective_info,
        )
        raw_applied["context_provider"] = context_provider.name
        raw_applied["context_skipped"] = False
        return self._finalize_and_persist(raw_applied, analysis_info=effective_info, persist=True)
