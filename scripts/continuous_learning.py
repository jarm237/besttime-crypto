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

from btc_scraper.core.config import COINS
from btc_scraper.telegram_bot import send_telegram_message
from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA

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

TRAIN_RATIO = 0.70
CALIB_RATIO = 0.20
# Holdout is implicitly 0.10
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


def should_promote_model(
    cv_auc: float,
    holdout_auc: float,
    calibration_error: float,
    n_samples: int,
) -> tuple[bool, list[str]]:
    reasons = []

    if n_samples < 1000:
        reasons.append("not_enough_samples")

    if cv_auc < 0.58:
        reasons.append("cv_auc_below_0_58")

    if holdout_auc < 0.56:
        reasons.append("holdout_auc_below_0_56")

    if calibration_error > 0.10:
        reasons.append("calibration_error_above_10pct")

    if abs(cv_auc - holdout_auc) > 0.05:
        reasons.append("cv_holdout_gap_too_large")

    return len(reasons) == 0, reasons



def run_continuous_learning():
    print("=" * 65)
    print("  BẮT ĐẦU CONTINUOUS LEARNING PIPELINE (FIXED)")
    print(f"  Features: FEATURE_SCHEMA ({len(FEATURE_SCHEMA)} fields)")
    print(f"  CV: TimeSeriesSplit (no shuffle)")
    print(f"  Drift threshold: holdout ROC-AUC >= {DRIFT_THRESHOLD}")
    print("=" * 65)

    print("\n⏳ Đang tải chỉ số Fear & Greed Index lịch sử cho 45 ngày qua...")
    from btc_scraper.core.sentiment import get_historical_sentiment_map
    import btc_scraper.core.sentiment
    import btc_scraper.analysis as _btc_analysis
    
    sentiment_map = get_historical_sentiment_map(limit=45)
    print(f"  ✅ Đã tải {len(sentiment_map)} ngày Fear & Greed Index lịch sử.")

    def mock_get_market_sentiment():
        date_str = getattr(btc_scraper.core.sentiment, "CURRENT_TRAINING_DATE", None)
        if date_str and date_str in sentiment_map:
            return sentiment_map[date_str]
        return {
            "score": 0.0,
            "label": "Neutral",
            "raw_value": 50,
            "timestamp": int(time.time()),
            "update_time_human": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    btc_scraper.core.sentiment.get_market_sentiment = mock_get_market_sentiment
    _btc_analysis.get_market_sentiment = mock_get_market_sentiment

    all_records = []

    def process_coin(coin):
        print(f"  [+] Đang xử lý {coin}...")
        mtf_candles = {}
        for tf, conf in INTERVALS.items():
            warmup_start = START_DT - timedelta(days=conf["warmup_days"])
            candles = fetch_candles(coin, tf, warmup_start, END_DT)
            mtf_candles[tf] = candles

        candles_15m = mtf_candles.get("15m", [])
        if len(candles_15m) < WARMUP_CANDLES:
            return []

        # MTF for 1h, 4h, 1d (used by generate_labeled_trades for time-aligned MTF)
        mtf = {tf: mtf_candles[tf] for tf in ["1h", "4h", "1d"]}

        # generate_labeled_trades now uses time-aligned MTF + FEATURE_SCHEMA
        result = generate_labeled_trades(coin, candles_15m, mtf, sentiment_map=sentiment_map)
        if isinstance(result, tuple):
            records, n_unclosed = result
        else:
            records, n_unclosed = result, 0

        print(f"      {coin}: {len(records)} closed trades | {n_unclosed} unclosed")
        return records

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_coin, COINS))
    
    for r in results:
        all_records.extend(r)

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

    # Temporal 70/20/10 split
    train_end = int(len(X) * TRAIN_RATIO)
    calib_end = int(len(X) * (TRAIN_RATIO + CALIB_RATIO))
    
    X_train, y_train = X[:train_end], y[:train_end]
    X_calib, y_calib = X[train_end:calib_end], y[train_end:calib_end]
    X_holdout, y_holdout = X[calib_end:], y[calib_end:]

    # 1. Feature Correlation Check
    import pandas as pd
    df_train = pd.DataFrame(X_train, columns=feature_names)
    corr_matrix = df_train.corr(method="spearman").abs()
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    to_drop = [column for column in upper.columns if any(upper[column] > 0.85)]
    
    selected_features = [f for f in feature_names if f not in to_drop]
    print(f"  [Correlation] Đã loại bỏ {len(to_drop)} features nhiễu: {to_drop}")
    
    sel_indices = [feature_names.index(f) for f in selected_features]
    X_train_sel = X_train[:, sel_indices]
    X_calib_sel = X_calib[:, sel_indices]
    X_holdout_sel = X_holdout[:, sel_indices]
    X_sel = X[:, sel_indices]

    # 2. Hyperparameter Tuning with Optuna
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        
        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 100, 300, step=50),
                "max_depth": trial.suggest_int("max_depth", 3, 8),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 3, 10),
                "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", None]),
                "class_weight": "balanced",
                "random_state": 42,
                "n_jobs": -1,
            }
            model = RandomForestClassifier(**params)
            tscv = TimeSeriesSplit(n_splits=5)
            scores = cross_val_score(model, X_train_sel, y_train, cv=tscv, scoring="roc_auc")
            return scores.mean()

        print("  [Optuna] Bắt đầu tối ưu hóa siêu tham số (20 trials)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=20)
        best_params = study.best_params
        best_params["class_weight"] = "balanced"
        best_params["random_state"] = 42
        best_params["n_jobs"] = -1
        print(f"  [Optuna] Best params: {best_params}")
        
        clf = RandomForestClassifier(**best_params)
        cv_auc = study.best_value
    except ImportError:
        print("  [Optuna] Chưa cài đặt optuna, dùng tham số mặc định.")
        clf = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1
        )
        tscv = TimeSeriesSplit(n_splits=5)
        cv_auc = float(cross_val_score(clf, X_train_sel, y_train, cv=tscv, scoring="roc_auc").mean())

    # Train on train split
    clf.fit(X_train_sel, y_train)

    # 3. Probability Calibration (70/20 split)
    print("  [Calibration] Bắt đầu hiệu chỉnh xác suất trên tập Calibration (20%)...")
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import PredefinedSplit
    from btc_scraper.ml_engine.meta_model_v3 import compute_calibration_buckets
    
    best_err = float("inf")
    best_model = clf
    best_method = "uncalibrated"
    
    if len(np.unique(y_calib)) > 1:
        # PredefinedSplit: -1 means training set, 0 means validation set
        test_fold = np.concatenate([
            np.full(len(y_train), -1, dtype=int),
            np.zeros(len(y_calib), dtype=int)
        ])
        cv_split = PredefinedSplit(test_fold)
        X_train_cal = np.vstack([X_train_sel, X_calib_sel])
        y_train_cal = np.concatenate([y_train, y_calib])
        
        for method in ("sigmoid", "isotonic"):
            try:
                calibrator = CalibratedClassifierCV(
                    estimator=clf,
                    method=method,
                    cv=cv_split,
                    n_jobs=-1
                )
                calibrator.fit(X_train_cal, y_train_cal)
                
                if len(y_holdout) >= 10:
                    probs = calibrator.predict_proba(X_holdout_sel)[:, 1]
                    buckets = compute_calibration_buckets(probs, y_holdout)
                    errs = [abs(v["calibration_error"]) for v in buckets.values() if v.get("calibration_error") is not None]
                    if errs:
                        mean_err = float(np.mean(errs))
                        if mean_err < best_err:
                            best_err = mean_err
                            best_model = calibrator
                            best_method = method
            except Exception as e:
                print(f"  [Warning] Calibration failed for {method}: {e}")
                
    print(f"  [Calibration] Chọn phương pháp: {best_method} (Error: {best_err:.2f}%)")

    # Holdout ROC-AUC (primary drift indicator)
    holdout_auc = None
    calib_error_display = "N/A"
    
    if len(y_holdout) >= 10:
        try:
            y_prob = best_model.predict_proba(X_holdout_sel)[:, 1]
            if len(np.unique(y_holdout)) > 1:
                holdout_auc = float(roc_auc_score(y_holdout, y_prob))
            # Calculate final calibration error on holdout
            buckets = compute_calibration_buckets(y_prob, y_holdout)
            errs = [abs(v["calibration_error"]) for v in buckets.values() if v.get("calibration_error") is not None]
            if errs:
                calib_error_display = f"{float(np.mean(errs)):.2f}%"
        except Exception as e:
            print(f"  [Warning] Holdout evaluation failed: {e}")

    msg_lines = [
        "🔄 <b>[CONTINUOUS LEARNING - RETRAIN MODEL]</b>",
        f"Dữ liệu: 30 ngày qua ({START_DT.strftime('%d/%m')} - {END_DT.strftime('%d/%m')})",
        f"Tổng số lệnh: {len(y)} (Win Rate Base: {win_rate:.1f}%)",
        f"Split: TRAIN={len(y_train)} | CALIB={len(y_calib)} | HOLDOUT={len(y_holdout)}",
        f"Time-Series CV ROC-AUC: <b>{cv_auc:.4f}</b>",
        f"Calibration Method: <b>{best_method}</b> (Holdout Error: {calib_error_display})",
    ]

    if holdout_auc is not None:
        msg_lines.append(f"Holdout ROC-AUC: <b>{holdout_auc:.4f}</b>")
        check_auc = holdout_auc
    else:
        msg_lines.append("Holdout: N/A (too few samples)")
        check_auc = cv_auc  # fallback to CV if holdout too small

    # Promote Gate Evaluation
    calib_err_val = best_err / 100.0 if best_err != float("inf") else 1.0
    promote, reasons = should_promote_model(
        cv_auc=cv_auc,
        holdout_auc=holdout_auc if holdout_auc is not None else 0.0,
        calibration_error=calib_err_val,
        n_samples=len(y)
    )

    if promote:
        # Save to production
        joblib.dump({"model": best_model, "features": selected_features}, MODEL_PATH)
        msg_lines.append(f"\n✅ Đã lưu đè mô hình PRODUCTION thành công.")
        msg_lines.append(f"Schema: Đã chọn {len(selected_features)}/{len(feature_names)} features")
    else:
        # Save to challenger
        challenger_dir = os.path.join(LOGS_DIR, "challenger")
        os.makedirs(challenger_dir, exist_ok=True)
        challenger_path = os.path.join(challenger_dir, f"adaptive_model_{datetime.now().strftime('%Y%m%d')}.joblib")
        joblib.dump({"model": best_model, "features": selected_features}, challenger_path)
        
        msg_lines.append(f"\n⚠️ <b>Challenger model trained but NOT promoted.</b>")
        msg_lines.append("Reason:")
        for r in reasons:
            msg_lines.append(f"- {r}")
        msg_lines.append("\nProduction model remains unchanged.")
        msg_lines.append("Challenger saved for shadow evaluation.")

    send_telegram_message("\n".join(msg_lines), parse_mode="HTML")
    print("\n  Hoàn thành Continuous Learning.")


if __name__ == "__main__":
    run_continuous_learning()
