#!/usr/bin/env python3
"""
Simulate and Calibrate Meta Model on April 2026 Data
===================================================
1. Load April candles for all coins (15m, 1h, 4h, 1d) with warmups.
2. Run historical rolling window backtest on 15m.
3. Align higher-timeframe candles dynamically to calculate htf_trend.
4. Extract features exactly via build_meta_features().
5. Track trade outcome (WIN / LOSS).
6. Train and Calibrate RandomForestClassifier (Platt scaling).
7. Save calibrated model to logs/meta_model.joblib.
8. Output before/after calibration report.
"""
import sys
import os
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV

# Force stdout to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ['DISABLE_KELLY'] = '1'

# Set paths
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from btc_scraper.config import COINS
from btc_scraper.analysis import analyze_market, analyze_all_market
from btc_scraper.meta_model import load_model, MODEL_OUT, METRIC_OUT, FEATURE_IMPORTANCE_OUT
from btc_scraper.feature_extractor import build_meta_features, FEATURE_SCHEMA

import btc_scraper.sentiment
def mock_get_market_sentiment():
    return {
        "score": -0.76,
        "label": "Extreme Fear",
        "raw_value": 12,
        "timestamp": 1718000000,
        "update_time_human": "2026-06-12 00:00:00"
    }
btc_scraper.sentiment.get_market_sentiment = mock_get_market_sentiment
btc_scraper.analysis.get_market_sentiment = mock_get_market_sentiment

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Configs
WARMUP_CANDLES = 220
BUY_MIN_SCORE = 51
SELL_MAX_SCORE = 49

INTERVALS = {
    "1h":  {"minutes": 60},
    "4h":  {"minutes": 240},
    "1d":  {"minutes": 1440},
}

def load_candles_raw(coin: str, interval: str, month: str) -> list[dict]:
    path = DATA_DIR / f"{month}_{coin}_{interval}.csv"
    if not path.exists():
        return []
    candles = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row["time"], "%Y-%m-%d %H:%M")
            candles.append({
                "time": row["time"],
                "time_dt": dt,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "is_warmup": int(row.get("is_warmup", 0))
            })
    candles.sort(key=lambda x: x["time_dt"])
    return candles

def load_all_timeframe_candles(coin: str, months: list[str]) -> tuple[list[dict], dict]:
    candles_15m_all = []
    for m in months:
        candles_15m_all.extend(load_candles_raw(coin, "15m", m))
    
    # De-duplicate 15m candles
    seen_15m = set()
    candles_15m = []
    for c in candles_15m_all:
        if c["time"] not in seen_15m:
            seen_15m.add(c["time"])
            candles_15m.append(c)
    candles_15m.sort(key=lambda x: x["time_dt"])
    
    mtf_candles = {}
    for tf in ["1h", "4h", "1d"]:
        tf_all = []
        for m in months:
            tf_all.extend(load_candles_raw(coin, tf, m))
            
        seen_tf = set()
        tf_dedup = []
        for c in tf_all:
            if c["time"] not in seen_tf:
                seen_tf.add(c["time"])
                tf_dedup.append(c)
        tf_dedup.sort(key=lambda x: x["time_dt"])
        mtf_candles[tf] = tf_dedup
        
    return candles_15m, mtf_candles

def get_closed_candles(htf_candles: list[dict], t_15m_dt: datetime, duration_minutes: int, limit: int = 220) -> list[dict]:
    cutoff = t_15m_dt - timedelta(minutes=duration_minutes)
    closed = [c for c in htf_candles if c["time_dt"] <= cutoff]
    return closed[-limit:]

def _classify_mtf_signal(signal: str) -> str:
    sig = str(signal or "").upper()
    if "STRONG BUY" in sig or "BUY" in sig or "BULL" in sig:
        return "BULL"
    if "STRONG SELL" in sig or "SELL" in sig or "BEAR" in sig:
        return "BEAR"
    return "NEUTRAL"

def _summarize_htf_trend(mtf_data: dict) -> str:
    if not mtf_data:
        return "NEUTRAL"
    counts = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
    for tf in ["1d", "4h", "1h"]:
        info = mtf_data.get(tf)
        if not info:
            continue
        sig = info.get("signal", "")
        counts[_classify_mtf_signal(sig)] += 1
        
    if counts["BULL"] >= 2 and counts["BEAR"] == 0:
        return "BULLISH"
    if counts["BEAR"] >= 2 and counts["BULL"] == 0:
        return "BEARISH"
    if counts["BULL"] > counts["BEAR"]:
        return "BULLISH-MIXED"
    if counts["BEAR"] > counts["BULL"]:
        return "BEARISH-MIXED"
    return "NEUTRAL"

