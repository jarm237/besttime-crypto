"""
Sweep META_REJECT_THRESHOLD values and run backtest for each.
- For each threshold value, set environment variable `META_REJECT_THRESHOLD` and run `python backtest.py`.
- Save trade logs per-run and a summary JSON in `logs/backtest_threshold_sweep_<timestamp>.json`.

Run: python scripts/backtest_threshold_sweep.py --thresholds 0.0 0.2 0.4 0.6 0.8
"""
from __future__ import annotations
import os
import sys
import json
import shutil
from datetime import datetime
import subprocess
import argparse

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LOGS = os.path.join(ROOT, "logs")
os.makedirs(LOGS, exist_ok=True)
OUT = os.path.join(LOGS, f"backtest_threshold_sweep_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json")

p = argparse.ArgumentParser()
p.add_argument("--thresholds", nargs="*", type=float, default=[0.0, 0.2, 0.4, 0.6, 0.8])
args = p.parse_args()

results = {"generated_at": datetime.utcnow().isoformat(), "runs": []}

for t in args.thresholds:
    name = f"thr_{int(t*100)}"
    print(f"Running backtest with META_REJECT_THRESHOLD={t}...")
    env = os.environ.copy()
    env["META_REJECT_THRESHOLD"] = str(t)
    # Run backtest as subprocess to isolate env
    rc = subprocess.run([sys.executable, "backtest.py"], env=env, cwd=ROOT)
    run_entry = {"threshold": t, "exit_code": rc.returncode}
    # copy trade log
    trade_log = os.path.join(LOGS, "backtest_trades.csv")
    if os.path.exists(trade_log):
        per = os.path.join(LOGS, f"backtest_trades_{name}.csv")
        try:
            shutil.copy2(trade_log, per)
            run_entry["trade_log"] = per
        except Exception as e:
            run_entry["trade_log_error"] = str(e)
    else:
        run_entry["trade_log"] = None
    results["runs"].append(run_entry)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Saved sweep summary to {OUT}")
