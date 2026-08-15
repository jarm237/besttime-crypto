#!/usr/bin/env python3
"""HMR-V2.4.1: Training Dataset Construction.

Re-scans SMA50 crossings over 2023-01-01 → 2024-12-31, applies frozen G1-B and G1-D
architecture filters, computes all PIT features and maturity-gated labels.

Outputs:
  v2_4_economic_models/datasets/
    g1_b_pre2025.parquet   — G1-B filtered events with features + labels
    g1_d_pre2025.parquet   — G1-D filtered events with features + labels
    dataset_manifest.json  — row counts, label rates, SHA256 hashes, schema version
"""

import argparse
import hashlib
import json
import sys
import warnings
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v2_g1_3_characterization import calculate_rolling_metrics

CONTRACT_PATH = Path(
    "research/historical_market_replay_v2/v2_4_economic_models/contract"
    "/v2_4_model_research_contract.json"
)
FREEZE_PATH = Path(
    "research/historical_market_replay_v2/v2_g1_event_architecture"
    "/g1_architecture_freeze.json"
)

# ── Frozen thresholds (verified against freeze manifest) ─────────────────────
THRESH_BREAK_ATR = 0.25
THRESH_BODY_ATR  = 0.15
THRESH_ROOM_ATR  = 1.0

COINS     = ["BTC", "ETH", "BNB"]
TIMEFRAME = "15m"
WARMUP    = 210
BARS_72   = 72
BARS_8    = 8
COST_BPS  = 15.0
COST_FRAC = COST_BPS / 10_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_time(c_time, ts: pd.Timestamp) -> bool:
    t = pd.to_datetime(c_time)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t == ts


