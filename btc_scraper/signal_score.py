"""
Signal scoring utilities.
Giai đoạn 1-5 (cơ bản): chuyển rule text -> điểm, tổng hợp, ánh xạ action, confidence, position size.
"""
from typing import Dict
import os
from pathlib import Path
import json


def _safe_float(v, default=0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _use_kelly() -> bool:
    """Return True when Kelly sizing should be enabled. Can be disabled via env var DISABLE_KELLY=1."""
    try:
        return os.environ.get('DISABLE_KELLY', '') != '1'
    except Exception:
        return True

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
            # Fix n_jobs issue for single sample inference
            model = data.get("model") if isinstance(data, dict) else data
            def set_n_jobs(est):
                if hasattr(est, 'n_jobs'): est.n_jobs = 1
                if hasattr(est, 'estimator'): set_n_jobs(est.estimator)
                if hasattr(est, 'base_estimator'): set_n_jobs(est.base_estimator)
                if hasattr(est, 'best_estimator_'): set_n_jobs(est.best_estimator_)
                if hasattr(est, 'steps'):
                    for name, step in est.steps: set_n_jobs(step)
                if hasattr(est, 'calibrated_classifiers_'):
                    for e in est.calibrated_classifiers_: set_n_jobs(e)
            set_n_jobs(model)
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


_KELLY_PARAMS_CACHE = None

def _load_kelly_params():
    """Load Kelly tuning parameters from `regime_config.json`.
    Returns defaults when config missing.
    Keys: max_fraction, decay_rate, min_fraction
    """
    global _KELLY_PARAMS_CACHE
    if _KELLY_PARAMS_CACHE is not None:
        return _KELLY_PARAMS_CACHE
        
    defaults = {"max_fraction": 0.5, "decay_rate": 0.0, "min_fraction": 0.0}
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "regime_config.json")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(os.path.dirname(__file__), "..", "btc_scraper", "regime_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            k = cfg.get("kelly") or {}
            _KELLY_PARAMS_CACHE = {
                "max_fraction": float(k.get("max_fraction", defaults["max_fraction"])),
                "decay_rate": float(k.get("decay_rate", defaults["decay_rate"])),
                "min_fraction": float(k.get("min_fraction", defaults["min_fraction"])),
            }
            return _KELLY_PARAMS_CACHE
    except Exception:
        pass
    _KELLY_PARAMS_CACHE = defaults
    return _KELLY_PARAMS_CACHE


_POSITION_SIZING_PARAMS_CACHE = None

def _load_position_sizing_params():
    """Load Position Sizing parameters from `regime_config.json` and/or environment variables.
    Returns a dict with keys: method, target_std_dev_pct, target_atr_pct, min_vol_mult, max_vol_mult
    """
    global _POSITION_SIZING_PARAMS_CACHE
    
    env_method = os.environ.get("AUTO_TRADE_POSITION_SIZING_METHOD")
    
    if _POSITION_SIZING_PARAMS_CACHE is not None:
        if env_method:
            res = _POSITION_SIZING_PARAMS_CACHE.copy()
            res["method"] = env_method.lower()
            return res
        return _POSITION_SIZING_PARAMS_CACHE

    defaults = {
        "method": env_method.lower() if env_method else "kelly",
        "target_std_dev_pct": 2.0,
        "target_atr_pct": 1.0,
        "min_vol_mult": 0.25,
        "max_vol_mult": 1.5
    }
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "regime_config.json")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(os.path.dirname(__file__), "..", "btc_scraper", "regime_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ps = cfg.get("position_sizing") or {}
            method = env_method.lower() if env_method else ps.get("method", "kelly").lower()
            _POSITION_SIZING_PARAMS_CACHE = {
                "method": method,
                "target_std_dev_pct": float(ps.get("target_std_dev_pct", defaults["target_std_dev_pct"])),
                "target_atr_pct": float(ps.get("target_atr_pct", defaults["target_atr_pct"])),
                "min_vol_mult": float(ps.get("min_vol_mult", defaults["min_vol_mult"])),
                "max_vol_mult": float(ps.get("max_vol_mult", defaults["max_vol_mult"])),
            }
            return _POSITION_SIZING_PARAMS_CACHE
    except Exception:
        pass
    _POSITION_SIZING_PARAMS_CACHE = defaults
    return _POSITION_SIZING_PARAMS_CACHE


_ESTIMATE_B_CACHE = None

def _estimate_b(strategy: str, regime: str) -> float:
    """Estimate reward/risk ratio `b` (average win / average loss) from analytics file.
    Falls back to 1.0 when no data available.
    """
    global _ESTIMATE_B_CACHE
    if _ESTIMATE_B_CACHE is None:
        _ESTIMATE_B_CACHE = {}
        try:
            p = Path(__file__).parent.parent / "logs" / "regime_strategy_matrix.csv"
            if p.exists():
                import csv
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        strat = row.get("strategy", "")
                        reg = row.get("regime", "")
                        aw = float(row.get("avg_win", 1.0))
                        al = float(row.get("avg_loss", 1.0))
                        b_val = max(0.01, aw / abs(al)) if al != 0 else max(1.0, aw)
                        
                        # Store in cache
                        _ESTIMATE_B_CACHE[(strat, reg)] = b_val
                        if strat and (strat, '') not in _ESTIMATE_B_CACHE:
                            _ESTIMATE_B_CACHE[(strat, '')] = b_val
        except Exception:
            pass

    # Lookup in cache
    try:
        return _ESTIMATE_B_CACHE.get((strategy, regime)) or _ESTIMATE_B_CACHE.get((strategy, '')) or 1.0
    except Exception:
        return 1.0


def compute_kelly_fraction(p: float, b: float) -> float:
    """Compute Kelly fraction for probability p and odds b.
    Returns clipped value between 0 and 1.
    """
    try:
        p = float(p)
        b = float(b)
        if b <= 0:
            return 0.0
        k = (p * b - (1 - p)) / b
        return max(0.0, min(1.0, k))
    except Exception:
        return 0.0


def score_signal(sig_text: str, data: Dict, context: Dict, htf_trend: str = None) -> Dict:
    """Return a signal object: {action, score, confidence, position_size}

    - Keep backward compatibility: consumers can still use original text in `signal`.
    - This function produces a numeric score and derived fields.
    """
    disable_ml = False
    if context and isinstance(context, dict):
        disable_ml = context.get("disable_ml", False)

    # reason accumulates filter notes appended throughout the function
    reason: str = ""

    s_upper = sig_text.upper() if sig_text else ""
    is_buy = ("BUY" in s_upper or "BULL" in s_upper) and "NEUTRAL" not in s_upper and "ERROR" not in s_upper
    is_sell = ("SELL" in s_upper or "BEAR" in s_upper) and "NEUTRAL" not in s_upper and "ERROR" not in s_upper

    merged = {}
    if isinstance(data, dict):
        merged.update(data)
    if isinstance(context, dict):
        merged.update(context)

    if not is_buy and not is_sell:
        action = "NEUTRAL"
        score = 50
        conf = "LOW"
        initial_pos_size = 0.25
    else:
        # First try adaptive model (if available)
        model_bundle = _load_adaptive_model() if not disable_ml else None
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
            initial_pos_size = float(base_pos)
        else:
            initial_pos_size = position_size_from_score(score)

    # determine regime early so meta prediction can use it
    regime = None
    try:
        regime = context.get("regime") or data.get("regime") or context.get("market_regime")
    except Exception:
        regime = None

    # ── Meta Model Confidence + Kelly Position Sizing ──────────────────────────
    meta_prob = None
    kelly = None
    b_est = None
    meta_err = None
    try:
        # allow disabling Kelly via environment for comparison runs
        if disable_ml:
            raise RuntimeError('ml_disabled')
        if not _use_kelly():
            raise RuntimeError('kelly_disabled')
        from btc_scraper.meta_model import predict_meta_confidence
        from btc_scraper.feature_extractor import build_meta_features

        # Gắn score hiện tại vào merged để feature_extractor có thể đọc
        merged['score'] = score
        merged['signal'] = sig_text
        # HTF trend cho mtf_alignment feature
        if htf_trend:
            merged['htf_trend'] = htf_trend
        elif 'htf_trend' not in merged:
            merged['htf_trend'] = merged.get('trend_label', '')

        meta = predict_meta_confidence(merged)
        if isinstance(meta, dict) and meta.get('probability') is not None:
            meta_prob = float(meta['probability'])
            # Tính Kelly sizing dựa trên meta_prob
            strategy = (data.get('strategy') or data.get('subtype')) if isinstance(data, dict) else None
            b_est = _estimate_b(strategy or '', regime or '')
            kelly_raw = compute_kelly_fraction(meta_prob, b_est)
            kparams = _load_kelly_params()
            try:
                kelly_capped = min(float(kparams.get('max_fraction', 0.5)), float(kelly_raw))
            except Exception:
                kelly_capped = float(kelly_raw)
            decay_rate = float(kparams.get('decay_rate', 0.0))
            try:
                decayed = kelly_capped * max(0.0, 1.0 - decay_rate * float(initial_pos_size))
            except Exception:
                decayed = kelly_capped
            try:
                kelly = max(float(kparams.get('min_fraction', 0.0)), float(decayed))
            except Exception:
                kelly = float(decayed)
        elif isinstance(meta, dict) and meta.get('error'):
            meta_err = meta['error']
    except Exception as e:
        if str(e) not in ('ml_disabled', 'kelly_disabled'):
            import traceback
            traceback.print_exc()
        meta_prob = None
        meta_err = str(e)
    # ─────────────────────────────────────────────────────────────────────────────

    # ── Sprint 3: Meta Signal Filter ─────────────────────────────────────────────
    # Penalize score khi Meta Model xác suất thấp (cấu hình qua env var).
    # Chỉ hoạt động khi META_REJECT_THRESHOLD được set trong .env hoặc environ.
    # Mặc định disabled (threshold = 0.0) để không phá hệ thống cũ.
    _meta_reject_threshold = None
    try:
        import os as _os
        _thresh_str = _os.getenv("META_REJECT_THRESHOLD", "0").strip()
        _thresh_val = float(_thresh_str)
        if _thresh_val > 0:
            _meta_reject_threshold = _thresh_val
    except Exception:
        pass

    if _meta_reject_threshold is not None and meta_prob is not None:
        if meta_prob < _meta_reject_threshold:
            _penalty = 20
            score = max(0, score - _penalty)
            reason += f" | Meta Filter: {meta_prob:.0%} < {_meta_reject_threshold:.0%} → score -{_penalty}"
    # ─────────────────────────────────────────────────────────────────────────────

    # ── Volatility (Standard Deviation) Sizing ──────────────────────────────────
    std_dev_pct = None
    vol_mult = 1.0
    ps_params = _load_position_sizing_params()

    # 1. Thử tính toán standard deviation từ Bollinger Bands
    try:
        bb_upper = _safe_float(merged.get("bb_upper"))
        bb_lower = _safe_float(merged.get("bb_lower"))
        close_p = _safe_float(merged.get("close") or merged.get("close_price"))
        if close_p > 0 and bb_upper > 0 and bb_lower > 0:
            bb_width_pct = (bb_upper - bb_lower) / close_p * 100
            std_dev_pct = bb_width_pct / 4.0
            target_std = float(ps_params.get("target_std_dev_pct", 2.0))
            if std_dev_pct > 0:
                vol_mult = target_std / std_dev_pct
    except Exception:
        pass

    # 2. Fallback sang ATR percentage nếu Bollinger Bands bị thiếu/sai lệch
    if std_dev_pct is None or std_dev_pct <= 0:
        try:
            atr_val = _safe_float(merged.get("atr") or merged.get("atr_15m"))
            close_p = _safe_float(merged.get("close") or merged.get("close_price"))
            if close_p > 0 and atr_val > 0:
                std_dev_pct = (atr_val / close_p) * 100
            else:
                std_dev_pct = _safe_float(merged.get("atr_pct") or merged.get("atr_pct_15m"), default=0.0)

            if std_dev_pct and std_dev_pct > 0:
                target_atr = float(ps_params.get("target_atr_pct", 1.0))
                vol_mult = target_atr / std_dev_pct
        except Exception:
            pass

    # Giới hạn Volatility Multiplier
    if vol_mult != 1.0:
        try:
            min_m = float(ps_params.get("min_vol_mult", 0.25))
            max_m = float(ps_params.get("max_vol_mult", 1.5))
            vol_mult = max(min_m, min(max_m, vol_mult))
        except Exception:
            vol_mult = 1.0

    # ── Áp dụng Position Sizing Method ──────────────────────────────────────────
    sizing_method = ps_params.get("method", "kelly")
    pos_size = initial_pos_size

    # Sprint 4: Sử dụng trực tiếp meta_prob thay thế cho Kelly fraction phức tạp
    prob_factor = meta_prob if meta_prob is not None else (kelly if kelly is not None else 1.0)

    if sizing_method == "kelly" and prob_factor is not None:
        try:
            pos_size = round(max(0.05, min(1.0, pos_size * float(prob_factor))), 2)
        except Exception:
            pass
    elif sizing_method == "std_dev" and vol_mult != 1.0:
        try:
            pos_size = round(max(0.05, min(1.0, pos_size * float(vol_mult))), 2)
        except Exception:
            pass
    elif sizing_method == "hybrid":
        try:
            mult_factor = 1.0
            if prob_factor is not None:
                mult_factor *= float(prob_factor)
            if vol_mult != 1.0:
                mult_factor *= float(vol_mult)
            pos_size = round(max(0.05, min(1.0, pos_size * mult_factor)), 2)
        except Exception:
            pass

    # Regime-specific position sizing multiplier (loadable from regime_config.json)

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
        "meta_confidence": meta_prob,                          # float 0-1
        "meta_confidence_pct": int(round(meta_prob * 100)) if meta_prob is not None else None,  # int 0-100 cho display
        "kelly_fraction": kelly,
        "b_estimate": b_est,
        "meta_error": meta_err,
        "position_sizing_method": sizing_method,
        "volatility_multiplier": round(vol_mult, 4) if vol_mult is not None else 1.0,
        "std_dev_pct": round(std_dev_pct, 4) if std_dev_pct is not None else None,
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
