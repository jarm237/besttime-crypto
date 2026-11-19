"""Track A v1 Forward Paper Observer (Manual Terminal Runner).

A standalone observation runner that tracks Track A v1 decisions, Donchian channels,
signals, simulated execution fills (at 30 bps), fees, NAV, and drawdown in forward
paper observation mode without broker or live exchange interaction.

Usage:
    python scripts/run_track_a_v1_paper_observer.py --status
    python scripts/run_track_a_v1_paper_observer.py --step
    python scripts/run_track_a_v1_paper_observer.py --dry-run
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_scraper.research.s5_economic_replay import solve_post_fee_equity
from btc_scraper.research.track_a_strategy import (
    LOOKBACK_HORIZONS,
    TRACK_A_NO_TRADE_BAND,
    DailySignalRecord,
    build_btc_daily_candles,
    compute_track_a_signals,
    load_universe_panels,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO_ROOT / "research/track_a/paper"
PAPER_STATE_FILE = PAPER_DIR / "track_a_v1_paper_state.json"
PAPER_LEDGER_FILE = PAPER_DIR / "track_a_v1_paper_ledger.csv"

FEE_BPS_PAPER = 30.0
INITIAL_PAPER_CAPITAL = 10000.0


def load_paper_state() -> dict[str, Any]:
    """Load current paper portfolio state or initialize with $10,000 USDT."""
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    if PAPER_STATE_FILE.exists():
        with open(PAPER_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "inception_utc": datetime.now(timezone.utc).isoformat(),
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "initial_capital": INITIAL_PAPER_CAPITAL,
        "cash": INITIAL_PAPER_CAPITAL,
        "btc_holdings": 0.0,
        "current_equity": INITIAL_PAPER_CAPITAL,
        "peak_equity": INITIAL_PAPER_CAPITAL,
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "total_traded_notional": 0.0,
        "total_fees": 0.0,
        "num_trades": 0,
        "last_decision_date": None,
        "last_approved_exposure": 0.0,
        "last_raw_exposure": 0.0,
    }


def save_paper_state(state: dict[str, Any]) -> None:
    """Save paper portfolio state."""
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    with open(PAPER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def append_paper_ledger_entry(entry: dict[str, Any]) -> None:
    """Append paper decision and simulated execution to CSV ledger."""
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    df_entry = pd.DataFrame([entry])
    if not PAPER_LEDGER_FILE.exists():
        df_entry.to_csv(PAPER_LEDGER_FILE, index=False)
    else:
        df_entry.to_csv(PAPER_LEDGER_FILE, mode="a", header=False, index=False)


def run_observer_step(dry_run: bool = False) -> dict[str, Any]:
    """Evaluate latest decision and simulate execution if triggered."""
    state = load_paper_state()
    panels = load_universe_panels(REPO_ROOT)
    btc_hourly = panels["BTCUSDT"]
    btc_daily = build_btc_daily_candles(btc_hourly)
    signals = compute_track_a_signals(btc_daily)

    latest_decision_dt = max(signals.keys())
    sig: DailySignalRecord = signals[latest_decision_dt]

    # Latest hourly bar for simulated execution
    latest_hourly_ts = btc_hourly.index[-1]
    latest_price = float(btc_hourly.iloc[-1]["close"])
    exec_price = float(btc_hourly.iloc[-1]["open"])

    # Mark to market prior to rebalance
    pre_btc_notional = state["btc_holdings"] * exec_price
    v_pre = state["cash"] + pre_btc_notional
    current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
    target_w = sig.approved_exposure
    deviation = abs(target_w - current_w)

    action = "HOLD"
    trade_notional = 0.0
    realized_fee = 0.0
    v_post = v_pre
    new_holdings = state["btc_holdings"]
    new_cash = state["cash"]

    if deviation > TRACK_A_NO_TRADE_BAND:
        action = "REBALANCE"
        fee_rate = FEE_BPS_PAPER / 10000.0
        current_notionals = np.array([pre_btc_notional])
        target_weights = np.array([target_w])
        v_post, realized_fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)

        target_notional = target_w * v_post
        trade_notional = abs(target_notional - pre_btc_notional)
        new_holdings = target_notional / exec_price
        new_cash = (1.0 - target_w) * v_post

    # Mark to market at latest close
    current_eq = new_cash + new_holdings * latest_price
    peak_eq = max(state["peak_equity"], current_eq)
    dd = (current_eq - peak_eq) / peak_eq if peak_eq > 0 else 0.0
    max_dd = min(state["max_drawdown"], dd)

    ledger_entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "decision_dt": latest_decision_dt.isoformat(),
        "candle_dt": sig.candle_dt.isoformat(),
        "close_price": sig.close_price,
        "state_20": sig.state_20,
        "state_55": sig.state_55,
        "state_90": sig.state_90,
        "raw_exposure": sig.raw_exposure,
        "approved_exposure": sig.approved_exposure,
        "confirmed": sig.confirmed,
        "current_btc_weight": current_w,
        "target_btc_weight": target_w,
        "deviation": deviation,
        "action": action,
        "exec_price": exec_price,
        "trade_notional": trade_notional,
        "realized_fee": realized_fee,
        "post_cash": new_cash,
        "post_btc_holdings": new_holdings,
        "nav": current_eq,
        "peak_nav": peak_eq,
        "drawdown": dd,
    }

    if not dry_run:
        state["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        state["cash"] = new_cash
        state["btc_holdings"] = new_holdings
        state["current_equity"] = current_eq
        state["peak_equity"] = peak_eq
        state["current_drawdown"] = dd
        state["max_drawdown"] = max_dd
        state["total_traded_notional"] += trade_notional
        state["total_fees"] += realized_fee
        if action == "REBALANCE":
            state["num_trades"] += 1
        state["last_decision_date"] = latest_decision_dt.isoformat()
        state["last_approved_exposure"] = sig.approved_exposure
        state["last_raw_exposure"] = sig.raw_exposure

        save_paper_state(state)
        append_paper_ledger_entry(ledger_entry)

    return ledger_entry


def print_status() -> None:
    state = load_paper_state()
    print("=== TRACK A V1 FORWARD PAPER OBSERVER STATUS ===")
    print(f"Inception UTC:         {state['inception_utc']}")
    print(f"Last Updated UTC:      {state['last_updated_utc']}")
    print(f"Initial Capital:       ${state['initial_capital']:,.2f}")
    print(f"Current NAV:           ${state['current_equity']:,.2f} ({((state['current_equity']/state['initial_capital'])-1)*100:+.2f}%)")
    print(f"Peak NAV:              ${state['peak_equity']:,.2f}")
    print(f"Current Drawdown:      {state['current_drawdown']*100:.2f}% (MaxDD: {state['max_drawdown']*100:.2f}%)")
    print(f"Cash Balance:          ${state['cash']:,.2f}")
    print(f"BTC Holdings:          {state['btc_holdings']:.6f} BTC")
    print(f"Last Approved Exposure:{state['last_approved_exposure']*100:.1f}%")
    print(f"Total Traded Notional: ${state['total_traded_notional']:,.2f}")
    print(f"Total Fees Incurred:   ${state['total_fees']:,.2f}")
    print(f"Total Rebalances:      {state['num_trades']}")
    print(f"State File:            {PAPER_STATE_FILE}")
    print(f"Ledger File:           {PAPER_LEDGER_FILE}")
    print("===============================================")


def main():
    parser = argparse.ArgumentParser(description="Track A v1 Forward Paper Observer")
    parser.add_argument("--status", action="store_true", help="Print current paper state and exit")
    parser.add_argument("--step", action="store_true", help="Evaluate latest bar and update paper ledger")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate latest bar without mutating state")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.step or args.dry_run:
        dry = args.dry_run
        entry = run_observer_step(dry_run=dry)
        mode_str = "[DRY-RUN] " if dry else ""
        print(f"{mode_str}Paper Observer Step Evaluated at {entry['timestamp_utc']}:")
        print(f"  Decision Date: {entry['decision_dt']} | Candle Date: {entry['candle_dt']}")
        print(f"  Close Price: ${entry['close_price']:,.2f}")
        print(f"  States [20, 55, 90]: [{entry['state_20']}, {entry['state_55']}, {entry['state_90']}]")
        print(f"  Raw Exposure: {entry['raw_exposure']*100:.1f}% | Confirmed: {entry['confirmed']} -> Approved: {entry['approved_exposure']*100:.1f}%")
        print(f"  Current Weight: {entry['current_btc_weight']*100:.1f}% | Target: {entry['target_btc_weight']*100:.1f}% | Deviation: {entry['deviation']*100:.1f}%")
        print(f"  Action: {entry['action']} (Band: {TRACK_A_NO_TRADE_BAND*100:.0f}%)")
        if entry["action"] == "REBALANCE":
            print(f"  Trade Notional: ${entry['trade_notional']:,.2f} | Fee (30 bps): ${entry['realized_fee']:,.2f}")
        print(f"  Updated NAV: ${entry['nav']:,.2f} | Drawdown: {entry['drawdown']*100:.2f}%")
    else:
        print_status()


if __name__ == "__main__":
    main()
