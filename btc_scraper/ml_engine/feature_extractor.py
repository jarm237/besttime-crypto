"""
Feature extractor for adaptive scoring training and runtime inference.

Functions:
- build_meta_features(info, htf_trend=None)  ← ENTRY POINT DUY NHẤT cho Meta Model
- records_to_dataset(records) -> (X, y, feature_names)
- features_from_analysis(info) -> dict feature_name->value (for runtime inference)

FEATURE_SCHEMA là schema CỐ ĐỊNH — KHÔNG ĐỔI TÊN field sau khi bắt đầu train.
Nếu cần thêm feature, tạo model version mới (thêm _v2 vào model file).
"""
from typing import Dict, List, Tuple, Any
import math

# ─── CANONICAL FEATURE SCHEMA ──────────────────────────────────────────────────
# 14 features cố định cho Meta Model (RandomForest).
# Thứ tự KHÔNG quan trọng (RandomForest không cần), nhưng tên PHẢI nhất quán.
FEATURE_SCHEMA = [
    "signal_score",           # 0-100: điểm tín hiệu tổng hợp
    "rsi",                    # 0-100: RSI 14 của khung 15m
    "macd_hist",              # float: MACD histogram (bình thường hóa theo close)
    "atr_pct",                # float: ATR / close * 100 (volatility %)
    "volume_ratio",           # float: volume / vol_sma20 (volume spike factor)
    "fear_greed",             # 0-100: raw Fear & Greed Index
    "ema_distance_pct",       # float: (ema9 - ema21) / close * 100
    "bb_width_pct",           # float: (bb_upper - bb_lower) / close * 100
    "adx",                    # 0-100: Average Directional Index
    "mtf_alignment",          # -1/0/1: xu hướng đa khung (BEAR/NEUTRAL/BULL)
    "regime_trending_bull",   # 0/1: one-hot regime
    "regime_trending_bear",   # 0/1: one-hot regime
    "regime_ranging",         # 0/1: one-hot regime
    "regime_high_volatility", # 0/1: one-hot regime
]

FEATURE_SCHEMA_V2 = FEATURE_SCHEMA + [
    "return_15m",
    "return_1h",
    "return_4h",
    "return_1d",
    "ema9_slope",
    "ema21_slope",
    "sma50_slope",
    "sma200_slope",
    "ema_distance_zscore",
    "realized_vol_20",
    "realized_vol_50",
    "atr_percentile",
    "volatility_regime_compression",
    "volatility_regime_breakout",
    "volatility_regime_mean_reversion",
    "volatility_regime_panic_sell",
    "volatility_regime_low_liquidity",
    "volatility_regime_pump_risk",
    "distance_support_pct",
    "distance_resistance_pct",
    "higher_high",
    "lower_low",
    "market_structure_break",
    "obv",
    "cmf",
    "mfi",
    "volume_acceleration",
    "volume_percentile",
    "roc_14",
    "roc_50",
    "hv20",
    "hv60",
    "bos_bull",
    "bos_bear",
    "choch_bull",
    "choch_bear",
    "regime_strong_trend",
    "regime_weak_trend",
    "regime_compression",
    "regime_breakout",
    "regime_mean_reversion",
    "regime_panic_sell",
    "regime_low_liquidity",
    "regime_pump_risk",
    "sentiment_momentum",
    "sentiment_recovery",
    "sentiment_risk",
    "sentiment_trend_up",
    "sentiment_trend_down",
]
# ───────────────────────────────────────────────────────────────────────────────

CONF_MAP = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.4}

_MTF_ALIGN_MAP = {
    "BULLISH": 1.0,
    "BULLISH-MIXED": 0.5,
    "NEUTRAL": 0.0,
    "BEARISH-MIXED": -0.5,
    "BEARISH": -1.0,
}


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


