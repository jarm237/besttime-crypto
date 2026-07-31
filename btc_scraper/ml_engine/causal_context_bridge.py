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

        # Sentiment
        _sentiment = ana.get("sentiment") or {}
        fear_greed = resolve_fear_greed_value(
            _sentiment.get("raw_value"),
            ana.get("fear_greed"),
            default=50.0,
        )
        state.sentiment.FearGreed = fear_greed

        # Liquidity
        state.liquidity.BTC_Funding = float(
            ana.get("funding_rate") or ana.get("funding") or 0.0
        )
        state.liquidity.OI_Delta = float(ana.get("oi_delta") or 0.0)

        # Crypto price
        state.crypto.BTC_Price = float(ana.get("close") or 0.0)

        # Macro values from collector with safe defaults
        macro_state = load_macro_state()
        state.macro.DXY = float(macro_state.get("DXY", 100.0))
        state.macro.VIX = float(macro_state.get("VIX", 20.0))
        state.macro.RealYield = float(macro_state.get("RealYield", 0.0))
        state.macro.BondYield = float(macro_state.get("BondYield", 4.5))

        # Alternative Data is deliberately not loaded into decision state.
        # It is attached only after scoring by SignalGeneratorAgent as a
        # reference-only payload. This prevents future rule/model changes from
        # silently turning an informational field into trading evidence.

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
        meta_prediction = {
            "probability": decision_input.get("meta_probability") or decision_input.get("meta_confidence"),
            "prediction_id": decision_input.get("prediction_id"),
            "signal_id": decision_input.get("signal_id"),
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
        if provider is None or state is None:
            return engine.decide(decision_input)
        enhanced = engine.decide_with_provider(decision_input, provider, state)
        return enhanced or {}

    except Exception as exc:
        logger.warning(f"[CausalBridge] enhance_signal_with_causal_context skipped: {exc}")
        return {}
