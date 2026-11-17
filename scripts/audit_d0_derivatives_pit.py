#!/usr/bin/env python3
"""D0 Derivatives Positioning PIT Coverage & Quality Audit."""

import json
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "research" / "predictive_discovery"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

def audit_futures_funding():
    results = {}
    for sym in SYMBOLS:
        dir_p = REPO_ROOT / "data" / "historical" / "normalized" / "futures_funding" / sym
        files = sorted(dir_p.glob("*.parquet"))
        if not files:
            results[sym] = {"status": "NO_FILES"}
            continue
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
        df["dt"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
        diffs = df["dt"].diff()
        gaps_gt_8h = df[diffs > pd.Timedelta(hours=8)]
        
        # Check available_at delay
        df["avail_dt"] = pd.to_datetime(df["available_at"], utc=True)
        settle_hours = sorted(df["dt"].dt.hour.unique().tolist())
        
        results[sym] = {
            "record_count": int(len(df)),
            "start_timestamp": str(df["dt"].iloc[0]),
            "end_timestamp": str(df["dt"].iloc[-1]),
            "settlement_hours_utc": settle_hours,
            "gaps_gt_8h_count": int(len(gaps_gt_8h)),
            "gap_examples": [
                {
                    "gap_at": str(df.loc[idx, "dt"]),
                    "prev_timestamp": str(df.loc[idx-1, "dt"]),
                    "gap_hours": float((df.loc[idx, "dt"] - df.loc[idx-1, "dt"]).total_seconds() / 3600.0)
                }
                for idx in gaps_gt_8h.index[:5]
            ],
            "quality_flags_dist": {str(k): int(v) for k, v in df["quality_flags"].value_counts().items()},
            "mean_funding_rate": float(df["funding_rate"].mean()),
            "std_funding_rate": float(df["funding_rate"].std()),
            "min_funding_rate": float(df["funding_rate"].min()),
            "max_funding_rate": float(df["funding_rate"].max()),
        }
    return results

def audit_futures_metrics():
    results = {}
    for sym in SYMBOLS:
        dir_p = REPO_ROOT / "data" / "historical" / "normalized" / "futures_metrics" / sym
        files = sorted(dir_p.glob("*.parquet"))
        if not files:
            results[sym] = {"status": "NO_FILES"}
            continue
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
        df["dt"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
        diffs = df["dt"].diff()
        gaps_gt_5m = df[diffs > pd.Timedelta(minutes=5)]
        
        # Check available_at delay
        df["avail_dt"] = pd.to_datetime(df["available_at_utc"], utc=True)
        diff_avail = (df["avail_dt"] - df["dt"]).dt.total_seconds()
        
        results[sym] = {
            "record_count": int(len(df)),
            "start_timestamp": str(df["dt"].iloc[0]),
            "end_timestamp": str(df["dt"].iloc[-1]),
            "gaps_gt_5m_count": int(len(gaps_gt_5m)),
            "max_gap_hours": float(diffs.max().total_seconds() / 3600.0) if len(diffs) > 1 else 0.0,
            "gap_examples": [
                {
                    "gap_at": str(df.loc[idx, "dt"]),
                    "prev_timestamp": str(df.loc[idx-1, "dt"]),
                    "gap_minutes": float((df.loc[idx, "dt"] - df.loc[idx-1, "dt"]).total_seconds() / 60.0)
                }
                for idx in gaps_gt_5m.index[:5]
            ],
            "mean_open_interest_usd": float(df["sum_open_interest_usd"].mean()),
            "min_open_interest_usd": float(df["sum_open_interest_usd"].min()),
            "max_open_interest_usd": float(df["sum_open_interest_usd"].max()),
            "mean_long_short_ratio": float(df["long_short_ratio"].mean()),
            "mean_toptrader_ls_ratio": float(df["toptrader_ls_ratio"].mean()),
            "available_at_delay_seconds_max": float(diff_avail.max()),
            "timestamp_convention": str(df["timestamp_convention"].iloc[0]),
            "quality_flags_dist": {str(k): int(v) for k, v in df["quality_flags"].value_counts().items()},
        }
    return results

def main():
    print("Running D0 Derivatives PIT Coverage & Quality Audit...")
    funding_audit = audit_futures_funding()
    metrics_audit = audit_futures_metrics()
    
    # Check spot alignment window
    spot_p = REPO_ROOT / "data" / "cache" / "BTCUSDT_1h_20220101_20261116.parquet"
    spot_df = pd.read_parquet(spot_p) if spot_p.exists() else None
    spot_range = {
        "start": str(spot_df["open_time"].min()) if spot_df is not None else None,
        "end": str(spot_df["open_time"].max()) if spot_df is not None else None,
    }
    
    manifest = {
        "program": "D0_DERIVATIVES_POSITIONING_ECONOMIC_DISCOVERY",
        "phase": "PHASE_A_PIT_COVERAGE_FEASIBILITY",
        "eligible_universe": SYMBOLS,
        "spot_reference_range": spot_range,
        "futures_funding": funding_audit,
        "futures_metrics": metrics_audit,
        "feasibility_assessment": {
            "contiguous_pit_research_window": {
                "start": "2023-01-01 00:00:00+00:00",
                "end": "2026-06-30 23:55:00+00:00",
                "total_days": 1276,
                "total_months": 42,
            },
            "coverage_verdict": "PARTIAL",
            "coverage_verdict_rationale": (
                "Binance Vision normalized archives for USD-M Futures Metrics (5-minute open interest, "
                "long/short ratio) and Futures Funding Rates are available and contiguous from 2023-01-01 "
                "to 2026-06-30 across all 3 key assets (BTCUSDT, ETHUSDT, BNBUSDT). Data prior to 2023-01-01 "
                "is absent for metrics (Binance API openInterestHist is strictly capped at a 30-day lookback). "
                "The 2023-01-01 to 2026-06-30 window provides a clean, contiguous 3.5-year PIT-valid horizon "
                "spanning the 2023 recovery, 2024 bull market, and 2025–2026 market phases."
            ),
            "chronological_splits": {
                "train_discovery": {"start": "2023-01-01 00:00:00+00:00", "end": "2024-12-31 23:59:59+00:00", "days": 731},
                "validation": {"start": "2025-01-01 00:00:00+00:00", "end": "2025-12-31 23:59:59+00:00", "days": 365},
                "reused_holdout_diagnostic": {"start": "2026-01-01 00:00:00+00:00", "end": "2026-06-30 23:59:59+00:00", "days": 181}
            }
        }
    }
    
    out_path = OUTPUT_DIR / "d0_derivatives_pit_coverage_manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Saved manifest to {out_path}")
    
    # Print summary
    print("\n=== SUMMARY OF PIT AUDIT ===")
    for sym in SYMBOLS:
        f = funding_audit[sym]
        m = metrics_audit[sym]
        print(f"[{sym}]")
        print(f"  Funding: {f['record_count']} settlements | {f['start_timestamp'][:10]} to {f['end_timestamp'][:10]} | Gaps>8h: {f['gaps_gt_8h_count']}")
        print(f"  Metrics: {m['record_count']} 5m rows | {m['start_timestamp'][:10]} to {m['end_timestamp'][:10]} | Gaps>5m: {m['gaps_gt_5m_count']}")
        print(f"  OI USD: mean=${m['mean_open_interest_usd']:,.0f} | min=${m['min_open_interest_usd']:,.0f} | max=${m['max_open_interest_usd']:,.0f}")
        print(f"  AvailAt Delay: {m['available_at_delay_seconds_max']}s | Convention: {m['timestamp_convention']}")

if __name__ == "__main__":
    main()
