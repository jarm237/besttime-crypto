"""
Train Adaptive Model từ dữ liệu April 2026
============================================
Luồng:
  1. Load CSV nến April (15m + 1h + 4h + 1d) từ fetch_april_data.py
  2. Chạy analyze_market() rolling window trên 15m → tạo lệnh ảo (BUY/SELL)
  3. Gắn MTF context (1h, 4h, 1d) vào mỗi lệnh dưới dạng features
  4. Đóng lệnh khi hit SL hoặc TP1 → label WIN/LOSS
  5. Extract features mở rộng (15m indicators + MTF summary)
  6. Train RandomForestClassifier
  7. Lưu model → logs/adaptive_model.joblib (tương thích signal_score.py)
  8. In báo cáo: accuracy, feature importance, cross-validation

Cách chạy:
  python train_april_model.py

Yêu cầu:
  pip install scikit-learn joblib numpy
  (đã chạy fetch_april_data.py trước)
"""

import sys, os, csv, json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from btc_scraper.analysis import analyze_market
from btc_scraper.config import COINS

# ─── Config ──────────────────────────────────────────────────────────────────
DATA_DIR      = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR      = os.path.join(os.path.dirname(__file__), "logs")
MODEL_PATH    = os.path.join(LOGS_DIR, "adaptive_model.joblib")
REPORT_PATH   = os.path.join(LOGS_DIR, "train_april_report.json")

WARMUP_CANDLES = 220     # Nến warmup trước khi bắt đầu tạo signal
FEE_RATE       = 0.001   # 0.1% mỗi chiều
BUY_MIN_SCORE  = 51      # Chỉ train trên BUY signal MEDIUM+
SELL_MAX_SCORE = 49      # Chỉ train trên SELL signal thực sự

os.makedirs(LOGS_DIR, exist_ok=True)
# ─────────────────────────────────────────────────────────────────────────────


# ─── 1. LOAD CSV ─────────────────────────────────────────────────────────────

import os
os.environ['DISABLE_KELLY'] = '1'

import btc_scraper.signal_score
def mock_load_adaptive_model():
    return None
btc_scraper.signal_score._load_adaptive_model = mock_load_adaptive_model

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

