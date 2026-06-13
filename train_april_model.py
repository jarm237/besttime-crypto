"""
Train Adaptive Model từ dữ liệu April 2026 (hoặc bất kỳ tháng nào có CSV)
==========================================================================
Luồng:
  1. Load CSV nến April (15m + 1h + 4h + 1d) từ fetch_april_data.py
  2. Chạy analyze_market() rolling window trên 15m → tạo lệnh ảo (BUY/SELL)
  3. Gắn MTF context tại từng thời điểm vào lệnh (KHÔNG dùng toàn bộ series)
  4. Đóng lệnh khi hit SL hoặc TP1 → label WIN/LOSS
  5. Extract features thống nhất qua build_meta_features() (FEATURE_SCHEMA 14 fields)
  6. Split 80/20 theo thời gian → train CV trên 80%, holdout trên 20%
  7. Dùng TimeSeriesSplit (không shuffle) thay vì StratifiedKFold(shuffle=True)
  8. Train RandomForestClassifier
  9. Lưu model → logs/adaptive_model.joblib (schema = FEATURE_SCHEMA)
  10. In báo cáo: CV ROC-AUC, holdout ROC-AUC, feature importance, unclosed trades

Cách chạy:
  python train_april_model.py

Yêu cầu:
  pip install scikit-learn joblib numpy
  (đã chạy fetch_april_data.py trước)
"""

import sys, os, csv, json
from datetime import datetime, timedelta, timezone

# Force stdout to UTF-8 to support Vietnamese characters in console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))

# Disable external side-effects before importing btc_scraper modules
os.environ['DISABLE_KELLY'] = '1'

import btc_scraper.signal_score
def mock_load_adaptive_model():
    return None
btc_scraper.signal_score._load_adaptive_model = mock_load_adaptive_model

import btc_scraper.sentiment
import btc_scraper.analysis as _btc_analysis
def mock_get_market_sentiment():
    return {
        "score": -0.76,
        "label": "Extreme Fear",
        "raw_value": 12,
        "timestamp": 1718000000,
        "update_time_human": "2026-06-12 00:00:00"
    }
btc_scraper.sentiment.get_market_sentiment = mock_get_market_sentiment
_btc_analysis.get_market_sentiment = mock_get_market_sentiment

from btc_scraper.analysis import analyze_market, analyze_all_market
from btc_scraper.config import COINS
from btc_scraper.feature_extractor import build_meta_features, FEATURE_SCHEMA

# ─── Config ──────────────────────────────────────────────────────────────────
DATA_DIR      = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR      = os.path.join(os.path.dirname(__file__), "logs")
MODEL_PATH    = os.path.join(LOGS_DIR, "adaptive_model.joblib")
REPORT_PATH   = os.path.join(LOGS_DIR, "train_report.json")

WARMUP_CANDLES = 220     # Nến warmup trước khi bắt đầu tạo signal
BUY_MIN_SCORE  = 51      # Chỉ train trên BUY signal MEDIUM+
SELL_MAX_SCORE = 49      # Chỉ train trên SELL signal thực sự

INTERVALS = {
    "1h":  {"minutes": 60},
    "4h":  {"minutes": 240},
    "1d":  {"minutes": 1440},
}

TRAIN_HOLDOUT_RATIO = 0.8  # 80% train, 20% holdout (by time order)

os.makedirs(LOGS_DIR, exist_ok=True)
# ─────────────────────────────────────────────────────────────────────────────


# ─── 1. LOAD CSV ─────────────────────────────────────────────────────────────

def load_candles_csv(coin: str, interval: str, month: str = "april") -> list[dict]:
    """
    Load nến từ CSV cho cụ thể coin, khung thời gian và tháng.
    """
    path = os.path.join(DATA_DIR, f"{month}_{coin}_{interval}.csv")
    if not os.path.exists(path):
        return []
        
    candles = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dt_str = row["time"]
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            except ValueError:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            candles.append({
                "time":      dt_str,
                "time_dt":   dt,
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     float(row["close"]),
                "volume":    float(row["volume"]),
                "is_warmup": int(row.get("is_warmup", 0)),
            })
    if candles:
        candles.sort(key=lambda x: x["time_dt"])
        return candles
    return []


# ─── 2. TIME-ALIGNED MTF HELPERS ─────────────────────────────────────────────
# Identical to calibrate_meta_model.py's approach — compute MTF using only
# candles BEFORE the signal timestamp to prevent lookahead bias.

def get_closed_candles(htf_candles: list[dict], t_dt: datetime, duration_minutes: int, limit: int = 220) -> list[dict]:
    """Return HTF candles that have fully closed before t_dt."""
    cutoff = t_dt - timedelta(minutes=duration_minutes)
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


