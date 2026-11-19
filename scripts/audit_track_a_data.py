#!/usr/bin/env python3
"""Hermetic Track A and S5 Baseline Data Readiness Audit Script.

Performs complete audit across:
1. Binance Spot 1h raw monthly archives (2017-2025)
2. Fresh training data 2023-2026 (1h, 1d)
3. Holdout Spot 2026 H2 (2026-07-01 to 2026-11-09)
4. Historical unified replay parquets (2022 to 2026-11-16)
5. Timestamp format, OHLCV invariants, gaps, and daily/hourly reconciliation.
6. Manifest generation: research/track_a/data_readiness/track_a_data_manifest.json
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")

BINANCE_COLUMNS = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def audit_raw_binance_archive(zip_path: Path) -> dict[str, Any]:
    file_sha256 = sha256_file(zip_path)
    sidecar_path = Path(str(zip_path) + ".sha256")
    sidecar_sha256 = None
    sidecar_match = None
    if sidecar_path.is_file():
        sidecar_sha256 = sidecar_path.read_text(encoding="utf-8").strip().split()[0].lower()
        sidecar_match = (file_sha256 == sidecar_sha256)

    rows = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            return {"error": "no csv in zip", "file_sha256": file_sha256}
        with zf.open(csv_names[0]) as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
            for r in reader:
                if not r:
                    continue
                try:
                    int(r[0])
                    rows.append(r)
                except ValueError:
                    continue

    if not rows:
        return {"error": "empty data", "file_sha256": file_sha256}

    open_times = [int(r[0]) for r in rows]
    first_ts = open_times[0]
    ts_unit = "ms" if first_ts < 3e14 else "us"
    scale = 1000 if ts_unit == "us" else 1

    open_times_ms = [t // scale for t in open_times]
    duplicates = len(open_times_ms) - len(set(open_times_ms))
    is_monotonic = all(open_times_ms[i] < open_times_ms[i+1] for i in range(len(open_times_ms)-1))

    # OHLCV invariants
    ohlcv_violations = 0
    for r in rows:
        try:
            o = float(r[1])
            h = float(r[2])
            l = float(r[3])
            c = float(r[4])
            v = float(r[5])
            if not (o > 0 and c > 0 and h >= max(o, c) - 1e-6 and l <= min(o, c) + 1e-6 and h >= l and v >= 0):
                ohlcv_violations += 1
        except Exception:
            ohlcv_violations += 1

    first_dt = pd.to_datetime(open_times_ms[0], unit="ms", utc=True)
    last_dt = pd.to_datetime(open_times_ms[-1], unit="ms", utc=True)

    rel_path = str(zip_path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")

    return {
        "path": rel_path,
        "sha256": file_sha256,
        "sidecar_sha256": sidecar_sha256,
        "sidecar_match": sidecar_match,
        "candle_count": len(rows),
        "timestamp_unit": ts_unit,
        "is_monotonic": is_monotonic,
        "duplicate_count": duplicates,
        "ohlcv_violations": ohlcv_violations,
        "first_timestamp_utc": first_dt.isoformat(),
        "last_timestamp_utc": last_dt.isoformat(),
        "first_ts_ms": open_times_ms[0],
        "last_ts_ms": open_times_ms[-1],
    }


def normalize_candle_row(r: list[str]) -> list[Any]:
    raw_ts = int(r[0])
    scale = 1000 if raw_ts > 3e14 else 1
    ts_ms = raw_ts // scale
    raw_close_ts = int(r[6])
    close_ts_ms = raw_close_ts // scale
    return [
        ts_ms,
        float(r[1]),
        float(r[2]),
        float(r[3]),
        float(r[4]),
        float(r[5]),
        close_ts_ms,
        float(r[7]),
        int(r[8]),
        float(r[9]),
        float(r[10]),
        int(r[11]) if len(r) > 11 else 0
    ]


def main():
    print("=== BESTTIME-CRYPTO TRACK A & S5 DATA READINESS AUDIT ===", flush=True)
    out_dir = REPO_ROOT / "research/track_a/data_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Audit Binance Spot 1h raw monthly archives
    raw_1h_root = REPO_ROOT / "data/historical/neural_n1/raw/binance_spot_klines_1h"
    raw_1h_results = {}
    total_raw_archives = 0
    sidecar_mismatches = 0
    microsecond_archive_count = 0

    print("\n1. Auditing Binance Spot 1h raw monthly archives...", flush=True)
    for sym in UNIVERSE:
        sym_dir = raw_1h_root / sym
        if not sym_dir.exists():
            print(f"Directory not found for {sym}: {sym_dir}", flush=True)
            continue
        zips = sorted(list(sym_dir.glob(f"{sym}-1h-*.zip")))
        raw_1h_results[sym] = []
        for z in zips:
            res = audit_raw_binance_archive(z)
            raw_1h_results[sym].append(res)
            total_raw_archives += 1
            if res.get("sidecar_match") is False:
                sidecar_mismatches += 1
            if res.get("timestamp_unit") == "us":
                microsecond_archive_count += 1

        first_p = raw_1h_results[sym][0]["first_timestamp_utc"] if raw_1h_results[sym] else "N/A"
        last_p = raw_1h_results[sym][-1]["last_timestamp_utc"] if raw_1h_results[sym] else "N/A"
        total_candles = sum(r["candle_count"] for r in raw_1h_results[sym])
        print(f"  {sym}: {len(zips)} archives, {total_candles} candles. Range: {first_p} to {last_p}", flush=True)

    print(f"Total raw archives audited: {total_raw_archives}, sidecar mismatches: {sidecar_mismatches}, microsecond archives (2025+): {microsecond_archive_count}", flush=True)

    # 2. Audit 2026 H2 Holdout Spot
    print("\n2. Auditing 2026 H2 Holdout Spot...", flush=True)
    holdout_root = REPO_ROOT / "data/historical/raw/holdout_spot"
    holdout_results = {}
    for sym in UNIVERSE:
        sym_dir = holdout_root / sym
        if not sym_dir.exists():
            holdout_results[sym] = {"status": "MISSING_DIR", "archives": []}
            print(f"  {sym}: NO holdout_spot directory found!", flush=True)
            continue
        zips = sorted(list(sym_dir.glob(f"{sym}-1h-*.zip")))
        holdout_results[sym] = {"status": "PRESENT" if zips else "EMPTY", "archives": []}
        for z in zips:
            res = audit_raw_binance_archive(z)
            holdout_results[sym]["archives"].append(res)
        total_c = sum(r["candle_count"] for r in holdout_results[sym]["archives"])
        print(f"  {sym}: {len(zips)} holdout archives, {total_c} candles.", flush=True)

    # 3. Audit fresh_training_data_2023_2026 (1h and 1d)
    print("\n3. Auditing fresh_training_data_2023_2026...", flush=True)
    fresh_root = REPO_ROOT / "data/fresh_training_data_2023_2026"
    fresh_1h_results = {}
    fresh_1d_results = {}
    coin_map = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "BNBUSDT": "BNB"}
    for sym in UNIVERSE:
        c = coin_map[sym]
        # 1h
        p_1h = fresh_root / c / "1h"
        if p_1h.exists():
            f_1h = sorted(list(p_1h.glob("*.csv")))
            total_rows_1h = 0
            first_row_1h = None
            last_row_1h = None
            for idx, fp in enumerate(f_1h):
                df = pd.read_csv(fp)
                total_rows_1h += len(df)
                if idx == 0 and len(df) > 0:
                    first_row_1h = df.iloc[0].to_dict()
                if idx == len(f_1h) - 1 and len(df) > 0:
                    last_row_1h = df.iloc[-1].to_dict()
            fresh_1h_results[sym] = {
                "file_count": len(f_1h),
                "total_rows": total_rows_1h,
                "first": first_row_1h,
                "last": last_row_1h,
            }
            print(f"  {sym} 1h: {len(f_1h)} monthly CSVs, {total_rows_1h} rows. First={first_row_1h.get('time') if first_row_1h else None}, Last={last_row_1h.get('time') if last_row_1h else None}", flush=True)

        # 1d
        p_1d = fresh_root / c / "1d"
        if p_1d.exists():
            f_1d = sorted(list(p_1d.glob("*.csv")))
            total_rows_1d = 0
            first_row_1d = None
            last_row_1d = None
            for idx, fp in enumerate(f_1d):
                df = pd.read_csv(fp)
                total_rows_1d += len(df)
                if idx == 0 and len(df) > 0:
                    first_row_1d = df.iloc[0].to_dict()
                if idx == len(f_1d) - 1 and len(df) > 0:
                    last_row_1d = df.iloc[-1].to_dict()
            fresh_1d_results[sym] = {
                "file_count": len(f_1d),
                "total_rows": total_rows_1d,
                "first": first_row_1d,
                "last": last_row_1d,
            }
            print(f"  {sym} 1d: {len(f_1d)} monthly CSVs, {total_rows_1d} rows. First={first_row_1d.get('time') if first_row_1d else None}, Last={last_row_1d.get('time') if last_row_1d else None}", flush=True)

    # 4. Detailed Gap & Alignment Audit on BTC 1h
    print("\n4. Checking full timeline continuity and gaps for BTCUSDT...", flush=True)
    # Load all BTC raw archives 2021 to 2025
    btc_zips = sorted([
        z for z in (raw_1h_root / "BTCUSDT").glob("BTCUSDT-1h-*.zip")
        if re.search(r"-(\d{4})-\d{2}\.zip$", z.name) and int(re.search(r"-(\d{4})-\d{2}\.zip$", z.name).group(1)) >= 2021
    ])
    btc_rows = []
    for z in btc_zips:
        with zipfile.ZipFile(z, "r") as zf:
            cname = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(cname) as f:
                rdr = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for r in rdr:
                    try:
                        int(r[0])
                        btc_rows.append(normalize_candle_row(r))
                    except ValueError:
                        pass

    # Append 2026-01 to 2026-06 from fresh_training_data
    for fp in sorted((fresh_root / "BTC/1h").glob("BTC_1h_2026-*.csv")):
        df = pd.read_csv(fp)
        df_non_warmup = df[df["is_warmup"] == 0] if "is_warmup" in df.columns else df
        dts = pd.to_datetime(df_non_warmup["time"], utc=True)
        # Convert timestamp to ms
        raw_int = dts.astype(np.int64).to_numpy()
        # if int is microseconds (>3e14), scale by 1000
        ts_ms = np.where(raw_int > 3e14, raw_int // 1000, raw_int)
        for idx in range(len(df_non_warmup)):
            btc_rows.append([
                int(ts_ms[idx]),
                float(df_non_warmup["open"].iloc[idx]),
                float(df_non_warmup["high"].iloc[idx]),
                float(df_non_warmup["low"].iloc[idx]),
                float(df_non_warmup["close"].iloc[idx]),
                float(df_non_warmup["volume"].iloc[idx]),
                int(ts_ms[idx] + 3599999),
                0.0, 0, 0.0, 0.0, 0
            ])

    # Append 2026 H2 holdout
    for z in sorted((holdout_root / "BTCUSDT").glob("BTCUSDT-1h-*.zip")):
        with zipfile.ZipFile(z, "r") as zf:
            cname = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(cname) as f:
                rdr = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for r in rdr:
                    try:
                        int(r[0])
                        btc_rows.append(normalize_candle_row(r))
                    except ValueError:
                        pass

    # Build DataFrame
    df_btc = pd.DataFrame(btc_rows, columns=BINANCE_COLUMNS)
    df_btc["open_time_ms"] = df_btc["open_time_ms"].astype(np.int64)
    # Deduplicate by open_time_ms
    df_btc = df_btc.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms").reset_index(drop=True)
    df_btc["dt"] = pd.to_datetime(df_btc["open_time_ms"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df_btc[col] = df_btc[col].astype(float)

    print(f"Total reconstructed continuous BTC 1h bars: {len(df_btc)}", flush=True)
    print(f"BTC 1h min dt: {df_btc['dt'].min()}, max dt: {df_btc['dt'].max()}", flush=True)

    # Check missing hours
    full_range = pd.date_range(df_btc["dt"].min(), df_btc["dt"].max(), freq="1h", tz="UTC")
    expected_hours = len(full_range)
    actual_hours = len(df_btc)
    missing_dts = full_range.difference(df_btc["dt"])
    print(f"Expected hours: {expected_hours}, Actual: {actual_hours}, Missing: {len(missing_dts)}", flush=True)
    print(f"Missing hours list: {[d.isoformat() for d in missing_dts]}", flush=True)

    # 5. Daily Aggregation & Reconciliation with fresh_training_data BTC 1d
    print("\n5. Daily/Hourly Reconciliation for BTC...", flush=True)
    df_btc_indexed = df_btc.set_index("dt")
    daily_agg = df_btc_indexed.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "open_time_ms": "count"
    }).rename(columns={"open_time_ms": "hour_count"})
    daily_agg = daily_agg[daily_agg["hour_count"] > 0]

    print(f"Aggregated daily candles: {len(daily_agg)} days, start={daily_agg.index[0]}, end={daily_agg.index[-1]}", flush=True)
    incomplete_days = daily_agg[daily_agg["hour_count"] < 24]
    print(f"Days with < 24 hours: {len(incomplete_days)}", flush=True)
    for dt, r in incomplete_days.iterrows():
        print(f"  {dt.strftime('%Y-%m-%d')}: {int(r['hour_count'])} hours", flush=True)

    # Load fresh_training_data BTC 1d CSVs
    fresh_1d_dfs = []
    for fp in sorted((fresh_root / "BTC/1d").glob("BTC_1d_*.csv")):
        fresh_1d_dfs.append(pd.read_csv(fp))
    df_fresh_1d = pd.concat(fresh_1d_dfs, ignore_index=True)
    df_fresh_1d["dt"] = pd.to_datetime(df_fresh_1d["time"], utc=True)
    df_fresh_1d = df_fresh_1d.drop_duplicates(subset=["dt"]).sort_values("dt").set_index("dt")

    overlap_idx = daily_agg.index.intersection(df_fresh_1d.index)
    print(f"Overlapping daily candles between aggregated 1h and fresh 1d: {len(overlap_idx)}", flush=True)
    reconciliation_results = {}
    if len(overlap_idx) > 0:
        agg_sub = daily_agg.loc[overlap_idx]
        fresh_sub = df_fresh_1d.loc[overlap_idx]

        for col in ["open", "high", "low", "close", "volume"]:
            diff = (agg_sub[col] - fresh_sub[col]).abs()
            rel_diff = diff / fresh_sub[col].replace(0, np.nan)
            reconciliation_results[col] = {
                "max_abs_diff": float(diff.max()),
                "mean_abs_diff": float(diff.mean()),
                "max_rel_diff": float(rel_diff.max()),
                "perfect_match_count": int((diff < 1e-4).sum()),
                "total_compared": len(overlap_idx)
            }
            print(f"  {col}: max_abs_diff={diff.max():.6f}, max_rel_diff={rel_diff.max():.6e}, perfect matches={int((diff < 1e-4).sum())}/{len(overlap_idx)}", flush=True)

    # 6. Audit Unified Replay Parquets
    print("\n6. Auditing Historical Unified Replay Parquets...", flush=True)
    replay_root = REPO_ROOT / "data/historical_unified_replay"
    replay_results = {}
    for sym in UNIVERSE:
        pfile = replay_root / f"{sym}_1h_20220101_20261116.parquet"
        if not pfile.exists():
            replay_results[sym] = {"status": "MISSING"}
            continue
        df_p = pd.read_parquet(pfile)
        df_p["dt"] = pd.to_datetime(df_p["open_time_ms"], unit="ms", utc=True)
        replay_results[sym] = {
            "status": "PRESENT",
            "path": str(pfile.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/"),
            "sha256": sha256_file(pfile),
            "total_bars": len(df_p),
            "start_dt": df_p["dt"].min().isoformat(),
            "end_dt": df_p["dt"].max().isoformat(),
        }
        print(f"  {sym}: {len(df_p)} bars, {df_p['dt'].min()} to {df_p['dt'].max()}", flush=True)

    # 7. S5 Universe Synchronization (BTC, ETH, SOL, BNB)
    print("\n7. Evaluating S5 Universe Synchronization & Baseline Eligibility...", flush=True)
    universe_summary = {}
    for sym in UNIVERSE:
        c = coin_map[sym]
        has_2021_raw = any("2021" in r["path"] for r in raw_1h_results.get(sym, []))
        has_2022_2023_raw = any("2022" in r["path"] or "2023" in r["path"] for r in raw_1h_results.get(sym, []))
        has_2024_2025_raw = any("2024" in r["path"] or "2025" in r["path"] for r in raw_1h_results.get(sym, []))
        has_2026_h1_fresh = fresh_1h_results.get(sym, {}).get("file_count", 0) >= 42
        has_2026_h2_holdout = len(holdout_results.get(sym, {}).get("archives", [])) > 0
        universe_summary[sym] = {
            "2021_raw": has_2021_raw,
            "2022_2023_raw": has_2022_2023_raw,
            "2024_2025_raw": has_2024_2025_raw,
            "2026_h1_fresh": has_2026_h1_fresh,
            "2026_h2_holdout_raw": has_2026_h2_holdout,
        }
        print(f"  {sym}: 2021={has_2021_raw}, 2022-2023={has_2022_2023_raw}, 2024-2025={has_2024_2025_raw}, 2026_H1={has_2026_h1_fresh}, 2026_H2_raw={has_2026_h2_holdout}", flush=True)

    # 8. Compute Decision Dates & Horizons
    print("\n8. Computing First and Latest Decision Dates...", flush=True)
    latest_completed_daily = daily_agg.index[-1]
    if daily_agg.loc[latest_completed_daily, "hour_count"] < 24:
        latest_verified_1d = daily_agg.index[-2]
    else:
        latest_verified_1d = latest_completed_daily

    latest_verified_1h = df_btc["dt"].iloc[-1]

    print(f"  LATEST_VERIFIED_1D_CANDLE: {latest_verified_1d.strftime('%Y-%m-%d')} (24 completed hourly bars)", flush=True)
    print(f"  LATEST_VERIFIED_1H_CANDLE: {latest_verified_1h.isoformat()}", flush=True)

    # 9. Output Manifest
    manifest_data = {
        "manifest_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_objective": "Track A Data Readiness Audit & S5 Baseline Compatibility",
        "universe": list(UNIVERSE),
        "summary": {
            "btc_1h_bars": len(df_btc),
            "btc_1h_start_utc": df_btc["dt"].iloc[0].isoformat(),
            "btc_1h_end_utc": df_btc["dt"].iloc[-1].isoformat(),
            "btc_1d_aggregated_days": len(daily_agg),
            "btc_1d_first_day": daily_agg.index[0].strftime("%Y-%m-%d"),
            "btc_1d_last_day": daily_agg.index[-1].strftime("%Y-%m-%d"),
            "latest_verified_1d_candle": latest_verified_1d.strftime("%Y-%m-%d"),
            "latest_verified_1h_candle": latest_verified_1h.isoformat(),
            "known_gaps": [d.isoformat() for d in missing_dts],
            "universe_summary": universe_summary,
            "reconciliation_daily_hourly": reconciliation_results,
        },
        "raw_1h_archives": raw_1h_results,
        "holdout_spot_archives": holdout_results,
        "fresh_training_data_1h": fresh_1h_results,
        "fresh_training_data_1d": fresh_1d_results,
        "unified_replay_parquets": replay_results,
    }

    manifest_file = out_dir / "track_a_data_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"\nWrote manifest to {manifest_file} ({manifest_file.stat().st_size} bytes)", flush=True)

    return manifest_data


if __name__ == "__main__":
    main()
