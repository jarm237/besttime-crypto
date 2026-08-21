"""
Signal scoring utilities.
Giai đoạn 1-5 (cơ bản): chuyển rule text -> điểm, tổng hợp, ánh xạ action, confidence, position size.
"""
from typing import Dict
import os
import time
import gzip
import shutil
import warnings
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta

from btc_scraper.core.paths import build_logs_path
from btc_scraper.regime.config import (
    compute_regime_config_sha256,
    load_runtime_regime_config,
    regime_effect_metadata,
    regime_position_sizing_enabled,
)
from btc_scraper.regime.contract import coerce_regime_snapshot

# ── TTL Cache cho calculate_risk_metrics ─────────────────────────────────────
# Tránh query MongoDB 24 lần/chu kỳ (1 lần/coin) → chỉ query 1 lần/phút
_RISK_METRICS_CACHE: dict = {}
_RISK_METRICS_CACHE_TS: float = 0.0
_RISK_METRICS_TTL: float = 60.0  # giây

def _get_cached_risk_metrics() -> dict:
    global _RISK_METRICS_CACHE, _RISK_METRICS_CACHE_TS
    now = time.monotonic()
    if now - _RISK_METRICS_CACHE_TS < _RISK_METRICS_TTL and _RISK_METRICS_CACHE:
        return _RISK_METRICS_CACHE
    try:
        from btc_scraper.trading.risk_manager import calculate_risk_metrics
        _RISK_METRICS_CACHE = calculate_risk_metrics()
        _RISK_METRICS_CACHE_TS = now
    except Exception:
        _RISK_METRICS_CACHE = {
            "status": "UNAVAILABLE",
            "failure_reason": "risk_manager_exception",
            "consecutive_losses": None,
            "drawdown_pct": None,
            "risk_multiplier": 0.0,
            "blocked": True,
            "block_action": "BLOCK_ENTRY",
            "peak_equity": None,
            "current_equity": None,
        }
    return _RISK_METRICS_CACHE


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


def _get_meta_prob_log_dir() -> Path:
    return build_logs_path()


def _get_meta_prob_log_path(logs_dir: Path | None = None, ts: datetime | None = None) -> Path:
    ts = ts or datetime.now(timezone.utc)
    logs_dir = logs_dir or _get_meta_prob_log_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / f"meta_prob_entry_{ts.strftime('%Y-%m-%d')}.log"


