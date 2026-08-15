#!/usr/bin/env python3
"""HMR-V2-G1.3: Whipsaw, Strength, and Context Characterization.

Recomputes point-in-time whipsaw and context indicators for all SMA50_BREAK candidates:
  - Whipsaw count: recent crossovers in last 8 and 16 bars
  - Break strength: distance in bps/atr, body ATR, volume ratio
  - Context/Trend: SMA50 slope, SMA200 slope, EMA9-EMA21 distance
  - Economic room: distance to 20-period rolling support/resistance

Runs quintile analysis, whipsaw regime diagnostic classification, and a 2D
whipsaw/trend diagnostic matrix to evaluate the SMA50_BREAK_CONTEXTUAL_EDGE gate.
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v2_g1_1_multiplicity_audit import calculate_indicators_and_crossings

COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


def calculate_rolling_metrics(df: pd.DataFrame) -> Dict[str, pd.Series]:
    close_col = next((c for c in ["close", "Close", "CLOSE"] if c in df.columns), "close")
    high_col = next((c for c in ["high", "High", "HIGH"] if c in df.columns), "high")
    low_col = next((c for c in ["low", "Low", "LOW"] if c in df.columns), "low")
    volume_col = next((c for c in ["volume", "Volume", "VOLUME"] if c in df.columns), "volume")
    
    close = df[close_col].astype(float)
    high = df[high_col].astype(float)
    low = df[low_col].astype(float)
    volume = df[volume_col].astype(float)
    
    sma50 = close.rolling(window=50, min_periods=1).mean()
    sma200 = close.rolling(window=200, min_periods=1).mean()
    
    # EMAs
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    
    # ATR
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14, min_periods=1).mean()
    
    # Volume SMA20
    vol_sma = volume.rolling(window=20, min_periods=1).mean()
    
    # Support/Resistance (rolling 20-period local min/max)
    support = low.rolling(window=20, min_periods=1).min()
    resistance = high.rolling(window=20, min_periods=1).max()
    
    # Crossing counts
    # Indicator cross (crossover occurrences)
    cross50 = np.zeros(len(df))
    for i in range(1, len(df)):
        prev_c, curr_c = close.iloc[i-1], close.iloc[i]
        prev_s50, curr_s50 = sma50.iloc[i-1], sma50.iloc[i]
        if (prev_c <= prev_s50 and curr_c > curr_s50) or (prev_c >= prev_s50 and curr_c < curr_s50):
            cross50[i] = 1
            
    cross50_series = pd.Series(cross50, index=df.index)
    cross_count_8 = cross50_series.rolling(window=8).sum()
    cross_count_16 = cross50_series.rolling(window=16).sum()
    
    # Slopes (5-bar diff)
    sma50_slope = (sma50 - sma50.shift(4)) / 5
    sma200_slope = (sma200 - sma200.shift(4)) / 5
    
    df_idx = df.index
    return {
        "sma50": sma50,
        "sma200": sma200,
        "ema9": ema9,
        "ema21": ema21,
        "atr": atr,
        "vol_sma": vol_sma,
        "support": support,
        "resistance": resistance,
        "cross_count_8": cross_count_8,
        "cross_count_16": cross_count_16,
        "sma50_slope": sma50_slope,
        "sma200_slope": sma200_slope
    }


def compute_quintiles(df: pd.DataFrame, col: str) -> List[Dict[str, Any]]:
    # Drop NaNs
    sub = df[["return_72bars", col]].dropna().copy()
    if len(sub) < 10:
        return []
        
    # Sort and split into 5 equal buckets
    sub = sub.sort_values(col).reset_index(drop=True)
    n = len(sub)
    chunk_size = max(1, n // 5)
    
    records = []
    for q in range(5):
        start_idx = q * chunk_size
        end_idx = (q + 1) * chunk_size if q < 4 else n
        chunk = sub.iloc[start_idx:end_idx]
        
        c_vals = chunk[col]
        rets = chunk["return_72bars"]
        
        mean_gross = float(rets.mean() * 10_000.0)
        med_gross = float(rets.median() * 10_000.0)
        gt_30 = float((rets > 0.0030).mean())
        gt_40 = float((rets > 0.0040).mean())
        net_pos = float((rets > COST_FRAC).mean())
        
        records.append({
            "quintile": q + 1,
            "min_val": float(c_vals.min()),
            "max_val": float(c_vals.max()),
            "n": len(chunk),
            "mean_gross_bps": mean_gross,
            "median_gross_bps": med_gross,
            "gross_gt_30_rate": gt_30,
            "gross_gt_40_rate": gt_40,
            "net_positive_rate": net_pos
        })
    return records


def run_characterization_audit(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run V2.1 first.")
        return 1

    print("HMR-V2-G1.3: Whipsaw, Strength, and Context Characterization")
    print(f"  Input candidates: {parquet_path}")
    print()

    # Load candidates (only filter SMA50_BREAK for characterization since it is 95% of database)
    df = pd.read_parquet(parquet_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
        
    sma50_df = df[df["technical_signal_family"] == "SMA50_BREAK"].copy().reset_index(drop=True)
    print(f"  Total SMA50_BREAK candidates: {len(sma50_df)}")
    
    # Load candles
    coins = list(sma50_df["symbol"].unique())
    start_time = sma50_df["timestamp"].min() - pd.Timedelta(days=5)
    end_time = sma50_df["timestamp"].max() + pd.Timedelta(days=1)
    
    print("  Loading closed candles...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start_time, end_time, end_time,
        warmup_bars=args.warmup_bars
    )
    
    # Compute rolling metrics
    coin_metrics: Dict[str, Dict[str, pd.Series]] = {}
    for coin, rows in candles_dict.items():
        df_candles = pd.DataFrame(rows)
        df_candles["time"] = pd.to_datetime(df_candles["time"])
        if df_candles["time"].dt.tz is None:
            df_candles["time"] = df_candles["time"].dt.tz_localize("UTC")
        else:
            df_candles["time"] = df_candles["time"].dt.tz_convert("UTC")
        df_candles.set_index("time", inplace=True)
        df_candles.sort_index(inplace=True)
        
        coin_metrics[coin] = calculate_rolling_metrics(df_candles)

    # Enrich candidates with PIT metrics
    whipsaw_8 = []
    whipsaw_16 = []
    slope50 = []
    slope200 = []
    ema_dist = []
    break_bps = []
    break_atr = []
    body_atr = []
    vol_ratio = []
    room_bps = []

    for idx, row in sma50_df.iterrows():
        coin = row["symbol"]
        side = row["side"]
        ts = row["timestamp"]
        entry_price = float(row["entry_price"])
        
        m = coin_metrics.get(coin)
        if m is None or ts not in m["sma50"].index:
            # Fallback values
            whipsaw_8.append(0.0)
            whipsaw_16.append(0.0)
            slope50.append(0.0)
            slope200.append(0.0)
            ema_dist.append(0.0)
            break_bps.append(0.0)
            break_atr.append(0.0)
            body_atr.append(0.0)
            vol_ratio.append(1.0)
            room_bps.append(100.0)
            continue
            
        # Extract indicators at candidate timestamp
        s50 = float(m["sma50"].loc[ts])
        s200 = float(m["sma200"].loc[ts])
        e9 = float(m["ema9"].loc[ts])
        e21 = float(m["ema21"].loc[ts])
        a_val = float(m["atr"].loc[ts])
        v_sma = float(m["vol_sma"].loc[ts])
        supp = float(m["support"].loc[ts])
        resis = float(m["resistance"].loc[ts])
        
        df_coin = candles_dict[coin]
        
        def match_time(c_time, target_ts):
            t = pd.to_datetime(c_time)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            else:
                t = t.tz_convert("UTC")
            return t == target_ts

        idx_candle = next(i for i, c in enumerate(df_coin) if match_time(c["time"], ts))
        curr_open = float(df_coin[idx_candle]["open"])
        curr_vol = float(df_coin[idx_candle]["volume"])
        
        w8 = float(m["cross_count_8"].loc[ts])
        w16 = float(m["cross_count_16"].loc[ts])
        sl50 = float(m["sma50_slope"].loc[ts])
        sl200 = float(m["sma200_slope"].loc[ts])
        
        whipsaw_8.append(w8)
        whipsaw_16.append(w16)
        slope50.append(sl50)
        slope200.append(sl200)
        
        # EMA distance
        ema_dist.append((e9 - e21) / entry_price * 10_000.0)
        
        # Break strength
        break_bps.append(abs(entry_price - s50) / s50 * 10_000.0)
        break_atr.append(abs(entry_price - s50) / max(a_val, 1e-6))
        body_atr.append(abs(entry_price - curr_open) / max(a_val, 1e-6))
        vol_ratio.append(curr_vol / max(v_sma, 1e-6))
        
        # Economic Room
        if side == "SELL":
            room = (entry_price - supp) / entry_price * 10_000.0
        else:
            room = (resis - entry_price) / entry_price * 10_000.0
        room_bps.append(room)

    sma50_df["recent_cross_count_8bars"] = whipsaw_8
    sma50_df["recent_cross_count_16bars"] = whipsaw_16
    sma50_df["sma50_slope"] = slope50
    sma50_df["sma200_slope"] = slope200
    sma50_df["ema9_ema21_distance"] = ema_dist
    sma50_df["break_distance_bps"] = break_bps
    sma50_df["break_distance_atr"] = break_atr
    sma50_df["candle_body_atr"] = body_atr
    sma50_df["volume_ratio"] = vol_ratio
    sma50_df["room_to_structure_bps"] = room_bps

    # --- G1.3 Quintile Sweep ---
    features = [
        "recent_cross_count_16bars",
        "break_distance_atr",
        "candle_body_atr",
        "volume_ratio",
        "sma50_slope",
        "ema9_ema21_distance",
        "room_to_structure_bps"
    ]
    
    quintile_sweeps = {}
    for feat in features:
        quintile_sweeps[feat] = compute_quintiles(sma50_df, feat)

    # --- G1.4 Whipsaw-Prone Diagnostic ---
    # Define candidate as WHIPSAW_PRONE if it crossed 2+ times in the last 16 bars
    sma50_df["whipsaw_prone"] = (sma50_df["recent_cross_count_16bars"] >= 2).astype(int)
    
    whipsaw_groups = []
    for is_prone, sub in sma50_df.groupby("whipsaw_prone"):
        rets = sub["return_72bars"].dropna()
        n = len(sub)
        mean_g = float(rets.mean() * 10_000.0) if n > 0 else 0.0
        gt_30 = float((rets > 0.0030).mean()) if n > 0 else 0.0
        gt_40 = float((rets > 0.0040).mean()) if n > 0 else 0.0
        net_pos = float((rets > COST_FRAC).mean()) if n > 0 else 0.0
        
        whipsaw_groups.append({
            "regime": "WHIPSAW_PRONE" if is_prone == 1 else "NON_WHIPSAW",
            "n": n,
            "mean_gross_bps": mean_g,
            "gross_gt_30_rate": gt_30,
            "gross_gt_40_rate": gt_40,
            "net_positive_rate": net_pos
        })

    # --- G1.7 Whipsaw-Specific Economic Diagnosis Matrix ---
    # 2D cross: crossover frequency (Low vs High) x SMA50 slope magnitude (Weak vs Strong)
    # Low cross: < 2 crosses in 16 bars. High cross: >= 2 crosses in 16 bars.
    # Weak slope: magnitude < median slope. Strong slope: magnitude >= median slope.
    med_slope = abs(sma50_df["sma50_slope"]).median()
    
    def classify_2d(row):
        freq = "Low" if row["recent_cross_count_16bars"] < 2 else "High"
        slope = "Strong" if abs(row["sma50_slope"]) >= med_slope else "Weak"
        return f"{freq}Cross_{slope}Slope"

    sma50_df["matrix_group"] = sma50_df.apply(classify_2d, axis=1)
    
    matrix_groups = []
    for g_name, sub in sma50_df.groupby("matrix_group"):
        rets = sub["return_72bars"].dropna()
        n = len(sub)
        mean_g = float(rets.mean() * 10_000.0) if n > 0 else 0.0
        gt_30 = float((rets > 0.0030).mean()) if n > 0 else 0.0
        gt_40 = float((rets > 0.0040).mean()) if n > 0 else 0.0
        net_pos = float((rets > COST_FRAC).mean()) if n > 0 else 0.0
        
        matrix_groups.append({
            "group": g_name,
            "n": n,
            "mean_gross_bps": mean_g,
            "gross_gt_30_rate": gt_30,
            "gross_gt_40_rate": gt_40,
            "net_positive_rate": net_pos
        })

    # Save to JSON files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "break_strength.json", "w") as f:
        json.dump(quintile_sweeps, f, indent=2)
    print(f"  ✓ Saved break strength quintiles JSON.")

    room_data = {
        "quintiles": compute_quintiles(sma50_df, "room_to_structure_bps"),
        "whipsaw_prone_regimes": whipsaw_groups,
        "diagnosis_2d_matrix": matrix_groups
    }
    with open(output_dir / "economic_room.json", "w") as f:
        json.dump(room_data, f, indent=2)
    print(f"  ✓ Saved economic room and whipsaw matrix JSON.")

    # Check the SMA50_BREAK_CONTEXTUAL_EDGE Gate
    # Threshold: is there any bucket/quintile with Gross>30 rate >= 15% AND sample size n >= 50?
    gate_passed = False
    winning_group = None
    
    # Check sweeps
    for feat, q_list in quintile_sweeps.items():
        for q in q_list:
            if q["gross_gt_30_rate"] >= 0.15 and q["n"] >= 50:
                gate_passed = True
                winning_group = f"Quintile {q['quintile']} of feature {feat}"
                break
        if gate_passed:
            break
            
    # Check whipsaw groups
    for w in whipsaw_groups:
        if w["gross_gt_30_rate"] >= 0.15 and w["n"] >= 50:
            gate_passed = True
            winning_group = f"Whipsaw group {w['regime']}"
            break
            
    # Check matrix groups
    for m in matrix_groups:
        if m["gross_gt_30_rate"] >= 0.15 and m["n"] >= 50:
            gate_passed = True
            winning_group = f"2D matrix group {m['group']}"
            break

    gate_status = "PASS" if gate_passed else "FAIL"

    # Build report markdown
    md_lines = [
        "# HMR-V2-G1.3: Whipsaw, Strength, and Context Characterization Report\n",
        f"Analyzed **{len(sma50_df)} SMA50_BREAK candidates** over the period **{start_time.date()}** to **{end_time.date()}**.\n",
        "## 1. Whipsaw-Prone Diagnostic Classifier (G1.4)\n",
        "Splitting candidates into `WHIPSAW_PRONE` (crossovers >= 2 in last 16 bars) versus `NON_WHIPSAW`:\n",
        "| Regime | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |",
        "|:-------|--:|---------------------:|------------------:|------------------:|----------:|",
    ]
    for w in whipsaw_groups:
        md_lines.append(
            f"| {w['regime']} | {w['n']} | {w['mean_gross_bps']:+.2f} | {w['gross_gt_30_rate']:.1%} | {w['gross_gt_40_rate']:.1%} | {w['net_positive_rate']:.1%} |"
        )
        
    md_lines.append("\n## 2. Whipsaw-Specific Economic Diagnosis Matrix (G1.7)\n")
    md_lines.append("2D Matrix: Crossing frequency (Low/High) x SMA50 Slope Magnitude (Weak/Strong):\n")
    md_lines.append("| Matrix Group | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |")
    md_lines.append("|:-------------|--:|---------------------:|------------------:|------------------:|----------:|")
    for m in matrix_groups:
        md_lines.append(
            f"| {m['group']} | {m['n']} | {m['mean_gross_bps']:+.2f} | {m['gross_gt_30_rate']:.1%} | {m['gross_gt_40_rate']:.1%} | {m['net_positive_rate']:.1%} |"
        )

    md_lines.append("\n## 3. Quintile Sweeps Spread Analysis\n")
    for feat, q_list in quintile_sweeps.items():
        md_lines.append(f"### Feature: `{feat}`")
        md_lines.append("| Quintile | Range | n | Mean Gross @72 (bps) | Gross >30bps Rate | Gross >40bps Rate | Net+ Rate |")
        md_lines.append("|:--------:|:------|--:|---------------------:|------------------:|------------------:|----------:|")
        for q in q_list:
            md_lines.append(
                f"| {q['quintile']} | `{q['min_val']:.4f}` to `{q['max_val']:.4f}` | {q['n']} | "
                f"{q['mean_gross_bps']:+.2f} | {q['gross_gt_30_rate']:.1%} | {q['gross_gt_40_rate']:.1%} | {q['net_positive_rate']:.1%} |"
            )
        md_lines.append("")

    md_lines.append("\n## 4. Transition Gate Verdict\n")
    md_lines.append(f"* **SMA50_BREAK_CONTEXTUAL_EDGE Gate Status**: **{gate_status}**  \n")
    if gate_passed:
        md_lines.append(f"  - **Winning Subgroup**: `{winning_group}`  \n")
        md_lines.append(f"  - **Result**: Pre-entry context successfully isolated a region that enriches `Gross > 30bps` rate above the 15% threshold with adequate sample size. **We retain the SMA50_BREAK trigger family and proceed to evaluate event confirmation filters**.\n")
    else:
        md_lines.append("  - **Result**: No single context or bucket reached the 15% positive rate target with sufficient sample size. **We reject the SMA50_BREAK family as fundamentally toxic and recommend stopping research on it**.\n")

    md_path = output_dir / "report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD report: {md_path}")
    print()

    print(f"  GATE: SMA50_BREAK_CONTEXTUAL_EDGE = {gate_status}")
    if winning_group:
        print(f"    Winning group: {winning_group}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2-G1.3: Whipsaw, Strength, and Context Characterization")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v2/v2_1_candidate_decomposition/candidates.parquet",
    )
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--warmup-bars", type=int, default=200)
    p.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v2/v2_g1_event_architecture/g1_3_characterization",
    )
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_characterization_audit(args))