# ─── 3. GENERATE LABELED TRADES ──────────────────────────────────────────────

def generate_labeled_trades(coin: str, candles_15m: list[dict], mtf_candles: dict) -> list[dict]:
    """
    Rolling window trên 15m candles, tạo lệnh ảo và gắn label WIN/LOSS.

    FIXES:
    - MTF features computed using ONLY past candles at each signal time (no leakage).
    - Features extracted via build_meta_features() → unified FEATURE_SCHEMA.
    - Unclosed trades are tracked and returned separately as 'unclosed'.
    """
    n = len(candles_15m)
    if n < WARMUP_CANDLES + 2:
        return []

    all_ana = analyze_all_market(candles_15m)
    ana_by_time = {x["time"]: x for x in all_ana}

    records  = []
    position = None
    n_unclosed_at_end = 0

    for i in range(WARMUP_CANDLES, n):
        candle = candles_15m[i]

        # skip warmup candles for entry signals
        if candle.get("is_warmup", 0):
            continue

        high  = candle["high"]
        low   = candle["low"]
        close = candle["close"]

        # ── Close open position ─────────────────────────────────────────────
        if position is not None:
            sl  = position["sl"]
            tp1 = position["tp1"]
            direction = position["direction"]
            entry = position["entry"]

            hit_sl  = (low <= sl)  if direction == "LONG" else (high >= sl)
            hit_tp1 = (high >= tp1) if direction == "LONG" else (low <= tp1)

            if hit_sl or hit_tp1:
                exit_price = sl if hit_sl else tp1
                result     = "LOSS" if hit_sl else "WIN"

                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100

                rec = dict(position["record"])
                rec["result"]    = result
                rec["pnl_pct"]   = round(pnl_pct, 4)
                rec["exit_time"] = candle["time"]
                records.append(rec)
                position = None

        # ── Find new signal ─────────────────────────────────────────────────
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
            score  = int(sig_score_info.get("score") or 0)
            action = sig_score_info.get("action", "NEUTRAL")

            if action == "BUY"  and score < BUY_MIN_SCORE:
                continue
            if action == "SELL" and score > SELL_MAX_SCORE:
                continue
            if action == "NEUTRAL":
                continue

            tp_sl = ana.get("tp_sl", {})
            sl    = tp_sl.get("sl",  0.0)
            tp1   = tp_sl.get("tp1", 0.0)
            rr1   = tp_sl.get("rr1", 0.0)

            if sl <= 0 or tp1 <= 0:
                continue

            direction = "LONG" if "BUY" in s_upper else "SHORT"
            if direction == "LONG"  and (sl >= close or tp1 <= close):
                continue
            if direction == "SHORT" and (sl <= close or tp1 >= close):
                continue

            # ── Time-aligned MTF: use only past candles at this timestamp ──
            t_dt = candle["time_dt"]
            mtf_analysis = {}
            for tf, tf_candles in mtf_candles.items():
                closed = get_closed_candles(tf_candles, t_dt, duration_minutes=INTERVALS[tf]["minutes"])
                if len(closed) >= 30:
                    try:
                        mtf_analysis[tf] = analyze_market(closed)
                    except Exception:
                        mtf_analysis[tf] = {}
                else:
                    mtf_analysis[tf] = {}

            htf_trend = _summarize_htf_trend(mtf_analysis)

            # ── Unified feature extraction via FEATURE_SCHEMA ──────────────
            ana_copy = dict(ana)
            ana_copy["score"] = score
            ana_copy["signal"] = signal
            feat = build_meta_features(ana_copy, htf_trend)

            record = {
                "coin":       coin,
                "direction":  direction,
                "entry":      close,
                "entry_time": candle["time"],
                "sl":         sl,
                "tp1":        tp1,
                "rr1":        rr1,
                "signal":     signal,
                "score":      score,
                "htf_trend":  htf_trend,
                # features is the FEATURE_SCHEMA vector (14 fields)
                "features":   feat,
                "result":     None,
                "pnl_pct":    0.0,
                "exit_time":  None,
            }

            position = {
                "entry":    close,
                "sl":       sl,
                "tp1":      tp1,
                "direction": direction,
                "record":   record,
            }

    # Count unclosed position at end of data
    if position is not None:
        n_unclosed_at_end += 1

    closed_records = [r for r in records if r["result"] is not None]

    # Attach summary metadata
    for r in closed_records:
        r["_n_unclosed_at_end"] = n_unclosed_at_end

    return closed_records, n_unclosed_at_end


# ─── 4. TRAIN MODEL ──────────────────────────────────────────────────────────

