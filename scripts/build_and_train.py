#!/usr/bin/env python3
"""
build_and_train.py — Pipeline tạo data từ đầu + train model tự động
=====================================================================
1. Đọc dữ liệu nến từ data/historical_18m (không gọi API Binance)
2. Tải sentiment lịch sử từ logs/sentiment_history.json — tra cứu đúng ngày
   của từng cây nến, không set cứng giá trị.
3. Chạy rolling-window backtest cho từng coin → sinh labeled trades (WIN/LOSS)
4. Trích xuất 40+ features theo FEATURE_SCHEMA_V2
5. Lưu dataset ra logs/adaptive_signals_v2.json
6. Tự động train Ensemble Meta Model và lưu model mới

Usage:
  python scripts/build_and_train.py
  python scripts/build_and_train.py --skip-build   # Chỉ train, dùng data có sẵn
  python scripts/build_and_train.py --no-calibrate # Train không Platt scaling
"""
import sys
import os
import csv
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import bisect

# ── Force UTF-8 output ──────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR         = BASE_DIR / "data" / "historical_18m"
LOGS_DIR         = BASE_DIR / "logs"
SENTIMENT_FILE   = LOGS_DIR / "sentiment_history.json"
OUTPUT_FILE      = LOGS_DIR / "adaptive_signals_v2.json"
WARMUP           = 220
BUY_MIN_SCORE    = 51
SELL_MAX_SCORE   = 49
HTF_INTERVALS    = {"1h": 60, "4h": 240, "1d": 1440}

_FALLBACK_SENTIMENT = {
    "score": 0.0, "label": "Neutral", "raw_value": 50,
    "timestamp": 0, "update_time_human": "N/A",
}

# ── Sentiment History Loader ─────────────────────────────────────────────────
# Được build một lần duy nhất lúc khởi động
_SENTIMENT_BY_DATE: dict[str, dict] = {}   # "YYYY-MM-DD" → sentiment dict
_SENTIMENT_DATES_SORTED: list[str]  = []   # sorted list của tất cả keys

def _load_sentiment_history() -> None:
    global _SENTIMENT_BY_DATE, _SENTIMENT_DATES_SORTED
    if not SENTIMENT_FILE.exists():
        print(f"  [Sentiment] Không tìm thấy {SENTIMENT_FILE}, dùng neutral mặc định.")
        return
    try:
        with open(SENTIMENT_FILE, "r", encoding="utf-8") as f:
            raw: dict = json.load(f)
        # Key format: "2025-06-15T00:00:00Z" → lấy phần YYYY-MM-DD
        for k, v in raw.items():
            date_key = k[:10]   # "2025-06-15"
            # Chỉ ghi đè nếu chưa có (giữ entry sớm nhất của ngày)
            if date_key not in _SENTIMENT_BY_DATE:
                _SENTIMENT_BY_DATE[date_key] = {
                    "score":    float(v.get("score", 0.0)),
                    "raw_value": int(v.get("raw_value", 50)),
                    "label":    str(v.get("label", "Neutral")),
                    "timestamp": 0,
                    "update_time_human": date_key,
                }
        _SENTIMENT_DATES_SORTED = sorted(_SENTIMENT_BY_DATE.keys())
        print(f"  [Sentiment] Đã tải {len(_SENTIMENT_BY_DATE)} ngày sentiment từ {SENTIMENT_FILE}")
    except Exception as e:
        print(f"  [Sentiment] Lỗi tải history: {e}")


def _lookup_sentiment(date_str: str) -> dict:
    """Tra cứu sentiment cho ngày `date_str` (YYYY-MM-DD).
    Nếu không có đúng ngày đó, lấy ngày gần nhất trong lịch sử (backward)."""
    if not _SENTIMENT_DATES_SORTED:
        return _FALLBACK_SENTIMENT.copy()
    # Exact match
    if date_str in _SENTIMENT_BY_DATE:
        return _SENTIMENT_BY_DATE[date_str]
    # Tìm ngày gần nhất TRƯỚC date_str (bisect_right − 1)
    idx = bisect.bisect_right(_SENTIMENT_DATES_SORTED, date_str) - 1
    if idx < 0:
        # date_str trước toàn bộ history → dùng ngày đầu tiên
        return _SENTIMENT_BY_DATE[_SENTIMENT_DATES_SORTED[0]]
    return _SENTIMENT_BY_DATE[_SENTIMENT_DATES_SORTED[idx]]


