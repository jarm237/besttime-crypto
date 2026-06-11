"""
Signal scoring utilities.
Giai đoạn 1-5 (cơ bản): chuyển rule text -> điểm, tổng hợp, ánh xạ action, confidence, position size.
"""
from typing import Dict
import os

# Lazy-loaded model cache (joblib sklearn model + feature names)
_ADAPTIVE_MODEL = None
_REGIME_MULTIPLIERS = None


def _load_adaptive_model():
    global _ADAPTIVE_MODEL
    if _ADAPTIVE_MODEL is not None:
        return _ADAPTIVE_MODEL
    try:
        import joblib
        model_path = os.path.join(os.path.dirname(__file__), "..", "logs", "adaptive_model.joblib")
        if os.path.exists(model_path):
            data = joblib.load(model_path)
            _ADAPTIVE_MODEL = data
            return _ADAPTIVE_MODEL
    except Exception:
        pass
    _ADAPTIVE_MODEL = None
    return None


def _base_score_from_text(sig_text: str) -> int:
    s = sig_text.upper() if sig_text else ""
    if "STRONG BUY" in s or "STRONG BUY" in s:
        return 90
    if "BUY" in s and "WEAK" not in s:
        return 70
    if "WEAK BUY" in s or "WEAK" in s and "BUY" in s:
        return 55
    if "STRONG SELL" in s:
        return 10
    if "SELL" in s and "WEAK" not in s:
        return 30
    if "WEAK SELL" in s:
        return 45
    # Neutral / other
    return 50


def _apply_context_adjustments(score: int, data: Dict, context: Dict) -> int:
    # volume spike
    if context.get("vol_spike"):
        score += 5

    # trend / market regime
    if context.get("above_sma200") and "BUY" in data.get("signal", ""):
        score += 5
    if context.get("below_sma200") and "SELL" in data.get("signal", ""):
        score -= 0  # keep for now

    # ATR shock reduces confidence
    if data.get("atr_shock"):
        score -= 10

    # Sentiment extreme adjustments if provided
    sentiment = data.get("sentiment") or {}
    score_adj = 0
    try:
        s = float(sentiment.get("score", 0.0))
        # Allow overriding penalty via context: use explicit penalty value if provided
        explicit_penalty = None
        try:
            explicit_penalty = float(context.get("sentiment_penalty")) if context and context.get("sentiment_penalty") is not None else None
        except Exception:
            explicit_penalty = None

        if s <= -0.6 and "BUY" in data.get("signal", ""):
            if explicit_penalty is not None:
                score += explicit_penalty
            else:
                score -= 20
        if s >= 0.6 and "SELL" in data.get("signal", ""):
            if explicit_penalty is not None:
                score += explicit_penalty
            else:
                score -= 20
    except Exception:
        pass

    score = max(0, min(100, int(round(score + score_adj))))
    return score


def map_score_to_action(score: int) -> str:
    if score >= 51:
        return "BUY"
    if score <= 49:
        return "SELL"
    return "NEUTRAL"


def map_score_to_confidence(score: int) -> str:
    dist = abs(score - 50)
    if dist >= 30:
        return "HIGH"
    if dist >= 10:
        return "MEDIUM"
    return "LOW"


def position_size_from_score(score: int, min_size: float = 0.25, max_size: float = 1.0) -> float:
    frac = abs(score - 50) / 50.0
    size = min_size + frac * (max_size - min_size)
    return round(max(min_size, min(max_size, size)), 2)


