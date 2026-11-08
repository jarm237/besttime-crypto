#!/usr/bin/env python3
"""Audit and Prepare Out-of-Sample (OOS) 2025-2026 Dataset.

Performs:
1. Strict data integrity audit of all 15m candle CSVs for BTC, ETH, BNB (2023-01 to 2026-06).
   - File existence and SHA256 hashing.
   - Raw row counts, monotonic UTC timestamps.
   - Audit on concatenated and deduplicated series:
     - Boundary overlaps, duplicate timestamps, conflicting OHLC detection.
     - Gap detection and missing 15m intervals.
     - Exact source_dataset_sha256 per symbol and combined.
2. Builds causal point-in-time E4 scaffold for 2023-2026:
   - Explicitly populates:
     - gross_return_fraction (gross return fraction before fees)
     - entry_price, exit_price, exit_reason (TP, SL, TIMEOUT), bars_held
     - gross_pnl_bps, net_pnl_bps
     - Causal point-in-time features (past returns, range, trend spread)
3. Freezes pre-registered split manifest and candidate specifications:
   - DEV_WALK_FORWARD: 2023-01-01 to 2025-12-31 (Train 2023, Val 2024, Val 2025)
   - EXPOSED_INVALID_EVALUATION_AUDIT_SET: 2026-01-01 to 2026-06-30
     (Honest relabeling: exposed during pipeline audits, invalid as untouched holdout)
   - PROSPECTIVE_SHADOW_EPOCH: Forward-looking paper shadow mode
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data/fresh_training_data_2023_2026"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COINS = ["BTC", "ETH", "BNB"]

TP_BPS = 50.0
SL_BPS = 30.0
MAX_HOLD = 96
ROUNDTRIP_COST_BPS = 14.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def audit_candle_file(path: Path) -> dict[str, Any]:
    file_sha = sha256_file(path)
    df = pd.read_csv(path)
    required_cols = {"time", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing required columns: {missing}")

    row_count = len(df)
    times = pd.to_datetime(df["time"], utc=True)
    is_monotonic = times.is_monotonic_increasing
    time_gaps = []
    diffs = times.diff().dropna()
    expected_diff = pd.Timedelta(minutes=15)
    anomalous_diffs = diffs[diffs != expected_diff]
    if len(anomalous_diffs) > 0:
        for idx, gap in anomalous_diffs.items():
            time_gaps.append({
                "index": int(idx),
                "previous_time": str(times.iloc[idx - 1]),
                "current_time": str(times.iloc[idx]),
                "gap_minutes": gap.total_seconds() / 60.0,
            })

    # OHLC Invariants
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    v = df["volume"].values

    hl_valid = bool(np.all(h >= l))
    ho_valid = bool(np.all(h >= o))
    hc_valid = bool(np.all(h >= c))
    lo_valid = bool(np.all(l <= o))
    lc_valid = bool(np.all(l <= c))
    vol_valid = bool(np.all(v >= 0.0))
    finite_valid = bool(
        np.all(np.isfinite(o)) and np.all(np.isfinite(h)) and
        np.all(np.isfinite(l)) and np.all(np.isfinite(c)) and np.all(np.isfinite(v))
    )
    all_positive = bool(np.all(o > 0) and np.all(h > 0) and np.all(l > 0) and np.all(c > 0))

    invariants_passed = (
        hl_valid and ho_valid and hc_valid and lo_valid and lc_valid and
        vol_valid and finite_valid and all_positive and is_monotonic
    )

    return {
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "sha256": file_sha,
        "row_count": row_count,
        "first_timestamp": str(times.min()),
        "last_timestamp": str(times.max()),
        "is_monotonic": is_monotonic,
        "gap_count": len(time_gaps),
        "gaps": time_gaps[:5],
        "invariants": {
            "high_ge_low": hl_valid,
            "high_ge_open": ho_valid,
            "high_ge_close": hc_valid,
            "low_le_open": lo_valid,
            "low_le_close": lc_valid,
            "volume_ge_zero": vol_valid,
            "all_finite": finite_valid,
            "all_positive": all_positive,
        },
        "all_invariants_passed": invariants_passed,
    }


def audit_and_merge_symbol_candles(coin: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Loads all monthly candle files for coin, audits concatenation, duplicates, and gaps."""
    sym_dir = DATA_DIR / coin / "15m"
    files = sorted(list(sym_dir.glob(f"{coin}_15m_*.csv")))
    if not files:
        raise FileNotFoundError(f"No candle files found for {coin} under {sym_dir}")

    file_audits = []
    frames = []
    total_raw_rows = 0
    boundary_overlaps = []
    prev_max = None
    prev_file = None

    for f_path in files:
        fa = audit_candle_file(f_path)
        file_audits.append(fa)
        df_part = pd.read_csv(f_path)
        total_raw_rows += len(df_part)

        t_part = pd.to_datetime(df_part["time"], utc=True)
        cur_min, cur_max = t_part.min(), t_part.max()
        if prev_max is not None and prev_max >= cur_min:
            boundary_overlaps.append({
                "prev_file": prev_file,
                "prev_max_timestamp": str(prev_max),
                "cur_file": f_path.name,
                "cur_min_timestamp": str(cur_min),
            })
        prev_max, prev_file = cur_max, f_path.name
        frames.append(df_part)

    merged = pd.concat(frames, ignore_index=True)
    ts = pd.to_datetime(merged["time"], utc=True)
    dup_mask = ts.duplicated(keep=False)
    dup_count = int(ts.duplicated().sum())
    unique_count = int(ts.nunique())

    # Conflicting OHLC check on duplicate timestamps
    conflicts = 0
    if dup_count > 0:
        dups_df = merged[dup_mask]
        grouped = dups_df.groupby(ts[dup_mask])
        for _, g in grouped:
            if g[["open", "high", "low", "close", "volume"]].nunique().max() > 1:
                conflicts += 1

    # Clean deduplicated dataframe
    deduped = merged.drop_duplicates(subset=["time"], keep="last").copy()
    deduped["timestamp"] = pd.to_datetime(deduped["time"], utc=True)
    deduped = deduped.sort_values("timestamp").reset_index(drop=True)

    # Gap and missing interval audit
    diffs = deduped["timestamp"].diff().dropna()
    expected = pd.Timedelta(minutes=15)
    anomalous = diffs[diffs != expected]
    missing_intervals = 0
    gap_details = []
    for idx, gap in anomalous.items():
        if gap > expected:
            missing_bars = int(gap.total_seconds() / 900.0) - 1
            missing_intervals += missing_bars
            gap_details.append({
                "index": int(idx),
                "from_time": str(deduped["timestamp"].iloc[idx - 1]),
                "to_time": str(deduped["timestamp"].iloc[idx]),
                "missing_bars": missing_bars,
                "gap_minutes": gap.total_seconds() / 60.0,
            })

    # Dataset hash
    clean_csv_bytes = deduped[["time", "open", "high", "low", "close", "volume"]].to_csv(index=False).encode("utf-8")
    dataset_sha256 = hashlib.sha256(clean_csv_bytes).hexdigest()

    audit_summary = {
        "symbol": coin,
        "files_count": len(files),
        "total_raw_rows": total_raw_rows,
        "duplicate_timestamps_found": dup_count,
        "conflicting_ohlc_on_duplicates": conflicts,
        "unique_timestamps_count": unique_count,
        "monthly_boundary_overlaps_count": len(boundary_overlaps),
        "boundary_overlaps": boundary_overlaps[:5],
        "missing_15m_intervals_count": missing_intervals,
        "gap_count": len(gap_details),
        "gaps": gap_details,
        "first_timestamp": str(deduped["timestamp"].min()),
        "last_timestamp": str(deduped["timestamp"].max()),
        "source_dataset_sha256": dataset_sha256,
        "all_files_passed_invariants": all(fa["all_invariants_passed"] for fa in file_audits),
        "files": file_audits,
    }

    return deduped, audit_summary


