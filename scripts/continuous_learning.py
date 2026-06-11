"""
Continuous Learning Script
--------------------------
Chạy định kỳ mỗi tuần (ví dụ: tối Chủ Nhật).
1. Lấy dữ liệu OHLCV 30 ngày gần nhất + warmup.
2. Mô phỏng backtest để tạo labeled trades (WIN/LOSS).
3. Train lại mô hình RandomForest.
4. Phát hiện Concept Drift (ROC-AUC < 0.55).
5. Nếu pass, lưu đè model và gửi báo cáo Telegram.
"""

import sys, os, time, csv, requests, json
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_scraper.config import COINS
from btc_scraper.telegram_bot import send_telegram_message

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

# Import các logic cần thiết
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
            all_candles.append({
                "time":      datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "open":      float(k[1]),
                "high":      float(k[2]),
                "low":       float(k[3]),
                "close":     float(k[4]),
                "volume":    float(k[5]),
                "is_warmup": 1 if k[0] < int(START_DT.timestamp() * 1000) else 0,
            })

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < 1000:
            break
        current_start = last_ts + 1
        time.sleep(0.1)

    return all_candles

def run_continuous_learning():
    print("=" * 60)
    print("  BẮT ĐẦU CONTINUOUS LEARNING PIPELINE")
    print("=" * 60)
    
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
            
        # Lọc ra mtf_candles cho 1h, 4h, 1d
        mtf = {tf: mtf_candles[tf] for tf in ["1h", "4h", "1d"]}
        
        # Gọi generate_labeled_trades từ train_april_model
        records = generate_labeled_trades(coin, candles_15m, mtf)
        all_records.extend(records)
        
    if not all_records:
        msg = "⚠️ <b>[Continuous Learning]</b> Thất bại! Không tạo được record nào từ dữ liệu 30 ngày qua."
        send_telegram_message(msg, parse_mode="HTML")
        return
        
    print(f"\n  Tổng số lệnh: {len(all_records)}")
    
    # Train mô hình
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.pipeline import Pipeline
        import joblib
    except ImportError:
        print("Thiếu thư viện scikit-learn!")
        return
        
    feature_names = sorted(all_records[0]["features"].keys())
    X = np.array([[float(r["features"].get(k, 0.0)) for k in feature_names] for r in all_records])
    y = np.array([1 if r["result"] == "WIN" else 0 for r in all_records])
    
    n_win = int(y.sum())
    win_rate = n_win / len(y) * 100
    
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
    
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(clf, X, y, cv=cv, scoring="roc_auc")
    roc_auc = float(cv_scores.mean())
    
    # Huấn luyện trên toàn bộ dữ liệu mới
    clf.fit(X, y)
    
    msg_lines = [
        "🔄 <b>[CONTINUOUS LEARNING - RETRAIN MODEL]</b>",
        f"Dữ liệu: 30 ngày qua ({START_DT.strftime('%d/%m')} - {END_DT.strftime('%d/%m')})",
        f"Tổng số lệnh: {len(y)} (Win Rate Base: {win_rate:.1f}%)",
        f"Cross-Validation ROC-AUC: <b>{roc_auc:.4f}</b>"
    ]
    
    # Kiểm tra Drift
    if roc_auc < 0.55:
        msg_lines.append("\n🚨 <b>CẢNH BÁO: CONCEPT DRIFT DETECTED!</b>")
        msg_lines.append("ROC-AUC quá thấp (< 0.55). Mô hình hiện tại không học được quy luật hiệu quả từ thị trường gần đây.")
        msg_lines.append("❌ <b>HỦY</b> thao tác lưu đè mô hình. Hệ thống vẫn sử dụng mô hình cũ.")
    else:
        joblib.dump({"model": clf, "features": feature_names}, MODEL_PATH)
        msg_lines.append("\n✅ Đã lưu đè mô hình thành công. Sẵn sàng cho giao dịch tuần mới!")
        
    send_telegram_message("\n".join(msg_lines), parse_mode="HTML")
    print("\n  Hoàn thành Continuous Learning.")

if __name__ == "__main__":
    run_continuous_learning()