def build_meta_features(info: Dict, htf_trend: str = None) -> Dict[str, float]:
    """
    Build feature dict theo FEATURE_SCHEMA cố định để feed vào Meta Model.

    Entry point DUY NHẤT cho cả training và runtime prediction.
    Đảm bảo training feature == live feature 100%.

    Args:
        info: analysis dict từ analyze_market() hoặc logged record
        htf_trend: HTF trend summary string (VD: 'BULLISH', 'BEARISH', 'NEUTRAL')
                   Nếu None, sẽ cố lấy từ info.get('htf_trend')

    Returns:
        dict với đúng 14 keys trong FEATURE_SCHEMA, tất cả float.
    """
    f: Dict[str, float] = {}

    ss = info.get("signal_score") or {}
    close = _safe_float(info.get("close", 0.0) or info.get("close_price", 0.0))

    # 1. signal_score (0-100)
    if isinstance(ss, dict):
        f["signal_score"] = _safe_float(ss.get("score") or info.get("score"), default=50.0)
    else:
        f["signal_score"] = _safe_float(ss, default=50.0)

    # 2. rsi (0-100)
    f["rsi"] = _safe_float(info.get("rsi") or info.get("rsi_15m"), default=50.0)

    # 3. macd_hist (bình thường hóa theo close nếu có)
    macd_hist = _safe_float(info.get("macd_hist"), default=0.0)
    if close > 0 and abs(macd_hist) > 0:
        f["macd_hist"] = macd_hist / close * 100  # normalize thành %
    else:
        f["macd_hist"] = macd_hist

    # 4. atr_pct = ATR / close * 100
    atr = _safe_float(info.get("atr") or info.get("atr_15m"), default=0.0)
    if close > 0 and atr > 0:
        f["atr_pct"] = atr / close * 100
    else:
        f["atr_pct"] = _safe_float(info.get("atr_pct") or info.get("atr_pct_15m"), default=2.0)

    # 5. volume_ratio = volume / vol_sma20
    volume = _safe_float(info.get("volume"), default=0.0)
    vol_sma = _safe_float(info.get("vol_sma20") or info.get("vol_sma"), default=0.0)
    if vol_sma > 0 and volume > 0:
        f["volume_ratio"] = volume / vol_sma
    else:
        f["volume_ratio"] = 1.0  # neutral default

    # 6. fear_greed (raw 0-100)
    # Lấy từ nhiều nguồn: context.sentiment_raw, sentiment.raw_value
    fg_raw = (
        info.get("sentiment_raw")
        or info.get("fear_greed")
        or (info.get("sentiment") or {}).get("raw_value")
        or (info.get("sentiment") or {}).get("score")
    )
    if fg_raw is not None:
        # Có thể là score dạng -1..1, cần chuẩn hóa về 0-100
        fg = _safe_float(fg_raw, default=50.0)
        if -1.0 <= fg <= 1.0 and fg != 50.0:
            # dạng normalized score -> convert to 0-100
            f["fear_greed"] = (fg + 1) / 2 * 100
        else:
            f["fear_greed"] = max(0.0, min(100.0, fg))
    else:
        f["fear_greed"] = 50.0

    # 7. ema_distance_pct = (ema9 - ema21) / close * 100
    ema9 = _safe_float(info.get("ema9"), default=0.0)
    ema21 = _safe_float(info.get("ema21"), default=0.0)
    if close > 0 and ema9 > 0 and ema21 > 0:
        f["ema_distance_pct"] = (ema9 - ema21) / close * 100
    else:
        f["ema_distance_pct"] = 0.0

    # 8. bb_width_pct = (bb_upper - bb_lower) / close * 100
    bb_upper = _safe_float(info.get("bb_upper"), default=0.0)
    bb_lower = _safe_float(info.get("bb_lower"), default=0.0)
    if close > 0 and bb_upper > 0 and bb_lower > 0:
        f["bb_width_pct"] = (bb_upper - bb_lower) / close * 100
    else:
        f["bb_width_pct"] = 0.0

    # 9. adx (0-100)
    f["adx"] = _safe_float(info.get("adx") or info.get("adx_15m"), default=20.0)

    # 10. mtf_alignment (-1/0/1 hoặc continuous -1..1)
    htf = htf_trend or info.get("htf_trend") or ""
    f["mtf_alignment"] = _MTF_ALIGN_MAP.get(str(htf).upper(), 0.0)

    # 11-14. Regime one-hot
    regime_raw = (
        info.get("regime")
        or (ss.get("regime") if isinstance(ss, dict) else None)
        or info.get("market_regime")
        or ""
    )
    regime = str(regime_raw).upper().strip()
    f["regime_trending_bull"]   = 1.0 if "TRENDING_BULL" in regime else 0.0
    f["regime_trending_bear"]   = 1.0 if "TRENDING_BEAR" in regime else 0.0
    f["regime_ranging"]         = 1.0 if "RANGING" in regime else 0.0
    f["regime_high_volatility"] = 1.0 if "HIGH_VOLATILITY" in regime or "VOLATILITY" in regime else 0.0

    # Đảm bảo tất cả FEATURE_SCHEMA keys có mặt và là float
    for k in FEATURE_SCHEMA:
        if k not in f:
            f[k] = 0.0
        else:
            f[k] = float(f[k]) if not math.isnan(f[k]) and not math.isinf(f[k]) else 0.0

    return f


