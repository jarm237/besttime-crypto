#!/usr/bin/env python3
"""HMR-V2-G1.8/9: Pre-2025 Corpus Expansion and Out-of-Discovery Architecture Validation.

G1.8 — Run frozen G1-B and G1-D on pre-2025 historical candles (2023-01-01 → 2024-12-31)
        to accumulate training corpus for V2.4 and confirm architectures at scale.
        Includes overlap audit (G1-D ⊂ G1-B), B-only vs D economics.

G1.9 — Run frozen G1-B and G1-D on the out-of-discovery validation window
        (2025-04-01 → 2025-06-30). No threshold modification allowed.

Frozen architecture rules (from g1_architecture_freeze.json):
  G1-B: break_distance_atr <= 0.25, candle_body_atr <= 0.15
  G1-D: G1-B + room_to_structure_atr >= 1.0
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# ── Frozen thresholds (DO NOT MODIFY) ────────────────────────────────────────
THRESH_BREAK_ATR  = 0.25
THRESH_BODY_ATR   = 0.15
THRESH_ROOM_ATR   = 1.0
FREEZE_MANIFEST   = "research/historical_market_replay_v2/v2_g1_event_architecture/g1_architecture_freeze.json"

COST_BPS   = 15.0
COST_FRAC  = COST_BPS / 10_000.0
COINS      = ["BTC", "ETH", "BNB"]
TIMEFRAME  = "15m"
WARMUP_BARS = 210  # > 200-period SMA

BARS_72 = 72
BARS_8  = 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _econ(rets72: pd.Series, rets8: Optional[pd.Series] = None) -> Dict[str, Any]:
    n = len(rets72.dropna())
    if n == 0:
        return {"n": 0, "mean_bps": None, "median_bps": None,
                "gt30_rate": None, "gt30_count": None,
                "gt40_rate": None, "gt40_count": None, "net_pos_rate": None}
    r = rets72.dropna()
    d: Dict[str, Any] = {
        "n": n,
        "mean_bps":   round(float(r.mean() * 10_000), 2),
        "median_bps": round(float(r.median() * 10_000), 2),
        "gt30_rate":  round(float((r > 0.003).mean()), 4),
        "gt30_count": int((r > 0.003).sum()),
        "gt40_rate":  round(float((r > 0.004).mean()), 4),
        "gt40_count": int((r > 0.004).sum()),
        "net_pos_rate": round(float((r > COST_FRAC).mean()), 4),
    }
    if rets8 is not None:
        r8 = rets8.dropna()
        if len(r8):
            d["mean_bps_8bar"] = round(float(r8.mean() * 10_000), 2)
    return d


def _match_time(c_time, ts: pd.Timestamp) -> bool:
    t = pd.to_datetime(c_time)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t == ts


# ---------------------------------------------------------------------------
# Crossing + feature scanner
# ---------------------------------------------------------------------------

def scan_crossings_for_coin(coin: str, candles_dict: Dict,
                             period_start: pd.Timestamp,
                             period_end: pd.Timestamp,
                             settle_end: pd.Timestamp) -> pd.DataFrame:
    """Scan SMA50 SELL crossings for one coin, compute PIT features and forward returns."""
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
    close = dfc[close_col].astype(float)
    open_ = dfc[open_col].astype(float)

    m = calculate_rolling_metrics(dfc)
    sma50  = m["sma50"]
    atr    = m["atr"]
    supp   = m["support"]
    resis  = m["resistance"]
    cross16 = m["cross_count_16"]

    records = []
    for i in range(1, len(dfc)):
        ts   = dfc.index[i]
        if ts < period_start or ts > period_end:
            continue
        prev_c = close.iloc[i - 1]
        curr_c = close.iloc[i]
        prev_s = sma50.iloc[i - 1]
        curr_s = sma50.iloc[i]

        # SELL crossing: price crosses below SMA50
        is_sell_cross = (prev_c >= prev_s) and (curr_c < curr_s)
        # BUY crossing: price crosses above SMA50
        is_buy_cross  = (prev_c <= prev_s) and (curr_c > curr_s)

        if not (is_sell_cross or is_buy_cross):
            continue

        side = "SELL" if is_sell_cross else "BUY"
        ep   = float(curr_c)
        a    = max(float(atr.iloc[i]), 1e-8)
        curr_open = float(open_.iloc[i])

        # PIT features
        break_atr = abs(ep - float(curr_s)) / a
        body_atr  = abs(ep - curr_open) / a
        atr_bps   = a / ep * 10_000.0
        room_bps  = ((ep - float(supp.iloc[i])) / ep * 10_000.0 if side == "SELL"
                     else (float(resis.iloc[i]) - ep) / ep * 10_000.0)
        room_atr  = room_bps / max(atr_bps, 1e-6)
        w16       = float(cross16.iloc[i])

        # Forward returns (from close prices)
        ret72 = ret8 = np.nan
        if i + BARS_72 < len(dfc):
            exit_p72 = float(close.iloc[i + BARS_72])
            ret72 = (exit_p72 - ep) / ep if side == "SELL" else (ep - exit_p72) / ep
            # Invert for SELL: profit when price falls
            if side == "SELL":
                ret72 = (ep - exit_p72) / ep
            else:
                ret72 = (exit_p72 - ep) / ep
        if i + BARS_8 < len(dfc):
            exit_p8 = float(close.iloc[i + BARS_8])
            ret8 = (ep - exit_p8) / ep if side == "SELL" else (exit_p8 - ep) / ep

        records.append({
            "timestamp": ts,
            "symbol": coin,
            "side": side,
            "entry_price": ep,
            "break_distance_atr": break_atr,
            "candle_body_atr": body_atr,
            "room_to_structure_atr": room_atr,
            "recent_cross_count_16bars": w16,
            "return_72bars": ret72,
            "return_8bars": ret8,
            # Variant membership
            "G1A": True,
            "G1B": (break_atr <= THRESH_BREAK_ATR and body_atr <= THRESH_BODY_ATR),
            "G1D": (break_atr <= THRESH_BREAK_ATR and body_atr <= THRESH_BODY_ATR
                    and room_atr >= THRESH_ROOM_ATR),
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Analysis builders
# ---------------------------------------------------------------------------

def analyse_period(df: pd.DataFrame) -> Dict[str, Any]:
    """Full G1.8/G1.9 economic comparison + overlap audit."""
    out: Dict[str, Any] = {}

    # Overall + per-variant
    for var in ["G1A", "G1B", "G1D"]:
        sub = df[df[var]]
        r72 = pd.to_numeric(sub["return_72bars"], errors="coerce")
        r8  = pd.to_numeric(sub["return_8bars"],  errors="coerce")
        e = _econ(r72, r8)
        e["by_symbol"] = {}
        e["by_side"]   = {}
        for sym in sorted(sub["symbol"].unique()):
            sg = sub[sub["symbol"] == sym]
            e["by_symbol"][sym] = _econ(pd.to_numeric(sg["return_72bars"], errors="coerce"))
        for side in sorted(sub["side"].unique()):
            sg = sub[sub["side"] == side]
            e["by_side"][side] = _econ(pd.to_numeric(sg["return_72bars"], errors="coerce"))
        out[var] = e

    # Overlap audit: B-only (G1-B minus G1-D) vs G1-D
    b_only = df[df["G1B"] & ~df["G1D"]]
    b_only_r72 = pd.to_numeric(b_only["return_72bars"], errors="coerce")
    out["G1B_ONLY"] = _econ(b_only_r72)

    # Year / month distribution for corpus audit
    df2 = df[df["G1B"]].copy()
    df2["year"]  = pd.to_datetime(df2["timestamp"]).dt.year
    df2["month"] = pd.to_datetime(df2["timestamp"]).dt.strftime("%Y-%m")
    out["G1B_by_year"]  = df2.groupby("year").size().to_dict()
    out["G1B_by_month"] = df2.groupby("month").size().to_dict()

    df3 = df[df["G1D"]].copy()
    df3["year"]  = pd.to_datetime(df3["timestamp"]).dt.year
    df3["month"] = pd.to_datetime(df3["timestamp"]).dt.strftime("%Y-%m")
    out["G1D_by_year"]  = df3.groupby("year").size().to_dict()
    out["G1D_by_month"] = df3.groupby("month").size().to_dict()

    return out


def gate_check_corpus(e: Dict) -> str:
    """G1.8 gate: check if corpus has sufficient positives."""
    gt30 = e.get("gt30_count") or 0
    gt40 = e.get("gt40_count") or 0
    if gt30 >= 200 and gt40 >= 75:
        return "PASS_PREFERRED"
    elif gt30 >= 100:
        return "PASS_MINIMUM" + ("/DROP_GT40" if gt40 < 75 else "")
    else:
        return "FAIL_INSUFFICIENT_SAMPLE"


def gate_check_validation(e: Dict) -> str:
    """G1.9 gate: check validation enrichment."""
    gt30_rate = e.get("gt30_rate") or 0.0
    mean_bps  = e.get("mean_bps") or -999.0
    n         = e.get("n") or 0
    if n < 100:
        return "INSUFFICIENT_SAMPLE"
    if gt30_rate >= 0.18 and mean_bps > -10.0:
        return "PASS_PREFERRED"
    elif gt30_rate >= 0.15 and mean_bps > -10.0:
        return "PASS_MINIMUM"
    elif gt30_rate >= 0.15:
        return "PASS_RATE_ONLY/MEAN_MARGINAL"
    else:
        return "FAIL"


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------

def build_report(phase: str, period_start: str, period_end: str,
                 results: Dict, freeze: Dict) -> str:
    lines = [f"# HMR-V2-G1.{phase}: Architecture {'Corpus Expansion' if phase == '8' else 'Validation'}\n",
             f"Period: **{period_start}** → **{period_end}**\n",
             f"Frozen manifest SHA256: `{freeze.get('content_sha256', 'N/A')[:16]}...`\n"]

    # Canonical matrix
    lines += [
        "## 1. Canonical Economic Matrix\n",
        "| Metric | G1-A Raw Event | G1-B Compression | G1-D Both |",
        "|:-------|:--------------:|:----------------:|:---------:|",
    ]
    metrics = [
        ("n", "n", "{}"),
        ("Mean @72 (bps)", "mean_bps", "{:+.2f}"),
        ("Median @72 (bps)", "median_bps", "{:+.2f}"),
        ("Gross >30 rate", "gt30_rate", "{:.1%}"),
        ("Gross >30 count", "gt30_count", "{}"),
        ("Gross >40 rate", "gt40_rate", "{:.1%}"),
        ("Gross >40 count", "gt40_count", "{}"),
        ("Net+ rate", "net_pos_rate", "{:.1%}"),
        ("Mean @8 (bps)", "mean_bps_8bar", "{:+.2f}"),
    ]
    for label, key, fmt in metrics:
        cells = []
        for var in ["G1A", "G1B", "G1D"]:
            val = results[var].get(key)
            cells.append(fmt.format(val) if val is not None else "—")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    # Per-symbol
    lines += ["\n## 2. Per-Symbol Gross>30 Rate\n",
              "| Symbol | G1-A | G1-B | G1-D |",
              "|:-------|:----:|:----:|:----:|"]
    symbols = sorted({s for v in ["G1A", "G1B", "G1D"]
                      for s in results[v].get("by_symbol", {})})
    for sym in symbols:
        cells = []
        for var in ["G1A", "G1B", "G1D"]:
            r = results[var].get("by_symbol", {}).get(sym, {}).get("gt30_rate")
            cells.append(f"{r:.1%}" if r is not None else "—")
        lines.append(f"| {sym} | " + " | ".join(cells) + " |")

    # Per-side
    lines += ["\n## 3. Per-Side Gross>30 Rate\n",
              "| Side | G1-A | G1-B | G1-D |",
              "|:-----|:----:|:----:|:----:|"]
    sides = sorted({s for v in ["G1A", "G1B", "G1D"]
                    for s in results[v].get("by_side", {})})
    for side in sides:
        cells = []
        for var in ["G1A", "G1B", "G1D"]:
            r = results[var].get("by_side", {}).get(side, {}).get("gt30_rate")
            cells.append(f"{r:.1%}" if r is not None else "—")
        lines.append(f"| {side} | " + " | ".join(cells) + " |")

    # Overlap audit
    b_only = results.get("G1B_ONLY", {})
    d_econ = results.get("G1D", {})
    lines += [
        "\n## 4. Overlap Audit (G1-D ⊂ G1-B)\n",
        f"| Segment | n | Mean @72 | Gross>30 | Gross>40 |",
        f"|:--------|--:|:--------:|:--------:|:--------:|",
        f"| G1-B total | {results['G1B'].get('n', 0)} | "
        f"{results['G1B'].get('mean_bps', 0):+.2f} | "
        f"{results['G1B'].get('gt30_rate', 0):.1%} | "
        f"{results['G1B'].get('gt40_rate', 0):.1%} |",
        f"| G1-B only (excl D) | {b_only.get('n', 0)} | "
        f"{b_only.get('mean_bps', 0) or 0:+.2f} | "
        f"{b_only.get('gt30_rate', 0) or 0:.1%} | "
        f"{b_only.get('gt40_rate', 0) or 0:.1%} |",
        f"| G1-D | {d_econ.get('n', 0)} | "
        f"{d_econ.get('mean_bps', 0) or 0:+.2f} | "
        f"{d_econ.get('gt30_rate', 0) or 0:.1%} | "
        f"{d_econ.get('gt40_rate', 0) or 0:.1%} |",
    ]
    b_mean = results["G1B"].get("mean_bps") or 0.0
    d_mean = d_econ.get("mean_bps") or 0.0
    bo_mean = b_only.get("mean_bps") or 0.0
    if abs(d_mean - bo_mean) < 3.0:
        room_verdict = "ROOM_INCREMENTAL_VALUE = MARGINAL (B-only ≈ D)"
    elif d_mean > bo_mean + 3.0:
        room_verdict = "ROOM_INCREMENTAL_VALUE = CONFIRMED (D materially better than B-only)"
    else:
        room_verdict = "ROOM_INCREMENTAL_VALUE = NEGATIVE (B-only better than D)"
    lines += [f"\n> **Overlap verdict**: `{room_verdict}`\n"]

    # Gate verdicts
    lines += [f"\n## 5. Gate Verdicts\n"]
    if phase == "8":
        for var, label in [("G1B", "G1-B Compression"), ("G1D", "G1-D Both")]:
            gate = gate_check_corpus(results[var])
            gt30 = results[var].get("gt30_count", 0) or 0
            gt40 = results[var].get("gt40_count", 0) or 0
            lines.append(f"* **{label}**: `{gate}` (Gross>30 positives={gt30}, Gross>40 positives={gt40})")
    else:
        for var, label in [("G1B", "G1-B Compression"), ("G1D", "G1-D Both")]:
            gate = gate_check_validation(results[var])
            gt30r = results[var].get("gt30_rate", 0) or 0.0
            mean_ = results[var].get("mean_bps", -999) or -999.0
            n_    = results[var].get("n", 0) or 0
            lines.append(f"* **{label}**: `{gate}` (Gross>30={gt30r:.1%}, Mean={mean_:+.2f} bps, n={n_})")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_period(mode: str, args) -> int:
    """mode: 'corpus' (G1.8) or 'validation' (G1.9)."""
    freeze_path = REPO_ROOT / FREEZE_MANIFEST
    if not freeze_path.exists():
        print(f"ERROR: Architecture freeze manifest not found at {freeze_path}")
        return 1
    freeze = json.loads(freeze_path.read_text())
    print(f"  Freeze manifest loaded (SHA: {freeze.get('content_sha256','?')[:16]}...)")

    if mode == "corpus":
        period_start = pd.Timestamp("2023-01-01", tz="UTC")
        period_end   = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
        settle_end   = pd.Timestamp("2025-01-21", tz="UTC")  # +72 bars buffer
        phase        = "8"
        out_subdir   = "g1_8_corpus"
        print(f"  G1.8: Pre-2025 corpus expansion ({period_start.date()} → {period_end.date()})")
    else:
        period_start = pd.Timestamp("2025-04-01", tz="UTC")
        period_end   = pd.Timestamp("2025-06-30 23:59:59", tz="UTC")
        settle_end   = pd.Timestamp("2025-08-01", tz="UTC")  # +72 bars buffer
        phase        = "9"
        out_subdir   = "g1_9_validation"
        print(f"  G1.9: Out-of-discovery validation ({period_start.date()} → {period_end.date()})")

    print("  Loading candles...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), COINS, TIMEFRAME,
        period_start, period_end, settle_end,
        warmup_bars=WARMUP_BARS,
    )

    print("  Scanning crossings and computing features...")
    all_dfs = []
    for coin in COINS:
        df_coin = scan_crossings_for_coin(coin, candles_dict, period_start, period_end, settle_end)
        if len(df_coin):
            print(f"    {coin}: {len(df_coin)} total crossings, "
                  f"G1B={df_coin['G1B'].sum()}, G1D={df_coin['G1D'].sum()}")
        all_dfs.append(df_coin)

    df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    if df.empty:
        print("  ERROR: No crossings found in period.")
        return 1

    print(f"  Total: {len(df)} crossings, G1A={df['G1A'].sum()}, "
          f"G1B={df['G1B'].sum()}, G1D={df['G1D'].sum()}")

    print("  Analysing economics...")
    results = analyse_period(df)

    # Stdout summary
    print("\n  Economic Summary:")
    for var in ["G1A", "G1B", "G1D"]:
        e = results[var]
        print(f"    {var:5s}  n={e.get('n',0):5d}  "
              f"mean={e.get('mean_bps',0) or 0:+.1f}bps  "
              f">30={e.get('gt30_rate',0) or 0:.1%}({e.get('gt30_count',0) or 0})  "
              f">40={e.get('gt40_rate',0) or 0:.1%}({e.get('gt40_count',0) or 0})")

    print("\n  Gate Verdicts:")
    if phase == "8":
        for var in ["G1B", "G1D"]:
            print(f"    {var}: {gate_check_corpus(results[var])}")
    else:
        for var in ["G1B", "G1D"]:
            print(f"    {var}: {gate_check_validation(results[var])}")

    # Save
    out = Path(args.output_base) / out_subdir
    out.mkdir(parents=True, exist_ok=True)

    df_save = df.copy()
    df_save["timestamp"] = df_save["timestamp"].astype(str)
    df_save.to_parquet(out / "events.parquet", index=False)

    (out / "results.json").write_text(
        json.dumps({k: v for k, v in results.items()
                    if not isinstance(v, pd.DataFrame)}, indent=2, default=str)
    )

    report = build_report(phase, str(period_start.date()), str(period_end.date()), results, freeze)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"  ✓ Saved report: {out / 'report.md'}")
    print(f"\n  GATE: G1_{phase}_COMPLETE = PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2-G1.8/9: Corpus Expansion and Architecture Validation")
    p.add_argument("--mode", choices=["corpus", "validation", "both"], default="both",
                   help="corpus=G1.8, validation=G1.9, both=run sequentially")
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument("--output-base",
                   default="research/historical_market_replay_v2/v2_g1_event_architecture")
    return p


if __name__ == "__main__":
    args = _parser().parse_args()
    if args.mode in ("corpus", "both"):
        print("\n" + "=" * 60)
        rc = run_period("corpus", args)
        if rc and args.mode == "both":
            sys.exit(rc)
    if args.mode in ("validation", "both"):
        print("\n" + "=" * 60)
        rc = run_period("validation", args)
    sys.exit(rc)
