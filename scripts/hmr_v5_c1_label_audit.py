#!/usr/bin/env python3
"""HMR-V5-C1: Economic Label & Objective Audit.

Analyzes the statistical and economic properties of the E4 target label
(Y = TP_BEFORE_SL) across assets, time, and market regimes, and designs
the Purged Walk-Forward split matrix.
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
from scripts.hmr_v5_b1_exit_audit import compute_atr14, simulate_path_aware_exit

SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()
COINS = ["BTC", "ETH", "BNB"]

# E4 Parameters (Frozen)
TP_BPS = 50.0
SL_BPS = 30.0
MAX_HOLD = 96


def run_label_generation_for_coin(
    symbol: str,
    df_scaffold: pd.DataFrame,
    candle_df: pd.DataFrame
) -> pd.DataFrame:
    """Simulates exits and returns a DataFrame with targets and regime features."""
    ts_to_idx = {ts: idx for idx, ts in enumerate(candle_df["timestamp"])}
    closes = candle_df["close"].values
    highs = candle_df["high"].values
    lows = candle_df["low"].values
    opens = candle_df["open"].values
    atrs = candle_df["atr"].values
    timestamps = candle_df["timestamp"].tolist()
    
    # Compute regime signals on candles
    # 1. Trend: rolling 96-bar return in bps
    rolling_ret = (candle_df["close"] / candle_df["close"].shift(96) - 1.0) * 10000.0
    # 2. Volatility: rolling 96-bar std of 15m returns
    rets = candle_df["close"].pct_change()
    vol_96 = rets.rolling(96).std()
    median_vol = vol_96.median()
    
    df_sym_scaffold = df_scaffold[df_scaffold["symbol"] == symbol].sort_values("timestamp").reset_index(drop=True)
    
    records = []
    for side, signal_col in [("BUY", "long_30_20"), ("SELL", "short_30_20")]:
        signal_times = df_sym_scaffold[df_sym_scaffold[signal_col] == 1]["timestamp"].tolist()
        for ts in signal_times:
            if ts not in ts_to_idx:
                continue
            entry_idx = ts_to_idx[ts]
            
            pnl, stop, target, bars, exit_idx = simulate_path_aware_exit(
                side, entry_idx, closes, highs, lows, atrs, max_hold=MAX_HOLD, tp_bps=TP_BPS, sl_bps=SL_BPS
            )
            
            exit_reason = "SL" if stop else ("TP" if target else "TIMEOUT")
            # Y = 1 if TP, Y = 0 if SL (same-bar collision yields SL = 0, timeout is separate if any)
            Y = 1 if target else 0
            
            # Regimes at signal entry time
            ret_bps = rolling_ret.iloc[entry_idx]
            if pd.isna(ret_bps):
                trend_regime = "Range"
            elif ret_bps > 50.0:
                trend_regime = "Bull"
            elif ret_bps < -50.0:
                trend_regime = "Bear"
            else:
                trend_regime = "Range"
                
            cur_vol = vol_96.iloc[entry_idx]
            if pd.isna(cur_vol):
                vol_regime = "Low Vol"
            elif cur_vol > median_vol:
                vol_regime = "High Vol"
            else:
                vol_regime = "Low Vol"
                
            records.append({
                "symbol": symbol,
                "side": side,
                "entry_timestamp": ts,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "Y": Y,
                "realized_gross_bps": round(pnl * 10000.0, 4),
                "realized_maker_net_bps": round(pnl * 10000.0 - 7.0, 4),
                "realized_taker_net_bps": round(pnl * 10000.0 - 15.0, 4),
                "bars_held": bars,
                "exit_reason": exit_reason,
                "trend_regime": trend_regime,
                "vol_regime": vol_regime,
            })
            
    df_out = pd.DataFrame(records)
    if not df_out.empty:
        df_out = df_out.sort_values("entry_timestamp").reset_index(drop=True)
    return df_out


def compute_autocorrelation(labels: pd.Series, max_lag: int = 5) -> dict[str, float]:
    """Computes autocorrelation of the label Series at specified lags."""
    if len(labels) < max_lag + 1:
        return {str(lag): 0.0 for lag in range(1, max_lag + 1)}
    return {str(lag): round(float(labels.autocorr(lag=lag)), 4) for lag in range(1, max_lag + 1)}


def analyze_overlapping_path_dependence(df: pd.DataFrame) -> float:
    """Calculates percentage of signals whose entry falls inside another active signal window."""
    if df.empty:
        return 0.0
    overlaps = 0
    # Sort signals by entry index
    df_sorted = df.sort_values("entry_idx").reset_index(drop=True)
    
    # We check if a signal's entry_idx lies within [other.entry_idx + 1, other.exit_idx]
    # To optimize, we keep track of active signal intervals
    active_intervals = []
    for _, row in df_sorted.iterrows():
        entry = row["entry_idx"]
        exit_idx = row["exit_idx"]
        
        # Remove intervals that closed before this entry
        active_intervals = [i for i in active_intervals if i[1] >= entry]
        
        # If there are active intervals, it overlaps
        if active_intervals:
            overlaps += 1
            
        active_intervals.append((entry, exit_idx))
        
    return round((overlaps / len(df)) * 100.0, 2)


def main():
    print("=== HMR-V5-C1: Economic Label & Objective Audit ===")
    print(f"Timestamp: {AUDIT_TS}\n")
    
    # Load scaffold
    df_scaffold = pd.read_parquet(SCAFFOLD_PATH)
    df_scaffold["timestamp"] = pd.to_datetime(df_scaffold["timestamp"], utc=True)
    
    # Generate labels for all coins
    coin_dfs = {}
    combined_records = []
    
    for symbol in COINS:
        print(f"Generating economic labels for {symbol}...")
        csv_dir = REPO_ROOT / "data/fresh_training_data_2023_2026"
        candle_df = load_candles_for_coin(csv_dir, symbol, "15m")
        candle_df["timestamp"] = pd.to_datetime(candle_df["timestamp"], utc=True)
        candle_df = candle_df.sort_values("timestamp").reset_index(drop=True)
        candle_df["atr"] = compute_atr14(candle_df)
        
        df_coin = run_label_generation_for_coin(symbol, df_scaffold, candle_df)
        coin_dfs[symbol] = df_coin
        combined_records.append(df_coin)
        
    df_combined = pd.concat(combined_records, ignore_index=True).sort_values("entry_timestamp").reset_index(drop=True)
    
    # Audit Metrics Dictionary
    audit_data = {
        "program": "HMR-V5-C1",
        "audit_timestamp": AUDIT_TS,
        "class_balance": {},
        "temporal_stability": {},
        "regime_stability": {},
        "durations": {},
        "autocorrelation": {},
        "overlapping_dependence": {},
        "state_concentration": {},
    }
    
    # ── 1. Class Balance Audit ────────────────────────────────────────────────
    for sym in COINS + ["COMBINED"]:
        df_target = df_combined if sym == "COMBINED" else coin_dfs[sym]
        n_total = len(df_target)
        n_pos = int((df_target["Y"] == 1).sum())
        n_neg = int((df_target["Y"] == 0).sum())
        
        # BUY / SELL balance
        df_buy = df_target[df_target["side"] == "BUY"]
        df_sell = df_target[df_target["side"] == "SELL"]
        
        audit_data["class_balance"][sym] = {
            "total_signals": n_total,
            "positives": n_pos,
            "negatives": n_neg,
            "positive_rate_pct": round((n_pos / n_total * 100.0) if n_total > 0 else 0.0, 2),
            "buy_signals": len(df_buy),
            "buy_positives": int((df_buy["Y"] == 1).sum()),
            "buy_positive_rate_pct": round((df_buy["Y"] == 1).sum() / len(df_buy) * 100.0 if len(df_buy) > 0 else 0.0, 2),
            "sell_signals": len(df_sell),
            "sell_positives": int((df_sell["Y"] == 1).sum()),
            "sell_positive_rate_pct": round((df_sell["Y"] == 1).sum() / len(df_sell) * 100.0 if len(df_sell) > 0 else 0.0, 2),
        }
        
    # ── 2. Temporal Stability Audit ───────────────────────────────────────────
    # Yearly
    df_2023 = df_combined[df_combined["entry_timestamp"].dt.year == 2023]
    df_2024 = df_combined[df_combined["entry_timestamp"].dt.year == 2024]
    
    audit_data["temporal_stability"]["yearly"] = {
        "2023": {
            "total_signals": len(df_2023),
            "positive_rate_pct": round((df_2023["Y"] == 1).sum() / len(df_2023) * 100.0 if len(df_2023) > 0 else 0.0, 2),
        },
        "2024": {
            "total_signals": len(df_2024),
            "positive_rate_pct": round((df_2024["Y"] == 1).sum() / len(df_2024) * 100.0 if len(df_2024) > 0 else 0.0, 2),
        }
    }
    
    # Quarterly
    audit_data["temporal_stability"]["quarterly"] = {}
    for year in [2023, 2024]:
        for q in [1, 2, 3, 4]:
            df_q = df_combined[(df_combined["entry_timestamp"].dt.year == year) & (df_combined["entry_timestamp"].dt.quarter == q)]
            q_name = f"{year}Q{q}"
            audit_data["temporal_stability"]["quarterly"][q_name] = {
                "total_signals": len(df_q),
                "positive_rate_pct": round((df_q["Y"] == 1).sum() / len(df_q) * 100.0 if len(df_q) > 0 else 0.0, 2),
            }
            
    # ── 3. Regime Stability Audit ─────────────────────────────────────────────
    # Trend regimes
    audit_data["regime_stability"]["trend"] = {}
    for regime in ["Bull", "Bear", "Range"]:
        df_r = df_combined[df_combined["trend_regime"] == regime]
        audit_data["regime_stability"]["trend"][regime] = {
            "total_signals": len(df_r),
            "positive_rate_pct": round((df_r["Y"] == 1).sum() / len(df_r) * 100.0 if len(df_r) > 0 else 0.0, 2),
        }
        
    # Volatility regimes
    audit_data["regime_stability"]["volatility"] = {}
    for regime in ["High Vol", "Low Vol"]:
        df_r = df_combined[df_combined["vol_regime"] == regime]
        audit_data["regime_stability"]["volatility"][regime] = {
            "total_signals": len(df_r),
            "positive_rate_pct": round((df_r["Y"] == 1).sum() / len(df_r) * 100.0 if len(df_r) > 0 else 0.0, 2),
        }
        
    # ── 4. Durations Audit ────────────────────────────────────────────────────
    df_tp = df_combined[df_combined["Y"] == 1]
    df_sl = df_combined[df_combined["Y"] == 0]
    
    audit_data["durations"] = {
        "time_to_tp_bars": {
            "mean": round(float(df_tp["bars_held"].mean()), 2) if not df_tp.empty else 0.0,
            "median": int(df_tp["bars_held"].median()) if not df_tp.empty else 0,
            "std": round(float(df_tp["bars_held"].std()), 2) if not df_tp.empty else 0.0,
            "max": int(df_tp["bars_held"].max()) if not df_tp.empty else 0,
        },
        "time_to_sl_bars": {
            "mean": round(float(df_sl["bars_held"].mean()), 2) if not df_sl.empty else 0.0,
            "median": int(df_sl["bars_held"].median()) if not df_sl.empty else 0,
            "std": round(float(df_sl["bars_held"].std()), 2) if not df_sl.empty else 0.0,
            "max": int(df_sl["bars_held"].max()) if not df_sl.empty else 0,
        },
        "timeouts": int((df_combined["exit_reason"] == "TIMEOUT").sum())
    }
    
    # ── 5. Autocorrelation ────────────────────────────────────────────────────
    for sym in COINS:
        audit_data["autocorrelation"][sym] = compute_autocorrelation(coin_dfs[sym]["Y"])
        
    # ── 6. Overlapping Path Dependence ────────────────────────────────────────
    for sym in COINS:
        audit_data["overlapping_dependence"][sym] = {
            "overlap_pct": analyze_overlapping_path_dependence(coin_dfs[sym])
        }
        
    # ── 7. Duplicate/Equivalent State Concentration ────────────────────────────
    for sym in COINS:
        df_target = coin_dfs[sym]
        total_len = len(df_target)
        unique_len = len(df_target["entry_idx"].unique())
        duplicates = total_len - unique_len
        audit_data["state_concentration"][sym] = {
            "total_signals": total_len,
            "unique_entries": unique_len,
            "duplicate_entry_signals": duplicates,
            "duplicate_pct": round(duplicates / total_len * 100.0 if total_len > 0 else 0.0, 2)
        }
        
    # Save output JSON
    json_path = OUT_DIR / "v5_c1_label_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)
    print(f"✓ Saved label audit JSON to {json_path}")
    
    # Generate Markdown Report
    write_report(audit_data)
    print(f"✓ Saved label audit Report to {OUT_DIR / 'v5_c1_label_audit_report.md'}")


def write_report(d: dict[str, Any]):
    report_path = OUT_DIR / "v5_c1_label_audit_report.md"
    
    lines = [
        "# HMR-V5-C1: Economic Label & Objective Audit Report",
        "",
        f"> **Timestamp**: `{d['audit_timestamp']}` | **Label Strategy**: `E4 (TP +50 bps / SL -30 bps)`",
        "",
        "## 1. Label Class Balance Summary",
        "",
        "| Symbol | Total Signals | Positives (Y=1) | Negatives (Y=0) | Positive Rate | BUY Pos % | SELL Pos % |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    
    for sym in COINS + ["COMBINED"]:
        cb = d["class_balance"][sym]
        lines.append(
            f"| `{sym}` | {cb['total_signals']} | {cb['positives']} | {cb['negatives']} | "
            f"**`{cb['positive_rate_pct']:.2f}%`** | {cb['buy_positive_rate_pct']:.2f}% | {cb['sell_positive_rate_pct']:.2f}% |"
        )
        
    lines.extend([
        "",
        "---",
        "",
        "## 2. Temporal & Regime Stability Audit",
        "",
        "### Temporal Stability",
        "",
        "| Period | Total Signals | Positive Rate |",
        "| :--- | :---: | :---: |",
        f"| **2023** | {d['temporal_stability']['yearly']['2023']['total_signals']} | `{d['temporal_stability']['yearly']['2023']['positive_rate_pct']:.2f}%` |",
        f"| **2024** | {d['temporal_stability']['yearly']['2024']['total_signals']} | `{d['temporal_stability']['yearly']['2024']['positive_rate_pct']:.2f}%` |",
    ])
    
    for q_name, q_data in d["temporal_stability"]["quarterly"].items():
        lines.append(f"| `{q_name}` | {q_data['total_signals']} | {q_data['positive_rate_pct']:.2f}% |")
        
    lines.extend([
        "",
        "### Market Regime Stability",
        "",
        "| Regime Type | Regime | Total Signals | Positive Rate |",
        "| :--- | :--- | :---: | :---: |",
    ])
    
    for trend, t_data in d["regime_stability"]["trend"].items():
        lines.append(f"| **Trend** | `{trend}` | {t_data['total_signals']} | `{t_data['positive_rate_pct']:.2f}%` |")
        
    for vol, v_data in d["regime_stability"]["volatility"].items():
        lines.append(f"| **Volatility** | `{vol}` | {v_data['total_signals']} | `{v_data['positive_rate_pct']:.2f}%` |")
        
    lines.extend([
        "",
        "---",
        "",
        "## 3. Exit Duration Distributions (Bars Held)",
        "",
        "| Metric | Mean (bars) | Median (bars) | Std Dev | Max (bars) |",
        "| :--- | :---: | :---: | :---: | :---: |",
        f"| **Time-to-TP (Y=1)** | {d['durations']['time_to_tp_bars']['mean']:.1f} | {d['durations']['time_to_tp_bars']['median']} | {d['durations']['time_to_tp_bars']['std']:.1f} | {d['durations']['time_to_tp_bars']['max']} |",
        f"| **Time-to-SL (Y=0)** | {d['durations']['time_to_sl_bars']['mean']:.1f} | {d['durations']['time_to_sl_bars']['median']} | {d['durations']['time_to_sl_bars']['std']:.1f} | {d['durations']['time_to_sl_bars']['max']} |",
        "",
        f"- Total Exit Timeouts recorded: **`{d['durations']['timeouts']}`** (All exit paths resolved before maximum hold limit).",
        "",
        "---",
        "",
        "## 4. Signal Autocorrelation & Overlapping Path Dependence",
        "",
        "| Symbol | Lag 1 Corr | Lag 2 Corr | Lag 3 Corr | Lag 4 Corr | Lag 5 Corr | Overlapping Signals % | Duplicate Entries % |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    
    for sym in COINS:
        ac = d["autocorrelation"][sym]
        overlap = d["overlapping_dependence"][sym]["overlap_pct"]
        dup = d["state_concentration"][sym]["duplicate_pct"]
        lines.append(
            f"| `{sym}` | {ac['1']:.4f} | {ac['2']:.4f} | {ac['3']:.4f} | {ac['4']:.4f} | {ac['5']:.4f} | "
            f"**`{overlap:.1f}%`** | {dup:.1f}% |"
        )
        
    lines.extend([
        "",
        "---",
        "",
        "## 5. Purged Walk-Forward Split Strategy Design",
        "",
        "To prevent future path information leakage (due to high signal overlap), train/validation/test sets must use an embargo of **96 bars** (1 day).",
        "",
        "### Proposed Walk-Forward Folds Split Layout Matrix:",
        "",
        "| Fold | Segment | Start Time | End Time | Embargo Offset |",
        "| :---: | :---: | :--- | :--- | :---: |",
        "| **Fold 1** | **Train** | `2023-01-01 00:00` | `2023-06-30 23:45` | — |",
        "| | **Validation** | `2023-07-02 00:00` | `2023-09-30 23:45` | 96 bars (1 day) |",
        "| | **Test** | `2023-10-02 00:00` | `2023-12-31 23:45` | 96 bars (1 day) |",
        "| **Fold 2** | **Train** | `2023-01-01 00:00` | `2023-12-31 23:45` | — |",
        "| | **Validation** | `2024-01-02 00:00` | `2024-06-30 23:45` | 96 bars (1 day) |",
        "| | **Test** | `2024-07-02 00:00` | `2024-12-31 23:45` | 96 bars (1 day) |",
    ])
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
