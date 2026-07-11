"""
Compute rolling 7/30/90d metrics from logs/predictions_YYYY-MM-DD.log and data/closed_trades.json.
Writes a JSON report to logs/meta_model_monitor_{now}.json and prints a short summary.

Usage:
  python scripts/meta_model_monitor.py --days 7 30 90
  python scripts/meta_model_monitor.py --asof 2026-06-19T00:00:00

Optional Slack webhook (env var `META_MODEL_SLACK_WEBHOOK`) can be used later for alerts.
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import argparse

BASE = os.path.dirname(os.path.dirname(__file__))
LOGS = os.path.join(BASE, "logs")
PRED_LOG_DIR = LOGS  # thư mục chứa các file predictions_YYYY-MM-DD.log
TRADES_PATH = os.path.join(BASE, "data", "closed_trades.json")


def parse_iso(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp, luôn trả về offset-naive UTC datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        # Nếu có timezone info, chuyển về UTC rồi loại bỏ tzinfo
        if dt.tzinfo is not None:
            import calendar
            epoch = calendar.timegm(dt.utctimetuple())
            dt = datetime.utcfromtimestamp(epoch).replace(microsecond=dt.microsecond)
        return dt
    except Exception:
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M")
            except Exception:
                return None


def load_predictions(logs_dir: str) -> List[Dict[str, Any]]:
    """Load tất cả predictions từ các file predictions_YYYY-MM-DD.log.
    
    Backward-compatible: nếu file predictions.log cũ tồn tại thì cũng đọc kèm.
    """
    import glob

    preds = []

    # Đọc các file theo ngày
    pattern = os.path.join(logs_dir, "predictions_????-??-??.log")
    daily_files = sorted(glob.glob(pattern))
    for fpath in daily_files:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get("timestamp")
                dt = parse_iso(ts)
                obj["_ts"] = dt
                preds.append(obj)

    # Backward-compatible: đọc file predictions.log cũ nếu còn tồn tại
    legacy_path = os.path.join(logs_dir, "predictions.log")
    if os.path.exists(legacy_path):
        with open(legacy_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                ts = obj.get("timestamp")
                dt = parse_iso(ts)
                obj["_ts"] = dt
                preds.append(obj)

    # Sắp xếp theo timestamp
    preds.sort(key=lambda x: x.get("timestamp", ""))
    return preds


def load_trades(path: str) -> List[Dict[str, Any]]:
    trades = []
    if not os.path.exists(path):
        return trades
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for r in data:
                # Prefer exit_time as the trade-close timestamp
                t = r.get("exit_time") or r.get("entry_time") or r.get("entry_time_str")
                dt = parse_iso(t) if isinstance(t, str) else None
                r["_ts"] = dt
                trades.append(r)
    except Exception:
        return []
    return trades


def metrics_for_window(preds: List[Dict[str, Any]], trades: List[Dict[str, Any]], days: int, asof: Optional[datetime]) -> Dict[str, Any]:
    end = asof or datetime.utcnow()
    start = end - timedelta(days=days)

    pwin = [p for p in preds if p.get("_ts") and start <= p.get("_ts") <= end]
    twin = [t for t in trades if t.get("_ts") and start <= t.get("_ts") <= end]

    def safe_float(x):
        try:
            return float(x)
        except Exception:
            return None

    pred_count = len(pwin)
    avg_prob = None
    pct_high = None
    by_coin = {}
    if pred_count:
        probs = [safe_float(p.get("probability") or p.get("prob")) for p in pwin]
        probs = [p for p in probs if p is not None]
        avg_prob = sum(probs) / len(probs) if probs else None
        pct_high = sum(1 for p in probs if p >= 0.75) / len(probs) if probs else None
        for p in pwin:
            c = p.get("coin") or "UNKNOWN"
            by_coin[c] = by_coin.get(c, 0) + 1

    trade_count = len(twin)
    wins = sum(1 for t in twin if str(t.get("result","")).upper() == "WIN")
    win_rate = wins / trade_count if trade_count else None
    avg_pnl = None
    pnls = [safe_float(t.get("pnl") or t.get("pnl_pct") or t.get("pnl_pct_usd")) for t in twin]
    pnls = [p for p in pnls if p is not None]
    if pnls:
        avg_pnl = sum(pnls) / len(pnls)

    return {
        "window_days": days,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "predictions": {"count": pred_count, "avg_probability": avg_prob, "pct_prob_ge_0_75": pct_high, "by_coin": by_coin},
        "trades": {"count": trade_count, "wins": wins, "win_rate": win_rate, "avg_pnl": avg_pnl},
        "delta_prob_vs_winrate": (avg_prob - win_rate) if (avg_prob is not None and win_rate is not None) else None,
    }


def make_report(days_list: List[int], asof: Optional[datetime] = None) -> Dict[str, Any]:
    preds = load_predictions(PRED_LOG_DIR)
    trades = load_trades(TRADES_PATH)

    report = {"generated_at": (asof or datetime.utcnow()).isoformat(), "windows": {}}
    for d in days_list:
        report["windows"][str(d)] = metrics_for_window(preds, trades, d, asof)
    report["predictions_loaded"] = len(preds)
    report["trades_loaded"] = len(trades)
    return report


def save_report(report: Dict[str, Any], out_dir: str = None) -> str:
    out_dir = out_dir or LOGS
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(out_dir, f"meta_model_monitor_{now}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, nargs="+", default=[7,30,90], help="Window sizes in days")
    p.add_argument("--asof", type=str, default=None, help="ISO timestamp to treat as 'now' (e.g. 2026-06-19T00:00:00)")
    args = p.parse_args()

    asof_dt = None
    if args.asof:
        asof_dt = parse_iso(args.asof)

    report = make_report(args.days, asof_dt)
    out_path = save_report(report)
    print(f"Wrote monitor report to: {out_path}")
    # Print concise summary
    for d, w in report["windows"].items():
        pinfo = w["predictions"]
        tinfo = w["trades"]
        print(f"Window {d}d: preds={pinfo['count']}, avg_prob={pinfo['avg_probability']}, trades={tinfo['count']}, win_rate={tinfo['win_rate']}")


if __name__ == "__main__":
    main()
