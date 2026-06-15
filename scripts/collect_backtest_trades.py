#!/usr/bin/env python3
"""Run backtests for a set of sentiment penalties and append results
to adaptive_signals.json for adaptive training.
"""
import csv
import os
from backtest import run_backtest

from btc_scraper.ml_engine import adaptive_scoring

WEIGHTS = [-5, -10, -15, -20, -25, -30]


def migrate_csv_to_adaptive(csv_path: str):
    if not os.path.exists(csv_path):
        print(f"CSV not found: {csv_path}")
        return 0
    count = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                coin = row.get("coin")
                typ = row.get("type")
                entry = float(row.get("entry_price", 0))
                exitp = float(row.get("exit_price", 0))
                result = row.get("result")
                entry_time = row.get("entry_time")
                exit_time = row.get("exit_time")

                # Compute pnl_pct
                pnl_pct = 0.0
                if entry and exitp:
                    if typ == "LONG":
                        pnl_pct = (exitp - entry) / entry * 100
                    else:
                        pnl_pct = (entry - exitp) / entry * 100
                # Parse optional serialized signal_score and confidence
                ss_field = row.get("signal_score") or ""
                conf_field = row.get("confidence") or ""
                signal_score = {}
                try:
                    if ss_field:
                        signal_score = json.loads(ss_field)
                except Exception:
                    signal_score = {"raw": ss_field}

                try:
                    confidence = float(conf_field) if conf_field not in ("", None) else None
                except Exception:
                    confidence = None

                rec = {
                    "coin": coin,
                    "id": None,
                    "entry_price": entry,
                    "sell_price": exitp,
                    "pnl_pct": round(pnl_pct, 4),
                    "result": result,
                    "hold_hours": 0.0,
                    "exit_time": exit_time,
                    "signal_raw": None,
                    "signal_score": signal_score,
                    "confidence": confidence,
                }
                adaptive_scoring.log_trade_outcome(rec)
                count += 1
            except Exception:
                continue
    return count


def main():
    total = 0
    for w in WEIGHTS:
        print(f"\n--- Running backtest with sentiment_penalty={w} ---")
        run_backtest(initial_balance=10000.0, sentiment_penalty=w)
        csv_path = os.path.join("logs", "backtest_trades.csv")
        migrated = migrate_csv_to_adaptive(csv_path)
        print(f"Migrated {migrated} trades from {csv_path} to adaptive logs.")
        total += migrated

    print(f"\nDone. Total migrated trades: {total}")


if __name__ == "__main__":
    main()
