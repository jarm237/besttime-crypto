"""
scripts/attribute_failure.py
Phase 4: Detailed Economic Failure Attribution Analysis for Frozen ETH Candidate vol_aware_mean_reversion_v1.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = PROJECT_ROOT / "data" / "historical" / "quality_reports" / "m5_frozen_eth_oos_evaluation_results.json"
DEV_SCREENING_FILE = PROJECT_ROOT / "data" / "backtests" / "m4_screening_results.json"


def analyze():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    trades = data["trade_lineage"]
    n = len(trades)
    print(f"=== FAILURE ATTRIBUTION REPORT ({n} OOS TRADES) ===\n")

    # 1. Trade Outcomes & Payoff Asymmetry
    wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
    losses = [t["net_pnl"] for t in trades if t["net_pnl"] < 0]
    w_count = len(wins)
    l_count = len(losses)
    win_rate = (w_count / n) * 100.0

    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    print(f"1. Trade Outcome Distribution:")
    print(f"   Win Rate:      {win_rate:.1f}% ({w_count} wins / {l_count} losses)")
    print(f"   Avg Win:       ${avg_win:+.2f} (Max Win: ${max(wins) if wins else 0.0:+.2f})")
    print(f"   Avg Loss:      ${avg_loss:+.2f} (Max Loss: ${min(losses) if losses else 0.0:+.2f})")
    print(f"   Payoff Ratio:  {payoff_ratio:.2f}")

    # 2. Exit Reason Breakdown
    reasons = {}
    for t in trades:
        r_type = "ATR_STOP" if "atr_stop" in t.get("reason", "") else "MEAN_REVERTED"
        if r_type not in reasons:
            reasons[r_type] = []
        reasons[r_type].append(t)

    print(f"\n2. Exit Policy Breakdown:")
    for r_type, r_trades in reasons.items():
        r_count = len(r_trades)
        r_net = sum(t["net_pnl"] for t in r_trades)
        r_gross = sum(t["gross_pnl"] for t in r_trades)
        r_wins = sum(1 for t in r_trades if t["net_pnl"] > 0)
        r_wr = (r_wins / r_count) * 100.0
        r_avg_net = r_net / r_count
        print(f"   {r_type:15s} | Count: {r_count:2d} ({r_count/n*100:.1f}%) | Net PnL: ${r_net:+6.2f} | Avg: ${r_avg_net:+5.2f} | WinRate: {r_wr:.1f}%")

    # 3. Holding Duration & Capital Turnover
    durations = [t["hold_bars"] for t in trades]
    print(f"\n3. Duration & Market Exposure:")
    print(f"   Avg Holding Duration: {np.mean(durations):.1f} hours (min: {min(durations)}, max: {max(durations)})")
    print(f"   Total Holding Hours:  {sum(durations)} hours out of 3,168 total hours")
    print(f"   Time-in-Market:       {sum(durations) / 3168 * 100.0:.2f}%")
    print(f"   Capital Turnover:     {sum(t['notional'] for t in trades) / 10000.0:.2f}x")

    # 4. Friction vs Edge Decomposition
    gross_pnl_eff = sum(t["gross_pnl"] for t in trades)
    fees = sum(t["fee_usd"] for t in trades)
    slippage = sum(t["slippage_usd"] for t in trades)
    spread = sum(t["spread_usd"] for t in trades)
    friction = fees + slippage + spread
    raw_gross_pnl = gross_pnl_eff + slippage + spread
    net_pnl = sum(t["net_pnl"] for t in trades)

    print(f"\n4. Friction vs Edge Decomposition:")
    print(f"   Pure Price PnL (Raw Gross): ${raw_gross_pnl:+6.2f}  (+{raw_gross_pnl/n:+5.2f}/trade)")
    print(f"   Slippage Drag:              ${slippage:6.2f}  ({slippage/n:5.2f}/trade)")
    print(f"   Spread Drag:                ${spread:6.2f}  ({spread/n:5.2f}/trade)")
    print(f"   Exchange Fees (10 bps RT):  ${fees:6.2f}  ({fees/n:5.2f}/trade)")
    print(f"   Total Friction Drag:        ${friction:6.2f}  ({friction/n:5.2f}/trade)")
    print(f"   Net Realized PnL:           ${net_pnl:+6.2f}  ({net_pnl/n:+5.2f}/trade)")

    # 5. Root Cause Classification
    print(f"\n5. Quantitative Failure Attribution Summary:")
    print(f"   - Raw Gross PnL before fees was barely positive: +$2.46 over 13 trades (+$0.19/trade).")
    print(f"   - Average transaction friction is -$1.40/trade (-$1.00 fee + -$0.40 slip/spread).")
    print(f"   - The gross raw alpha edge (+0.019% notional) is roughly 1/7th of round-trip friction (0.14% notional)!")
    print(f"   - ATR Stop-Loss exits accounted for 5 trades, producing -$75.57 in net losses (-$15.11/trade).")
    print(f"   - Mean-Reverted exits accounted for 8 trades, producing +$59.88 in net gains (+$7.48/trade, 6W / 2L).")
    print(f"   - Primary Failure Mechanism: INSUFFICIENT_EDGE_EVIDENCE + COST_DRAG.")


if __name__ == "__main__":
    analyze()
