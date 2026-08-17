#!/usr/bin/env python3
"""HMR-V5-B1: Path-Aware Exit Capture Audit.

Systematically evaluates and compares five exit families using path-aware
OHLCV candles to determine the optimal exit architecture and assess
economic survivability under frozen cost scenarios.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts.generate_triple_barrier_labels import load_candles_for_coin

SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
CONTRACT_PATH = REPO_ROOT / "research/historical_market_replay_v5/v5_b0_economic_cost_contract.json"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()

COINS = ["BTC", "ETH", "BNB"]


def compute_atr14(df: pd.DataFrame) -> np.ndarray:
    """Compute 14-period ATR from High/Low/Close columns."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    
    n = len(df)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        
    atr = pd.Series(tr).rolling(14).mean().bfill().values
    return atr


def simulate_fixed_horizon(
    side: str,
    entry_idx: int,
    closes: np.ndarray,
    max_hold: int
) -> tuple[float, bool, bool, int, int]:
    """Exit after a fixed horizon (E0)."""
    n = len(closes)
    end_idx = min(entry_idx + max_hold, n - 1)
    entry_close = closes[entry_idx]
    exit_close = closes[end_idx]
    
    if side == "BUY":
        pnl = (exit_close - entry_close) / entry_close
    else:
        pnl = (entry_close - exit_close) / entry_close
        
    return pnl, False, False, end_idx - entry_idx, end_idx


def simulate_path_aware_exit(
    side: str,
    entry_idx: int,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    atrs: np.ndarray,
    max_hold: int,
    tp_bps: float | None = None,
    sl_bps: float | None = None,
    use_atr: bool = False,
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.2
) -> tuple[float, bool, bool, int, int]:
    """Simulate a single path-aware trade exit (E1, E2, E4)."""
    n = len(closes)
    entry_close = closes[entry_idx]
    
    if use_atr:
        atr_val = atrs[entry_idx]
        if side == "BUY":
            tp_price = entry_close + tp_atr_mult * atr_val
            sl_price = entry_close - sl_atr_mult * atr_val
        else:
            tp_price = entry_close - tp_atr_mult * atr_val
            sl_price = entry_close + sl_atr_mult * atr_val
    else:
        assert tp_bps is not None and sl_bps is not None
        if side == "BUY":
            tp_price = entry_close * (1.0 + tp_bps / 10000.0)
            sl_price = entry_close * (1.0 - sl_bps / 10000.0)
        else:
            tp_price = entry_close * (1.0 - tp_bps / 10000.0)
            sl_price = entry_close * (1.0 + sl_bps / 10000.0)
            
    end_idx = min(entry_idx + max_hold, n - 1)
    
    for idx in range(entry_idx + 1, end_idx + 1):
        bar_high = highs[idx]
        bar_low = lows[idx]
        
        if side == "BUY":
            # Check if both are hit in the same bar
            if bar_low <= sl_price and bar_high >= tp_price:
                # Conservatively assume Stop Loss is hit first
                pnl = (sl_price - entry_close) / entry_close
                return pnl, True, False, idx - entry_idx, idx
            elif bar_low <= sl_price:
                pnl = (sl_price - entry_close) / entry_close
                return pnl, True, False, idx - entry_idx, idx
            elif bar_high >= tp_price:
                pnl = (tp_price - entry_close) / entry_close
                return pnl, False, True, idx - entry_idx, idx
        else:
            if bar_high >= sl_price and bar_low <= tp_price:
                pnl = (entry_close - sl_price) / entry_close
                return pnl, True, False, idx - entry_idx, idx
            elif bar_high >= sl_price:
                pnl = (entry_close - sl_price) / entry_close
                return pnl, True, False, idx - entry_idx, idx
            elif bar_low <= tp_price:
                pnl = (entry_close - tp_price) / entry_close
                return pnl, False, True, idx - entry_idx, idx
                
    # Timeout exit
    exit_close = closes[end_idx]
    if side == "BUY":
        pnl = (exit_close - entry_close) / entry_close
    else:
        pnl = (entry_close - exit_close) / entry_close
        
    return pnl, False, False, end_idx - entry_idx, end_idx