def backtest_coin_meta(coin: str, candles_15m: list[dict], mtf_candles: dict) -> list[dict]:
    n = len(candles_15m)
    if n < WARMUP_CANDLES + 2:
        return []
        
    all_ana = analyze_all_market(candles_15m)
    ana_by_time = {x["time"]: x for x in all_ana}
    
    trades = []
    position = None
    
    for i in range(WARMUP_CANDLES, n):
        candle = candles_15m[i]
        
        # skip warmup candles for entry signals
        if candle["is_warmup"]:
            continue
            
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]
        
        # Check closed positions
        if position is not None:
            sl = position["sl"]
            tp1 = position["tp1"]
            direction = position["direction"]
            entry = position["entry"]
            
            hit_sl = False
            hit_tp1 = False
            
            if direction == "LONG":
                hit_sl = low <= sl
                hit_tp1 = high >= tp1
            else: # SHORT
                hit_sl = high >= sl
                hit_tp1 = low <= tp1
                
            if hit_sl or hit_tp1:
                exit_price = sl if hit_sl else tp1
                result = "LOSS" if hit_sl else "WIN"
                
                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100
                    
                rec = position["record"]
                rec["actual_result"] = result
                rec["actual_pnl_pct"] = round(pnl_pct, 4)
                rec["closed_at"] = candle["time"]
                trades.append(rec)
                
                position = None
                
        # Find new signals
        if position is None:
            ana = ana_by_time.get(candle["time"])
            if ana is None:
                continue
                
            signal = ana.get("signal", "")
            s_upper = signal.upper()
            if "BUY" not in s_upper and "SELL" not in s_upper:
                continue
            if "NEUTRAL" in s_upper or "WEAK" in s_upper:
                continue
                
            sig_score_info = ana.get("signal_score", {}) or {}
            score = int(sig_score_info.get("score") or 0)
            action = sig_score_info.get("action", "NEUTRAL")
            
            if action == "BUY" and score < BUY_MIN_SCORE:
                continue
            if action == "SELL" and score > SELL_MAX_SCORE:
                continue
            if action == "NEUTRAL":
                continue
                
            tp_sl = ana.get("tp_sl", {})
            sl = tp_sl.get("sl", 0.0)
            tp1 = tp_sl.get("tp1", 0.0)
            if sl <= 0 or tp1 <= 0:
                continue
                
            direction = "LONG" if "BUY" in s_upper else "SHORT"
            if direction == "LONG" and (sl >= close or tp1 <= close):
                continue
            if direction == "SHORT" and (sl <= close or tp1 >= close):
                continue
                
            # Align higher timeframes and run analysis
            mtf_analysis = {}
            for tf, tf_candles in mtf_candles.items():
                closed = get_closed_candles(tf_candles, candle["time_dt"], duration_minutes=INTERVALS[tf]["minutes"])
                if len(closed) >= 220:
                    try:
                        mtf_analysis[tf] = analyze_market(closed)
                    except Exception:
                        mtf_analysis[tf] = {}
                else:
                    mtf_analysis[tf] = {}
                    
            htf_trend = _summarize_htf_trend(mtf_analysis)
            
            # Prepare data context for build_meta_features
            ana_copy = dict(ana)
            ana_copy["score"] = score
            ana_copy["signal"] = signal
            
            # Extracted features
            feat = build_meta_features(ana_copy, htf_trend)
            
            # Setup record
            record = {
                "prediction_id": f"{coin}_{int(candle['time_dt'].timestamp())}_{i}",
                "symbol": f"{coin}USDT",
                "timestamp": candle["time_dt"].timestamp(),
                "timestamp_str": candle["time"],
                "signal": signal,
                "signal_score": score,
                "regime": ana.get("market_regime", "UNKNOWN"),
                "htf_trend": htf_trend,
                "position_id": f"SIM_{coin}_{i}",
                "actual_result": None,
                "actual_pnl_pct": None,
                "closed_at": None,
                "features": feat,
                "direction": direction,
                "entry": close,
                "sl": sl,
                "tp1": tp1,
            }
            
            position = {
                "entry": close,
                "sl": sl,
                "tp1": tp1,
                "direction": direction,
                "record": record
            }
            
    return trades

