"""
Feature extractor for adaptive scoring training and runtime inference.

Functions:
- records_to_dataset(records) -> (X, y, feature_names)
- features_from_analysis(info) -> dict feature_name->value (for runtime inference)

The extractor is intentionally simple and resilient to missing fields.
"""
from typing import Dict, List, Tuple, Any
import math

CONF_MAP = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.4}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _interpret_conf(conf: Any) -> float:
    if conf is None:
        return 0.5
    if isinstance(conf, (int, float)):
        return float(conf)
    return CONF_MAP.get(str(conf).upper(), 0.5)


def _text_flags(sig_raw: str) -> Dict[str, int]:
    s = (sig_raw or "").upper()
    return {
        "is_buy": 1 if "BUY" in s else 0,
        "is_sell": 1 if "SELL" in s else 0,
        "is_strong": 1 if "STRONG" in s else 0,
        "is_weak": 1 if "WEAK" in s else 0,
    }


def features_from_analysis(info: Dict) -> Dict[str, float]:
    """Extract a flat feature dict from an analysis or logged record.

    Resilient: missing fields are filled with 0/median-like defaults.
    """
    f: Dict[str, float] = {}

    ss = info.get("signal_score") or {}
    raw = ss.get("raw_text") or info.get("signal") or info.get("signal_raw") or ""

    # Core features
    f["score"] = _safe_float(ss.get("score"), default=50.0)
    f["confidence"] = _interpret_conf(ss.get("confidence") or info.get("confidence"))
    f["position_size"] = _safe_float(ss.get("position_size") or info.get("position_size"), default=0.5)

    # Text flags
    flags = _text_flags(raw)
    f.update(flags)

    # Outcome/hold features removed to prevent data leakage during runtime prediction

    # Indicators if available
    f["rsi"] = _safe_float(info.get("rsi"), default=50.0)
    f["atr"] = _safe_float(info.get("atr"), default=0.0)
    ema9 = _safe_float(info.get("ema9", 0.0))
    ema21 = _safe_float(info.get("ema21", 0.0))
    f["ema_trend"] = 1.0 if ema9 > ema21 else 0.0

    close = _safe_float(info.get("close", 0.0))
    bb_upper = _safe_float(info.get("bb_upper", 0.0))
    bb_lower = _safe_float(info.get("bb_lower", 0.0))
    if close > 0 and bb_upper and bb_lower:
        f["bb_width"] = (bb_upper - bb_lower) / close
    else:
        f["bb_width"] = 0.0

    vol_spike = info.get("vol_spike")
    f["vol_spike"] = 1.0 if vol_spike else 0.0

    return f


def records_to_dataset(records: List[Dict]) -> Tuple[List[List[float]], List[int], List[str]]:
    """Convert logged records to X, y, feature_names suitable for sklearn.

    Label: WIN -> 1, else 0 (LOSS/BREAKEVEN treated as 0).
    """
    if not records:
        return [], [], []

    # Build features for each record
    X: List[List[float]] = []
    y: List[int] = []
    feature_names = None

    for r in records:
        feat = features_from_analysis(r)
        if feature_names is None:
            feature_names = sorted(list(feat.keys()))
        row = [float(feat.get(k, 0.0)) for k in feature_names]
        X.append(row)
        label = 1 if (r.get("result") == "WIN") else 0
        y.append(label)

    return X, y, feature_names or []