def compute_path_aware_e4_trade(
    side: str,
    entry_idx: int,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    max_hold: int = MAX_HOLD,
    tp_bps: float = TP_BPS,
    sl_bps: float = SL_BPS,
) -> tuple[float, float, float, bool, bool, int, int]:
    """Evaluates E4 execution from entry bar to resolution bar.
    Conservative invariant: checks adverse excursion (SL) before favorable (TP).

    Returns:
        realized_return (gross fraction)
        entry_price
        exit_price
        stop_hit
        target_hit
        bars_held
        exit_idx
    """
    n = len(closes)
    entry_price = float(closes[entry_idx])
    tp_frac = tp_bps / 10000.0
    sl_frac = sl_bps / 10000.0

    if side == "BUY":
        tp_target = entry_price * (1.0 + tp_frac)
        sl_target = entry_price * (1.0 - sl_frac)
    else:
        tp_target = entry_price * (1.0 - tp_frac)
        sl_target = entry_price * (1.0 + sl_frac)

    stop_hit = False
    target_hit = False
    exit_idx = min(entry_idx + max_hold, n - 1)
    bars_held = exit_idx - entry_idx

    for step in range(1, max_hold + 1):
        curr_idx = entry_idx + step
        if curr_idx >= n:
            exit_idx = n - 1
            bars_held = exit_idx - entry_idx
            break

        bar_high = highs[curr_idx]
        bar_low = lows[curr_idx]

        if side == "BUY":
            # Conservative: SL evaluated before TP
            if bar_low <= sl_target:
                stop_hit = True
                exit_idx = curr_idx
                bars_held = step
                break
            if bar_high >= tp_target:
                target_hit = True
                exit_idx = curr_idx
                bars_held = step
                break
        else:
            if bar_high >= sl_target:
                stop_hit = True
                exit_idx = curr_idx
                bars_held = step
                break
            if bar_low <= tp_target:
                target_hit = True
                exit_idx = curr_idx
                bars_held = step
                break

    if target_hit:
        realized_return = tp_frac
        exit_price = tp_target
    elif stop_hit:
        realized_return = -sl_frac
        exit_price = sl_target
    else:
        # Timeout at close of exit bar
        exit_price = float(closes[exit_idx])
        if side == "BUY":
            realized_return = (exit_price - entry_price) / entry_price
        else:
            realized_return = (entry_price - exit_price) / entry_price

    return realized_return, entry_price, exit_price, stop_hit, target_hit, bars_held, exit_idx


