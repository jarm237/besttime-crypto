#!/usr/bin/env python3
"""Run baseline backtest, then force action=NEUTRAL when meta_prob < threshold, and re-run backtest."""
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

def run_threshold(threshold: float = 0.7):
    import importlib
    import backtest as bt
    mm = importlib.import_module("btc_scraper.ml_engine.meta_model")
    ss_module = importlib.import_module("btc_scraper.ml_engine.signal_score")

    # Run baseline
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    print(f"[hard-reject] Running baseline backtest...")
    net_baseline = bt.run_backtest()
    baseline_log = _copy_trade_log(f"baseline_{ts}")

    # Wrap predict_meta_confidence to set a flag on mm when prob < threshold
    orig_predict = getattr(mm, "predict_meta_confidence")
    def predict_wrapped(analysis_info):
        res = orig_predict(analysis_info)
        try:
            p = res.get("probability")
            mm._last_force_neutral = (p is not None and p < threshold)
        except Exception:
            mm._last_force_neutral = False
        return res
    setattr(mm, "predict_meta_confidence", predict_wrapped)

    # Wrap score_signal to force NEUTRAL when mm._last_force_neutral is set
    orig_score = getattr(ss_module, "score_signal")
    def score_wrapped(sig_text, data, context, htf_trend=None):
        out = orig_score(sig_text, data, context, htf_trend)
        try:
            if getattr(mm, "_last_force_neutral", False):
                out["action"] = "NEUTRAL"
                out["score"] = 50
                out["display_score"] = 0
                out["display_label"] = "NEUTRAL"
                out["confidence"] = "LOW"
                out["position_size"] = 0.05
                out["gated"] = True
        except Exception:
            pass
        return out
    setattr(ss_module, "score_signal", score_wrapped)

    print(f"[hard-reject] Running adjusted backtest (force NEUTRAL when prob<{threshold})...")
    net_adjusted = bt.run_backtest()
    adjusted_log = _copy_trade_log(f"hardreject_{int(threshold*100)}_{ts}")

    # Save summary
    import json
    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "threshold": threshold,
        "baseline_net": net_baseline,
        "adjusted_net": net_adjusted,
        "baseline_log": baseline_log,
        "adjusted_log": adjusted_log,
    }
    out = LOGS / f"backtest_hard_reject_summary_{int(threshold*100)}_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[hard-reject] Saved summary to {out}")
    return summary

def main():
    # default threshold 0.7
    run_threshold(0.7)

if __name__ == '__main__':
    main()
