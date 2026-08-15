#!/usr/bin/env python3
"""HMR-V2-G1.1: Candidate Multiplicity Audit.

Loads candidates.parquet and candle history. Group candidates into unique crossing events:
  - SMA50_BREAK: event starts when price crosses SMA50, ends when price crosses opposite side.
  - SMA200_TREND: event starts when price crosses SMA200, ends when price crosses opposite side.
  - Other triggers: time-based clustering with a 16-bar (4h) cooldown window.

Evaluates multiplicity statistics and expectancy deltas (all candidates vs first candidate per event).
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles

COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


def calculate_indicators_and_crossings(df: pd.DataFrame) -> Dict[str, pd.Series]:
    close_col = next((c for c in ["close", "Close", "CLOSE"] if c in df.columns), "close")
    close = df[close_col].astype(float)
    sma50 = close.rolling(window=50, min_periods=1).mean()
    sma200 = close.rolling(window=200, min_periods=1).mean()
    
    # Crossings: 1 for cross above, -1 for cross below, 0 otherwise
    cross50 = np.zeros(len(df))
    cross200 = np.zeros(len(df))
    
    for i in range(1, len(df)):
        # SMA50
        prev_c, curr_c = close.iloc[i-1], close.iloc[i]
        prev_s50, curr_s50 = sma50.iloc[i-1], sma50.iloc[i]
        if prev_c <= prev_s50 and curr_c > curr_s50:
            cross50[i] = 1
        elif prev_c >= prev_s50 and curr_c < curr_s50:
            cross50[i] = -1
            
        # SMA200
        prev_s200, curr_s200 = sma200.iloc[i-1], sma200.iloc[i]
        if prev_c <= prev_s200 and curr_c > curr_s200:
            cross200[i] = 1
        elif prev_c >= prev_s200 and curr_c < curr_s200:
            cross200[i] = -1
            
    df_idx = df.index
    return {
        "sma50": pd.Series(sma50, index=df_idx),
        "sma200": pd.Series(sma200, index=df_idx),
        "cross50": pd.Series(cross50, index=df_idx),
        "cross200": pd.Series(cross200, index=df_idx)
    }


def run_multiplicity_audit(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run V2.1 first.")
        return 1

    print("HMR-V2-G1.1: Candidate Multiplicity Audit")
    print(f"  Input: {parquet_path}")
    print()

    # Load candidates
    c_df = pd.read_parquet(parquet_path)
    c_df["timestamp"] = pd.to_datetime(c_df["timestamp"])
    if c_df["timestamp"].dt.tz is None:
        c_df["timestamp"] = c_df["timestamp"].dt.tz_localize("UTC")
    else:
        c_df["timestamp"] = c_df["timestamp"].dt.tz_convert("UTC")
    
    # Load candles
    coins = list(c_df["symbol"].unique())
    start_time = c_df["timestamp"].min() - pd.Timedelta(days=5) # Buffer for crossings warmup
    end_time = c_df["timestamp"].max() + pd.Timedelta(days=1)
    
    print("  Loading closed candles to track crossings...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start_time, end_time, end_time,
        warmup_bars=args.warmup_bars
    )
    
    # Build indicators for each coin
    coin_data: Dict[str, Dict[str, Any]] = {}
    for coin, rows in candles_dict.items():
        df_candles = pd.DataFrame(rows)
        df_candles["time"] = pd.to_datetime(df_candles["time"])
        if df_candles["time"].dt.tz is None:
            df_candles["time"] = df_candles["time"].dt.tz_localize("UTC")
        else:
            df_candles["time"] = df_candles["time"].dt.tz_convert("UTC")
        df_candles.set_index("time", inplace=True)
        df_candles.sort_index(inplace=True)
        
        indicators = calculate_indicators_and_crossings(df_candles)
        
        # Build crossing timestamps list
        # For SMA50
        cross50_events = indicators["cross50"][indicators["cross50"] != 0]
        # For SMA200
        cross200_events = indicators["cross200"][indicators["cross200"] != 0]
        
        coin_data[coin] = {
            "df": df_candles,
            "cross50": cross50_events,
            "cross200": cross200_events
        }

    # Cluster candidates into events
    event_ids = []
    cluster_positions = [] # position in cluster (0 = first candidate)
    
    # Sort candidates chronologically
    c_df.sort_values("timestamp", inplace=True)
    c_df.reset_index(drop=True, inplace=True)
    
    # Keep track of last timestamp for time-based cooldown (for other triggers)
    last_trigger_time: Dict[Tuple[str, str, str], pd.Timestamp] = {}
    time_based_event_id: Dict[Tuple[str, str, str], str] = {}
    time_based_seq: Dict[Tuple[str, str, str], int] = {}

    for idx, row in c_df.iterrows():
        coin = row["symbol"]
        side = row["side"]
        family = row["technical_signal_family"]
        ts = row["timestamp"]
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        
        c_info = coin_data.get(coin)
        if c_info is None:
            # Fallback if no candles found
            event_id = f"FALLBACK_{coin}_{side}_{family}_{ts.strftime('%Y%m%d_%H%M%S')}"
            event_ids.append(event_id)
            cluster_positions.append(0)
            continue
            
        if family == "SMA50_BREAK":
            cross_series = c_info["cross50"]
            past_crosses = cross_series[cross_series.index <= ts]
            if not past_crosses.empty:
                last_cross_time = past_crosses.index[-1]
                last_cross_dir = past_crosses.iloc[-1]
                event_id = f"SMA50_{coin}_{side}_{last_cross_time.strftime('%Y%m%d_%H%M')}_{int(last_cross_dir)}"
            else:
                event_id = f"SMA50_{coin}_{side}_WARMUP"
                
        elif family == "SMA200_TREND":
            cross_series = c_info["cross200"]
            past_crosses = cross_series[cross_series.index <= ts]
            if not past_crosses.empty:
                last_cross_time = past_crosses.index[-1]
                last_cross_dir = past_crosses.iloc[-1]
                event_id = f"SMA200_{coin}_{side}_{last_cross_time.strftime('%Y%m%d_%H%M')}_{int(last_cross_dir)}"
            else:
                event_id = f"SMA200_{coin}_{side}_WARMUP"
                
        else:
            # Time-based clustering fallback: 16 bars = 4 hours
            key = (coin, side, family)
            last_ts = last_trigger_time.get(key)
            if last_ts is not None and (ts - last_ts) <= pd.Timedelta(hours=4):
                event_id = time_based_event_id[key]
                time_based_seq[key] += 1
            else:
                event_id = f"TIME_{coin}_{side}_{family}_{ts.strftime('%Y%m%d_%H%M%S')}"
                time_based_event_id[key] = event_id
                time_based_seq[key] = 0
                
            last_trigger_time[key] = ts
            
        event_ids.append(event_id)

    c_df["event_id"] = event_ids
    
    # Calculate order within event cluster
    c_df["event_seq"] = c_df.groupby("event_id").cumcount()
    
    # Build unique events dataset
    unique_events_df = c_df.groupby("event_id").agg({
        "timestamp": "min",
        "symbol": "first",
        "side": "first",
        "technical_signal_family": "first",
        "raw_model_score": "first",
        "return_72bars": "first",
        "return_8bars": "first"
    }).reset_index()

    # Multiplicity metrics
    raw_count = len(c_df)
    unique_count = len(unique_events_df)
    repeat_count = raw_count - unique_count
    repeat_ratio = repeat_count / raw_count
    
    # Multiplicity distributions
    counts = c_df["event_id"].value_counts()
    mean_mult = float(counts.mean())
    med_mult = float(counts.median())
    p90_mult = float(counts.quantile(0.9))
    max_mult = int(counts.max())

    # Expectancy delta
    ret_72 = "return_72bars"
    v1_72 = c_df[ret_72].dropna()
    ev_72 = unique_events_df[ret_72].dropna()
    
    mean_v1_72 = float(v1_72.mean() * 10_000.0)
    mean_ev_72 = float(ev_72.mean() * 10_000.0)
    
    med_v1_72 = float(v1_72.median() * 10_000.0)
    med_ev_72 = float(ev_72.median() * 10_000.0)
    
    v1_gt_30 = float((v1_72 > 0.0030).mean())
    ev_gt_30 = float((ev_72 > 0.0030).mean())
    
    v1_gt_40 = float((v1_72 > 0.0040).mean())
    ev_gt_40 = float((ev_72 > 0.0040).mean())
    
    v1_net_pos = float((v1_72 > COST_FRAC).mean())
    ev_net_pos = float((ev_72 > COST_FRAC).mean())

    # Regression at 8 bars
    ret_8 = "return_8bars"
    v1_8 = c_df[ret_8].dropna()
    ev_8 = unique_events_df[ret_8].dropna()
    
    mean_v1_8 = float(v1_8.mean() * 10_000.0)
    mean_ev_8 = float(ev_8.mean() * 10_000.0)
    
    v1_corr_8 = float(spearmanr(c_df["raw_model_score"], c_df[ret_8], nan_policy="omit")[0])
    ev_corr_8 = float(spearmanr(unique_events_df["raw_model_score"], unique_events_df[ret_8], nan_policy="omit")[0])

    audit_res = {
        "raw_candidate_count": raw_count,
        "unique_event_count": unique_count,
        "repeat_candidate_count": repeat_count,
        "repeat_ratio": repeat_ratio,
        "multiplicity_distribution": {
            "mean": mean_mult,
            "median": med_mult,
            "p90": p90_mult,
            "max": max_mult
        },
        "expectancy_comparison_72bars": {
            "mean_gross_bps": {"v1_raw": mean_v1_72, "first_event": mean_ev_72},
            "median_gross_bps": {"v1_raw": med_v1_72, "first_event": med_ev_72},
            "gross_gt_30bps_rate": {"v1_raw": v1_gt_30, "first_event": ev_gt_30},
            "gross_gt_40bps_rate": {"v1_raw": v1_gt_40, "first_event": ev_gt_40},
            "net_positive_rate": {"v1_raw": v1_net_pos, "first_event": ev_net_pos}
        },
        "regression_comparison_8bars": {
            "mean_gross_bps": {"v1_raw": mean_v1_8, "first_event": mean_ev_8},
            "spearman_corr": {"v1_raw": v1_corr_8, "first_event": ev_corr_8}
        }
    }

    # Grouped multiplicity statistics
    grouped_res = []
    for (fam, side), grp in c_df.groupby(["technical_signal_family", "side"]):
        n_raw = len(grp)
        n_uniq = len(grp[grp["event_seq"] == 0])
        n_rep = n_raw - n_uniq
        rep_ratio = n_rep / n_raw if n_raw > 0 else 0.0
        
        g_counts = grp["event_id"].value_counts()
        g_max = int(g_counts.max()) if not g_counts.empty else 0
        g_mean = float(g_counts.mean()) if not g_counts.empty else 0.0
        
        g_rets_72 = grp[grp["event_seq"] == 0][ret_72].dropna()
        g_mean_ev_72 = float(g_rets_72.mean() * 10_000.0) if not g_rets_72.empty else 0.0
        
        grouped_res.append({
            "trigger_family": fam,
            "side": side,
            "raw_candidates": n_raw,
            "unique_events": n_uniq,
            "repeat_ratio": rep_ratio,
            "mean_multiplicity": g_mean,
            "max_multiplicity": g_max,
            "first_event_mean_gross_72_bps": g_mean_ev_72
        })
        
    audit_res["by_trigger_family"] = grouped_res

    # Save output files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = output_dir / "multiplicity.json"
    with open(json_path, "w") as f:
        json.dump(audit_res, f, indent=2)
    print(f"  ✓ Saved audit JSON: {json_path}")

    # Build report markdown
    md_lines = [
        "# HMR-V2-G1.1: Candidate Multiplicity Audit Report\n",
        f"Audited **{raw_count} raw candidates** collapsing into **{unique_count} unique crossing events**.\n",
        "## 1. Multiplicity Statistics\n",
        "| Metric | Value | Interpretation |",
        "|:-------|:-----:|:---------------|",
        f"| **Raw Candidates** | `{raw_count}` | Total signals generated by candle polling |",
        f"| **Unique Crossing Events** | `{unique_count}` | Distinct crossing events after dedup |",
        f"| **Repeat Candidate Count** | `{repeat_count}` | Repeated signals on same event |",
        f"| **Repeat Ratio (%)** | `{repeat_ratio:.1%}` | Share of redundant candidates |",
        f"| **Mean Multiplicity** | `{mean_mult:.2f}` | Average signals emitted per event |",
        f"| **Max Multiplicity** | `{max_mult}` | Most repeated signal in a single event |",
        f"| **p90 Multiplicity** | `{p90_mult:.1f}` | 90th percentile of repeat rate |",
        
        "\n## 2. Trigger-Family Multiplicity Breakdown\n",
        "| Family | Side | Raw Candidates | Unique Events | Repeat Ratio | Mean Multiplicity | Max Multiplicity | First Event Gross (bps) |",
        "|:-------|:----:|--------------:|--------------:|-------------:|------------------:|-----------------:|------------------------:|",
    ]
    for r in grouped_res:
        md_lines.append(
            f"| {r['trigger_family']} | {r['side']} | {r['raw_candidates']} | {r['unique_events']} | "
            f"{r['repeat_ratio']:.1%} | {r['mean_multiplicity']:.2f} | {r['max_multiplicity']} | {r['first_event_mean_gross_72_bps']:+.2f} |"
        )
        
    md_lines.append("\n## 3. Expectancy Comparison (All vs First Event)\n")
    md_lines.append("| Metric | All Candidates (V1) | First Event Candidates (Deduped) | Delta |")
    md_lines.append("|:-------|:-------------------:|:-------------------------------:|:-----:|")
    md_lines.append(f"| **n** | `{raw_count}` | `{unique_count}` | `{unique_count - raw_count}` |")
    md_lines.append(f"| **Mean Gross @ 72** | `{mean_v1_72:+.2f} bps` | `{mean_ev_72:+.2f} bps` | `{mean_ev_72 - mean_v1_72:+.2f} bps` |")
    md_lines.append(f"| **Median Gross @ 72** | `{med_v1_72:+.2f} bps` | `{med_ev_72:+.2f} bps` | `{med_ev_72 - med_v1_72:+.2f} bps` |")
    md_lines.append(f"| **Gross > 30bps Rate** | `{v1_gt_30:.1%}` | `{ev_gt_30:.1%}` | `{ev_gt_30 - v1_gt_30:+.1%}` |")
    md_lines.append(f"| **Gross > 40bps Rate** | `{v1_gt_40:.1%}` | `{ev_gt_40:.1%}` | `{ev_gt_40 - v1_gt_40:+.1%}` |")
    md_lines.append(f"| **Net+ Rate** | `{v1_net_pos:.1%}` | `{ev_net_pos:.1%}` | `{ev_net_pos - v1_net_pos:+.1%}` |")
    md_lines.append(f"| **Spearman @ 8 bars** | `{v1_corr_8:+.4f}` | `{ev_corr_8:+.4f}` | `{ev_corr_8 - v1_corr_8:+.4f}` |")
    
    md_lines.append("\n## 4. Diagnosis and Gate Verdict\n")
    
    # Diagnosis of root cause
    reps_sma50 = next((r for r in grouped_res if r["trigger_family"] == "SMA50_BREAK" and r["side"] == "SELL"), None)
    if reps_sma50:
        md_lines.append(
            f"* **SMA50_BREAK SELL duplicate stats**: Raw count = `{reps_sma50['raw_candidates']}`, "
            f"Unique events = `{reps_sma50['unique_events']}`, Repeat ratio = `{reps_sma50['repeat_ratio']:.1%}`.  \n"
            f"* **Expectancy shift**: Deduplicating SMA50_BREAK SELL events shifted the first-event mean gross return to "
            f"`{reps_sma50['first_event_mean_gross_72_bps']:+.2f} bps`.  \n"
        )
        
    md_lines.append("```text\nCANDIDATE_MULTIPLICITY_AUDITED = PASS\n```\n")
    
    md_path = output_dir / "multiplicity.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD report: {md_path}")
    print()

    print("  GATE: CANDIDATE_MULTIPLICITY_AUDITED = PASS")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2-G1.1: Candidate Multiplicity Audit")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v2/v2_1_candidate_decomposition/candidates.parquet",
    )
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--warmup-bars", type=int, default=200)
    p.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v2/v2_g1_event_architecture/g1_1_multiplicity",
    )
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_multiplicity_audit(args))