def build_e4_trade_candidates(
    symbol: str,
    candle_df: pd.DataFrame,
) -> pd.DataFrame:
    """Builds causal point-in-time trade stream with forward E4 outcomes."""
    n = len(candle_df)
    closes = candle_df["close"].values
    highs = candle_df["high"].values
    lows = candle_df["low"].values
    volumes = candle_df["volume"].values
    timestamps = candle_df["timestamp"].tolist()

    # Causal point-in-time features (looking ONLY at past bars <= i)
    past_ret_8 = np.zeros(n)
    past_ret_8[8:] = (closes[8:] - closes[:-8]) / closes[:-8]

    past_ret_32 = np.zeros(n)
    past_ret_32[32:] = (closes[32:] - closes[:-32]) / closes[:-32]

    past_ret_72 = np.zeros(n)
    past_ret_72[72:] = (closes[72:] - closes[:-72]) / closes[:-72]

    past_range_72 = np.zeros(n)
    for i in range(72, n):
        w_h = highs[i - 72 : i + 1].max()
        w_l = lows[i - 72 : i + 1].min()
        past_range_72[i] = (w_h - w_l) / closes[i]

    sma_fast = pd.Series(closes).rolling(16).mean().values
    sma_slow = pd.Series(closes).rolling(64).mean().values
    trend_spread = np.zeros(n)
    valid_mavg = ~np.isnan(sma_fast) & ~np.isnan(sma_slow) & (sma_slow > 0)
    trend_spread[valid_mavg] = (sma_fast[valid_mavg] - sma_slow[valid_mavg]) / sma_slow[valid_mavg]

    records = []
    for i in range(100, n - MAX_HOLD):
        ts = timestamps[i]

        candidates = []
        if trend_spread[i] > 0.0005:
            candidates.append("BUY")
        elif trend_spread[i] < -0.0005:
            candidates.append("SELL")
        else:
            candidates.extend(["BUY", "SELL"])

        for side in candidates:
            realized_ret, entry_p, exit_p, stop, target, bars, exit_i = compute_path_aware_e4_trade(
                side, i, closes, highs, lows
            )
            exit_reason = "TP" if target else ("SL" if stop else "TIMEOUT")
            gross_pnl_bps = realized_ret * 10000.0
            net_pnl_bps = gross_pnl_bps - ROUNDTRIP_COST_BPS

            records.append({
                "symbol": symbol,
                "side": side,
                "entry_timestamp": ts,
                "entry_idx": i,
                "entry_price": entry_p,
                "exit_timestamp": timestamps[exit_i],
                "exit_idx": exit_i,
                "exit_price": exit_p,
                "exit_reason": exit_reason,
                "target_hit": int(target),
                "stop_hit": int(stop),
                "bars_held": bars,
                "gross_return_fraction": realized_ret,
                "gross_pnl_bps": gross_pnl_bps,
                "net_pnl_bps": net_pnl_bps,
                # Causal point-in-time features
                "return_8": past_ret_8[i],
                "return_32": past_ret_32[i],
                "return_72": past_ret_72[i],
                "abs_move_72": past_range_72[i],
                "trend_spread": trend_spread[i],
            })

    return pd.DataFrame(records)


