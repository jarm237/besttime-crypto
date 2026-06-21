#!/usr/bin/env python3
"""Run baseline backtest, apply merged-bucket calibration adjustment, re-run backtest, save comparison."""
from pathlib import Path
import sys

# Ensure repo root is on sys.path so we can import top-level modules like `backtest`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import shutil
import json
from datetime import datetime

LOGS = Path("logs")
LOGS.mkdir(exist_ok=True)

def _copy_trade_log(suffix: str):
    src = LOGS / "backtest_trades.csv"
    if src.exists():
        dst = LOGS / f"backtest_trades_{suffix}.csv"
        shutil.copy(str(src), str(dst))
        return str(dst)
    return None

def _load_adjusted_prob():
    p = LOGS / "meta_model_agg_calibration.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            j = json.load(f)
        b = j.get("merged", {}).get("0.7-1.0", {})
        pr = b.get("predicted_wr")
        if pr is None:
            return None
        return float(pr) / 100.0
    except Exception:
        return None

def main():
    import backtest as bt
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

    print("[runner] Running baseline backtest...")
    net_baseline = bt.run_backtest()
    baseline_log = _copy_trade_log(f"baseline_{ts}")

    adjusted_prob = _load_adjusted_prob()
    if adjusted_prob is None:
        print("[runner] No adjusted probability found in logs/meta_model_agg_calibration.json — aborting adjusted run.")
        return

    print(f"[runner] Applying calibration adjustment: set prob>=0.7 -> {adjusted_prob:.3f}")
    import importlib
    mm = importlib.import_module("btc_scraper.ml_engine.meta_model")
    orig = getattr(mm, "predict_meta_confidence")

    def wrapped(analysis_info):
        res = orig(analysis_info)
        try:
            p = res.get("probability")
            if p is not None and p >= 0.7:
                res["probability"] = adjusted_prob
        except Exception:
            pass
        return res

    setattr(mm, "predict_meta_confidence", wrapped)

    print("[runner] Running adjusted backtest...")
    net_adjusted = bt.run_backtest()
    adjusted_log = _copy_trade_log(f"calib_adjust_{ts}")

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "baseline_net": net_baseline,
        "adjusted_net": net_adjusted,
        "adjusted_prob": adjusted_prob,
        "baseline_log": baseline_log,
        "adjusted_log": adjusted_log,
    }
    out = LOGS / f"backtest_calib_adjust_summary_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[runner] Saved summary to {out}")

if __name__ == "__main__":
    main()
