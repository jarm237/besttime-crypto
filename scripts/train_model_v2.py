"""
Train Model v2 - Ensemble Meta Model Trainer

This script builds adaptive signals from historical CSVs (same logic as
`train_april_model.py`), writes `logs/adaptive_signals.json`, then trains the
ensemble meta model in `btc_scraper.meta_model` and writes metrics.

Usage:
  python train_model_v2.py --train
  python train_model_v2.py --train --n 200 --no-calibrate
"""
import sys, os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ['DISABLE_KELLY'] = '1'

from datetime import datetime, timedelta
import json

from btc_scraper.core.config import COINS
import btc_scraper.core.sentiment

# Reuse functions from train_april_model to generate labeled trades
import train_april_model as old_train
from btc_scraper.ml_engine.meta_model import train_meta_model

# Load historical sentiment map
print("Loading historical sentiment map...")
HISTORICAL_SENTIMENT_MAP = old_train.HISTORICAL_SENTIMENT_MAP
HISTORICAL_SENTIMENT_MAP.clear()
HISTORICAL_SENTIMENT_MAP.update(btc_scraper.sentiment.get_historical_sentiment_map(limit=1000))
print(f"  Loaded {len(HISTORICAL_SENTIMENT_MAP)} sentiment entries")

MONTHS = [
    "january_2025", "february_2025", "march_2025", "april_2025", "may_2025", "june_2025",
    "july_2025", "august_2025", "september_2025", "october_2025", "november_2025", "december_2025",
    "january", "february", "march", "april", "may", "june"
]

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
SIGNALS_PATH = os.path.join(LOGS_DIR, "adaptive_signals.json")


def load_candles(coin: str, interval: str, months: list[str]) -> list[dict]:
    combined = []
    for m in months:
        combined.extend(old_train.load_candles_csv(coin, interval, m))
    # dedupe
    seen = set()
    dedup = []
    for c in combined:
        if c["time"] not in seen:
            seen.add(c["time"])
            dedup.append(c)
    dedup.sort(key=lambda x: x["time_dt"])
    return dedup


def build_signals():
    all_records = []
    missing = []
    total_unclosed = 0

    for coin in COINS:
        print(f"Processing {coin}...")
        candles_15m = load_candles(coin, "15m", MONTHS)
        if not candles_15m:
            missing.append(coin)
            continue

        mtf = {}
        for tf in ["1h", "4h", "1d"]:
            mtf[tf] = load_candles(coin, tf, MONTHS)

        records, n_unclosed = old_train.generate_labeled_trades(coin, candles_15m, mtf, sentiment_map=HISTORICAL_SENTIMENT_MAP)
        print(f"  Generated {len(records)} closed records, unclosed {n_unclosed}")
        total_unclosed += n_unclosed
        all_records.extend(records)

    if missing:
        print("Missing data for:", ", ".join(missing))

    if not all_records:
        raise RuntimeError("No records generated. Check CSV data.")

    # Write adaptive_signals.json compact format expected by meta_model
    compact = []
    for r in all_records:
        entry = {
            "coin": r.get("coin"),
            "result": r.get("result") or r.get("actual_result"),
            "pnl_pct": r.get("pnl_pct") or r.get("actual_pnl_pct"),
            "signal_raw": r.get("signal"),
            "entry_time": r.get("entry_time") or r.get("timestamp_str"),
            "exit_time": r.get("exit_time") or r.get("closed_at"),
            "htf_trend": r.get("htf_trend", ""),
            "signal_score": {
                "score": r.get("score") or r.get("signal_score") or 50,
                "raw_text": r.get("signal"),
                "action": "BUY" if (r.get("signal") or "").upper().find("BUY") >= 0 else "SELL",
            },
        }
        # inline features
        entry.update(r.get("features", {}))
        compact.append(entry)

    with open(SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(compact)} signals to {SIGNALS_PATH}")
    return len(compact)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true")
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--no-calibrate", action="store_true")
    args = p.parse_args()

    print("Building signals and training ensemble meta model (v2)...")
    try:
        n = build_signals()
    except Exception as e:
        print("Failed to build signals:", e)
        raise

    print("Starting ensemble training...")
    metrics = train_meta_model(n_estimators=args.n, cv=5, calibrate=not args.no_calibrate)
    print("Training complete. Metrics summary:")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
