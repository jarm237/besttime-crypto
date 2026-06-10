"""
Simple backtest harness to evaluate Signal Scoring.
- Loads historical candles CSV from data/ (expects files like BTC_15m.csv)
- Calls analysis.analyze_all_market to get per-candle analysis (including signal_score)
- Simulates simple intraday entries: when signal_score.action==BUY -> enter long at next candle open
  - Uses tp_sl from analysis to set TP1/SL
  - Exits when TP1/TP2/SL hit
- Aggregates basic metrics: total trades, wins, losses, win rate, avg pnl

Usage:
  python scripts/backtest_signal_scoring.py data/BTC_15m.csv --capital 1000 --symbol BTC
"""

import csv
import sys
import os
import argparse
from typing import List, Dict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from btc_scraper.analysis import analyze_all_market
from btc_scraper.adaptive_scoring import log_trade_outcome


def load_csv(path: str) -> List[Dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # convert common numeric fields
            r2 = dict(r)
            for k in ["open", "high", "low", "close", "volume"]:
                if k in r2:
                    try:
                        r2[k] = float(r2[k])
                    except Exception:
                        r2[k] = 0.0
            rows.append(r2)
    return rows


class SimpleBacktest:
    def __init__(self, candles: List[Dict], capital: float = 1000.0, log_adaptive: bool = False, symbol: str = "BTC"):
        self.candles = candles
        self.capital = capital
        self.trades = []
        self.log_adaptive = log_adaptive
        self.symbol = symbol

    def run(self):
        analyses = analyze_all_market(self.candles)
        # build time->index for candles
        time_to_idx = {c["time"]: i for i, c in enumerate(self.candles)}

        for ana in analyses:
            sig_score = ana.get("signal_score") or {}
            action = sig_score.get("action")
            score = sig_score.get("score", 50)
            ana_time = ana.get("time")
            if ana_time not in time_to_idx:
                continue
            base_idx = time_to_idx[ana_time]
            # enter at next candle open
            entry_idx = base_idx + 1
            if entry_idx >= len(self.candles):
                continue

            entry_price = self.candles[entry_idx]["open"]
            tp1 = ana.get("tp_sl", {}).get("tp1")
            tp2 = ana.get("tp_sl", {}).get("tp2")
            sl = ana.get("tp_sl", {}).get("sl")

            if action == "BUY" and score >= 65:
                result = self.simulate_trade(entry_idx, entry_price, tp1, tp2, sl, direction="LONG")
                if result:
                    result.update({"direction": "LONG", "score": score, "signal_time": ana_time, "entry_idx": entry_idx})
                    self.trades.append(result)
                    if self.log_adaptive:
                        self._log_adaptive(result, ana)
            elif action == "SELL" and score <= 35:
                result = self.simulate_trade(entry_idx, entry_price, tp1, tp2, sl, direction="SHORT")
                if result:
                    result.update({"direction": "SHORT", "score": score, "signal_time": ana_time, "entry_idx": entry_idx})
                    self.trades.append(result)
                    if self.log_adaptive:
                        self._log_adaptive(result, ana)

    def _log_adaptive(self, result: Dict, ana: Dict):
        closed_data = dict(ana)
        closed_data["coin"] = self.symbol
        closed_data["entry_price"] = result["entry"]
        closed_data["sell_price"] = result["exit"]
        closed_data["pnl_pct"] = result["pnl_pct"]
        closed_data["result"] = result["result"]
        closed_data["hold_hours"] = round((result.get("exit_idx", result["entry_idx"]) - result["entry_idx"]) * 0.25, 2)
        closed_data["exit_time"] = self.candles[result["exit_idx"]]["time"] if "exit_idx" in result else ""
        log_trade_outcome(closed_data)

    def simulate_trade(self, start_idx: int, entry: float, tp1: float, tp2: float, sl: float, direction: str):
        # simple: iterate candles from start_idx, check high/low
        for j in range(start_idx, len(self.candles)):
            h = self.candles[j]["high"]
            l = self.candles[j]["low"]
            # LONG
            if direction == "LONG":
                if sl and l <= sl:
                    pnl = (sl - entry) / entry * 100
                    return {"entry": entry, "exit": sl, "pnl_pct": round(pnl, 3), "result": "LOSS", "exit_idx": j}
                if tp2 and h >= tp2:
                    pnl = (tp2 - entry) / entry * 100
                    return {"entry": entry, "exit": tp2, "pnl_pct": round(pnl, 3), "result": "WIN", "exit_idx": j}
                if tp1 and h >= tp1:
                    pnl = (tp1 - entry) / entry * 100
                    return {"entry": entry, "exit": tp1, "pnl_pct": round(pnl, 3), "result": "WIN", "exit_idx": j}
            else:
                # SHORT
                if sl and h >= sl:
                    pnl = (entry - sl) / entry * 100
                    return {"entry": entry, "exit": sl, "pnl_pct": round(pnl, 3), "result": "LOSS", "exit_idx": j}
                if tp2 and l <= tp2:
                    pnl = (entry - tp2) / entry * 100
                    return {"entry": entry, "exit": tp2, "pnl_pct": round(pnl, 3), "result": "WIN", "exit_idx": j}
                if tp1 and l <= tp1:
                    pnl = (entry - tp1) / entry * 100
                    return {"entry": entry, "exit": tp1, "pnl_pct": round(pnl, 3), "result": "WIN", "exit_idx": j}
        return None

    def summary(self):
        wins = [t for t in self.trades if t["result"] == "WIN"]
        losses = [t for t in self.trades if t["result"] == "LOSS"]
        total = len(self.trades)
        win_rate = len(wins) / total * 100 if total else 0
        avg_pnl = sum(t["pnl_pct"] for t in self.trades) / total if total else 0
        print(f"Trades: {total} | Wins: {len(wins)} | Losses: {len(losses)} | WinRate: {win_rate:.1f}% | AvgPnL: {avg_pnl:.2f}%")

    def export_csv(self, path: str):
        if not self.trades:
            print(f"No trades to export to {path}")
            return
        # determine columns
        cols = []
        for t in self.trades:
            for k in t.keys():
                if k not in cols:
                    cols.append(k)
        try:
            with open(path, "w", encoding="utf-8", newline='') as f:
                import csv
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for t in self.trades:
                    writer.writerow(t)
            print(f"Exported {len(self.trades)} trades to {path}")
        except Exception as e:
            print(f"Failed to export trades to CSV: {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("file", help="CSV candles file path")
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--symbol", default="BTC")
    p.add_argument("--log-adaptive", action="store_true", help="Log simulated trades to adaptive_signals.json")
    args = p.parse_args()

    candles = load_csv(args.file)
    bt = SimpleBacktest(candles, capital=args.capital, log_adaptive=args.log_adaptive, symbol=args.symbol)
    bt.run()
    bt.summary()
    out_csv = os.path.join(".", f"backtest_signal_trades_{args.symbol}.csv")
    bt.export_csv(out_csv)
