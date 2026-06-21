#!/usr/bin/env python3
"""Run baseline backtest, then lower any meta prob >=0.7 to 0.65 and re-run backtest."""
from pathlib import Path
import sys
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

def main():
    import backtest as bt
    import importlib
    from btc_scraper.ml_engine import meta_model as mm

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

    print("[lower-run] Running baseline backtest...")
    net_baseline = bt.run_backtest()
    baseline_log = _copy_trade_log(f"baseline_{ts}")

    # Patch predict_meta_confidence: any prob >= 0.7 -> 0.65
    orig = getattr(mm, "predict_meta_confidence")
    def patched(analysis_info):
        res = orig(analysis_info)
        try:
            p = res.get("probability")
            if p is not None and p >= 0.7:
                res["probability"] = 0.65
        except Exception:
            pass
        return res

    setattr(mm, "predict_meta_confidence", patched)

    print("[lower-run] Running adjusted backtest (high-conf -> 0.65)...")
    net_adjusted = bt.run_backtest()
    adjusted_log = _copy_trade_log(f"lowered_0.65_{ts}")

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "baseline_net": net_baseline,
        "adjusted_net": net_adjusted,
        "adjustment": "prob>=0.7 -> 0.65",
        "baseline_log": baseline_log,
        "adjusted_log": adjusted_log,
    }
    out = LOGS / f"backtest_lower_highconf_summary_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        import json
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[lower-run] Saved summary to {out}")

if __name__ == '__main__':
    main()