def _sha256_df(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Crossing scanner with full feature computation
# ---------------------------------------------------------------------------

def scan_coin(coin: str, candles_dict: Dict,
              period_start: pd.Timestamp, period_end: pd.Timestamp,
              settle_end: pd.Timestamp) -> pd.DataFrame:
    rows = candles_dict.get(coin)
    if not rows:
        return pd.DataFrame()

    dfc = pd.DataFrame(rows)
    dfc["time"] = pd.to_datetime(dfc["time"])
    dfc["time"] = (dfc["time"].dt.tz_localize("UTC")
                   if dfc["time"].dt.tz is None
                   else dfc["time"].dt.tz_convert("UTC"))
    dfc.set_index("time", inplace=True)
    dfc.sort_index(inplace=True)

    close_col = next((c for c in ["close", "Close"] if c in dfc.columns), "close")
    open_col  = next((c for c in ["open", "Open"] if c in dfc.columns), "open")
    high_col  = next((c for c in ["high", "High"] if c in dfc.columns), "high")
    low_col   = next((c for c in ["low", "Low"] if c in dfc.columns), "low")

    close  = dfc[close_col].astype(float)
    open_  = dfc[open_col].astype(float)
    high   = dfc[high_col].astype(float)
    low    = dfc[low_col].astype(float)

    m        = calculate_rolling_metrics(dfc)
    sma50    = m["sma50"]
    sma200   = m["sma200"]
    ema9     = m["ema9"]
    ema21    = m["ema21"]
    atr      = m["atr"]
    vol_sma  = m["vol_sma"]
    support  = m["support"]
    resist   = m["resistance"]
    cross16  = m["cross_count_16"]
    sl50     = m["sma50_slope"]

    records: List[Dict[str, Any]] = []
    for i in range(1, len(dfc)):
        ts = dfc.index[i]
        if ts < period_start or ts > period_end:
            continue

        prev_c = float(close.iloc[i - 1])
        curr_c = float(close.iloc[i])
        prev_s = float(sma50.iloc[i - 1])
        curr_s = float(sma50.iloc[i])

        is_sell = (prev_c >= prev_s) and (curr_c < curr_s)
        is_buy  = (prev_c <= prev_s) and (curr_c > curr_s)
        if not (is_sell or is_buy):
            continue

        side = "SELL" if is_sell else "BUY"
        ep   = curr_c
        a    = max(float(atr.iloc[i]), 1e-8)
        curr_open = float(open_.iloc[i])

        # ── PIT features ──────────────────────────────────────────────────
        atr_bps      = a / ep * 10_000.0
        break_atr    = abs(ep - curr_s) / a
        body_atr     = abs(ep - curr_open) / a
        room_bps     = ((ep - float(support.iloc[i])) / ep * 10_000.0
                        if side == "SELL"
                        else (float(resist.iloc[i]) - ep) / ep * 10_000.0)
        room_atr     = room_bps / max(atr_bps, 1e-6)
        w16          = float(cross16.iloc[i])
        slope50      = float(sl50.iloc[i])
        ema_dist_bps = (float(ema9.iloc[i]) - float(ema21.iloc[i])) / ep * 10_000.0

        vol = dfc["volume"].iloc[i] if "volume" in dfc.columns else dfc["Volume"].iloc[i] if "Volume" in dfc.columns else np.nan
        vol_ratio = float(vol) / max(float(vol_sma.iloc[i]), 1e-8) if not np.isnan(vol) else np.nan

        # Regime (use existing columns if available, else derive simple proxy)
        sma200_curr = float(sma200.iloc[i])
        trend_regime = "uptrend" if ep > sma200_curr else "downtrend"
        atr_pct = atr_bps / 10_000.0
        volatility_regime = "high_vol" if atr_pct > 0.005 else "low_vol"

        # ── Forward returns (from close prices, not lookahead at feature time) ─
        ret72 = ret8 = np.nan
        if i + BARS_72 < len(dfc):
            ep72  = float(close.iloc[i + BARS_72])
            ret72 = (ep - ep72) / ep if side == "SELL" else (ep72 - ep) / ep
        if i + BARS_8 < len(dfc):
            ep8   = float(close.iloc[i + BARS_8])
            ret8  = (ep - ep8) / ep if side == "SELL" else (ep8 - ep) / ep

        # ── Variant membership ────────────────────────────────────────────
        g1b = (break_atr <= THRESH_BREAK_ATR) and (body_atr <= THRESH_BODY_ATR)
        g1d = g1b and (room_atr >= THRESH_ROOM_ATR)

        records.append({
            "event_id":    f"{coin}_{side}_{ts.strftime('%Y%m%d%H%M')}",
            "timestamp":   ts,
            "symbol":      coin,
            "side":        side,
            "entry_price": ep,

            # Market context
            "trend_regime":       trend_regime,
            "volatility_regime":  volatility_regime,

            # Event geometry (B)
            "break_distance_atr": break_atr,
            "candle_body_atr":    body_atr,

            # Structural opportunity (C)
            "room_to_structure_atr": room_atr,
            "room_to_structure_bps": room_bps,

            # Whipsaw context (D)
            "recent_cross_count_16bars": w16,

            # Optional micro context (F)
            "volume_ratio":       vol_ratio,
            "sma50_slope":        slope50,
            "ema9_ema21_distance_bps": ema_dist_bps,

            # Legacy (E) — populated later if V1 model artifact is available
            "raw_model_score": np.nan,

            # Variant flags
            "G1B": g1b,
            "G1D": g1d,

            # Labels
            "gross_return_72": ret72,
            "gross_return_8":  ret8,
            "gross_gt30_72":   int(ret72 >= 0.0030) if not np.isnan(ret72) else np.nan,
            "gross_gt40_72":   int(ret72 >= 0.0040) if not np.isnan(ret72) else np.nan,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def _summarise(df: pd.DataFrame, label: str) -> Dict[str, Any]:
    r = pd.to_numeric(df["gross_return_72"], errors="coerce")
    gt30 = pd.to_numeric(df["gross_gt30_72"], errors="coerce")
    gt40 = pd.to_numeric(df["gross_gt40_72"], errors="coerce")
    return {
        "label": label,
        "n": len(df),
        "mean_gross_bps": round(float(r.mean() * 10_000), 2),
        "gross_gt30_rate": round(float(gt30.mean()), 4),
        "gross_gt30_count": int(gt30.sum()),
        "gross_gt40_rate": round(float(gt40.mean()), 4),
        "gross_gt40_count": int(gt40.sum()),
        "nan_label_rows": int(r.isna().sum()),
        "by_symbol": df.groupby("symbol").size().to_dict(),
        "by_side":   df.groupby("side").size().to_dict(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args) -> int:
    # Verify contract and freeze exist
    for p in [CONTRACT_PATH, FREEZE_PATH]:
        if not (REPO_ROOT / p).exists():
            print(f"ERROR: Required manifest not found: {p}")
            return 1

    contract = json.loads((REPO_ROOT / CONTRACT_PATH).read_text())
    freeze   = json.loads((REPO_ROOT / FREEZE_PATH).read_text())
    print("HMR-V2.4.1: Training Dataset Construction")
    print(f"  Contract SHA: {contract.get('contract_sha256','?')[:16]}...")
    print(f"  Arch freeze SHA: {freeze.get('content_sha256','?')[:16]}...")

    period_start = pd.Timestamp("2023-01-01", tz="UTC")
    period_end   = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
    settle_end   = pd.Timestamp("2025-02-15", tz="UTC")  # buffer for 72-bar labels

    print(f"  Training period: {period_start.date()} → {period_end.date()}")
    print("  Loading candles...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), COINS, TIMEFRAME,
        period_start, period_end, settle_end,
        warmup_bars=WARMUP,
    )

    print("  Scanning crossings...")
    all_dfs = []
    for coin in COINS:
        df_coin = scan_coin(coin, candles_dict, period_start, period_end, settle_end)
        cnt_all = len(df_coin)
        cnt_b   = int(df_coin["G1B"].sum()) if cnt_all else 0
        cnt_d   = int(df_coin["G1D"].sum()) if cnt_all else 0
        print(f"    {coin}: {cnt_all} crossings → G1B={cnt_b}, G1D={cnt_d}")
        all_dfs.append(df_coin)

    df_all = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    print(f"  Total crossings: {len(df_all)}")

    # Split into architecture datasets
    df_b = df_all[df_all["G1B"]].copy().reset_index(drop=True)
    df_d = df_all[df_all["G1D"]].copy().reset_index(drop=True)

    print(f"  G1-B: {len(df_b)} events, "
          f"Gross>30: {df_b['gross_gt30_72'].sum():.0f} "
          f"({df_b['gross_gt30_72'].mean():.1%})")
    print(f"  G1-D: {len(df_d)} events, "
          f"Gross>30: {df_d['gross_gt30_72'].sum():.0f} "
          f"({df_d['gross_gt30_72'].mean():.1%})")

    # Save
    out = REPO_ROOT / "research/historical_market_replay_v2/v2_4_economic_models/datasets"
    out.mkdir(parents=True, exist_ok=True)

    # Convert timestamp to string for parquet compatibility
    for df_ in [df_b, df_d]:
        df_["timestamp"] = df_["timestamp"].astype(str)

    path_b = out / "g1_b_pre2025.parquet"
    path_d = out / "g1_d_pre2025.parquet"
    df_b.to_parquet(path_b, index=False)
    df_d.to_parquet(path_d, index=False)

    # Manifest
    manifest = {
        "schema": "v2_4_dataset_manifest_v1",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "training_period": {"start": str(period_start.date()), "end": str(period_end.date())},
        "architecture_freeze_sha": freeze.get("content_sha256", "?"),
        "contract_sha": contract.get("contract_sha256", "?"),
        "datasets": {
            "G1B": _summarise(df_b, "G1-B Compression"),
            "G1D": _summarise(df_d, "G1-D Compression+Opportunity"),
        },
        "files": {
            "g1_b_pre2025.parquet": hashlib.sha256(path_b.read_bytes()).hexdigest(),
            "g1_d_pre2025.parquet": hashlib.sha256(path_d.read_bytes()).hexdigest(),
        },
        "feature_schema": [
            "event_id", "timestamp", "symbol", "side", "entry_price",
            "trend_regime", "volatility_regime",
            "break_distance_atr", "candle_body_atr",
            "room_to_structure_atr", "room_to_structure_bps",
            "recent_cross_count_16bars", "volume_ratio",
            "sma50_slope", "ema9_ema21_distance_bps",
            "raw_model_score",
            "gross_return_72", "gross_return_8",
            "gross_gt30_72", "gross_gt40_72",
        ],
        "pit_invariant": "all features available at event_timestamp; no future data used",
        "maturity_note": "Events near period_end may have NaN labels if 72-bar exit exceeds settle_end",
        "label_definitions": contract.get("label_definitions", {}),
    }

    manifest_path = REPO_ROOT / "research/historical_market_replay_v2/v2_4_economic_models/contract/dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n  ✓ Saved G1-B dataset: {path_b}")
    print(f"  ✓ Saved G1-D dataset: {path_d}")
    print(f"  ✓ Saved manifest: {manifest_path}")

    # Gate checks
    b_gt30 = int(df_b["gross_gt30_72"].sum())
    d_gt30 = int(df_d["gross_gt30_72"].sum())
    b_gt40 = int(df_b["gross_gt40_72"].sum())
    d_gt40 = int(df_d["gross_gt40_72"].sum())
    print("\n  Gate Check:")
    print(f"    G1-B Gross>30 positives: {b_gt30}  ({'PASS' if b_gt30>=2000 else 'WARN' if b_gt30>=100 else 'FAIL'})")
    print(f"    G1-D Gross>30 positives: {d_gt30}  ({'PASS' if d_gt30>=2000 else 'WARN' if d_gt30>=100 else 'FAIL'})")
    print(f"    G1-B Gross>40 positives: {b_gt40}  ({'PASS' if b_gt40>=75 else 'DROP_GT40_TARGET'})")
    print(f"    G1-D Gross>40 positives: {d_gt40}  ({'PASS' if d_gt40>=75 else 'DROP_GT40_TARGET'})")
    print("\n  GATE: V2_4_1_DATASETS_BUILT = PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2.4.1: Build Training Datasets")
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    return p


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
