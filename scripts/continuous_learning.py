"""
Continuous Learning Script
--------------------------
Chạy định kỳ mỗi tuần (ví dụ: tối Chủ Nhật).
1. Lấy dữ liệu OHLCV 30 ngày gần nhất + warmup.
2. Mô phỏng backtest để tạo labeled trades (WIN/LOSS) với time-aligned MTF.
3. Train lại mô hình RandomForest.
4. Phát hiện Concept Drift trên HOLDOUT (20% cuối theo thời gian).
5. Nếu pass, lưu đè model và gửi báo cáo Telegram.

FIXES:
- TimeSeriesSplit thay cho StratifiedKFold(shuffle=True).
- Temporal 80/20 holdout — drift check trên holdout ROC-AUC, không phải CV mean.
- Feature schema thống nhất qua FEATURE_SCHEMA (14 fields).
- generate_labeled_trades() đã fix leakage trong train_april_model.py.
"""

import sys, os, time, csv, requests, json
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DISABLE_KELLY'] = '1'

from btc_scraper.config import COINS
from btc_scraper.telegram_bot import send_telegram_message
from btc_scraper.feature_extractor import FEATURE_SCHEMA

# ─── Config ──────────────────────────────────────────────────────────────────
DAYS_TO_TRAIN = 30
END_DT   = datetime.now(timezone.utc)
START_DT = END_DT - timedelta(days=DAYS_TO_TRAIN)
WARMUP_CANDLES = 220
INTERVALS = {
    "15m": {"minutes": 15,   "warmup_days": 3},
    "1h":  {"minutes": 60,   "warmup_days": 10},
    "4h":  {"minutes": 240,  "warmup_days": 38},
    "1d":  {"minutes": 1440, "warmup_days": 222},
}

DATA_DIR     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LOGS_DIR     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
MODEL_PATH   = os.path.join(LOGS_DIR, "adaptive_model.joblib")
BINANCE_BASE = "https://api.binance.com"

TRAIN_HOLDOUT_RATIO = 0.8   # 80% train, 20% holdout
DRIFT_THRESHOLD     = 0.53  # Holdout ROC-AUC must exceed this to swap model

# Import the fixed labeled-trade generator (time-aligned MTF, FEATURE_SCHEMA)
from train_april_model import generate_labeled_trades
# ─────────────────────────────────────────────────────────────────────────────

def fetch_candles(coin: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    symbol   = f"{coin}USDT"
    url      = f"{BINANCE_BASE}/api/v3/klines"
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    all_candles = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     1000,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"    [Lỗi] {coin}/{interval}: {e}")
            break

        if not raw:
            break

        for k in raw:
            ts_ms = k[0]
            all_candles.append({
                "time":      datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "time_dt":   datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None),
                "open":      float(k[1]),
                "high":      float(k[2]),
                "low":       float(k[3]),
                "close":     float(k[4]),
                "volume":    float(k[5]),
                "is_warmup": 1 if ts_ms < int(START_DT.timestamp() * 1000) else 0,
            })

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < 1000:
            break
        current_start = last_ts + 1
        time.sleep(0.1)

    return all_candles