def load_candles_csv(coin: str, interval: str) -> list[dict]:
    """
    Load nến từ CSV. Thử theo thứ tự:
      1. backtest_candles_{coin}.csv  (backtest_1month.py) — ưu tiên dùng data này
      2. april_{coin}_{interval}.csv  (fetch_april_data.py)
    """
    candidates = []
    if interval == "15m":
        candidates.append(os.path.join(DATA_DIR, f"backtest_candles_{coin}.csv"))
    candidates.append(os.path.join(DATA_DIR, f"april_{coin}_{interval}.csv"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        candles = []
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                candles.append({
                    "time":      row["time"],
                    "open":      float(row["open"]),
                    "high":      float(row["high"]),
                    "low":       float(row["low"]),
                    "close":     float(row["close"]),
                    "volume":    float(row["volume"]),
                    # backtest_candles không có is_warmup → mặc định 0 (tất cả đều dùng)
                    "is_warmup": int(row.get("is_warmup", 0)),
                })
        if candles:
            return candles
    return []


# ─── 2. MTF FEATURE SUMMARY ──────────────────────────────────────────────────

def _mtf_summary(tf_candles: list[dict]) -> dict:
    """
    Tóm tắt nhanh MTF analysis thành các feature số.
    Dùng analyze_market trên cả chuỗi, lấy giá trị cuối cùng.
    """
    if not tf_candles or len(tf_candles) < 30:
        return {}
    try:
        ana = analyze_market(tf_candles)
        signal = ana.get("signal", "")
        is_bull = 1 if ("BUY" in signal.upper() or "BULL" in signal.upper()) else 0
        is_bear = 1 if ("SELL" in signal.upper() or "BEAR" in signal.upper()) else 0
        return {
            "rsi":          ana.get("rsi", 50.0),
            "ema_trend":    1.0 if ana.get("ema9", 0) > ana.get("ema21", 0) else 0.0,
            "above_sma200": 1.0 if (ana.get("sma200", 0) > 0 and ana.get("close", 0) > ana.get("sma200", 0)) else 0.0,
            "macd_hist":    ana.get("macd_hist", 0.0),
            "atr":          ana.get("atr", 0.0),
            "is_bull":      float(is_bull),
            "is_bear":      float(is_bear),
        }
    except Exception:
        return {}


# ─── 3. FEATURE EXTRACTION ───────────────────────────────────────────────────

def extract_features(ana: dict, mtf: dict) -> dict:
    """
    Tạo feature vector từ analyze_market output + MTF context.
    Tất cả đều là float để sklearn xử lý.
    """
    sig_score = ana.get("signal_score", {}) or {}
    signal    = ana.get("signal", "")
    close     = ana.get("close", 0.0)
    bb_upper  = ana.get("bb_upper", 0.0)
    bb_lower  = ana.get("bb_lower", 0.0)
    bb_middle = ana.get("bb_middle", 0.0)
    ema9      = ana.get("ema9", 0.0)
    ema21     = ana.get("ema21", 0.0)
    sma50     = ana.get("sma50", 0.0)
    sma200    = ana.get("sma200", 0.0)

    s = signal.upper()

    feat = {
        # Signal score
        "score":            float(sig_score.get("score") or 50),
        "confidence":       {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.4}.get(
                                str(sig_score.get("confidence") or "LOW"), 0.4),
        "position_size":    float(sig_score.get("position_size") or 0.5),

        # Signal type flags
        "is_buy":           1.0 if "BUY" in s else 0.0,
        "is_sell":          1.0 if "SELL" in s else 0.0,
        "is_strong":        1.0 if "STRONG" in s else 0.0,
        "is_sfp":           1.0 if "SFP" in s else 0.0,
        "is_crossover":     1.0 if "CROSSOVER" in s else 0.0,
        "is_reversal":      1.0 if "REVERSAL" in s else 0.0,
        "is_pullback":      1.0 if "PULLBACK" in s else 0.0,
        "is_break":         1.0 if "BREAK" in s else 0.0,

        # 15m indicators
        "rsi_15m":          float(ana.get("rsi", 50.0)),
        "ema_trend_15m":    1.0 if ema9 > ema21 else 0.0,
        "above_sma50_15m":  1.0 if sma50 > 0 and close > sma50 else 0.0,
        "above_sma200_15m": 1.0 if sma200 > 0 and close > sma200 else 0.0,
        "macd_hist_15m":    float(ana.get("macd_hist", 0.0)),
        "atr_pct_15m":      float(ana.get("atr", 0.0)) / close if close > 0 else 0.0,
        "adx_15m":          float(ana.get("adx", 0.0)),
        "choppiness_15m":   float(ana.get("choppiness", 0.0)),
        "bb_width_15m":     (bb_upper - bb_lower) / close if close > 0 and bb_upper > 0 else 0.0,
        "bb_position_15m":  (close - bb_lower) / (bb_upper - bb_lower)
                            if bb_upper > bb_lower else 0.5,
        "chandelier_bull":  1.0 if ana.get("chandelier") == "BULL" else 0.0,
        "vol_spike":        1.0 if ana.get("vol_spike") else 0.0,
    }

    # MTF features (1h, 4h, 1d)
    for tf in ["1h", "4h", "1d"]:
        tf_data = mtf.get(tf, {})
        for k, v in tf_data.items():
            feat[f"{k}_{tf}"] = float(v) if v is not None else 0.0

    return feat


from btc_scraper.analysis import analyze_market, analyze_all_market

def generate_labeled_trades(coin: str, candles_15m: list[dict], mtf_candles: dict) -> list[dict]:
    """
    Rolling window trên 15m candles, tạo lệnh ảo và gắn label WIN/LOSS.
    Đồng thời extract MTF features tại thời điểm vào lệnh.
    """
    n = len(candles_15m)
    if n < WARMUP_CANDLES + 2:
        return []

    # Pre-compute MTF summary tại từng mốc thời gian
    # (dùng toàn bộ MTF data vì nó đã bao gồm warmup và April)
    mtf_precomputed = {}
    for tf, tf_candles in mtf_candles.items():
        if tf_candles:
            mtf_precomputed[tf] = _mtf_summary(tf_candles)
        else:
            mtf_precomputed[tf] = {}

    records  = []
    position = None

    all_ana = analyze_all_market(candles_15m)

    for i in range(WARMUP_CANDLES, n):
        candle = candles_15m[i]

        # Bỏ qua warmup candles (trước tháng 4)
        # is_warmup=1 chỉ xét khi mở lệnh, không cần check khi đóng
        is_warmup_candle = candle.get("is_warmup", 0)

        high  = candle["high"]
        low   = candle["low"]
        close = candle["close"]

        # ── Đóng lệnh đang mở ─────────────────────────────────────────────
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

                position["result"]    = result
                position["pnl_pct"]   = round(pnl_pct, 4)
                position["exit_time"] = candle["time"]
                records.append(position)
                position = None

        # ── Tìm tín hiệu mới ──────────────────────────────────────────────
        if position is None and not is_warmup_candle:
            ana = all_ana[i - WARMUP_CANDLES]

            signal = ana.get("signal", "")
            s_upper = signal.upper()
            if "BUY" not in s_upper and "SELL" not in s_upper:
                continue
            if "NEUTRAL" in s_upper or "WEAK" in s_upper:
                continue

            sig_score_info = ana.get("signal_score", {}) or {}
            score      = int(sig_score_info.get("score") or 0)
            action     = sig_score_info.get("action", "NEUTRAL")

            # Filter theo score
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

            # Extract features
            features = extract_features(ana, mtf_precomputed)

            position = {
                "coin":       coin,
                "direction":  direction,
                "entry":      close,
                "entry_time": candle["time"],
                "sl":         sl,
                "tp1":        tp1,
                "rr1":        rr1,
                "signal":     signal,
                "score":      score,
                "features":   features,
                "result":     None,
                "pnl_pct":    0.0,
                "exit_time":  None,
            }

    return [r for r in records if r["result"] is not None]


# ─── 5. TRAIN MODEL ──────────────────────────────────────────────────────────

def train_model(all_records: list[dict]) -> dict:
    """Train RandomForest + đánh giá cross-validation."""
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.metrics import classification_report
        import joblib
    except ImportError as e:
        print(f"[Lỗi] Thiếu thư viện: {e}")
        print("Cài đặt: pip install scikit-learn joblib numpy")
        return {}

    if not all_records:
        print("[Lỗi] Không có records để train.")
        return {}

    # Build X, y
    feature_names = sorted(all_records[0]["features"].keys())
    X = np.array([[float(r["features"].get(k, 0.0)) for k in feature_names]
                  for r in all_records])
    y = np.array([1 if r["result"] == "WIN" else 0 for r in all_records])

    n_win  = int(y.sum())
    n_loss = len(y) - n_win
    print(f"\n  Dataset: {len(y)} samples | WIN={n_win} ({n_win/len(y)*100:.1f}%) | LOSS={n_loss}")

    # Model pipeline
    clf = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
        )),
    ])

    # Cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(clf, X, y, cv=cv, scoring="roc_auc")
    print(f"  CV ROC-AUC: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Train trên toàn bộ data
    clf.fit(X, y)
    preds = clf.predict(X)
    acc = float((preds == y).mean())
    print(f"  Train accuracy: {acc*100:.1f}%")
    print(f"\n{classification_report(y, preds, target_names=['LOSS','WIN'])}")

    # Feature importance
    rf = clf.named_steps["clf"]
    importances = sorted(
        zip(feature_names, rf.feature_importances_),
        key=lambda x: -x[1]
    )
    print("\n  Top 15 features:")
    for fname, imp in importances[:15]:
        bar = "█" * int(imp * 200)
        print(f"    {fname:<35} {imp:.4f} {bar}")

    # Lưu model
    joblib.dump({"model": clf, "features": feature_names}, MODEL_PATH)
    print(f"\n  ✅ Model đã lưu: {MODEL_PATH}")

    # Lưu report
    report = {
        "train_date":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_samples":      len(y),
        "n_win":          n_win,
        "n_loss":         n_loss,
        "win_rate":       round(n_win / len(y) * 100, 2),
        "cv_roc_auc":     round(float(cv_scores.mean()), 4),
        "cv_roc_auc_std": round(float(cv_scores.std()), 4),
        "train_accuracy": round(acc * 100, 2),
        "feature_names":  feature_names,
        "top_features":   [(f, round(float(i), 4)) for f, i in importances[:20]],
        "coins":          list(set(r["coin"] for r in all_records)),
        "data_period":    "April 2026 (15m)",
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  📄 Report: {REPORT_PATH}")

    return report


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  TRAIN ADAPTIVE MODEL — April 2026 Data")
    print(f"  Coins: {', '.join(COINS)}")
    print("  Filter: BUY score>=51 | SELL score<=49 | No WEAK")
    print("=" * 60)

    all_records = []
    missing_data = []

    for coin in COINS:
        candles_15m = load_candles_csv(coin, "15m")
        if not candles_15m:
            missing_data.append(coin)
            continue

        # Load MTF data
        mtf_candles = {}
        for tf in ["1h", "4h", "1d"]:
            mtf_candles[tf] = load_candles_csv(coin, tf)

        print(f"\n[{coin}] 15m={len(candles_15m)} nến | "
              + " | ".join(f"{tf}={len(mtf_candles[tf])}" for tf in ["1h", "4h", "1d"]))

        records = generate_labeled_trades(coin, candles_15m, mtf_candles)
        wins  = sum(1 for r in records if r["result"] == "WIN")
        total = len(records)

        if total:
            print(f"  → {total} lệnh | WIN={wins} ({wins/total*100:.1f}%)")
        else:
            print(f"  → Không có lệnh nào được tạo.")

        all_records.extend(records)

    if missing_data:
        print(f"\n⚠️  Thiếu dữ liệu April cho: {', '.join(missing_data)}")
        print("   Chạy: python fetch_april_data.py trước")

    if not all_records:
        print("\n[Lỗi] Không có records nào. Kiểm tra dữ liệu CSV.")
        return

    print(f"\n{'='*60}")
    print(f"  Tổng records: {len(all_records)} lệnh ảo từ {len(COINS)} coins")
    print(f"{'='*60}")

    # Cũng lưu records vào adaptive_signals.json để tương thích
    signals_path = os.path.join(LOGS_DIR, "adaptive_signals.json")
    compact = []
    for r in all_records:
        compact.append({
            "coin":       r["coin"],
            "result":     r["result"],
            "pnl_pct":    r["pnl_pct"],
            "signal_raw": r["signal"],
            "entry_time": r["entry_time"],
            "exit_time":  r["exit_time"],
            "signal_score": {
                "score":      r["score"],
                "raw_text":   r["signal"],
                "action":     "BUY" if "BUY" in r["signal"].upper() else "SELL",
            },
            **{k: v for k, v in r["features"].items()},
        })

    with open(signals_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"  Signals log: {signals_path}")

    print("\n  Đang train model...")
    train_model(all_records)


if __name__ == "__main__":
    main()
