#!/usr/bin/env python3
"""Sweep hard-reject thresholds and run backtests for each threshold."""
from pathlib import Path
import sys
from datetime import datetime
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from btc_scraper import ml_engine
import importlib

def run_sweep(thresholds):
    from scripts import backtest_hard_reject as bhr
    results = []
    for t in thresholds:
        print(f"--- Running threshold {t} ---")
        summary = bhr.run_threshold(t)
        results.append(summary)
    out = Path("logs") / f"backtest_hard_reject_sweep_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved sweep summary to {out}")
    return results

if __name__ == '__main__':
    THRESHOLDS = [0.5, 0.6, 0.7, 0.8]
    run_sweep(THRESHOLDS)