# ── Context variable: ngày của cây nến đang được phân tích ──────────────────
_current_date_ctx: str = ""   # "YYYY-MM-DD"

def _set_candle_date(dt: datetime) -> None:
    global _current_date_ctx
    _current_date_ctx = dt.strftime("%Y-%m-%d")

def _mock_get_sentiment() -> dict:
    return _lookup_sentiment(_current_date_ctx)

def _mock_get_sentiment_trend(*args, **kwargs) -> dict:
    current = _lookup_sentiment(_current_date_ctx)
    dt = datetime.strptime(_current_date_ctx, "%Y-%m-%d")
    prev_dt = dt - timedelta(days=1)
    prev = _lookup_sentiment(prev_dt.strftime("%Y-%m-%d"))
    
    current_score = current.get("score", 0.0)
    prev_score = prev.get("score", 0.0)
    score_diff = current_score - prev_score
    
    if score_diff > 0.1:
        trend = "UP"
    elif score_diff < -0.1:
        trend = "DOWN"
    else:
        trend = "STABLE"

    current_label = current.get("label", "Neutral")
    prev_label = prev.get("label", "Neutral")
    
    recovery_signal = (
        prev_label == "Extreme Fear"
        and current_label in ["Fear", "Neutral", "Greed"]
        and score_diff > 0
    ) or (trend == "UP" and current_score < 0)
    
    risk_signal = (
        prev_label == "Extreme Greed"
        and current_label in ["Greed", "Neutral", "Fear"]
        and score_diff < 0
    ) or (trend == "DOWN" and current_score > 0.6)

    return {
        "trend": trend,
        "momentum": round(score_diff, 3),
        "recovery_signal": recovery_signal,
        "risk_signal": risk_signal,
        "hours_in_extreme": 0,
    }

# ── Patch modules TRƯỚC KHI import analysis ─────────────────────────────────
import btc_scraper.core.sentiment as _sentiment_mod
_sentiment_mod.get_market_sentiment         = _mock_get_sentiment
_sentiment_mod.get_sentiment_trend          = _mock_get_sentiment_trend
_sentiment_mod._save_sentiment_to_history   = lambda data, **kw: None  # no-op

from btc_scraper.core.db import closed_positions_col
import btc_scraper.trading.risk_manager as _risk_mod

# Lôi hết dữ liệu DB lên bảng tạm 1 lần duy nhất để tối ưu tốc độ
print("  [Init] Đang tải bảng tạm closed_positions từ MongoDB...")
_TEMP_TRADES_TABLE = list(closed_positions_col.find({}, {"_id": 0}).sort("_id", 1))
_original_calculate_risk_metrics = _risk_mod.calculate_risk_metrics

def _cached_calculate_risk_metrics(*args, **kwargs):
    # Truyền bảng tạm vào để tính toán thay vì query DB
    kwargs["trades_cache"] = _TEMP_TRADES_TABLE
    return _original_calculate_risk_metrics(*args, **kwargs)

_risk_mod.calculate_risk_metrics = _cached_calculate_risk_metrics

try:
    import btc_scraper.ml_engine.signal_score as _score_mod
    _score_mod.calculate_risk_metrics = _cached_calculate_risk_metrics
except Exception:
    pass

# Cũng patch trên module analysis (nếu nó đã import riêng)
try:
    import btc_scraper.analysis as _analysis_pkg
    _analysis_pkg.get_market_sentiment = _mock_get_sentiment
    _analysis_pkg.get_sentiment_trend  = _mock_get_sentiment_trend
except Exception:
    pass
try:
    import btc_scraper.analysis.core as _core_mod
    _core_mod.get_market_sentiment       = _mock_get_sentiment
    _core_mod.get_sentiment_trend        = _mock_get_sentiment_trend
    _core_mod._save_sentiment_to_history = lambda data, **kw: None
except Exception:
    pass

