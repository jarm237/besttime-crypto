"""
causal_context_bridge.py — Phase C Integration

Cung cấp singleton HybridContextProvider và helper để tích hợp causal context
vào SignalGeneratorAgent mà không coupling trực tiếp ml_engine internals vào multi_agent.py.

Cách sử dụng:
    from btc_scraper.ml_engine.causal_context_bridge import enhance_signal_with_causal_context
    enhanced = enhance_signal_with_causal_context(ana, analysis_info, alpha=0.0)

alpha=0.0  → Rule-only (100% safe, mặc định)
alpha=0.3  → 70% rules + 30% Bayesian (bật sau khi validate shadow mode)
"""

from __future__ import annotations

import logging
import os
import datetime
from typing import Dict, Optional

from btc_scraper.collectors.macro_collector import load_macro_state
from btc_scraper.collectors.alternative_reference import strip_alternative_reference
from btc_scraper.core.fear_greed import resolve_fear_greed_value

logger = logging.getLogger(__name__)

# ── Singletons ────────────────────────────────────────────────────────────────
_HYBRID_PROVIDER = None
_DECISION_ENGINE = None
# ─────────────────────────────────────────────────────────────────────────────


def _get_causal_alpha() -> float:
    """Đọc CAUSAL_ALPHA từ env (mặc định 0.0 = rule-only, safe mode)."""
    try:
        return float(os.environ.get("CAUSAL_ALPHA", "0.0"))
    except Exception:
        return 0.0


def get_hybrid_provider(alpha: Optional[float] = None):
    """Lấy hoặc khởi tạo singleton HybridContextProvider."""
    global _HYBRID_PROVIDER
    if _HYBRID_PROVIDER is None:
        try:
            from btc_scraper.ml_engine.hybrid_context_provider import HybridContextProvider
            _alpha = alpha if alpha is not None else _get_causal_alpha()
            _HYBRID_PROVIDER = HybridContextProvider.build(
                alpha=_alpha,
                graph_path="data/causal_graph.json",
                rules_path="data/context_rules.json",
            )
            logger.info(f"[CausalBridge] HybridContextProvider initialized (alpha={_alpha:.2f})")
        except Exception as exc:
            logger.warning(f"[CausalBridge] Failed to init HybridContextProvider: {exc}")
            return None
    return _HYBRID_PROVIDER


def get_decision_engine():
    """Lấy hoặc khởi tạo singleton MetaDecisionEngine."""
    global _DECISION_ENGINE
    if _DECISION_ENGINE is None:
        try:
            from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
            _DECISION_ENGINE = MetaDecisionEngine()
        except Exception as exc:
            logger.warning(f"[CausalBridge] Failed to init MetaDecisionEngine: {exc}")
            return None
    return _DECISION_ENGINE


