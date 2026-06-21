#!/usr/bin/env python3
"""Sweep META_HARD_REJECT_THRESHOLD env var and run backtests for each threshold."""
from pathlib import Path
import sys
import os
import json
from datetime import datetime
import shutil

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LOGS = Path("logs")
LOGS.mkdir(exist_ok=True)

def _copy_trade_log(suffix: str):
    src = LOGS / "backtest_trades.csv"
    if src.exists():
        dst = LOGS / f"backtest_trades_{suffix}.csv"
        shutil.copy(str(src), str(dst))
        return str(dst)
    return None

def run_env_sweep(thresholds):
    import importlib
    import backtest as bt
    results = []
    for t in thresholds:
        print(f"--- Running threshold {t} ---")
        os.environ['META_HARD_REJECT_THRESHOLD'] = str(t)
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        net = bt.run_backtest()
        log = _copy_trade_log(f"env_hardreject_{int(t*100)}_{ts}")
        results.append({'threshold': t, 'net': net, 'log': log})
        # clear env
        os.environ.pop('META_HARD_REJECT_THRESHOLD', None)
    out = LOGS / f"backtest_hard_reject_env_sweep_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json"
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved sweep summary to {out}")
    return results

if __name__ == '__main__':
    THRESHOLDS = [0.5, 0.6, 0.7, 0.8]
    run_env_sweep(THRESHOLDS)