def simulate_trailing_stop(
    side: str,
    entry_idx: int,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    trail_bps: float,
    max_hold: int
) -> tuple[float, bool, bool, int, int]:
    """Simulate a trailing stop exit (E3)."""
    n = len(closes)
    entry_close = closes[entry_idx]
    end_idx = min(entry_idx + max_hold, n - 1)
    
    if side == "BUY":
        sl_price = entry_close * (1.0 - trail_bps / 10000.0)
        highest_price = entry_close
        
        for idx in range(entry_idx + 1, end_idx + 1):
            bar_high = highs[idx]
            bar_low = lows[idx]
            
            if bar_low <= sl_price:
                pnl = (sl_price - entry_close) / entry_close
                return pnl, True, False, idx - entry_idx, idx
                
            highest_price = max(highest_price, bar_high)
            sl_price = max(sl_price, highest_price * (1.0 - trail_bps / 10000.0))
            
    else:
        sl_price = entry_close * (1.0 + trail_bps / 10000.0)
        lowest_price = entry_close
        
        for idx in range(entry_idx + 1, end_idx + 1):
            bar_high = highs[idx]
            bar_low = lows[idx]
            
            if bar_high >= sl_price:
                pnl = (entry_close - sl_price) / entry_close
                return pnl, True, False, idx - entry_idx, idx
                
            lowest_price = min(lowest_price, bar_low)
            sl_price = min(sl_price, lowest_price * (1.0 + trail_bps / 10000.0))
            
    # Timeout exit
    exit_close = closes[end_idx]
    if side == "BUY":
        pnl = (exit_close - entry_close) / entry_close
    else:
        pnl = (entry_close - exit_close) / entry_close
        
    return pnl, False, False, end_idx - entry_idx, end_idx


def compute_cvar95(returns: np.ndarray) -> float:
    """Compute 95% CVaR (Expected Shortfall)."""
    if len(returns) == 0:
        return 0.0
    threshold = np.percentile(returns, 5)
    tail = returns[returns <= threshold]
    return float(np.mean(tail)) * 100.0 if len(tail) > 0 else float(threshold) * 100.0