def compute_calibration_buckets(probs, actual_results, min_samples=3):
    buckets = {
        "0.0-0.4": [],
        "0.4-0.6": [],
        "0.6-0.7": [],
        "0.7-0.8": [],
        "0.8-1.0": [],
    }
    
    for prob, res in zip(probs, actual_results):
        label = 1 if res == "WIN" else 0
        if prob < 0.4:
            buckets["0.0-0.4"].append(label)
        elif prob < 0.6:
            buckets["0.4-0.6"].append(label)
        elif prob < 0.7:
            buckets["0.6-0.7"].append(label)
        elif prob < 0.8:
            buckets["0.7-0.8"].append(label)
        else:
            buckets["0.8-1.0"].append(label)
            
    analysis = {}
    for bucket, labels in buckets.items():
        if len(labels) < min_samples:
            analysis[bucket] = {
                "count": len(labels),
                "actual_wr": None,
                "predicted_wr": None,
                "calibration_error": None,
                "calibrated": False,
            }
            continue
            
        wins = sum(labels)
        actual_wr = wins / len(labels) * 100
        
        parts = bucket.split("-")
        lo, hi = float(parts[0]), float(parts[1])
        predicted_wr = (lo + hi) / 2 * 100
        
        error = actual_wr - predicted_wr
        calibrated = abs(error) <= 10.0
        
        analysis[bucket] = {
            "count": len(labels),
            "wins": wins,
            "losses": len(labels) - wins,
            "actual_wr": round(actual_wr, 1),
            "predicted_wr": round(predicted_wr, 1),
            "calibration_error": round(error, 1),
            "calibrated": calibrated,
        }
    return analysis

def print_calibration_table(title: str, analysis: dict):
    print(f"\n📊 {title}")
    print(f"   {'Bucket':<12} {'Count':<8} {'Predicted WR':<15} {'Actual WR':<12} {'Error':<10} {'OK?'}")
    print("   " + "-" * 65)
    for bucket, data in analysis.items():
        if data.get("actual_wr") is not None:
            ok = "✅" if data["calibrated"] else "❌"
            print(f"   {bucket:<12} {data['count']:<8} {data['predicted_wr']:<15.1f} {data['actual_wr']:<12.1f} {data['calibration_error']:+.1f}%     {ok}")
        else:
            print(f"   {bucket:<12} {data['count']:<8} {'N/A':<15} {'N/A':<12} {'N/A':<10} ⏳")
    print()