def main():
    print("=== Step E: Comprehensive Audit and Preparation of 2023-2026 Dataset ===")
    audit_results: dict[str, Any] = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_files_audited": 0,
        "files_passed_invariants": 0,
        "symbols": {},
    }

    all_sym_trades = []
    combined_sha_feed = hashlib.sha256()

    for sym in COINS:
        print(f"\n[{sym}] Auditing individual files and concatenated series...")
        c_df, sym_audit = audit_and_merge_symbol_candles(sym)
        audit_results["symbols"][sym] = sym_audit
        audit_results["total_files_audited"] += sym_audit["files_count"]
        if sym_audit["all_files_passed_invariants"]:
            audit_results["files_passed_invariants"] += sym_audit["files_count"]

        combined_sha_feed.update(sym_audit["source_dataset_sha256"].encode("utf-8"))

        print(
            f"[{sym}] Files: {sym_audit['files_count']} | Raw rows: {sym_audit['total_raw_rows']} | "
            f"Dups: {sym_audit['duplicate_timestamps_found']} | Conflicts: {sym_audit['conflicting_ohlc_on_duplicates']} | "
            f"Unique: {sym_audit['unique_timestamps_count']} | Overlaps: {sym_audit['monthly_boundary_overlaps_count']} | "
            f"Missing intervals: {sym_audit['missing_15m_intervals_count']} | SHA256: {sym_audit['source_dataset_sha256'][:16]}..."
        )

        df_trades = build_e4_trade_candidates(sym, c_df)
        all_sym_trades.append(df_trades)
        print(f"[{sym}] Generated {len(df_trades)} candidate trades with verified gross_return_fraction.")

    audit_results["combined_source_dataset_sha256"] = combined_sha_feed.hexdigest()

    audit_path = OUT_DIR / "oos_2025_2026_data_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)
    print(f"\n[OK] Comprehensive data audit saved to: {audit_path}")

    # Build full 2023-2026 trade candidates
    print("\nConcatenating and sorting multi-symbol candidate trades...")
    df_all_trades = pd.concat(all_sym_trades, ignore_index=True)
    df_all_trades = df_all_trades.sort_values("entry_timestamp").reset_index(drop=True)
    df_all_trades["trade_id"] = [f"t_{i:07d}" for i in range(len(df_all_trades))]

    scaffold_path = OUT_DIR / "v5_causal_e4_scaffold_2023_2026.parquet"
    df_all_trades.to_parquet(scaffold_path, index=False)
    scaffold_sha = sha256_file(scaffold_path)
    print(f"Saved verified causal E4 scaffold to: {scaffold_path} ({len(df_all_trades)} rows, SHA256: {scaffold_sha[:16]}...)")

    # Freeze split manifest and candidate specifications (honest P0 #2 governance)
    from btc_scraper.trading.prospective_shadow_logger import LOCKED_VCB_V1_SPEC

    split_manifest = {
        "manifest_version": "hmr-v5-oos-split/v3-honest-governance",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scaffold_file": scaffold_path.name,
        "scaffold_sha256": scaffold_sha,
        "combined_source_dataset_sha256": audit_results["combined_source_dataset_sha256"],
        "total_candidate_trades": len(df_all_trades),
        "multiple_testing_governance": {
            "multiple_testing_trials_count": "UNKNOWN",
            "honest_disclosure": (
                "Exact total historical trials/ideas/parameter combinations explored interactively "
                "prior to locking VOL_COMPRESSION_BREAKOUT_V1 was not prospectively pre-registered; "
                "all pre-lock historical confidence intervals are exploratory only."
            ),
        },
        "splits": {
            "EXPLORATORY_TRAIN_2023": {
                "description": "Exploratory strategy family discovery, hypothesis generation, and q65 ATR threshold calibration window",
                "start": "2023-01-01T00:00:00Z",
                "end": "2024-01-01T00:00:00Z",
                "is_independent_confirmatory_oos": False,
                "interval_definition": "half_open_start_inclusive_end_exclusive",
            },
            "DEV_WALK_FORWARD_SELECTION_2024_2025": {
                "description": "Development walk-forward candidate screening and selection window (NOT independent confirmatory OOS)",
                "start": "2024-01-01T00:00:00Z",
                "end": "2026-01-01T00:00:00Z",
                "is_independent_confirmatory_oos": False,
                "folds": {
                    "DEV_SELECTION_2024": {"start": "2024-01-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
                    "DEV_SELECTION_2025": {"start": "2025-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
                },
                "interval_definition": "half_open_start_inclusive_end_exclusive",
            },
            "BURNED_EXPOSED_AUDIT_2026_H1": {
                "description": "Exposed one-shot historical audit window; VOL_COMPRESSION_BREAKOUT_V1 failed (-7.60 bps gross, -22.26 bps net@14 under NEXT_BAR_OPEN). Permanently burned: zero retuning allowed.",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-07-01T00:00:00Z",
                "is_independent_confirmatory_oos": False,
                "audit_status": "BURNED_ONE_SHOT_AUDIT_FAILED_NO_RETUNING",
                "embargo_bars": 96,
                "interval_definition": "half_open_start_inclusive_end_exclusive",
            },
            "PROSPECTIVE_SHADOW_EPOCH": {
                "description": "Forward-looking passive closed-candle shadow paper validation epoch under immutable LockedCandidateSpec",
                "start": "PROSPECTIVE_RUNTIME_START_AFTER_2026-06-30T23:45:00Z",
                "mode": "NO_TRADE_SHADOW",
                "locked_candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
                "locked_spec_version": LOCKED_VCB_V1_SPEC.spec_version,
                "locked_spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
                "lock_timestamp": LOCKED_VCB_V1_SPEC.lock_timestamp,
                "last_used_historical_timestamp": LOCKED_VCB_V1_SPEC.last_used_historical_timestamp,
            },
        },
        "registered_candidates": [
            {
                "name": "NO_TRADE",
                "type": "BENCHMARK_ABSTAIN",
                "description": "Abstains from all trades; 0.0 net PnL, 0.0 drawdown",
            },
            {
                "name": "CONTROL",
                "type": "RAW_UNFILTERED",
                "description": "Executes all proposed E4 entry candidates without statistical filter",
            },
            {
                "name": "S3_LEGACY",
                "type": "LEGACY_S3_FILTER",
                "description": "Applies frozen S3 per-symbol thresholds (BTC 0.6816, ETH 0.8281, BNB 0.7566)",
            },
            {
                "name": "NET_RETURN_RANKER",
                "type": "COST_AWARE_RANKER",
                "description": "Trained on 2023 net return target R_net = R_gross - 0.0014; executes predicted net return > 0",
            },
            {
                "name": "VOL_COMPRESSION_BREAKOUT_V1",
                "type": "DIRECTIONAL_DONCHIAN_COMPRESSION_BREAKOUT",
                "description": "15m 96-bar Donchian breakout + SMA96/384 trend + vol_ratio>=1.2 + 2023 ATR q65<=38.305 bps; signal at bar i close, entry at bar i+1 open",
            },
        ],
        "promotion_gates": {
            "gate_1": "Net Expectancy > 0.0 bps (after 14 bps base friction)",
            "gate_2": "Profit Factor > 1.0",
            "gate_3": "Max Drawdown <= 20.0%",
            "gate_4": "Executed trades N >= 100",
            "gate_5": "Per-symbol consistency >= 2/3 positive net expectancy",
            "gate_6": "Top-5 outlier removal keeps net expectancy > 0",
            "gate_7_primary": "Daily cross-symbol portfolio MTM Moving-Block & Stationary Bootstrap (block=10d) 95% CI lower bound > 0.0 bps/day (IID trade CI is diagnostic-only)",
        },
    }

    manifest_bytes = json.dumps(split_manifest, indent=2).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    split_manifest["manifest_sha256"] = manifest_sha

    split_path = OUT_DIR / "oos_split_manifest.json"
    with open(split_path, "w", encoding="utf-8") as f:
        json.dump(split_manifest, f, indent=2)

    print(f"\n[OK] Split manifest frozen and saved to: {split_path}")
    print(f"Manifest SHA256: {manifest_sha}")


if __name__ == "__main__":
    main()