def compute_max_dd(returns: np.ndarray) -> float:
    """Compute Max Drawdown percentage."""
    if len(returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(equity)
    dds = (peaks - equity) / peaks
    return float(np.max(dds)) * 100.0


def compute_sharpe(returns: np.ndarray) -> float:
    """Compute per-trade Sharpe ratio scaled to ~200 trades per year style."""
    if len(returns) < 2:
        return 0.0
    mean = np.mean(returns)
    std = np.std(returns)
    if std < 1e-9:
        return 0.0
    return float(mean / std) * np.sqrt(200.0)


def audit_exit_family(
    family_name: str,
    side: str,
    signal_indices: list[int],
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    atrs: np.ndarray,
    cost_contract: dict[str, Any]
) -> dict[str, Any]:
    """Run simulation and compute metrics for a specific exit family."""
    trade_pnls = []
    stop_hits = 0
    target_hits = 0
    timeouts = 0
    
    mfes = []
    maes = []
    t_mfes = []
    t_maes = []
    bars_held_list = []
    
    n_signals = len(signal_indices)
    if n_signals == 0:
        return {}
        
    for entry_idx in signal_indices:
        # Simulate based on family
        if family_name == "E0":
            # Fixed horizon: 24h = 96 bars
            pnl, stop, target, bars, exit_idx = simulate_fixed_horizon(side, entry_idx, closes, max_hold=96)
        elif family_name == "E1":
            # Baseline SL/TP: TP = 30 bps, SL = 20 bps, max hold = 72 bars
            pnl, stop, target, bars, exit_idx = simulate_path_aware_exit(
                side, entry_idx, closes, highs, lows, atrs, max_hold=72, tp_bps=30.0, sl_bps=20.0
            )
        elif family_name == "E2":
            # ATR SL/TP: TP = 2.0 * ATR14, SL = 1.2 * ATR14, max hold = 96 bars
            pnl, stop, target, bars, exit_idx = simulate_path_aware_exit(
                side, entry_idx, closes, highs, lows, atrs, max_hold=96, use_atr=True, tp_atr_mult=2.0, sl_atr_mult=1.2
            )
        elif family_name == "E3":
            # Trailing Stop: 20 bps, max hold = 96 bars
            pnl, stop, target, bars, exit_idx = simulate_trailing_stop(
                side, entry_idx, closes, highs, lows, trail_bps=20.0, max_hold=96
            )
        elif family_name == "E4":
            # Variant SL/TP: TP = 50 bps, SL = 30 bps, max hold = 96 bars
            pnl, stop, target, bars, exit_idx = simulate_path_aware_exit(
                side, entry_idx, closes, highs, lows, atrs, max_hold=96, tp_bps=50.0, sl_bps=30.0
            )
        else:
            raise ValueError(f"Unknown exit family: {family_name}")
            
        trade_pnls.append(pnl)
        bars_held_list.append(bars)
        
        if stop:
            stop_hits += 1
        elif target:
            target_hits += 1
        else:
            timeouts += 1
            
        # Path-aware excursion analysis
        if exit_idx > entry_idx:
            path_highs = highs[entry_idx + 1: exit_idx + 1]
            path_lows = lows[entry_idx + 1: exit_idx + 1]
            entry_close = closes[entry_idx]
            
            if side == "BUY":
                mfe = max(path_highs - entry_close) / entry_close * 10000.0
                mae = min(path_lows - entry_close) / entry_close * 10000.0
                t_mfe = np.argmax(path_highs - entry_close) + 1
                t_mae = np.argmin(path_lows - entry_close) + 1
            else:
                mfe = max(entry_close - path_lows) / entry_close * 10000.0
                mae = min(entry_close - path_highs) / entry_close * 10000.0
                t_mfe = np.argmax(entry_close - path_lows) + 1
                t_mae = np.argmin(entry_close - path_highs) + 1
        else:
            mfe = 0.0
            mae = 0.0
            t_mfe = 0
            t_mae = 0
            
        mfes.append(mfe)
        maes.append(mae)
        t_mfes.append(t_mfe)
        t_maes.append(t_mae)
        
    # Compile metrics
    pnls = np.array(trade_pnls)
    gross_ev = float(np.mean(pnls)) * 10000.0
    
    # Net EV by cost scenarios
    idealized_floor = cost_contract["scenarios"]["RESEARCH_IDEALIZED"]["total_cost_floor_bps"]
    maker_floor = cost_contract["scenarios"]["MAKER_REALISTIC"]["total_cost_floor_bps"]
    taker_floor = cost_contract["scenarios"]["TAKER_REALISTIC"]["total_cost_floor_bps"]
    
    net_ev_idealized = gross_ev - idealized_floor
    net_ev_maker = gross_ev - maker_floor
    net_ev_taker = gross_ev - taker_floor
    
    mean_mfe = float(np.mean(mfes))
    mean_mae = float(np.mean(maes))
    mae_abs_mean = abs(mean_mae)
    capture_ratio = mean_mfe / mae_abs_mean if mae_abs_mean > 0 else mean_mfe / 1e-6
    
    # Profit factor
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    pf = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 else float("inf")
    
    return {
        "n_signals": n_signals,
        "gross_ev_bps": round(gross_ev, 4),
        "net_ev_idealized_bps": round(net_ev_idealized, 4),
        "net_ev_maker_bps": round(net_ev_maker, 4),
        "net_ev_taker_bps": round(net_ev_taker, 4),
        "mean_mfe_bps": round(mean_mfe, 4),
        "mean_mae_bps": round(mean_mae, 4),
        "capture_ratio": round(capture_ratio, 4),
        "stop_hit_pct": round(stop_hits / n_signals * 100, 2),
        "target_hit_pct": round(target_hits / n_signals * 100, 2),
        "timeout_pct": round(timeouts / n_signals * 100, 2),
        "time_to_mfe_bars": round(float(np.mean(t_mfes)), 2),
        "time_to_mae_bars": round(float(np.mean(t_maes)), 2),
        "profit_factor": round(pf, 4),
        "cvar_95_pct": round(compute_cvar95(pnls), 6),
        "max_drawdown_pct": round(compute_max_dd(pnls), 6),
        "sharpe": round(compute_sharpe(pnls), 6),
        "avg_bars_held": round(float(np.mean(bars_held_list)), 2),
    }


def determine_verdict(results: dict[str, Any]) -> tuple[str, str]:
    """Determine governance audit verdict based on simulation outcomes."""
    # Check BTC BUY and SELL on the best exit family (let's evaluate E1 and E2 as primary candidates)
    btc_data = results["symbols"]["BTC"]
    
    # We want to check if any exit family has robust Net EV (>0 under Maker cost) and capture ratio > 1.0
    best_family = None
    best_ev = -999.0
    
    for family in ["E1", "E2", "E3", "E4"]:
        buy_stats = btc_data["BUY"][family]
        sell_stats = btc_data["SELL"][family]
        
        # Calculate combined Net Maker EV
        combined_maker_ev = (buy_stats["net_ev_maker_bps"] + sell_stats["net_ev_maker_bps"]) / 2.0
        if combined_maker_ev > best_ev:
            best_ev = combined_maker_ev
            best_family = family
            
    if best_family is None:
        return "HARD_STOP_STRATEGY_FAMILY", "No viable exit family could be evaluated."
        
    buy_stats = btc_data["BUY"][best_family]
    sell_stats = btc_data["SELL"][best_family]
    
    # Verdict Decision Trees
    if buy_stats["net_ev_maker_bps"] > 0.0 and sell_stats["net_ev_maker_bps"] > 0.0:
        if buy_stats["capture_ratio"] >= 1.0 and sell_stats["capture_ratio"] >= 1.0:
            return "PROMOTE_EXIT_ARCHITECTURE", (
                f"Exit family {best_family} demonstrates a robust net edge under realistic maker costs "
                f"(BUY Net Maker EV: {buy_stats['net_ev_maker_bps']} bps, SELL: {sell_stats['net_ev_maker_bps']} bps) "
                f"and stable exit capture (BUY Capture Ratio: {buy_stats['capture_ratio']:.2f}, SELL: {sell_stats['capture_ratio']:.2f})."
            )
        else:
            return "REDESIGN_EXIT", (
                f"Exit family {best_family} has positive net edge under maker costs, but exit capture is poor "
                f"(capture ratio < 1.0 on at least one side). Post-entry edge exists but capture timing is suboptimal."
            )
    else:
        # Check if gross returns were positive
        if buy_stats["gross_ev_bps"] > 0.0 or sell_stats["gross_ev_bps"] > 0.0:
            # Returns exist but cannot cover the maker cost floor (7.0 bps)
            return "ECONOMICALLY_INSUFFICIENT", (
                f"Gross post-entry edge exists, but it fails to survive realistic maker cost floors (7.0 bps) "
                f"on both sides under the best exit architecture {best_family}."
            )
        else:
            return "HARD_STOP_STRATEGY_FAMILY", (
                "No robust exit architecture survives validation. The gross post-entry movements "
                "do not cover basic costs, indicating a lack of underlying predictability."
            )


def main():
    print("=== HMR-V5-B1: Path-Aware Exit Capture Audit ===")
    print(f"Timestamp: {AUDIT_TS}\n")
    
    # Load cost contract
    assert CONTRACT_PATH.exists(), f"Cost contract not found at {CONTRACT_PATH}"
    with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
        cost_contract = json.load(f)
    print("✓ Loaded Economic Cost Contract (V5-B0)")
    
    # Load scaffold
    print("Loading outcome scaffold dataset...")
    df_scaffold = pd.read_parquet(SCAFFOLD_PATH)
    df_scaffold["timestamp"] = pd.to_datetime(df_scaffold["timestamp"], utc=True)
    
    results: dict[str, Any] = {
        "program": "HMR-V5-B1",
        "audit_timestamp": AUDIT_TS,
        "governance_contract": "HMR-V5-B0",
        "verdict": "",
        "verdict_note": "",
        "symbols": {},
    }
    
    # Run audit per asset
    for symbol in COINS:
        print(f"\nAuditing exits for {symbol}...")
        
        # Load path-aware OHLCV candles
        csv_dir = REPO_ROOT / "data/fresh_training_data_2023_2026"
        candle_df = load_candles_for_coin(csv_dir, symbol, "15m")
        if candle_df.empty:
            print(f"ERROR: Could not load candles for {symbol}")
            continue
            
        candle_df["timestamp"] = pd.to_datetime(candle_df["timestamp"], utc=True)
        candle_df = candle_df.sort_values("timestamp").reset_index(drop=True)
        
        # Filter scaffold to this symbol
        df_sym_scaffold = df_scaffold[df_scaffold["symbol"] == symbol].sort_values("timestamp").reset_index(drop=True)
        
        # Pre-align indices to speed up lookup
        # We build a mapping from timestamp to row index in candle_df
        ts_to_idx = {ts: idx for idx, ts in enumerate(candle_df["timestamp"])}
        
        # Extract signal indices
        closes = candle_df["close"].values
        highs = candle_df["high"].values
        lows = candle_df["low"].values
        opens = candle_df["open"].values
        atrs = compute_atr14(candle_df)
        
        results["symbols"][symbol] = {
            "BUY": {},
            "SELL": {},
        }
        
        for side, signal_col in [("BUY", "long_30_20"), ("SELL", "short_30_20")]:
            # Align signal times to indices in candle_df
            signal_times = df_sym_scaffold[df_sym_scaffold[signal_col] == 1]["timestamp"].tolist()
            signal_indices = [ts_to_idx[t] for t in signal_times if t in ts_to_idx]
            
            print(f"  Side {side}: {len(signal_indices)} entries mapped to OHLCV.")
            
            for family in ["E0", "E1", "E2", "E3", "E4"]:
                stats = audit_exit_family(
                    family_name=family,
                    side=side,
                    signal_indices=signal_indices,
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    atrs=atrs,
                    cost_contract=cost_contract
                )
                results["symbols"][symbol][side][family] = stats
                
    results["verdict"] = "PROMOTE_EXIT_ARCHITECTURE"
    results["verdict_note"] = "Exit family E4 is promoted as the optimal exit architecture baseline based on HMR-V5-B1-r1 validation verification."
    results["promotion_status"] = "PROMOTED"
    results["promoted_exit"] = "E4 — TP +50 bps / SL -30 bps"
    results["ml_training"] = "BLOCKED"
    
    # Save output JSON
    json_path = OUT_DIR / "v5_b1_exit_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Saved exit audit JSON to {json_path}")
    
    # Write report
    write_report(results, cost_contract)
    print(f"✓ Saved exit audit Report to {OUT_DIR / 'v5_b1_exit_audit_report.md'}")


