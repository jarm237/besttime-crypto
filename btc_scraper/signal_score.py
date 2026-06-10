"""
Signal scoring utilities.
Giai đoạn 1-5 (cơ bản): chuyển rule text -> điểm, tổng hợp, ánh xạ action, confidence, position size.
"""
from typing import Dict
import os

# Lazy-loaded model cache (joblib sklearn model + feature names)
_ADAPTIVE_MODEL = None


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
    if score >= 65:
        return "BUY"
    if score <= 35:
        return "SELL"
    return "NEUTRAL"


def map_score_to_confidence(score: int) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def position_size_from_score(score: int, min_size: float = 0.25, max_size: float = 1.0) -> float:
    frac = score / 100.0
    size = min_size + frac * (max_size - min_size)
    return round(max(min_size, min(max_size, size)), 2)


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
            score = int(round(prob * 100))
        except Exception:
            base = _base_score_from_text(sig_text)
            score = _apply_context_adjustments(base, data or {}, context or {})
    else:
        base = _base_score_from_text(sig_text)
        score = _apply_context_adjustments(base, data or {}, context or {})
    action = map_score_to_action(score)
    conf = map_score_to_confidence(score)
    pos_size = position_size_from_score(score)
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