def _rotate_meta_prob_log(log_path: Path, max_bytes: int | None = None) -> None:
    max_bytes = max_bytes if max_bytes is not None else int(os.getenv("META_PROB_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    if not log_path.exists():
        return
    if log_path.stat().st_size < max_bytes:
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rotated_path = log_path.parent / f"{log_path.name}.{timestamp}.gz"
    try:
        with log_path.open("rb") as src, gzip.open(rotated_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        log_path.unlink(missing_ok=True)
    except Exception:
        pass


def _prune_meta_prob_logs(logs_dir: Path | None = None, retention_days: int | None = None) -> None:
    logs_dir = logs_dir or _get_meta_prob_log_dir()
    retention_days = retention_days if retention_days is not None else int(os.getenv("META_PROB_LOG_RETENTION_DAYS", "7"))
    if retention_days < 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        for path in logs_dir.glob("meta_prob_entry_*"):
            if not path.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            except Exception:
                continue
            if mtime < cutoff:
                path.unlink(missing_ok=True)
    except Exception:
        pass


def _append_meta_prob_entry(entry: Dict) -> None:
    try:
        logs_dir = _get_meta_prob_log_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        _prune_meta_prob_logs(logs_dir)
        log_path = _get_meta_prob_log_path(logs_dir)
        _rotate_meta_prob_log(log_path)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# Lazy-loaded model cache (joblib sklearn model + feature names)
_ADAPTIVE_MODEL = None
_REGIME_MULTIPLIERS = None


def _load_adaptive_model():
    global _ADAPTIVE_MODEL
    if _ADAPTIVE_MODEL is not None:
        return _ADAPTIVE_MODEL
    try:
        from btc_scraper.ml_engine.governed_artifact_loader import get_governed_artifact_loader
        loaded = get_governed_artifact_loader().load_production("adaptive_rf", "adaptive-rf-v2")
        if loaded.model is not None:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*xgboost.*(No visible GPU is found|Device is changed from GPU to CPU|Changing updater from `grow_gpu_hist`).*",
                    category=UserWarning,
                )
                data = loaded.model
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
    except Exception as exc:
        warnings.warn(f"Adaptive RF disabled: {exc}", RuntimeWarning)
    _ADAPTIVE_MODEL = None
    return None


import re

_SIGNAL_ACTION_RE = re.compile(r"\b(STRONG BUY|WEAK BUY|STRONG SELL|WEAK SELL|BUY|SELL|BULL|BEAR)\b", flags=re.IGNORECASE)


def _primary_signal_action(sig_text: str) -> str:
    """Return primary action from raw signal text: BUY, SELL, or NEUTRAL."""
    if not sig_text:
        return "NEUTRAL"
    s = str(sig_text).upper()
    if "NEUTRAL" in s or "ERROR" in s:
        return "NEUTRAL"

    match = _SIGNAL_ACTION_RE.search(str(sig_text))
    if not match:
        return "NEUTRAL"

    token = match.group(1).upper()
    if "SELL" in token or token == "BEAR":
        return "SELL"
    return "BUY"


def _base_score_from_text(sig_text: str) -> int:
    s = sig_text.upper() if sig_text else ""
    action = _primary_signal_action(sig_text)
    if action == "BUY":
        if "STRONG BUY" in s:
            return 90
        if "WEAK BUY" in s or ("WEAK" in s and "BUY" in s):
            return 55
        if "BUY" in s:
            return 70
        return 70
    if action == "SELL":
        if "STRONG SELL" in s:
            return 10
        if "WEAK SELL" in s:
            return 45
        if "SELL" in s:
            return 30
        return 30
    return 50


def _apply_context_adjustments(score: int, data: Dict, context: Dict) -> int:
    # volume spike
    if context.get("vol_spike"):
        score += 5

    signal_action = _primary_signal_action(data.get("signal", ""))
    # trend / market regime
    if context.get("above_sma200") and signal_action == "BUY":
        score += 5
    if context.get("below_sma200") and signal_action == "SELL":
        score -= 0  # keep for now

    # ATR shock reduces confidence
    if data.get("atr_shock"):
        score -= 10

    # Sentiment extreme adjustments if provided
    sentiment = data.get("sentiment") or {}
    score_adj = 0
    try:
        score_value = sentiment.get("normalized_score", sentiment.get("score"))
        s = float(score_value) if score_value is not None else None
        # Allow overriding penalty via context: use explicit penalty value if provided
        explicit_penalty = None
        try:
            explicit_penalty = float(context.get("sentiment_penalty")) if context and context.get("sentiment_penalty") is not None else None
        except Exception:
            explicit_penalty = None

        if s is not None and s <= -0.6 and "BUY" in data.get("signal", ""):
            if explicit_penalty is not None:
                score += explicit_penalty
            else:
                score -= 20
        if s is not None and s >= 0.6 and "SELL" in data.get("signal", ""):
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


def map_score_to_display(score: int, action: str) -> tuple[int, str]:
    """
    Chuyển score nội bộ (0-100) sang dạng hiển thị dễ hiểu hơn:
    - display_score: 0-100, đại diện cho sức mạnh theo chiều action (luôn dương)
    - display_label: chuỗi hiển thị ví dụ "BUY 80%" hoặc "SELL 75%" hoặc "NEUTRAL"

    Score nội bộ:
      - 0   = STRONG SELL (100% sức mạnh bán)
      - 50  = NEUTRAL
      - 100 = STRONG BUY  (100% sức mạnh mua)

    Quy đổi:
      - BUY:  display_score = score       (51-100 → 51-100%)
      - SELL: display_score = 100 - score (0-49  → 51-100%)
      - NEUTRAL: display_score = 0
    """
    if action == "BUY":
        display_score = int(score)
        display_label = f"BUY {display_score}%"
    elif action == "SELL":
        display_score = int(100 - score)
        display_label = f"SELL {display_score}%"
    else:
        display_score = 0
        display_label = "NEUTRAL"
    return display_score, display_label


def signal_strength_from_score(action: str, score: int | float) -> int:
    """
    Convert directional score into side-agnostic signal strength.

    Internal score uses a directional axis:
      0   = strongest SELL
      50  = NEUTRAL
      100 = strongest BUY

    Strength is used for trade eligibility:
      0   = weak/no signal
      100 = strong signal, regardless of BUY or SELL side
    """
    action = str(action or "NEUTRAL").upper()
    try:
        score_val = float(score)
    except Exception:
        score_val = 50.0

    if action == "BUY":
        strength = score_val
    elif action == "SELL":
        strength = 100.0 - score_val
    else:
        strength = 0.0
    return int(round(max(0.0, min(100.0, strength))))


# ── Signed score normalization ────────────────────────────────────────────────
# Used by the canonical entry decision pipeline (PR 1).

from btc_scraper.trading.decision_types import NormalizedSignalScore, TradeAction

# Default threshold: strength must reach this to be considered BUY/SELL.
# Matches the existing AUTO_TRADE_SCORE_THRESHOLD default of 75.
DEFAULT_ACTION_THRESHOLD: float = 50.0


def normalize_directional_score(
    raw_score: float,
    *,
    action_threshold: float = DEFAULT_ACTION_THRESHOLD,
) -> NormalizedSignalScore:
    """Normalize a raw 0-100 directional score into a canonical representation.

    Formula::

        directional_score = round((raw_score - 50) * 2)

    Examples:

        | Raw score | Directional | Strength | Action  |
        |----------:|------------:|---------:|---------|
        |        95 |         +90 |       90 | BUY     |
        |         5 |         -90 |       90 | SELL    |
        |        70 |         +40 |       40 | NEUTRAL |
        |        30 |         -40 |       40 | NEUTRAL |
        |        50 |           0 |        0 | NEUTRAL |

    The action is derived *solely* from ``directional_score`` and
    ``action_threshold`` — it is never taken from an external input.
    Callers should compare the returned ``action`` with any upstream
    action to detect ``DIRECTION_ENCODING_INCONSISTENT``.

    Args:
        raw_score: Internal score on the 0-100 axis
                   (0 = strongest SELL, 50 = NEUTRAL, 100 = strongest BUY).
        action_threshold: Minimum ``strength`` required for a non-NEUTRAL
                          action.  Defaults to ``DEFAULT_ACTION_THRESHOLD``.

    Returns:
        NormalizedSignalScore with directional_score, strength, and derived action.
    """
    try:
        raw = float(raw_score)
    except (TypeError, ValueError):
        raw = 50.0
    raw = max(0.0, min(100.0, raw))

    directional = round((raw - 50.0) * 2.0)
    strength = abs(directional)

    # Clamp to [-100, +100] and [0, 100] respectively
    directional = max(-100, min(100, directional))
    strength = max(0, min(100, strength))

    threshold = max(0.0, float(action_threshold))
    if strength >= threshold and directional > 0:
        action = TradeAction.BUY
    elif strength >= threshold and directional < 0:
        action = TradeAction.SELL
    else:
        action = TradeAction.NEUTRAL

    return NormalizedSignalScore(
        raw_score=raw,
        directional_score=directional,
        strength=strength,
        action=action,
    )


def position_size_from_score(score: int, min_size: float = 0.25, max_size: float = 1.0) -> float:
    frac = abs(score - 50) / 50.0
    size = min_size + frac * (max_size - min_size)
    return round(max(min_size, min(max_size, size)), 2)


def _load_regime_multipliers():
    global _REGIME_MULTIPLIERS
    if _REGIME_MULTIPLIERS is not None:
        return _REGIME_MULTIPLIERS
    default = {}
    try:
        cfg = load_runtime_regime_config()
        pm = cfg.get("position_size_multipliers") or {}
        _REGIME_MULTIPLIERS = {
            "default": dict(pm.get("default", {})),
            "per_strategy": dict(pm.get("per_strategy", {})),
        }
        return _REGIME_MULTIPLIERS
    except Exception as exc:
        raise RuntimeError(f"REGIME_CONFIG_UNAVAILABLE: {exc}") from exc


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
    cfg = load_runtime_regime_config()
    k = cfg.get("kelly") or {}
    _KELLY_PARAMS_CACHE = {
        "max_fraction": float(k.get("max_fraction", defaults["max_fraction"])),
        "decay_rate": float(k.get("decay_rate", defaults["decay_rate"])),
        "min_fraction": float(k.get("min_fraction", defaults["min_fraction"])),
    }
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
    cfg = load_runtime_regime_config()
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


_OPTIMIZED_PARAMS_CACHE = None

def _load_optimized_params():
    global _OPTIMIZED_PARAMS_CACHE
    if _OPTIMIZED_PARAMS_CACHE is not None:
        return _OPTIMIZED_PARAMS_CACHE
    from pathlib import Path
    import json
    candidate_paths = [
        Path(__file__).parent.parent / "logs" / "optimized_trading_params.json",
        Path(__file__).parent.parent.parent / "logs" / "optimized_trading_params.json",
    ]
    for cfg_path in candidate_paths:
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    _OPTIMIZED_PARAMS_CACHE = json.load(f)
                    return _OPTIMIZED_PARAMS_CACHE
            except Exception:
                pass
    _OPTIMIZED_PARAMS_CACHE = {}
    return _OPTIMIZED_PARAMS_CACHE



_ESTIMATE_B_CACHE = None

def _estimate_b(strategy: str, regime: str) -> float:
    """Estimate reward/risk ratio `b` (average win / average loss) from analytics file.
    Falls back to 1.0 when no data available.
    """
    global _ESTIMATE_B_CACHE
    if _ESTIMATE_B_CACHE is None:
        _ESTIMATE_B_CACHE = {}
        try:
            p = build_logs_path("regime_strategy_matrix.csv")
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


def score_signal(
    sig_text: str,
    data: Dict,
    context: Dict,
    htf_trend: str = None,
    *,
    meta_prediction: Dict | None = None,
) -> Dict:
    """Return a signal object: {action, score, confidence, position_size}

    - Keep backward compatibility: consumers can still use original text in `signal`.
    - This function produces a numeric score and derived fields.
    """
    disable_ml = False
    if context and isinstance(context, dict):
        disable_ml = context.get("disable_ml", False)

    # reason accumulates filter notes appended throughout the function
    reason: str = ""

    action_from_text = _primary_signal_action(sig_text)
    is_buy = action_from_text == "BUY"
    is_sell = action_from_text == "SELL"

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
                from btc_scraper.ml_engine.feature_extractor import features_from_analysis
                from btc_scraper.ml_engine.meta_model import model_predict_proba

                feat = features_from_analysis({**(data or {}), **(context or {}), "signal_score": {"score": None, "raw_text": sig_text}})
                feature_names = model_bundle.get("features")
                model = model_bundle.get("model")
                row = [float(feat.get(k, 0.0)) for k in feature_names]
                prob = float(model_predict_proba(model, [row], feature_names)[0][1])
                action_from_text = _primary_signal_action(sig_text)
                is_buy = action_from_text == "BUY"
                is_sell = action_from_text == "SELL"

                if is_buy:
                    base = _base_score_from_text(sig_text)
                    score = _apply_context_adjustments(base, data or {}, context or {})
                    score = score + int(round((prob - 0.5) * 40))
                elif is_sell:
                    base = _base_score_from_text(sig_text)
                    score = _apply_context_adjustments(base, data or {}, context or {})
                    score = score - int(round((prob - 0.5) * 40))
                else:
                    score = 50
                score = max(0, min(100, int(score)))

                # Use the blended score to keep sizing aligned with displayed signal strength.
                try:
                    base_pos = position_size_from_score(int(score))
                except Exception:
                    base_pos = position_size_from_score(int(score))
            except Exception:
                base = _base_score_from_text(sig_text)
                score = _apply_context_adjustments(base, data or {}, context or {})
        else:
            base = _base_score_from_text(sig_text)
            score = _apply_context_adjustments(base, data or {}, context or {})
        action = action_from_text if action_from_text in ("BUY", "SELL") else map_score_to_action(score)
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
    regime_cfg = load_runtime_regime_config()
    regime_config_sha256 = compute_regime_config_sha256(regime_cfg)
    regime_snapshot = coerce_regime_snapshot(
        merged.get("regime_snapshot") if isinstance(merged, dict) else None,
        fallback_regime=regime,
        fallback_confidence=_safe_float(merged.get("regime_confidence"), default=0.0),
        config_sha256=regime_config_sha256,
    ).to_dict()

    # ── Meta Model Confidence + Kelly Position Sizing ──────────────────────────
    meta_prob = None
    model_probability_up = None
    meta_expected_return = None
    meta_expected_drawdown = None
    meta_expected_hold_time = None
    meta_decision = {}
    kelly = None
    b_est = None
    meta_err = None
    gated = False

    opt_params = _load_optimized_params()
    signal_cutoff = opt_params.get("signal_cutoff", 0.0)
    kelly_multiplier = opt_params.get("kelly_multiplier", 1.0)

    risk_metrics = _get_cached_risk_metrics()
    risk_multiplier = risk_metrics.get("risk_multiplier", 0.0)
    risk_blocked = risk_metrics.get("blocked", True)
    risk_status = str(risk_metrics.get("status") or ("HEALTHY" if not risk_blocked else "UNAVAILABLE")).upper()
    risk_failure_reason = risk_metrics.get("failure_reason")

    try:
        if disable_ml:
            raise RuntimeError('ml_disabled')
        if meta_prediction is None:
            raise RuntimeError("inference_owner_required")
        meta = dict(meta_prediction)
        if isinstance(meta, dict) and meta.get('probability') is not None:
            model_win_probability = max(0.0, min(1.0, float(meta['probability'])))
            # CONTRACT: meta['probability'] = P(win | proposed_trade), side-agnostic.
            # DO NOT invert for SELL. P(win) for a SELL trade already reflects the
            # probability that the trade wins (i.e. price falls). The directional
            # posterior flip is applied later in MetaDecisionEngine.decide() via
            # side_probability → posterior = 1 - side_probability for SELL.
            #
            # The previous code did `1.0 - model_probability_up` for SELL, which
            # mapped P(win) → P(loss), selecting the worst SELL candidates.
            # This was an unambiguous defect. See R1 proof: probability_contract.md.
            model_probability_up = model_win_probability  # legacy alias — do not use for new code
            meta_prob = model_win_probability
            meta_expected_return = meta.get("expected_return")
            meta_expected_drawdown = meta.get("expected_drawdown")
            meta_expected_hold_time = meta.get("expected_hold_time")
            meta_decision = {
                **meta,
                "model_probability_up": model_probability_up,
                "probability_semantics": "P(win_given_proposed_trade)",
                "execution_probability": meta_prob,
                "execution_probability_semantics": "P(win_given_proposed_trade)",
                "proposed_action": action,
            }
            
            # Apply optimized signal probability cutoff
            if meta_prob < signal_cutoff:
                action = "NEUTRAL"
                reason += f" | Optuna Reject: win prob {meta_prob:.2f} < signal_cutoff {signal_cutoff:.2f}"
                
            # Tính Kelly sizing dựa trên meta_prob
            strategy = (data.get('strategy') or data.get('subtype')) if isinstance(data, dict) else None
            b_est = _estimate_b(strategy or '', regime or '')
            kelly_raw = compute_kelly_fraction(meta_prob, b_est) if _use_kelly() else 0.0
            
            # Apply dynamic sizing scale and risk reduction
            kelly_raw = kelly_raw * kelly_multiplier * risk_multiplier
            
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

        # (Hard-reject gating was moved below to run outside the ML try/except)
    except Exception as e:
        if str(e) not in ('ml_disabled', 'inference_owner_required'):
            import traceback
            traceback.print_exc()
        meta_prob = None
        meta_err = str(e)

    # Hard reject gate via environment variable: when set, force NEUTRAL if meta_prob < threshold
    try:
        import os as _os
        _hard = _os.getenv('META_HARD_REJECT_THRESHOLD', '').strip()
        if _hard:
            try:
                _hard_val = float(_hard)
                if meta_prob is not None and meta_prob < _hard_val:
                    action = "NEUTRAL"
                    reason += f" | HardReject: meta_prob {meta_prob:.2f} < {_hard_val:.2f}"
                    gated = True
            except Exception:
                pass
    except Exception:
        pass

    # Apply Drawdown Risk management block
    if risk_blocked:
        action = "NEUTRAL"
        risk_reason = risk_failure_reason or (
            f"drawdown_{risk_metrics.get('drawdown_pct')}pct_exceeds_limit"
        )
        reason += f" | Risk Block: {risk_reason}"
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

    # ── MTF Confluence Filter (Layer 8) ──────────────────────────────────────────
    # Phạt tín hiệu đi ngược chiều TF lớn hơn, thưởng khi xác nhận đa khung.
    # tf_X_bull: +1=BULL, 0=NEUTRAL, -1=BEAR (EMA cross + Chandelier + SMA50 trên TF đó)
    try:
        if is_buy or is_sell:
            signal_dir = 1 if is_buy else -1
            _mtf_weights = [
                (int(merged.get("tf_1h_bull", 0) or 0), 8, 15),   # (tf_val, bonus, penalty)
                (int(merged.get("tf_4h_bull", 0) or 0), 5, 10),
                (int(merged.get("tf_1d_bull", 0) or 0), 5, 5),
            ]
            _mtf_score_delta = 0
            for tf_val, bonus_mag, penalty_mag in _mtf_weights:
                align = tf_val * signal_dir
                if align > 0:
                    _mtf_score_delta += signal_dir * bonus_mag
                elif align < 0:
                    _mtf_score_delta -= signal_dir * penalty_mag
            if _mtf_score_delta != 0:
                score = max(0, min(100, score + _mtf_score_delta))
                _tf_vals = [t[0] for t in _mtf_weights]
                reason += f" | MTF 1h={_tf_vals[0]:+d} 4h={_tf_vals[1]:+d} 1d={_tf_vals[2]:+d} adj={_mtf_score_delta:+d}"
    except Exception:
        pass
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

    proposed_regime_multiplier = 1.0
    applied_regime_multiplier = 1.0
    regime_sizing_effect_enabled = regime_position_sizing_enabled()
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
            proposed_regime_multiplier = float(mult)
            applied_regime_multiplier = proposed_regime_multiplier if regime_sizing_effect_enabled else 1.0
            pos_size = round(max(0.25, min(1.0, pos_size * applied_regime_multiplier)), 2)
        except Exception:
            proposed_regime_multiplier = 1.0
            applied_regime_multiplier = 1.0

    # ── Display fields (human-readable) ─────────────────────────────────────────
    display_score, display_label = map_score_to_display(int(score), action)
    strength = signal_strength_from_score(action, score)

    # Entry-time meta_prob logging for diagnostics
    try:
        _entry_ts = datetime.now(timezone.utc).isoformat()
        _entry = {
            "ts": _entry_ts,
            "symbol": merged.get("symbol") or merged.get("pair") or merged.get("market") or merged.get("ticker") or None,
            "action": action,
            "score": int(score),
            "meta_prob": meta_prob,
            "model_probability_up": model_probability_up,
            "meta_expected_return": meta_expected_return,
            "meta_expected_drawdown": meta_expected_drawdown,
            "meta_expected_hold_time": meta_expected_hold_time,
            "meta_error": meta_err,
            "meta_decision": meta_decision.get("action") if isinstance(meta_decision, dict) else None,
            "posterior_probability": meta_decision.get("posterior_probability") if isinstance(meta_decision, dict) else None,
            "kelly": kelly,
            "position_size": pos_size,
            "gated": gated,
            "reason": reason,
        }
        _append_meta_prob_entry(_entry)
    except Exception:
        pass

    return {
        "action": action,
        "score": int(score),               # internal 0-100 (0=strong sell, 100=strong buy)
        "strength": strength,              # side-agnostic 0-100 strength for trade gates
        "display_score": display_score,    # 0-100 strength in direction of action
        "display_label": display_label,    # e.g. "BUY 80%" / "SELL 75%" / "NEUTRAL"
        "confidence": conf,
        "position_size": pos_size,
        "raw_text": sig_text,
        "gated": gated,
        "meta_confidence": meta_prob,
        "meta_probability": meta_prob,
        "meta_probability_semantics": "P(win_given_proposed_trade)",
        "model_probability_up": model_probability_up,
        "model_probability_semantics": "P(up)",
        "meta_confidence_pct": int(round(meta_prob * 100)) if meta_prob is not None else None,
        "meta_expected_return": meta_expected_return,
        "meta_expected_drawdown": meta_expected_drawdown,
        "meta_expected_hold_time": meta_expected_hold_time,
        "meta_decision": meta_decision,
        "signal_id": meta_decision.get("signal_id"),
        "prediction_id": meta_decision.get("prediction_id"),
        "inference_contract_version": meta_decision.get(
            "inference_contract_version"
        ),
        "model_family": meta_decision.get("model_family"),
        "artifact_version": meta_decision.get("artifact_version"),
        "artifact_hash": meta_decision.get("artifact_hash")
        or meta_decision.get("artifact_sha256"),
        "feature_schema_hash": meta_decision.get("feature_schema_hash"),
        "prediction": meta_decision.get(
            "prediction", meta_decision.get("probability")
        ),
        "artifact_metadata_consistent": meta_decision.get(
            "artifact_metadata_consistent"
        ),
        "model_version": meta_decision.get("model_version"),
        "artifact_sha256": meta_decision.get("artifact_sha256"),
        "model_artifact_sha256": meta_decision.get("artifact_sha256"),
        "feature_schema_version": meta_decision.get("feature_schema_version"),
        "deployment_id": meta_decision.get("deployment_id"),
        "paper_run_id": meta_decision.get("paper_run_id"),
        "cycle_id": meta_decision.get("cycle_id"),
        "decision_context": meta_decision.get("decision_context"),
        "caller_context": meta_decision.get("caller_context"),
        "feature_hash": meta_decision.get("feature_hash"),
        "kelly_fraction": kelly,
        "b_estimate": b_est,
        "meta_error": meta_err,
        "risk_status": risk_status,
        "risk_failure_reason": risk_failure_reason,
        "risk_blocked": bool(risk_blocked),
        "risk_multiplier": float(risk_multiplier),
        "position_sizing_method": sizing_method,
        "volatility_multiplier": round(vol_mult, 4) if vol_mult is not None else 1.0,
        "std_dev_pct": round(std_dev_pct, 4) if std_dev_pct is not None else None,
        "regime": regime_snapshot["regime_id"],
        "regime_confidence": regime_snapshot["confidence"],
        "regime_snapshot": regime_snapshot,
        "regime_config_sha256": regime_config_sha256,
        "proposed_regime_multiplier": round(float(proposed_regime_multiplier), 4),
        "applied_regime_multiplier": round(float(applied_regime_multiplier), 4),
        **regime_effect_metadata(regime_sizing_effect_enabled),
    }


def evaluate_signal_score(ana: Dict, *, meta_prediction: Dict | None = None) -> Dict:
    """Evaluate or re-evaluate signal score for an analysis dict."""
    sig_text = ana.get("signal", "")
    htf_trend = ana.get("htf_trend", None)
    # Use the analysis dict itself as both data and context, as it contains all indicator metrics.
    return score_signal(
        sig_text,
        ana,
        ana,
        htf_trend=htf_trend,
        meta_prediction=meta_prediction,
    )


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