def build_world_state_from_ana(ana: Dict):
    """
    Xây dựng WorldState từ analysis dict của một coin.

    Các field macro (DXY, VIX, RealYield) sử dụng placeholder
    cho đến khi Phase E (macro_collector) được triển khai.
    """
    try:
        from btc_scraper.core.world_state import WorldState, MarketRegime

        sig = str(ana.get("signal", "")).upper()
        state = WorldState(timestamp=datetime.datetime.now(datetime.timezone.utc))
        state.regime = MarketRegime.RISK_ON if "BUY" in sig else MarketRegime.RISK_OFF

        # Sentiment: neutralize stale sentiment into 50.0 (Neutral)
        _sentiment = ana.get("sentiment") if isinstance(ana.get("sentiment"), dict) else {}
        sentiment_is_stale = bool(
            str(ana.get("sentiment_quality_status") or "").upper() == "STALE_NEUTRALIZED"
            or ana.get("sentiment_stale", False)
            or _sentiment.get("stale", False)
            or (_sentiment.get("status") == "stale")
        )
        raw_obs_sent = _sentiment.get("raw_observability") if isinstance(_sentiment.get("raw_observability"), dict) else {}
        raw_fear_greed = resolve_fear_greed_value(
            raw_obs_sent.get("raw_value") if sentiment_is_stale else None,
            _sentiment.get("raw_value"),
            ana.get("fear_greed"),
            default=50.0,
        )
        if sentiment_is_stale:
            state.sentiment.FearGreed = 50.0
            sentiment_quality_status = "STALE_NEUTRALIZED"
        else:
            state.sentiment.FearGreed = raw_fear_greed
            sentiment_quality_status = "FRESH"

        # Liquidity
        state.liquidity.BTC_Funding = float(
            ana.get("funding_rate") or ana.get("funding") or 0.0
        )
        state.liquidity.OI_Delta = float(ana.get("oi_delta") or 0.0)

        # Crypto price
        state.crypto.BTC_Price = float(ana.get("close") or 0.0)

        # Macro values from explicit payload or collector: neutralize stale macro values to baseline
        from btc_scraper.collectors.macro_collector import is_macro_state_fresh
        explicit_macro = ana.get("macro") if isinstance(ana.get("macro"), dict) else None
        macro_state = explicit_macro if explicit_macro is not None else load_macro_state()
        if explicit_macro is not None:
            macro_is_stale = bool(
                str(ana.get("macro_quality_status") or "").upper() == "STALE_NEUTRALIZED"
                or ana.get("macro_stale", False)
                or explicit_macro.get("stale", False)
                or explicit_macro.get("status") == "stale"
            )
        else:
            macro_is_stale = bool(
                str(ana.get("macro_quality_status") or "").upper() == "STALE_NEUTRALIZED"
                or ana.get("macro_stale", False)
                or macro_state.get("stale", False)
                or not is_macro_state_fresh()
            )
        raw_macro_obs = {
            "DXY": float(macro_state.get("DXY", 100.0)),
            "VIX": float(macro_state.get("VIX", 20.0)),
            "RealYield": float(macro_state.get("RealYield", 0.0)),
            "BondYield": float(macro_state.get("BondYield", 4.5)),
        }
        if macro_is_stale:
            state.macro.DXY = 100.0
            state.macro.VIX = 20.0
            state.macro.RealYield = 0.0
            state.macro.BondYield = 4.5
            macro_quality_status = "STALE_NEUTRALIZED"
        else:
            state.macro.DXY = raw_macro_obs["DXY"]
            state.macro.VIX = raw_macro_obs["VIX"]
            state.macro.RealYield = raw_macro_obs["RealYield"]
            state.macro.BondYield = raw_macro_obs["BondYield"]
            macro_quality_status = "FRESH"

        # Alternative Data is deliberately not loaded into decision state.
        # It is attached only after scoring by SignalGeneratorAgent as a
        # reference-only payload. This prevents future rule/model changes from
        # silently turning an informational field into trading evidence.
        state.macro_quality_status = macro_quality_status
        state.sentiment_quality_status = sentiment_quality_status
        observability_only: Dict[str, Dict] = {}
        if sentiment_is_stale:
            observability_only["raw_sentiment"] = {
                "FearGreed": raw_fear_greed,
                "raw_value": raw_obs_sent.get("raw_value", _sentiment.get("raw_value")),
                "score": raw_obs_sent.get("normalized_score", _sentiment.get("score")),
            }
        if macro_is_stale:
            observability_only["raw_macro"] = raw_macro_obs
        state.observability_only = observability_only

        return state
    except Exception as exc:
        logger.warning(f"[CausalBridge] build_world_state_from_ana failed: {exc}")
        return None