def run_continuous_learning():
    print("=" * 65)
    print("  BẮT ĐẦU CONTINUOUS LEARNING PIPELINE (FIXED)")
    print(f"  Features: FEATURE_SCHEMA ({len(FEATURE_SCHEMA)} fields)")
    print(f"  CV: TimeSeriesSplit (no shuffle)")
    print(f"  Drift threshold: holdout ROC-AUC >= {DRIFT_THRESHOLD}")
    print("=" * 65)

    all_records = []

    for coin in COINS:
        print(f"  [+] Đang xử lý {coin}...")
        mtf_candles = {}
        for tf, conf in INTERVALS.items():
            warmup_start = START_DT - timedelta(days=conf["warmup_days"])
            candles = fetch_candles(coin, tf, warmup_start, END_DT)
            mtf_candles[tf] = candles

        candles_15m = mtf_candles.get("15m", [])
        if len(candles_15m) < WARMUP_CANDLES:
            continue

        # MTF for 1h, 4h, 1d (used by generate_labeled_trades for time-aligned MTF)
        mtf = {tf: mtf_candles[tf] for tf in ["1h", "4h", "1d"]}

        # generate_labeled_trades now uses time-aligned MTF + FEATURE_SCHEMA
        result = generate_labeled_trades(coin, candles_15m, mtf)
        if isinstance(result, tuple):
            records, n_unclosed = result
        else:
            records, n_unclosed = result, 0

        print(f"      {len(records)} closed trades | {n_unclosed} unclosed")
        all_records.extend(records)

    if not all_records:
        msg = "⚠️ <b>[Continuous Learning]</b> Thất bại! Không tạo được record nào từ dữ liệu 30 ngày qua."
        send_telegram_message(msg, parse_mode="HTML")
        return

    print(f"\n  Tổng số lệnh: {len(all_records)}")

    # Train mô hình
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import TimeSeriesSplit, cross_val_score
        from sklearn.metrics import roc_auc_score
        import joblib
    except ImportError:
        print("Thiếu thư viện scikit-learn!")
        return

    # Sort chronologically
    all_records_sorted = sorted(all_records, key=lambda r: r["entry_time"])

    feature_names = list(FEATURE_SCHEMA)
    X = np.array([[float(r["features"].get(k, 0.0)) for k in feature_names] for r in all_records_sorted])
    y = np.array([1 if r["result"] == "WIN" else 0 for r in all_records_sorted])

    n_win = int(y.sum())
    win_rate = n_win / len(y) * 100

    # Temporal 80/20 split
    split_idx = int(len(X) * TRAIN_HOLDOUT_RATIO)
    X_train, X_holdout = X[:split_idx], X[split_idx:]
    y_train, y_holdout = y[:split_idx], y[split_idx:]

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
    cv_auc = float(cv_scores.mean())

    # Train on train split
    clf.fit(X_train, y_train)

    # Holdout ROC-AUC (primary drift indicator)
    holdout_auc = None
    if len(y_holdout) >= 10:
        try:
            y_prob = clf.predict_proba(X_holdout)[:, 1]
            holdout_auc = float(roc_auc_score(y_holdout, y_prob))
        except Exception as e:
            print(f"  [Warning] Holdout evaluation failed: {e}")

    msg_lines = [
        "🔄 <b>[CONTINUOUS LEARNING - RETRAIN MODEL]</b>",
        f"Dữ liệu: 30 ngày qua ({START_DT.strftime('%d/%m')} - {END_DT.strftime('%d/%m')})",
        f"Tổng số lệnh: {len(y)} (Win Rate Base: {win_rate:.1f}%)",
        f"Split: TRAIN={len(y_train)} | HOLDOUT={len(y_holdout)}",
        f"Time-Series CV ROC-AUC: <b>{cv_auc:.4f}</b>",
    ]

    if holdout_auc is not None:
        msg_lines.append(f"Holdout ROC-AUC: <b>{holdout_auc:.4f}</b>")
        check_auc = holdout_auc
    else:
        msg_lines.append("Holdout: N/A (too few samples)")
        check_auc = cv_auc  # fallback to CV if holdout too small

    # Concept drift check on holdout (more reliable than CV)
    if check_auc < DRIFT_THRESHOLD:
        msg_lines.append(f"\n🚨 <b>CẢNH BÁO: CONCEPT DRIFT DETECTED!</b>")
        msg_lines.append(f"ROC-AUC = {check_auc:.4f} < threshold {DRIFT_THRESHOLD}.")
        msg_lines.append("Mô hình hiện tại không học được quy luật hiệu quả từ thị trường gần đây.")
        msg_lines.append("❌ <b>HỦY</b> thao tác lưu đè mô hình. Hệ thống vẫn sử dụng mô hình cũ.")
    else:
        # Retrain on full dataset before saving
        clf.fit(X, y)
        joblib.dump({"model": clf, "features": feature_names}, MODEL_PATH)
        msg_lines.append(f"\n✅ Đã lưu đè mô hình thành công. Sẵn sàng cho giao dịch tuần mới!")
        msg_lines.append(f"Schema: FEATURE_SCHEMA ({len(feature_names)} fields)")

    send_telegram_message("\n".join(msg_lines), parse_mode="HTML")
    print("\n  Hoàn thành Continuous Learning.")


if __name__ == "__main__":
    run_continuous_learning()