def build_meta_features_v2(info: Dict, htf_trend: str = None) -> Dict[str, float]:
    """
    Build feature dict theo FEATURE_SCHEMA_V2 cho model version 2.
    """
    f = build_meta_features(info, htf_trend)

    extra_keys = {
        "return_15m": info.get("return_15m"),
        "return_1h": info.get("return_1h"),
        "return_4h": info.get("return_4h"),
        "return_1d": info.get("return_1d"),
        "ema9_slope": info.get("ema9_slope"),
        "ema21_slope": info.get("ema21_slope"),
        "sma50_slope": info.get("sma50_slope"),
        "sma200_slope": info.get("sma200_slope"),
        "ema_distance_zscore": info.get("ema_distance_zscore"),
        "realized_vol_20": info.get("realized_vol_20"),
        "realized_vol_50": info.get("realized_vol_50"),
        "atr_percentile": info.get("atr_percentile"),
        "volatility_regime_compression": info.get("volatility_regime_compression"),
        "volatility_regime_breakout": info.get("volatility_regime_breakout"),
        "volatility_regime_mean_reversion": info.get("volatility_regime_mean_reversion"),
        "volatility_regime_panic_sell": info.get("volatility_regime_panic_sell"),
        "volatility_regime_low_liquidity": info.get("volatility_regime_low_liquidity"),
        "volatility_regime_pump_risk": info.get("volatility_regime_pump_risk"),
        "distance_support_pct": info.get("distance_support_pct"),
        "distance_resistance_pct": info.get("distance_resistance_pct"),
        "higher_high": info.get("higher_high"),
        "lower_low": info.get("lower_low"),
        "market_structure_break": info.get("market_structure_break"),
        "obv": info.get("obv"),
        "cmf": info.get("cmf"),
        "mfi": info.get("mfi"),
        "volume_acceleration": info.get("volume_acceleration"),
        "volume_percentile": info.get("volume_percentile"),
        "roc_14": info.get("roc_14"),
        "roc_50": info.get("roc_50"),
        "hv20": info.get("hv20"),
        "hv60": info.get("hv60"),
        "bos_bull": info.get("bos_bull"),
        "bos_bear": info.get("bos_bear"),
        "choch_bull": info.get("choch_bull"),
        "choch_bear": info.get("choch_bear"),
        "sentiment_momentum": info.get("sentiment_momentum"),
        "sentiment_recovery": info.get("sentiment_recovery"),
        "sentiment_risk": info.get("sentiment_risk"),
        "sentiment_trend_up": info.get("sentiment_trend_up"),
        "sentiment_trend_down": info.get("sentiment_trend_down"),
    }

    regime_raw = str(
        info.get("regime")
        or info.get("market_regime")
        or (info.get("signal_score") or {}).get("regime")
        or ""
    ).upper()
    extra_keys.update({
        "regime_strong_trend": 1.0 if "STRONG_TREND" in regime_raw else 0.0,
        "regime_weak_trend": 1.0 if "WEAK_TREND" in regime_raw else 0.0,
        "regime_compression": 1.0 if "COMPRESSION" in regime_raw else 0.0,
        "regime_breakout": 1.0 if "BREAKOUT" in regime_raw else 0.0,
        "regime_mean_reversion": 1.0 if "MEAN_REVERSION" in regime_raw else 0.0,
        "regime_panic_sell": 1.0 if "PANIC_SELL" in regime_raw else 0.0,
        "regime_low_liquidity": 1.0 if "LOW_LIQUIDITY" in regime_raw else 0.0,
        "regime_pump_risk": 1.0 if "PUMP_RISK" in regime_raw else 0.0,
    })

    for k, v in extra_keys.items():
        f[k] = _safe_float(v, default=0.0)

    # Ensure all schema fields exist and are numeric for V2
    for k in FEATURE_SCHEMA_V2:
        if k not in f:
            f[k] = 0.0
        else:
            f[k] = float(f[k]) if not math.isnan(f[k]) and not math.isinf(f[k]) else 0.0

    return f