def _load_regime_multipliers():
    global _REGIME_MULTIPLIERS
    if _REGIME_MULTIPLIERS is not None:
        return _REGIME_MULTIPLIERS
    # default multipliers
    default = {
        "TRENDING_BULL": 1.0,
        "TRENDING_BEAR": 0.8,
        "RANGING": 0.5,
        "HIGH_VOLATILITY": 0.3,
    }
    try:
        import json
        cfg_path = os.path.join(os.path.dirname(__file__), "regime_config.json")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(os.path.dirname(__file__), "..", "btc_scraper", "regime_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            pm = cfg.get("position_size_multipliers") or {}
            # merge with defaults
            merged = default.copy()
            merged.update(pm.get("default", {}))
            per = pm.get("per_strategy", {})
            _REGIME_MULTIPLIERS = {"default": merged, "per_strategy": per}
            return _REGIME_MULTIPLIERS
    except Exception:
        pass
    _REGIME_MULTIPLIERS = {"default": default, "per_strategy": {}}
    return _REGIME_MULTIPLIERS


def score_signal(sig_text: str, data: Dict, context: Dict) -> Dict:
    """Return a signal object: {action, score, confidence, position_size}

    - Keep backward compatibility: consumers can still use original text in `signal`.
    - This function produces a numeric score and derived fields.
    """
    # First try adaptive model (if available)
    model_bundle = _load_adaptive_model()
    if model_bundle is not None:
        try:
            from btc_scraper.feature_extractor import features_from_analysis
            import numpy as np

            feat = features_from_analysis({**(data or {}), **(context or {}), "signal_score": {"score": None, "raw_text": sig_text}})
            feature_names = model_bundle.get("features")
            model = model_bundle.get("model")
            row = [float(feat.get(k, 0.0)) for k in feature_names]
            prob = float(model.predict_proba([row])[0][1])
            prob_percent = int(round(prob * 100))

            is_buy = "BUY" in sig_text.upper() or "BULL" in sig_text.upper()
            is_sell = "SELL" in sig_text.upper() or "BEAR" in sig_text.upper()

            if is_buy:
                # 50% win rate -> 50, 100% win rate -> 100
                score = prob_percent
            elif is_sell:
                # 50% win rate -> 50, 100% win rate -> 0
                score = 100 - prob_percent
            else:
                score = 50

            # Use model probability to determine a base position size (continuous)
            try:
                min_size = 0.25
                max_size = 1.0
                base_pos = round(min_size + prob * (max_size - min_size), 2)
            except Exception:
                base_pos = position_size_from_score(int(score))
        except Exception:
            base = _base_score_from_text(sig_text)
            score = _apply_context_adjustments(base, data or {}, context or {})
    else:
        base = _base_score_from_text(sig_text)
        score = _apply_context_adjustments(base, data or {}, context or {})
    action = map_score_to_action(score)
    conf = map_score_to_confidence(score)
    # If adaptive model provided base_pos (from above), use it; else derive from score
    if 'base_pos' in locals() and isinstance(base_pos, (int, float)):
        pos_size = float(base_pos)
    else:
        pos_size = position_size_from_score(score)

    # Regime-specific position sizing multiplier (loadable from regime_config.json)
    regime = None
    try:
        regime = context.get("regime") or data.get("regime") or context.get("market_regime")
    except Exception:
        regime = None

    if regime:
        cfg = _load_regime_multipliers()
        # try per-strategy override
        strategy = None
        try:
            strategy = data.get("strategy") or data.get("subtype") or None
        except Exception:
            strategy = None
        mult = None
        if strategy and cfg.get("per_strategy"):
            strat_map = cfg.get("per_strategy")
            if strategy in strat_map:
                mult = strat_map.get(strategy, {}).get(regime)
        if mult is None:
            mult = cfg.get("default", {}).get(regime, 1.0)
        try:
            pos_size = round(max(0.25, min(1.0, pos_size * float(mult))), 2)
        except Exception:
            pass
    return {
        "action": action,
        "score": int(score),
        "confidence": conf,
        "position_size": pos_size,
        "raw_text": sig_text,
    }


def extract_signal_fields(info: Dict) -> Dict:
    """Normalize signal info from analysis consumer.

    Returns dict with keys: action, raw, score, confidence, position_size
    """
    if not info:
        return {"action": "NEUTRAL", "raw": "", "score": None, "confidence": None, "position_size": None}

    sig_raw = None
    # prefer explicit raw_text from signal_score if present
    ss = info.get("signal_score") or {}
    if ss.get("raw_text"):
        sig_raw = ss.get("raw_text")
    elif isinstance(info.get("signal"), str):
        sig_raw = info.get("signal")
    else:
        sig_raw = str(info.get("signal") or "")

    action = ss.get("action") or ("BUY" if "BUY" in str(sig_raw).upper() else ("SELL" if "SELL" in str(sig_raw).upper() else "NEUTRAL"))
    score = ss.get("score")
    confidence = ss.get("confidence")
    position_size = ss.get("position_size") or info.get("position_size")

    return {"action": action, "raw": sig_raw, "score": score, "confidence": confidence, "position_size": position_size}
