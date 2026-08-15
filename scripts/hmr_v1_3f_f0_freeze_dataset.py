#!/usr/bin/env python3
"""HMR-V1.3F-F0: Freeze Score/Outcome Dataset with Extended Horizons.

Creates a canonical Parquet dataset with every technical candidate in the
specified window, enriched with:
  - raw model score
  - training label (if available)
  - multi-horizon fixed exits (1/2/4/8/16/24/32/48/72/96/192 bars)
  - MFE / MAE
  - TP-before-SL under 1%/1% symmetric contract
  - actual lifecycle outcome under current execution contract (3.13/2.38 ATR)
  - all-in cost model

Outputs to research/historical_market_replay_v1/v1_3f/f0_candidates.parquet.

Boundary:
  RESEARCH_ONLY
  NO_THRESHOLD_OPTIMIZATION
  NO_MODEL_PROMOTION
"""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import (
    load_closed_candles,
    research_model_override,
    isolated_policy_runtime,
)
from scripts.hmr_v1_3b_b0_model_ranking import compute_forward_excursion
from scripts.hmr_v1_3d_d1_d2_economic_audit import calculate_trade_costs


# ──────────────────────────────────────────────────────────────────────
# Execution contract constants (current production parameters)
# ──────────────────────────────────────────────────────────────────────

EXEC_TP_ATR_MULT = 3.1312
EXEC_SL_ATR_MULT = 2.3897
EXEC_TIMEOUT_BARS = 48


# ──────────────────────────────────────────────────────────────────────
# Multi-horizon fixed-exit returns
# ──────────────────────────────────────────────────────────────────────

# Extended list of horizons for V1.3F
HORIZON_BARS = [1, 2, 4, 8, 16, 24, 32, 48, 72, 96, 192]