os.environ["DISABLE_KELLY"] = "1"

from btc_scraper.core.config import COINS
from btc_scraper.analysis.core import analyze_market
from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2, FEATURE_SCHEMA_V2
from btc_scraper.ml_engine.meta_model import train_meta_model, INPUT as MODEL_INPUT


# ── Data Loading ─────────────────────────────────────────────────────────────

def get_available_months() -> list[str]:
    months = set()
    for f in DATA_DIR.glob("*_15m.csv"):
        parts = f.stem.split("_")
        if len(parts) >= 3:
            months.add(f"{parts[0]}_{parts[1]}")
    return sorted(months)


def load_candles(coin: str, interval: str, months: list[str]) -> list[dict]:
    combined = []
    for m in months:
        path = DATA_DIR / f"{m}_{coin}_{interval}.csv"
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                dt = datetime.strptime(row["time"], "%Y-%m-%d %H:%M")
                combined.append({
                    "time":      row["time"],
                    "time_dt":   dt,
                    "open":      float(row["open"]),
                    "high":      float(row["high"]),
                    "low":       float(row["low"]),
                    "close":     float(row["close"]),
                    "volume":    float(row["volume"]),
                    "is_warmup": int(row.get("is_warmup", 0)),
                })
    seen, dedup = set(), []
    for c in combined:
        if c["time"] not in seen:
            seen.add(c["time"])
            dedup.append(c)
    dedup.sort(key=lambda x: x["time_dt"])
    return dedup


# ── HTF Alignment ─────────────────────────────────────────────────────────────

def _classify_signal(signal: str) -> str:
    s = signal.upper()
    if "BUY"  in s or "BULL" in s: return "BULL"
    if "SELL" in s or "BEAR" in s: return "BEAR"
    return "NEUTRAL"

def _summarize_htf(mtf_analysis: dict) -> str:
    counts = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
    for tf in ["1d", "4h", "1h"]:
        info = mtf_analysis.get(tf)
        if not info: continue
        counts[_classify_signal(info.get("signal", ""))] += 1
    if counts["BULL"] >= 2 and counts["BEAR"] == 0:  return "BULLISH"
    if counts["BEAR"] >= 2 and counts["BULL"] == 0:  return "BEARISH"
    if counts["BULL"] > counts["BEAR"]:               return "BULLISH-MIXED"
    if counts["BEAR"] > counts["BULL"]:               return "BEARISH-MIXED"
    return "NEUTRAL"

def get_htf_slice(htf_candles: list[dict], cutoff_dt: datetime, limit: int = 220) -> list[dict]:
    dates = [c["time_dt"] for c in htf_candles]
    idx = bisect.bisect_right(dates, cutoff_dt)
    return htf_candles[max(0, idx - limit): idx]


# ── Backtest Simulation ───────────────────────────────────────────────────────