def enhance_signal_with_causal_context(
    ana: Dict,
    analysis_info: Dict,
    alpha: Optional[float] = None,
) -> Dict:
    """
    Chạy decide_with_provider() và trả về enhanced decision dict.

    Args:
        ana:           Analysis dict của coin (từ analyze_market).
        analysis_info: Merged dict gồm ana + signal_score (features cho MetaModel).
        alpha:         Blending factor (None → đọc từ env CAUSAL_ALPHA).

    Returns:
        Enhanced decision dict hoặc dict rỗng nếu bị lỗi (graceful degradation).
    """
    try:
        engine   = get_decision_engine()
        if engine is None:
            return {}
        decision_input = strip_alternative_reference(analysis_info)
        proposed_action = str(decision_input.get("action") or "").upper()
        model_probability_up = decision_input.get("model_probability_up")
        if model_probability_up is None:
            side_probability = (
                decision_input.get("meta_probability")
                if decision_input.get("meta_probability") is not None
                else decision_input.get("meta_confidence")
            )
            if side_probability is not None:
                model_probability_up = (
                    1.0 - float(side_probability)
                    if proposed_action == "SELL"
                    else float(side_probability)
                )
        meta_prediction = {
            "probability": model_probability_up,
            "model_probability_up": model_probability_up,
            "probability_semantics": "P(up)",
            "execution_probability": decision_input.get("meta_probability"),
            "execution_probability_semantics": "P(win_given_proposed_trade)",
            "prediction_id": decision_input.get("prediction_id"),
            "signal_id": decision_input.get("signal_id"),
            "symbol": (
                decision_input.get("symbol")
                or decision_input.get("coin")
                or decision_input.get("ticker")
            ),
            "inference_contract_version": decision_input.get(
                "inference_contract_version"
            ),
            "model_family": decision_input.get("model_family"),
            "artifact_version": decision_input.get("artifact_version"),
            "artifact_hash": decision_input.get("artifact_hash")
            or decision_input.get("artifact_sha256")
            or decision_input.get("model_artifact_sha256"),
            "feature_schema_hash": decision_input.get("feature_schema_hash"),
            "prediction": (
                decision_input.get("prediction")
                if decision_input.get("prediction") is not None
                else model_probability_up
            ),
            "artifact_metadata_consistent": decision_input.get(
                "artifact_metadata_consistent"
            ),
            "model_version": decision_input.get("model_version"),
            "artifact_sha256": decision_input.get("artifact_sha256") or decision_input.get("model_artifact_sha256"),
            "feature_schema_version": decision_input.get("feature_schema_version"),
            "deployment_id": decision_input.get("deployment_id"),
            "paper_run_id": decision_input.get("paper_run_id"),
            "cycle_id": decision_input.get("cycle_id"),
            "decision_context": decision_input.get("decision_context"),
            "caller_context": decision_input.get("caller_context"),
            "feature_hash": decision_input.get("feature_hash"),
            "expected_return": decision_input.get("meta_expected_return"),
            "expected_drawdown": decision_input.get("meta_expected_drawdown"),
            "expected_hold_time": decision_input.get("meta_expected_hold_time"),
        }
        if not meta_prediction["prediction_id"] or meta_prediction["probability"] is None:
            return {}
        decision_input["_meta_prediction"] = meta_prediction
        provider = get_hybrid_provider(alpha=alpha)
        state = build_world_state_from_ana(ana)
        if state is not None:
            decision_input["macro_quality_status"] = getattr(state, "macro_quality_status", "FRESH")
            decision_input["sentiment_quality_status"] = getattr(state, "sentiment_quality_status", "FRESH")
            state_obs = getattr(state, "observability_only", None)
            if isinstance(state_obs, dict) and state_obs:
                decision_input["observability_only"] = dict(state_obs)
        else:
            from btc_scraper.collectors.macro_collector import is_macro_state_fresh
            _sent = ana.get("sentiment") or decision_input.get("sentiment") or {}
            decision_input.setdefault(
                "sentiment_quality_status",
                "STALE_NEUTRALIZED" if bool(_sent.get("stale") or _sent.get("status") == "stale") else "FRESH",
            )
            _macro = load_macro_state()
            decision_input.setdefault(
                "macro_quality_status",
                "STALE_NEUTRALIZED" if bool(_macro.get("stale") or not is_macro_state_fresh()) else "FRESH",
            )
        if decision_input.get("sentiment_quality_status") == "STALE_NEUTRALIZED":
            decision_input["fear_greed"] = 50.0
            decision_input["sentiment_momentum"] = 0.0
            decision_input["sentiment_raw"] = 50.0
            decision_input["sentiment_score"] = 0.0
        if provider is None or state is None:
            return engine.decide(decision_input, persist_final=True)
        return engine.decide_with_provider(decision_input, provider, state) or {}

    except Exception as exc:
        logger.warning(f"[CausalBridge] enhance_signal_with_causal_context skipped: {exc}")
        return {}