def train_model(all_records: list[dict]) -> dict:
    """
    Train RandomForest + time-aware cross-validation + temporal holdout evaluation.

    FIXES:
    - Uses TimeSeriesSplit (no shuffle) instead of StratifiedKFold(shuffle=True).
    - Temporal 80/20 split: train on first 80%, evaluate on last 20%.
    - Feature schema = FEATURE_SCHEMA (14 fields) from feature_extractor.py.
    """
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import TimeSeriesSplit, cross_val_score
        from sklearn.metrics import roc_auc_score, classification_report
        import joblib
    except ImportError as e:
        print(f"[Lỗi] Thiếu thư viện: {e}")
        print("Cài đặt: pip install scikit-learn joblib numpy")
        return {}

    if not all_records:
        print("[Lỗi] Không có records để train.")
        return {}

    # Sort records chronologically (critical for time-series split)
    all_records_sorted = sorted(all_records, key=lambda r: r["entry_time"])

    # Build X, y using unified FEATURE_SCHEMA
    feature_names = list(FEATURE_SCHEMA)  # 14 fixed fields
    X = np.array([[float(r["features"].get(k, 0.0)) for k in feature_names]
                  for r in all_records_sorted])
    y = np.array([1 if r["result"] == "WIN" else 0 for r in all_records_sorted])

    n_win  = int(y.sum())
    n_loss = len(y) - n_win
    print(f"\n  Dataset: {len(y)} samples | WIN={n_win} ({n_win/len(y)*100:.1f}%) | LOSS={n_loss}")

    # Temporal 80/20 split
    split_idx = int(len(X) * TRAIN_HOLDOUT_RATIO)
    X_train, X_holdout = X[:split_idx], X[split_idx:]
    y_train, y_holdout = y[:split_idx], y[split_idx:]

    print(f"  Temporal split: TRAIN={len(y_train)} | HOLDOUT={len(y_holdout)}")
    if len(y_holdout) < 10:
        print("  [Warning] Holdout period too small — skipping holdout evaluation.")
        X_train, y_train = X, y
        X_holdout, y_holdout = None, None

    # Model (no StandardScaler needed for RandomForest, but kept for compat)
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    # Time-series cross-validation (no shuffling!)
    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = cross_val_score(clf, X_train, y_train, cv=tscv, scoring="roc_auc")
    print(f"  Time-Series CV ROC-AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Train on full training set
    clf.fit(X_train, y_train)

    # Holdout evaluation
    holdout_auc = None
    holdout_report = None
    if X_holdout is not None and len(y_holdout) >= 10:
        try:
            y_prob = clf.predict_proba(X_holdout)[:, 1]
            holdout_auc = float(roc_auc_score(y_holdout, y_prob))
            preds_holdout = clf.predict(X_holdout)
            holdout_report = classification_report(
                y_holdout, preds_holdout,
                target_names=["LOSS", "WIN"],
                output_dict=True
            )
            print(f"  Holdout ROC-AUC: {holdout_auc:.3f}")
            print(f"\n  Holdout Classification Report:")
            print(f"  {classification_report(y_holdout, preds_holdout, target_names=['LOSS','WIN'])}")
        except Exception as e:
            print(f"  [Warning] Holdout evaluation failed: {e}")

    # Full training set fit (for production model)
    clf.fit(X, y)
    preds_all = clf.predict(X)
    train_acc = float((preds_all == y).mean())
    print(f"  Full train accuracy: {train_acc*100:.1f}%")

    # Feature importance
    importances = sorted(
        zip(feature_names, clf.feature_importances_),
        key=lambda x: -x[1]
    )
    print("\n  Top features (FEATURE_SCHEMA):")
    for fname, imp in importances[:10]:
        bar = "█" * int(imp * 200)
        print(f"    {fname:<35} {imp:.4f} {bar}")

    # Save model — features = FEATURE_SCHEMA (14 fixed fields)
    joblib.dump({"model": clf, "features": feature_names}, MODEL_PATH)
    print(f"\n  ✅ Model saved: {MODEL_PATH}")
    print(f"  ✅ Feature schema: {len(feature_names)} fields (FEATURE_SCHEMA)")

    # Save report
    n_unclosed = sum(int(r.get("_n_unclosed_at_end", 0)) for r in all_records_sorted[:1]) if all_records_sorted else 0
    report = {
        "train_date":        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_samples":         len(y),
        "n_train":           int(len(y_train)),
        "n_holdout":         int(len(y_holdout)) if y_holdout is not None else 0,
        "n_win":             n_win,
        "n_loss":            n_loss,
        "win_rate_pct":      round(n_win / len(y) * 100, 2),
        "cv_roc_auc":        round(float(cv_scores.mean()), 4),
        "cv_roc_auc_std":    round(float(cv_scores.std()), 4),
        "holdout_roc_auc":   round(holdout_auc, 4) if holdout_auc is not None else None,
        "train_accuracy_pct": round(train_acc * 100, 2),
        "feature_schema":    "FEATURE_SCHEMA",
        "n_features":        len(feature_names),
        "feature_names":     feature_names,
        "top_features":      [(f, round(float(i), 4)) for f, i in importances[:14]],
        "coins":             list(set(r["coin"] for r in all_records_sorted)),
        "cv_method":         "TimeSeriesSplit(n_splits=5)",
        "mtf_method":        "time-aligned (no leakage)",
        "note":              "Fixed: no MTF lookahead bias, TimeSeriesSplit, FEATURE_SCHEMA unified",
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  📄 Report: {REPORT_PATH}")

    return report


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  TRAIN ADAPTIVE MODEL (FIXED PIPELINE)")
    print(f"  Coins: {', '.join(COINS)}")
    print("  Features: FEATURE_SCHEMA (14 fields)")
    print("  CV: TimeSeriesSplit (no shuffle)")
    print("  MTF: time-aligned (no lookahead)")
    print("  Split: 80% train / 20% holdout (by time)")
    print("=" * 65)

    all_records = []
    total_unclosed = 0
    missing_data = []

    months_to_load = ["january", "february", "march", "april", "may"]
    for coin in COINS:
        # Load and combine 15m candles from all target months
        candles_15m = []
        for month in months_to_load:
            candles_15m.extend(load_candles_csv(coin, "15m", month))
            
        # De-duplicate and sort 15m candles chronologically
        seen_15m = set()
        deduped_15m = []
        for c in candles_15m:
            if c["time"] not in seen_15m:
                seen_15m.add(c["time"])
                deduped_15m.append(c)
        deduped_15m.sort(key=lambda x: x["time_dt"])
        candles_15m = deduped_15m

        if not candles_15m:
            missing_data.append(coin)
            continue

        # Load MTF data (try multiple months)
        mtf_candles = {}
        for tf in ["1h", "4h", "1d"]:
            combined = []
            for month in months_to_load:
                combined.extend(load_candles_csv(coin, tf, month))
            # de-duplicate
            seen = set()
            deduped = []
            for c in combined:
                if c["time"] not in seen:
                    seen.add(c["time"])
                    deduped.append(c)
            deduped.sort(key=lambda x: x["time_dt"])
            mtf_candles[tf] = deduped

        print(f"\n[{coin}] 15m={len(candles_15m)} nến | "
              + " | ".join(f"{tf}={len(mtf_candles[tf])}" for tf in ["1h", "4h", "1d"]))

        result = generate_labeled_trades(coin, candles_15m, mtf_candles)
        if isinstance(result, tuple):
            records, n_unclosed = result
        else:
            records, n_unclosed = result, 0

        wins  = sum(1 for r in records if r["result"] == "WIN")
        total = len(records)
        total_unclosed += n_unclosed

        if total:
            print(f"  → {total} lệnh đóng | WIN={wins} ({wins/total*100:.1f}%) | Unclosed={n_unclosed}")
        else:
            print(f"  → Không có lệnh nào được tạo. Unclosed={n_unclosed}")

        all_records.extend(records)

    if missing_data:
        print(f"\n⚠️  Thiếu dữ liệu cho: {', '.join(missing_data)}")
        print("   Chạy các file fetch_xxx_data.py tương ứng trước")

    print(f"\n{'='*65}")
    print(f"  Tổng records đóng: {len(all_records)} lệnh")
    print(f"  Tổng unclosed (bị bỏ qua): {total_unclosed} lệnh")
    print(f"{'='*65}")

    if not all_records:
        print("\n[Lỗi] Không có records nào. Kiểm tra dữ liệu CSV.")
        return

    # Save signals to adaptive_signals.json for compatibility with meta_model.py
    signals_path = os.path.join(LOGS_DIR, "adaptive_signals.json")
    compact = []
    for r in all_records:
        entry = {
            "coin":       r["coin"],
            "result":     r["result"],
            "pnl_pct":    r["pnl_pct"],
            "signal_raw": r["signal"],
            "entry_time": r["entry_time"],
            "exit_time":  r["exit_time"],
            "htf_trend":  r.get("htf_trend", ""),
            "signal_score": {
                "score":    r["score"],
                "raw_text": r["signal"],
                "action":   "BUY" if "BUY" in r["signal"].upper() else "SELL",
            },
        }
        # Inline FEATURE_SCHEMA fields for meta_model.py train_meta_model()
        entry.update(r["features"])
        compact.append(entry)

    with open(signals_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"  Signals log: {signals_path}")

    print("\n  Đang train model...")
    train_model(all_records)


if __name__ == "__main__":
    main()