def simulate_coin(coin: str, candles_15m: list[dict], mtf_candles: dict) -> list[dict]:
    n = len(candles_15m)
    if n < WARMUP + 2:
        return []

    trades   = []
    position = None

    for i in range(WARMUP, n):
        candle    = candles_15m[i]
        candle_dt = candle["time_dt"]

        if candle.get("is_warmup"):
            continue

        high  = candle["high"]
        low   = candle["low"]
        close = candle["close"]

        # ── Kiểm tra đóng lệnh ──────────────────────────────────────────
        if position is not None:
            sl, tp1   = position["sl"], position["tp1"]
            direction = position["direction"]
            entry     = position["entry"]

            hit_sl  = (low  <= sl)  if direction == "LONG" else (high >= sl)
            hit_tp1 = (high >= tp1) if direction == "LONG" else (low  <= tp1)

            if hit_sl or hit_tp1:
                exit_price = sl if hit_sl else tp1
                result     = "LOSS" if hit_sl else "WIN"
                pnl_pct    = ((exit_price - entry) / entry * 100) if direction == "LONG" \
                             else ((entry - exit_price) / entry * 100)

                rec = position["record"]
                rec.update({"result": result, "pnl_pct": round(pnl_pct, 4),
                             "exit_time": candle["time"]})
                trades.append(rec)
                position = None

        if position is not None:
            continue

        # ── Set ngày hiện tại vào context TRƯỚC KHI gọi analyze_market ──
        _set_candle_date(candle_dt)

        window = candles_15m[max(0, i - 200): i + 1]
        try:
            ana = analyze_market(window)
        except Exception:
            continue

        signal = ana.get("signal", "")
        s_up   = signal.upper()
        if "BUY" not in s_up and "SELL" not in s_up:
            continue
        if "NEUTRAL" in s_up or "WEAK" in s_up:
            continue

        sig_score_info = ana.get("signal_score") or {}
        score  = int(sig_score_info.get("score") or 0)
        action = sig_score_info.get("action", "NEUTRAL")

        if action == "BUY"  and score < BUY_MIN_SCORE:  continue
        if action == "SELL" and score > SELL_MAX_SCORE: continue
        if action == "NEUTRAL": continue

        tp_sl = ana.get("tp_sl", {})
        sl    = tp_sl.get("sl", 0.0)
        tp1   = tp_sl.get("tp1", 0.0)
        if sl <= 0 or tp1 <= 0:
            continue

        direction = "LONG" if "BUY" in s_up else "SHORT"
        if direction == "LONG"  and (sl >= close or tp1 <= close): continue
        if direction == "SHORT" and (sl <= close or tp1 >= close): continue

        # ── HTF alignment ────────────────────────────────────────────────
        mtf_analysis = {}
        for tf, tf_cands in mtf_candles.items():
            closed = get_htf_slice(tf_cands, candle_dt)
            if len(closed) >= 50:
                _set_candle_date(candle_dt)   # đặt lại context cho HTF
                try:
                    mtf_analysis[tf] = analyze_market(closed)
                except Exception:
                    mtf_analysis[tf] = {}

        htf_trend = _summarize_htf(mtf_analysis)

        # ── Trích xuất features V2 ───────────────────────────────────────
        ana_copy = dict(ana)
        ana_copy["close"] = close
        feat = build_meta_features_v2(ana_copy, htf_trend)

        record = {
            "coin":       coin,
            "result":     None,
            "pnl_pct":    None,
            "signal_raw": signal,
            "entry_time": candle["time"],
            "exit_time":  None,
            "htf_trend":  htf_trend,
            "signal_score": {
                "score":    score,
                "raw_text": signal,
                "action":   action,
                "regime":   ana.get("regime") or ana.get("market_regime", ""),
            },
        }
        record.update(feat)

        position = {
            "entry": close, "sl": sl, "tp1": tp1,
            "direction": direction,
            "record": record,
        }

    return trades


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def build_dataset(months: list[str]) -> list[dict]:
    print(f"\n{'='*65}")
    print("  PHASE 1 — Tạo dataset từ dữ liệu lịch sử")
    print(f"{'='*65}")
    print(f"  Tháng: {months}\n")

    all_trades = []
    coin_results = {}
    
    progress_file = LOGS_DIR / "build_progress.json"
    if progress_file.exists():
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                all_trades = state.get("all_trades", [])
                coin_results = state.get("coin_results", {})
            print(f"  [Resume] Tiếp tục từ mốc trước: đã xong {len(coin_results)} coin, {len(all_trades)} lệnh.\n")
        except Exception as e:
            print(f"  [Warning] Không thể đọc {progress_file}, sẽ chạy lại từ đầu: {e}\n")
            all_trades = []
            coin_results = {}

    for coin in COINS:
        if coin in coin_results:
            print(f"  [+] {coin} ... BỎ QUA (đã có kết quả)")
            continue

        print(f"  [+] {coin} ...", end=" ", flush=True)
        candles_15m = load_candles(coin, "15m", months)
        if not candles_15m:
            print("SKIP (thiếu dữ liệu 15m)")
            continue

        mtf_candles = {tf: load_candles(coin, tf, months) for tf in HTF_INTERVALS}
        coin_trades = simulate_coin(coin, candles_15m, mtf_candles)

        wins   = sum(1 for t in coin_trades if t.get("result") == "WIN")
        losses = len(coin_trades) - wins
        wr     = wins / len(coin_trades) * 100 if coin_trades else 0
        print(f"{len(coin_trades)} lệnh | WIN={wins} LOSS={losses} WR={wr:.1f}%")
        all_trades.extend(coin_trades)

        coin_results[coin] = {
            "total_trades": len(coin_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 2)
        }

        # Lưu state sau mỗi coin để có thể resume
        try:
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump({
                    "coin_results": coin_results,
                    "all_trades": all_trades
                }, f, ensure_ascii=False)
        except Exception as e:
            print(f"  [Error] Không thể lưu tiến độ: {e}")

    print(f"\n  [OK] Tổng: {len(all_trades)} lệnh")
    if all_trades:
        wins_total = sum(1 for t in all_trades if t.get("result") == "WIN")
        print(f"  WIN={wins_total} ({wins_total/len(all_trades)*100:.1f}%) | LOSS={len(all_trades)-wins_total}")

    results_file = LOGS_DIR / "build_results_by_coin.json"
    try:
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(coin_results, f, indent=2, ensure_ascii=False)
        print(f"  [Saved] Kết quả build từng coin → {results_file}")
        
        # Nếu build xong toàn bộ, xóa file progress để lần chạy sau build lại từ đầu
        if progress_file.exists():
            progress_file.unlink()
            
    except Exception as e:
        print(f"  [Error] Không thể lưu kết quả build: {e}")

    return all_trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build",   action="store_true")
    parser.add_argument("--no-calibrate", action="store_true")
    parser.add_argument("--n", type=int, default=200)
    args = parser.parse_args()

    LOGS_DIR.mkdir(exist_ok=True)

    # Tải sentiment history một lần duy nhất
    _load_sentiment_history()

    # ── Phase 1: Build Dataset ───────────────────────────────────────────────
    if not args.skip_build:
        months = get_available_months()
        if not months:
            print(f"[ERROR] Không tìm thấy dữ liệu CSV trong {DATA_DIR}")
            sys.exit(1)

        trades = build_dataset(months)
        if len(trades) < 30:
            print(f"\n[ERROR] Chỉ có {len(trades)} lệnh. Cần ít nhất 30 để train.")
            sys.exit(1)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2, ensure_ascii=False)
        print(f"\n  [Saved] Dataset → {OUTPUT_FILE} ({len(trades)} records)")
    else:
        if not OUTPUT_FILE.exists():
            print(f"[ERROR] File không tồn tại: {OUTPUT_FILE}. Chạy lại không có --skip-build.")
            sys.exit(1)
        print(f"[Skip] Dùng dataset có sẵn: {OUTPUT_FILE}")

    # ── Phase 2: Train Model ─────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  PHASE 2 — Train Ensemble Meta Model (V2)")
    print(f"{'='*65}")
    print(f"  Input     : {MODEL_INPUT}")
    print(f"  Estimators: {args.n} | Calibrate: {not args.no_calibrate}\n")

    try:
        metrics = train_meta_model(
            n_estimators=args.n,
            cv=5,
            calibrate=not args.no_calibrate,
        )
        print(f"\n{'='*65}")
        print("  HOÀN TẤT!")
        print(f"{'='*65}")
        print(f"  Samples      : {metrics['n_samples']}")
        print(f"  Features     : {metrics['n_features']}")
        if metrics.get("cv_auc_mean") is not None:
            print(f"  Base AUC     : {metrics['cv_auc_mean']:.4f} ± {metrics.get('cv_auc_std', 0):.4f}")
        if metrics.get("ensemble_cv_auc_mean") is not None:
            print(f"  Ensemble AUC : {metrics['ensemble_cv_auc_mean']:.4f}")
        print(f"  Calibration  : {metrics.get('calibration_method', 'none')}")
        wf = metrics.get("walk_forward", [])
        if wf:
            valid_aucs = [w["roc_auc"] for w in wf if w.get("roc_auc") is not None]
            if valid_aucs:
                avg = sum(valid_aucs) / len(valid_aucs)
                print(f"  Walk-Forward : {avg:.4f} avg ({len(valid_aucs)} folds)")
    except Exception as e:
        import traceback
        print(f"\n[ERROR] Training thất bại: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