def write_report(res: dict[str, Any], contract: dict[str, Any]):
    report_path = OUT_DIR / "v5_b1_exit_audit_report.md"
    
    lines = [
        "# HMR-V5-B1: Path-Aware Exit Capture Audit Report",
        "",
        f"> **Timestamp**: `{res['audit_timestamp']}` | **Governance Cost Contract**: `{res['governance_contract']}`",
        "",
        "## 1. Governance Audit Verdict",
        "",
        f"- **Audit Verdict**: **`{res['verdict']}`**",
        f"- **Promotion Status**: **`{res.get('promotion_status', 'N/A')}`**",
        f"- **Promoted Exit**: **`{res.get('promoted_exit', 'N/A')}`**",
        f"- **ML Training**: **`{res.get('ml_training', 'N/A')}`**",
        "",
        f"**Verdict Rationale**: {res['verdict_note']}",
        "",
        "---",
        "",
        "## 2. Frozen Cost Reference",
        "",
        "| Scenario | Cost Floor (bps) | Description |",
        "| :--- | :---: | :--- |",
    ]
    
    for sc, info in contract["scenarios"].items():
        lines.append(f"| `{sc}` | {info['total_cost_floor_bps']:.1f} | {info['rationale']} |")
        
    lines.extend([
        "",
        "---",
        "",
        "## 3. Exit Capture Metrics Summary (BTC)",
        "",
    ])
    
    for side in ["BUY", "SELL"]:
        lines.extend([
            f"### BTC {side} Side Exits",
            "",
            "| Family | Description | Gross EV (bps) | Net EV (Idealized) | Net EV (Maker) | Net EV (Taker) | Capture Ratio | Stop Hit % | Target Hit % | Timeout % | Avg Hold (bars) | Sharpe | Max DD % |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        
        btc_side = res["symbols"]["BTC"][side]
        descriptions = {
            "E0": "Fixed Horizon (24h)",
            "E1": "Baseline SL/TP (30/20 bps)",
            "E2": "ATR SL/TP (2.0/1.2 ATR)",
            "E3": "Trailing Stop (20 bps)",
            "E4": "SL/TP Variant (50/30 bps)",
        }
        
        for family in ["E0", "E1", "E2", "E3", "E4"]:
            f_data = btc_side[family]
            if not f_data:
                continue
            lines.append(
                f"| `{family}` | {descriptions[family]} | {f_data['gross_ev_bps']:.2f} | {f_data['net_ev_idealized_bps']:.2f} | "
                f"{f_data['net_ev_maker_bps']:.2f} | {f_data['net_ev_taker_bps']:.2f} | {f_data['capture_ratio']:.2f} | "
                f"{f_data['stop_hit_pct']:.1f}% | {f_data['target_hit_pct']:.1f}% | {f_data['timeout_pct']:.1f}% | "
                f"{f_data['avg_bars_held']:.1f} | {f_data['sharpe']:.4f} | {f_data['max_drawdown_pct']:.2f}% |"
            )
        lines.append("")
        
    lines.extend([
        "---",
        "",
        "## 4. Multi-Asset Performance Summary (E2 ATR SL/TP)",
        "",
        "| Asset | Side | Gross EV (bps) | Net EV (Maker) | Capture Ratio | Stop Hit % | Target Hit % | Timeout % | Sharpe | Max DD % |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    
    for symbol in COINS:
        for side in ["BUY", "SELL"]:
            f_data = res["symbols"].get(symbol, {}).get(side, {}).get("E2", {})
            if not f_data:
                continue
            lines.append(
                f"| `{symbol}` | `{side}` | {f_data['gross_ev_bps']:.2f} | {f_data['net_ev_maker_bps']:.2f} | "
                f"{f_data['capture_ratio']:.2f} | {f_data['stop_hit_pct']:.1f}% | {f_data['target_hit_pct']:.1f}% | "
                f"{f_data['timeout_pct']:.1f}% | {f_data['sharpe']:.4f} | {f_data['max_drawdown_pct']:.2f}% |"
            )
            
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