def features_from_analysis(info: Dict) -> Dict[str, float]:
    """
    Backward-compatible alias cho build_meta_features().
    Giữ lại để không break các caller cũ (records_to_dataset, adaptive_scoring).

    Cũng trả về các extra legacy fields (is_buy, is_sell, ...) nếu cần.
    """
    # Dùng build_meta_features làm base
    f = build_meta_features(info)

    # Thêm legacy fields không có trong FEATURE_SCHEMA (backward compat)
    ss = info.get("signal_score") or {}
    raw = ss.get("raw_text") or info.get("signal") or info.get("signal_raw") or ""
    flags = _text_flags(raw)
    f.update(flags)

    f["confidence"] = _interpret_conf(ss.get("confidence") or info.get("confidence"))
    f["position_size"] = _safe_float(ss.get("position_size") or info.get("position_size"), default=0.5)
    f["rsi_delta"] = _safe_float(ss.get("rsi_delta") or info.get("rsi_delta"), default=0.0)
    f["ema_trend"] = 1.0 if _safe_float(info.get("ema9")) > _safe_float(info.get("ema21")) else 0.0
    vol_spike = info.get("vol_spike")
    f["vol_spike"] = 1.0 if vol_spike else 0.0
    f["regime_confidence"] = _safe_float(
        info.get("regime_confidence") or (ss.get("regime_confidence") if isinstance(ss, dict) else None),
        default=0.0,
    )
    f["regime_unknown"] = 1.0 if not (info.get("regime") or (ss.get("regime") if isinstance(ss, dict) else None)) else 0.0

    return f


def records_to_dataset(records: List[Dict]) -> Tuple[List[List[float]], List[int], List[str]]:
    """
    Convert logged records thành X, y, feature_names dùng FEATURE_SCHEMA cố định.

    Label: WIN -> 1, else 0 (LOSS/BREAKEVEN treated as 0).
    """
    if not records:
        return [], [], []

    X: List[List[float]] = []
    y: List[int] = []

    for r in records:
        if all(k in r for k in FEATURE_SCHEMA_V2):
            feat = r
        else:
            feat = build_meta_features_v2(r)
        row = [float(feat.get(k, 0.0)) for k in FEATURE_SCHEMA_V2]
        X.append(row)
        label = 1 if (r.get("result") == "WIN") else 0
        y.append(label)

    return X, y, list(FEATURE_SCHEMA_V2)
