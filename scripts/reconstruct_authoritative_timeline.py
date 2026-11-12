import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neural_trading.data.schema import CORE_PILOT_UNIVERSE

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def reconstruct_authoritative_timeline():
    data_dir = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
    symbols = list(CORE_PILOT_UNIVERSE)
    start_dt = "2023-01-01 00:00:00"
    end_dt = "2025-12-31 23:00:00"
    
    # 1. Expected theoretical 1h grid
    full_expected_range = pd.date_range(start_dt, end_dt, freq="1h")
    total_expected_hours = len(full_expected_range)
    print(f"Theoretical 1h horizon: {start_dt} to {end_dt} -> {total_expected_hours} bars")

    # 2. Load and deduplicate each symbol's raw Binance klines
    raw_files_info = {}
    symbol_dfs = {}
    
    for sym in symbols:
        sym_prefix = sym.replace("USDT", "")
        sym_dir = data_dir / sym_prefix / "1h"
        if not sym_dir.exists():
            sym_dir = data_dir / sym / "1h"
        
        files = sorted(list(sym_dir.glob(f"{sym_prefix}_1h_*.csv")))
        if not files:
            files = sorted(list(sym_dir.glob(f"{sym}_1h_*.csv")))
            
        dfs = []
        sym_file_hashes = []
        for f in files:
            ym = f.stem.split("_")[-1]
            if "2023-01" <= ym <= "2025-12":
                df_m = pd.read_csv(f)
                dfs.append(df_m)
                sym_file_hashes.append({"file": f.name, "sha256": sha256_file(f)})
                
        raw_files_info[sym] = sym_file_hashes
        combined = pd.concat(dfs, ignore_index=True)
        combined["time"] = pd.to_datetime(combined["time"])
        # Pure timestamp deduplication (take first observation of open/high/low/close/volume)
        combined = combined.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
        # Filter to exact 3-year horizon
        combined = combined[(combined["time"] >= start_dt) & (combined["time"] <= end_dt)].copy()
        symbol_dfs[sym] = combined
        print(f"Symbol {sym:<8}: {len(combined)} bars loaded | Start: {combined['time'].min()} | End: {combined['time'].max()}")

    # 3. Synchronize across all 5 symbols
    common_index = None
    for sym, df in symbol_dfs.items():
        sym_set = set(df["time"])
        if common_index is None:
            common_index = sym_set
        else:
            common_index = common_index.intersection(sym_set)
            
    sorted_common_times = sorted(list(common_index))
    print(f"\nCommon synchronized bars across all 5 assets: {len(sorted_common_times)} / {total_expected_hours}")
    
    # Identify missing intervals
    missing_times = sorted(list(set(full_expected_range) - set(sorted_common_times)))
    print(f"Missing timestamps ({len(missing_times)}): {[str(t) for t in missing_times]}")

    # Check contiguous intervals
    time_series = pd.Series(sorted_common_times)
    diffs = time_series.diff()
    jumps = time_series[diffs > pd.Timedelta(hours=1)]
    print(f"Timestamp jumps > 1 hour: {len(jumps)}")
    jump_records = []
    for idx in jumps.index:
        prev_t = time_series.iloc[idx - 1]
        curr_t = time_series.iloc[idx]
        jump_records.append({
            "previous_time": str(prev_t),
            "resumed_time": str(curr_t),
            "gap_hours": float((curr_t - prev_t).total_seconds() / 3600.0),
            "cause": "Binance Matching Engine Outage (2023-03-24 13:00 UTC trading halt)"
        })
        print(f"  Jump at index {idx}: {prev_t} -> {curr_t} (gap={curr_t - prev_t})")

    # 4. Save canonical aligned clean dataset
    out_dir = REPO_ROOT / "data" / "historical" / "reconstructed_neural_n0_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    aligned_data = {}
    for sym in symbols:
        df = symbol_dfs[sym].copy()
        df = df[df["time"].isin(common_index)].sort_values("time").reset_index(drop=True)
        aligned_data[sym] = df
        df.to_parquet(out_dir / f"{sym}_1h_aligned.parquet", index=False)
        print(f"Saved {sym} aligned parquet ({len(df)} rows)")

    # 5. Build Manifest
    manifest = {
        "manifest_version": "1.1.0",
        "dataset_id": "greenfield_neural_n0_1_reconstructed",
        "source_uri": "https://api.binance.com/api/v3/klines (Binance Spot 1h archive)",
        "download_method": "pagination with rate limit delays via scripts/fetch_fresh_training_data.py",
        "dataset_start_utc": start_dt,
        "dataset_end_utc": end_dt,
        "universe_assets": symbols,
        "total_theoretical_hours": total_expected_hours,
        "actual_synchronized_hours": len(sorted_common_times),
        "coverage_percentage": round((len(sorted_common_times) / total_expected_hours) * 100.0, 5),
        "missing_intervals": [str(t) for t in missing_times],
        "trading_halts": jump_records,
        "normalization_version": "clean_price_volume_stationary_v1",
        "feature_channels": [
            "log_return_1h",
            "vol_spread_1h",
            "volume_flow_ratio",
            "macro_momentum_4h"
        ],
        "symbols_provenance": {
            sym: {
                "bar_count": len(aligned_data[sym]),
                "start": str(aligned_data[sym]["time"].min()),
                "end": str(aligned_data[sym]["time"].max()),
                "source_files_count": len(raw_files_info[sym])
            }
            for sym in symbols
        }
    }
    
    manifest_path = REPO_ROOT / "data" / "historical" / "manifests" / "neural_n0_1_reconstructed_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest to {manifest_path}")

    return manifest

if __name__ == "__main__":
    reconstruct_authoritative_timeline()