def compute_fixed_horizon_returns(
    side: str,
    entry_price: float,
    forward_candles: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Compute close-to-close return at each fixed horizon bar.

    Returns dict with keys return_1bar, return_2bars, ..., return_192bars.
    Missing bars return NaN.
    """
    results: Dict[str, float] = {}
    is_long = side == "BUY"
    closes = [float(c["close"]) for c in forward_candles]

    for h in HORIZON_BARS:
        key = f"return_{h}bar" if h == 1 else f"return_{h}bars"
        if len(closes) >= h:
            exit_price = closes[h - 1]
            if is_long:
                results[key] = (exit_price - entry_price) / entry_price
            else:
                results[key] = (entry_price - exit_price) / entry_price
        else:
            results[key] = float("nan")

    return results


def compute_tp_sl_lifecycle(
    side: str,
    entry_price: float,
    atr_pct: float,
    forward_candles: List[Dict[str, Any]],
    tp_atr_mult: float,
    sl_atr_mult: float,
    timeout_bars: int,
) -> Dict[str, Any]:
    """Simulate TP/SL lifecycle exit using ATR-based targets."""
    is_long = side == "BUY"
    tp_pct = atr_pct * tp_atr_mult
    sl_pct = atr_pct * sl_atr_mult

    tp_price = entry_price * (1 + tp_pct) if is_long else entry_price * (1 - tp_pct)
    sl_price = entry_price * (1 - sl_pct) if is_long else entry_price * (1 + sl_pct)

    bars = forward_candles[:timeout_bars]
    hit_tp = False
    hit_sl = False
    exit_bar = len(bars) - 1
    exit_price = float(bars[-1]["close"]) if bars else entry_price

    for i, c in enumerate(bars):
        h = float(c["high"])
        lw = float(c["low"])
        if is_long:
            if lw <= sl_price:
                hit_sl = True
                exit_bar = i
                exit_price = sl_price
                break
            if h >= tp_price:
                hit_tp = True
                exit_bar = i
                exit_price = tp_price
                break
        else:
            if h >= sl_price:
                hit_sl = True
                exit_bar = i
                exit_price = sl_price
                break
            if lw <= tp_price:
                hit_tp = True
                exit_bar = i
                exit_price = tp_price
                break

    if is_long:
        gross = (exit_price - entry_price) / entry_price
    else:
        gross = (entry_price - exit_price) / entry_price

    if hit_tp:
        outcome = "WIN"
    elif hit_sl:
        outcome = "LOSS"
    else:
        outcome = "TIMEOUT"

    return {
        "lifecycle_gross_return": gross,
        "lifecycle_outcome": outcome,
        "lifecycle_exit_bar": exit_bar,
        "lifecycle_exit_price": exit_price,
    }


def compute_tp_before_sl_symmetric(
    side: str,
    entry_price: float,
    forward_candles: List[Dict[str, Any]],
    tp_pct: float = 0.01,
    sl_pct: float = 0.01,
    timeout_bars: int = 48,
) -> Dict[str, Any]:
    """Simulate symmetric 1%/1% TP/SL contract to check tp_before_sl."""
    is_long = side == "BUY"
    tp_price = entry_price * (1 + tp_pct) if is_long else entry_price * (1 - tp_pct)
    sl_price = entry_price * (1 - sl_pct) if is_long else entry_price * (1 + sl_pct)

    bars = forward_candles[:timeout_bars]
    hit_tp = False
    hit_sl = False
    tp_first_bar: Optional[int] = None
    sl_first_bar: Optional[int] = None

    for i, c in enumerate(bars):
        h = float(c["high"])
        lw = float(c["low"])
        if is_long:
            if lw <= sl_price and sl_first_bar is None:
                sl_first_bar = i
            if h >= tp_price and tp_first_bar is None:
                tp_first_bar = i
        else:
            if h >= sl_price and sl_first_bar is None:
                sl_first_bar = i
            if lw <= tp_price and tp_first_bar is None:
                tp_first_bar = i
        if tp_first_bar is not None and sl_first_bar is not None:
            break

    if tp_first_bar is not None and sl_first_bar is not None:
        hit_tp = tp_first_bar <= sl_first_bar
        hit_sl = not hit_tp
    elif tp_first_bar is not None:
        hit_tp = True
    elif sl_first_bar is not None:
        hit_sl = True

    return {
        "hit_tp_1pct": hit_tp,
        "hit_sl_1pct": hit_sl,
        "tp_before_sl_1pct": hit_tp and not hit_sl,
        "tp_first_bar_1pct": tp_first_bar,
        "sl_first_bar_1pct": sl_first_bar,
    }


# ──────────────────────────────────────────────────────────────────────
# Main dataset freeze
# ──────────────────────────────────────────────────────────────────────

def run_f0_freeze(args) -> int:
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars

    print("F0: Freeze Score/Outcome Dataset with Extended Horizons")
    print(f"  Window: {start.date()} → {end.date()}")
    print(f"  Coins:  {coins}")
    print(f"  Settlement bars: {args.settlement_bars}")
    print()

    # 1. Load candles
    print("  Loading candles...")
    candles = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start, end, settlement_end,
        warmup_bars=args.warmup_bars,
    )
    for coin_rows in candles.values():
        for row in coin_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")

    # 2. Load model bundle
    print("  Loading research model artifact...")
    manifest_path = Path(args.research_artifact_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle_path = REPO_ROOT / manifest["paths"]["bundle"]
    bundle = joblib.load(bundle_path)
    cclf = bundle["model"]
    feature_names = bundle["features"]

    # 3. Load training labels
    print("  Loading training labels from parquet...")
    training_labels: Dict[Tuple[str, str], int] = {}
    training_parquet = REPO_ROOT / manifest["paths"]["training_data"]
    if training_parquet.exists():
        try:
            tdf = pd.read_parquet(training_parquet)
            t_coin_col = next((c for c in ["symbol", "coin"] if c in tdf.columns), None)
            t_time_col = next((c for c in ["time", "observed_at", "timestamp"] if c in tdf.columns), None)
            t_label_col = next((c for c in ["label", "y", "target"] if c in tdf.columns), None)
            if t_coin_col and t_time_col and t_label_col:
                for _, row in tdf.iterrows():
                    coin_key = str(row[t_coin_col]).upper()
                    ts_key = str(pd.Timestamp(row[t_time_col]).strftime("%Y-%m-%d %H:%M"))
                    training_labels[(coin_key, ts_key)] = int(row[t_label_col])
                print(f"    Loaded {len(training_labels)} label records.")
        except Exception as e:
            print(f"    WARNING: Could not load training labels: {e}")
    else:
        print(f"    WARNING: Training parquet not found at {training_parquet}")

    # 4. Build analysis timeline
    print("  Building analysis timeline...")
    from btc_scraper.analysis import analyze_all_market
    analysis_by_time: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for coin in coins:
        rows = [dict(c) for c in candles.get(coin, [])]
        for val in analyze_all_market(rows):
            observed_at = pd.Timestamp(val["time"], tz="UTC")
            if start <= observed_at <= end:
                analysis_by_time.setdefault(val["time"], {})[coin] = val

    # 5. Score all technical candidates
    print("  Scoring candidates...")
    records: List[Dict[str, Any]] = []

    with research_model_override(str(manifest_path)):
        with isolated_policy_runtime():
            timestamps = sorted(analysis_by_time.keys())
            n_ts = len(timestamps)

            for idx, observed_at in enumerate(timestamps):
                if (idx + 1) % 250 == 0:
                    print(f"    {idx+1}/{n_ts} timestamps...")

                cycle_id = f"f0-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"

                for coin in coins:
                    analysis = analysis_by_time[observed_at].get(coin)
                    if analysis is None:
                        continue
                    analysis = dict(analysis)
                    analysis.update({
                        "coin": coin,
                        "symbol": f"{coin}USDT",
                        "timeframe": args.timeframe,
                        "cycle_id": cycle_id,
                        "observed_at": observed_at,
                    })

                    tech_action = str(analysis.get("action", "")).upper()
                    if tech_action not in ("BUY", "SELL"):
                        continue
                    side = tech_action

                    # Raw probability from base model
                    from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2
                    feat = build_meta_features_v2(analysis)
                    row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                    raw_prob = float(
                        cclf.calibrated_classifiers_[0].estimator.predict_proba(
                            [row_feat]
                        )[0, 1]
                    )

                    # Training label
                    ts_bucket = pd.Timestamp(observed_at).strftime("%Y-%m-%d %H:%M")
                    current_label = training_labels.get((coin, ts_bucket))

                    entry_price = float(analysis.get("close", 0.0))
                    entry_ts = pd.Timestamp(observed_at)
                    coin_candles = candles.get(coin, [])
                    atr_pct = float(analysis.get("atr_pct") or 0.015)

                    # Collect forward candles (up to settlement_bars)
                    forward_candles: List[Dict[str, Any]] = []
                    found_entry = False
                    for c in coin_candles:
                        c_time = pd.Timestamp(c["time"])
                        if not found_entry:
                            if c_time >= entry_ts:
                                found_entry = True
                            else:
                                continue
                        forward_candles.append(c)
                        if len(forward_candles) >= args.settlement_bars:
                            break

                    if not forward_candles:
                        continue

                    # MFE / MAE
                    exc = compute_forward_excursion(
                        coin=coin,
                        side=side,
                        entry_time=entry_ts,
                        entry_price=entry_price,
                        candles=coin_candles,
                        horizon_bars=EXEC_TIMEOUT_BARS,
                        tp_pct=0.01,
                        sl_pct=0.01,
                    )

                    # Multi-horizon fixed exits
                    horizon_rets = compute_fixed_horizon_returns(side, entry_price, forward_candles)

                    # TP/SL lifecycle: 1%/1% symmetric
                    tp_sl_1pct = compute_tp_before_sl_symmetric(
                        side, entry_price, forward_candles, tp_pct=0.01, sl_pct=0.01,
                    )

                    # Actual lifecycle: production ATR-based contract
                    lifecycle = compute_tp_sl_lifecycle(
                        side, entry_price, atr_pct, forward_candles,
                        tp_atr_mult=EXEC_TP_ATR_MULT,
                        sl_atr_mult=EXEC_SL_ATR_MULT,
                        timeout_bars=EXEC_TIMEOUT_BARS,
                    )

                    # Cost model
                    costs = calculate_trade_costs(atr_pct, spread_bps=2.0)
                    lifecycle_net = lifecycle["lifecycle_gross_return"] - costs["total"]

                    rec: Dict[str, Any] = {
                        "timestamp": observed_at,
                        "symbol": coin,
                        "side": side,
                        "entry_price": entry_price,
                        "atr_pct": atr_pct,
                        # Model
                        "raw_model_score": raw_prob,
                        "current_label": current_label,
                        # Excursion
                        "mfe_pct": exc["mfe"],
                        "mae_pct": exc["mae"],
                        # TP/SL 1%/1%
                        "hit_tp_1pct": tp_sl_1pct["hit_tp_1pct"],
                        "hit_sl_1pct": tp_sl_1pct["hit_sl_1pct"],
                        "tp_before_sl_1pct": tp_sl_1pct["tp_before_sl_1pct"],
                        "tp_first_bar_1pct": tp_sl_1pct["tp_first_bar_1pct"],
                        "sl_first_bar_1pct": tp_sl_1pct["sl_first_bar_1pct"],
                        # Lifecycle (production contract)
                        "lifecycle_gross_return": lifecycle["lifecycle_gross_return"],
                        "lifecycle_net_return": lifecycle_net,
                        "lifecycle_outcome": lifecycle["lifecycle_outcome"],
                        "lifecycle_exit_bar": lifecycle["lifecycle_exit_bar"],
                        # Costs
                        "cost_total_pct": costs["total"],
                        "cost_fee_pct": costs["fee"],
                        "cost_spread_pct": costs["spread"],
                        "cost_slippage_pct": costs["slippage"],
                    }
                    # Multi-horizon returns
                    rec.update(horizon_rets)
                    records.append(rec)

    print(f"\n  Total candidates recorded: {len(records)}")

    if not records:
        print("  WARNING: No technical candidates found in window.")
        return 1

    df = pd.DataFrame(records)

    # Cast bool columns
    for col in ["hit_tp_1pct", "hit_sl_1pct", "tp_before_sl_1pct"]:
        df[col] = df[col].astype(bool)

    # Write output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "f0_candidates.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  ✓ Saved: {parquet_path}")
    print(f"    Rows:  {len(df)}")
    print(f"    Cols:  {list(df.columns)}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F0: Freeze Score/Outcome Dataset with Extended Horizons")
    p.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    p.add_argument("--end",   default="2025-03-31T23:45:00+00:00")
    p.add_argument("--coins", default="BTC,ETH,BNB")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--settlement-bars", type=int, default=240,
                   help="Max forward bars to collect for horizon analysis")
    p.add_argument("--warmup-bars", type=int, default=200)
    p.add_argument(
        "--research-artifact-manifest",
        default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json",
    )
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/v1_3f",
    )
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_f0_freeze(args))