def main():
    print("=" * 65)
    print("  SIMULATING MARCH, APRIL & MAY 2026 TRADES WITH HTF ALIGNMENT & CALIBRATION")
    print("=" * 65)
    
    all_trades = []
    
    for coin in COINS:
        print(f"  [+] Loading & simulating {coin}...")
        candles_15m, mtf_candles = load_all_timeframe_candles(coin, ["march", "april", "may"])
        
        if not candles_15m:
            print(f"      [!] Missing 15m data for {coin}, skipping.")
            continue
            
        coin_trades = backtest_coin_meta(coin, candles_15m, mtf_candles)
        print(f"      Generated {len(coin_trades)} closed trade records.")
        all_trades.extend(coin_trades)
        
    print(f"\n  [OK] Total simulated trade records: {len(all_trades)}")
    
    if not all_trades:
        print("❌ No trade records found. Cannot perform calibration.")
        return
        
    # Build dataset X, y
    X = []
    y = []
    for r in all_trades:
        feat = r["features"]
        row = [float(feat.get(k, 0.0)) for k in FEATURE_SCHEMA]
        X.append(row)
        label = 1 if r["actual_result"] == "WIN" else 0
        y.append(label)
        
    X = np.array(X)
    y = np.array(y)
    
    print(f"  Dataset: {len(y)} samples | WIN={y.sum()} ({y.sum()/len(y)*100:.1f}%) | LOSS={len(y)-y.sum()}")
    
    # 1. Evaluate Current (Old) Model Calibration
    old_probs = []
    old_obj = load_model()
    if old_obj is not None:
        old_clf = old_obj.get("model") if isinstance(old_obj, dict) else old_obj
        old_features = old_obj.get("features", FEATURE_SCHEMA) if isinstance(old_obj, dict) else FEATURE_SCHEMA
        
        for r in all_trades:
            feat = r["features"]
            row = [float(feat.get(k, 0.0)) for k in old_features]
            try:
                prob = float(old_clf.predict_proba([row])[0, 1])
            except Exception:
                prob = 0.5
            old_probs.append(prob)
        
        old_analysis = compute_calibration_buckets(old_probs, [r["actual_result"] for r in all_trades])
        print_calibration_table("OLD MODEL CALIBRATION", old_analysis)
    else:
        print("  [!] Old model not found. Cannot evaluate old model calibration.")
        
    # 2. Train and Calibrate New Model (Sigmoid vs Isotonic comparison)
    print("  [+] Training new RandomForest models and comparing calibration methods...")
    rf_base = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    
    clf_sigmoid = CalibratedClassifierCV(rf_base, method="sigmoid", cv=5)
    clf_sigmoid.fit(X, y)
    probs_sigmoid = clf_sigmoid.predict_proba(X)[:, 1]
    analysis_sigmoid = compute_calibration_buckets(probs_sigmoid, [r["actual_result"] for r in all_trades])
    
    clf_isotonic = CalibratedClassifierCV(rf_base, method="isotonic", cv=5)
    clf_isotonic.fit(X, y)
    probs_isotonic = clf_isotonic.predict_proba(X)[:, 1]
    analysis_isotonic = compute_calibration_buckets(probs_isotonic, [r["actual_result"] for r in all_trades])
    
    def get_avg_error(analysis):
        errors = []
        for bucket, data in analysis.items():
            if data.get("calibration_error") is not None:
                errors.append(abs(data["calibration_error"]))
        return float(np.mean(errors)) if errors else 100.0
        
    err_sigmoid = get_avg_error(analysis_sigmoid)
    err_isotonic = get_avg_error(analysis_isotonic)
    
    print(f"  -> Sigmoid Mean Absolute Calibration Error: {err_sigmoid:.2f}%")
    print(f"  -> Isotonic Mean Absolute Calibration Error: {err_isotonic:.2f}%")
    
    if err_isotonic < err_sigmoid:
        print("  [Selected] ISOTONIC calibration selected due to lower calibration error.")
        new_clf = clf_isotonic
        new_analysis = analysis_isotonic
        new_probs = probs_isotonic
        cal_method = "isotonic"
    else:
        print("  [Selected] SIGMOID calibration selected due to lower calibration error.")
        new_clf = clf_sigmoid
        new_analysis = analysis_sigmoid
        new_probs = probs_sigmoid
        cal_method = "sigmoid"
        
    print_calibration_table("NEW CALIBRATED MODEL CALIBRATION", new_analysis)
    
    # 3. Save Model Bundle
    # Backup old model
    if MODEL_OUT.exists():
        backup_path = LOGS_DIR / "meta_model_backup.joblib"
        print(f"  [+] Backing up current model to {backup_path}")
        joblib.dump(old_obj, backup_path)
        
    print(f"  [+] Saving new calibrated model to {MODEL_OUT}")
    model_bundle = {
        "model": new_clf,
        "features": FEATURE_SCHEMA,
        "version": "v1.0-calibrated-may",
        "n_samples": int(len(y)),
        "calibrated": True,
    }
    joblib.dump(model_bundle, MODEL_OUT)

    # Fit base model on full dataset to extract feature importances
    try:
        rf_base.fit(X, y)
        if hasattr(rf_base, "feature_importances_"):
            importances = rf_base.feature_importances_
            feature_importance = dict(
                sorted(
                    zip(FEATURE_SCHEMA, importances.tolist()),
                    key=lambda x: x[1],
                    reverse=True,
                )
            )
            importance_path = LOGS_DIR / "meta_feature_importance.json"
            with open(importance_path, "w", encoding="utf-8") as f:
                json.dump(feature_importance, f, indent=2, ensure_ascii=False)
            print(f"  [+] Saved feature importance to {importance_path}")
    except Exception as e:
        print(f"  [Warning] Failed to save feature importance: {e}")
    
    # Save metrics
    metrics = {
        "version": "v1.0-calibrated-may",
        "n_samples": int(len(y)),
        "n_features": len(FEATURE_SCHEMA),
        "features": FEATURE_SCHEMA,
        "calibrated": True,
        "label_dist": {"WIN": int(y.sum()), "LOSS": int(len(y) - y.sum())},
        "calibration_buckets": new_analysis
    }
    with open(METRIC_OUT, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"  [+] Saved calibration metrics to {METRIC_OUT}")
    
    # Save simulated predictions to shadow log so that we can inspect it or run other reports
    shadow_records = []
    for r, new_prob in zip(all_trades, new_probs):
        r_copy = dict(r)
        r_copy.pop("features", None) # remove raw feature dict to keep shadow log clean
        r_copy["meta_prob"] = round(float(new_prob), 4)
        shadow_records.append(r_copy)
        
    shadow_log_path = LOGS_DIR / "shadow_predictions.json"
    with open(shadow_log_path, "w", encoding="utf-8") as f:
        json.dump(shadow_records, f, indent=2, ensure_ascii=False)
    print(f"  [+] Saved simulated shadow predictions to {shadow_log_path}")
    print("=" * 65)
    print("  CALIBRATION PROCESS COMPLETED SUCCESSFULLY!")
    print("=" * 65)

if __name__ == "__main__":
    main()
