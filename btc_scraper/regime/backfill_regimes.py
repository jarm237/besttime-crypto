"""
Backfill regime field into logs/adaptive_signals.json using available indicators
in each record. Writes a backup and updates file in-place.
"""
import json
import os
from pathlib import Path
from btc_scraper.core.paths import build_logs_path
from btc_scraper.regime.config import compute_regime_config_sha256, load_regime_config

BASE = os.path.dirname(__file__)
LOG = str(build_logs_path("adaptive_signals.json"))
BACKUP = str(build_logs_path("adaptive_signals_backup.json"))


def load_cfg():
    return load_regime_config()


def determine_regime_from_record(r, cfg):
    # pick adx from preferred timeframes
    adx = None
    for k in ("adx_1h", "adx_15m", "adx_4h", "adx_1d"):
        if k in r and r[k] is not None:
            adx = float(r[k])
            break
    if adx is None:
        adx = float(r.get("adx", 0.0) or 0.0)

    # pick atr_pct if present
    atr_pct = None
    for k in ("atr_pct_1h", "atr_pct_15m", "atr_pct_4h", "atr_pct_1d"):
        if k in r and r[k] is not None and r[k] != 0:
            atr_pct = float(r[k])
            break
    # fall back to atr_/close if available
    if atr_pct is None:
        # try atr_1h and approximate with avg price if present (no price available) -> fallback 0
        atr_pct = float(r.get("atr_pct", 0.0) or 0.0)

    # trend alignment heuristics
    ema21 = None
    sma50 = None
    sma200 = None
    # try trend flags
    try:
        ema21_trend = r.get("ema_trend_1h") or r.get("ema_trend_15m") or r.get("ema_trend_4h") or 0
    except Exception:
        ema21_trend = 0
    try:
        above_sma200 = r.get("above_sma200_1h") or r.get("above_sma200_15m") or r.get("above_sma200_4h") or 0
    except Exception:
        above_sma200 = 0
    try:
        ema21 = r.get("ema21") or None
    except Exception:
        ema21 = None

    adx_thresh = float(cfg.get("adx_threshold", 25.0))
    atr_thresh = float(cfg.get("atr_pct_threshold", 4.0))
    conf_cfg = cfg.get("confidence", {})

    # High volatility override
    if atr_pct and atr_pct > atr_thresh:
        regime = "HIGH_VOLATILITY"
        confidence = min(conf_cfg.get("max", 0.98), 0.5 + (atr_pct - atr_thresh) / (atr_thresh * 2 + 1e-9))
        return {"regime": regime, "confidence": round(float(confidence), 3), "adx": round(float(adx or 0.0), 2), "atr_pct": round(float(atr_pct or 0.0), 3)}

    # Use ADX and trend flags
    if adx and adx > adx_thresh:
        # attempt polarity from is_bull/is_bear flags
        is_bull = r.get("is_bull_1h") or r.get("is_bull_4h") or r.get("is_bull_1d") or 0
        is_bear = r.get("is_bear_1h") or r.get("is_bear_4h") or r.get("is_bear_1d") or 0
        if is_bull:
            regime = "TRENDING_BULL"
        elif is_bear:
            regime = "TRENDING_BEAR"
        else:
            # use ema trend flag as fallback
            regime = "TRENDING_BULL" if ema21_trend == 1 else "TRENDING_BEAR" if ema21_trend == -1 else "RANGING"
    else:
        regime = "RANGING"

    # confidence estimate
    base = float(conf_cfg.get("base", 0.2))
    adx_weight = float(conf_cfg.get("adx_weight", 0.5))
    trend_weight = float(conf_cfg.get("trend_weight", 0.3))
    max_conf = float(conf_cfg.get("max", 0.98))
    adx_component = max(0.0, (float(adx or 0.0) - adx_thresh) / max(1.0, adx_thresh))
    trend_align = 1.0 if ((regime == "TRENDING_BULL" and ema21_trend == 1) or (regime == "TRENDING_BEAR" and ema21_trend == -1)) else 0.0
    confidence = base + adx_weight * adx_component + trend_weight * trend_align
    confidence = float(min(max_conf, max(0.0, confidence)))

    return {"regime": regime, "confidence": round(float(confidence), 3), "adx": round(float(adx or 0.0), 2), "atr_pct": round(float(atr_pct or 0.0), 3)}


def main():
    if not os.path.exists(LOG):
        print("No adaptive log at", LOG)
        return
    with open(LOG, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfg = load_cfg()
    updated = []
    for r in data:
        if r.get("regime"):
            updated.append(r)
            continue
        info = determine_regime_from_record(r, cfg)
        r["regime"] = info.get("regime")
        r["regime_confidence"] = info.get("confidence")
        r["backfilled"] = True
        r["evidence_origin"] = "POINT_IN_TIME_BACKFILL"
        r["backfill_config_sha256"] = compute_regime_config_sha256(cfg)
        r["original_regime_missing"] = True
        updated.append(r)

    # backup
    try:
        if not os.path.exists(BACKUP):
            with open(BACKUP, "w", encoding="utf-8") as bf:
                json.dump(data, bf, indent=2)
    except Exception:
        pass

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    print("Backfilled regimes into", LOG)


if __name__ == "__main__":
    main()
