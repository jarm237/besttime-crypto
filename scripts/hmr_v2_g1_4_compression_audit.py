#!/usr/bin/env python3
"""HMR-V2-G1.4: Compression Feature Redundancy Audit.

Answers:
  1. Which context features are correlated proxies for the same latent compression state?
  2. Do any features add independent economic information beyond break_distance_atr?
  3. Is per-symbol and per-side enrichment stable (BTC/ETH/BNB, BUY/SELL)?
  4. Does recent_cross_count have a monotonic relationship with outcome?
     → WHIPSAW_CONTEXT = CONFIRMED  (monotonic)
     → OVEREXTENSION_CONTEXT = CONFIRMED, WHIPSAW = PLAUSIBLE  (no monotonic)

Outputs:
  g1_4_compression_audit/
    correlation_matrix.json
    conditional_tables.json
    per_symbol_stability.json
    per_side_stability.json
    whipsaw_monotonicity.json
    report.md
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v2_g1_3_characterization import calculate_rolling_metrics

COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _econ(rets: pd.Series) -> Dict[str, Any]:
    """Compute a standard economics summary dict from a return Series."""
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean_bps": None, "median_bps": None,
                "gt30_rate": None, "gt40_rate": None, "net_pos_rate": None}
    return {
        "n": n,
        "mean_bps": round(float(rets.mean() * 10_000), 2),
        "median_bps": round(float(rets.median() * 10_000), 2),
        "gt30_rate": round(float((rets > 0.0030).mean()), 4),
        "gt40_rate": round(float((rets > 0.0040).mean()), 4),
        "net_pos_rate": round(float((rets > COST_FRAC).mean()), 4),
    }


def _quintile_rows(df: pd.DataFrame, feat: str) -> List[Dict[str, Any]]:
    sub = df[[feat, "return_72bars"]].dropna()
    if len(sub) < 10:
        return []
    sub = sub.sort_values(feat).reset_index(drop=True)
    n = len(sub)
    rows = []
    for q in range(5):
        sl = slice(q * (n // 5), (q + 1) * (n // 5) if q < 4 else n)
        chunk = sub.iloc[sl]
        row = _econ(chunk["return_72bars"])
        row["quintile"] = q + 1
        row["min_val"] = round(float(chunk[feat].min()), 6)
        row["max_val"] = round(float(chunk[feat].max()), 6)
        rows.append(row)
    return rows


def _match_time(c_time, target_ts: pd.Timestamp) -> bool:
    t = pd.to_datetime(c_time)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t == target_ts


# ---------------------------------------------------------------------------
# Feature computation (identical logic to G1.3)
# ---------------------------------------------------------------------------

FEATURES = [
    "break_distance_atr",
    "candle_body_atr",
    "ema9_ema21_distance",
    "recent_cross_count_16bars",
    "room_to_structure_bps",
    "volume_ratio",
    "sma50_slope",
]


def build_feature_df(sma50_df: pd.DataFrame,
                     candles_dict: Dict[str, List[Dict]]) -> pd.DataFrame:
    """Compute PIT context features for every SMA50_BREAK candidate row."""
    coin_metrics: Dict[str, Dict] = {}
    for coin, rows in candles_dict.items():
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"])
        dfc["time"] = dfc["time"].dt.tz_localize("UTC") if dfc["time"].dt.tz is None \
            else dfc["time"].dt.tz_convert("UTC")
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        coin_metrics[coin] = calculate_rolling_metrics(dfc)

    records: List[Dict] = []
    for _, row in sma50_df.iterrows():
        coin = row["symbol"]
        side = row["side"]
        ts   = row["timestamp"]
        ep   = float(row["entry_price"])
        ret72 = float(row["return_72bars"]) if pd.notna(row.get("return_72bars")) else np.nan
        ret8  = float(row["return_8bars"])  if pd.notna(row.get("return_8bars"))  else np.nan

        m = coin_metrics.get(coin)
        feat_vals = {f: np.nan for f in FEATURES}
        feat_vals.update({"symbol": coin, "side": side, "timestamp": ts,
                          "return_72bars": ret72, "return_8bars": ret8})

        if m is None or ts not in m["sma50"].index:
            records.append(feat_vals)
            continue

        s50    = float(m["sma50"].loc[ts])
        e9     = float(m["ema9"].loc[ts])
        e21    = float(m["ema21"].loc[ts])
        a_val  = max(float(m["atr"].loc[ts]), 1e-8)
        v_sma  = max(float(m["vol_sma"].loc[ts]), 1e-8)
        supp   = float(m["support"].loc[ts])
        resis  = float(m["resistance"].loc[ts])
        w16    = float(m["cross_count_16"].loc[ts])
        sl50   = float(m["sma50_slope"].loc[ts])

        df_coin = candles_dict[coin]
        try:
            idx_c = next(i for i, c in enumerate(df_coin) if _match_time(c["time"], ts))
            curr_open = float(df_coin[idx_c]["open"])
            curr_vol  = float(df_coin[idx_c]["volume"])
        except StopIteration:
            records.append(feat_vals)
            continue

        feat_vals["break_distance_atr"]    = abs(ep - s50) / a_val
        feat_vals["candle_body_atr"]       = abs(ep - curr_open) / a_val
        feat_vals["ema9_ema21_distance"]   = (e9 - e21) / ep * 10_000.0
        feat_vals["recent_cross_count_16bars"] = w16
        feat_vals["volume_ratio"]          = curr_vol / v_sma
        feat_vals["sma50_slope"]           = sl50
        room = (ep - supp) / ep * 10_000.0 if side == "SELL" else (resis - ep) / ep * 10_000.0
        feat_vals["room_to_structure_bps"] = room

        records.append(feat_vals)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Analysis sections
# ---------------------------------------------------------------------------

def spearman_matrix(df: pd.DataFrame, feats: List[str]) -> Dict:
    sub = df[feats].dropna()
    mat = {}
    for f1 in feats:
        mat[f1] = {}
        for f2 in feats:
            if f1 == f2:
                mat[f1][f2] = 1.0
            else:
                rho, _ = stats.spearmanr(sub[f1], sub[f2])
                mat[f1][f2] = round(float(rho), 4)
    return mat


def conditional_tables(df: pd.DataFrame) -> Dict:
    """break_distance_atr Q1  ×  each other feature's quintile."""
    sub = df.dropna(subset=["break_distance_atr", "return_72bars"])
    q20 = sub["break_distance_atr"].quantile(0.20)   # bottom 20%
    tight = sub[sub["break_distance_atr"] <= q20]
    other = sub[sub["break_distance_atr"] > q20]

    tables = {
        "overall_tight_n": int(len(tight)),
        "overall_other_n": int(len(other)),
        "overall_tight_econ": _econ(tight["return_72bars"]),
        "overall_other_econ": _econ(other["return_72bars"]),
        "cross_quintiles": {}
    }

    for feat in ["candle_body_atr", "ema9_ema21_distance",
                 "recent_cross_count_16bars", "room_to_structure_bps", "volume_ratio"]:
        if feat not in df.columns:
            continue
        cross = []
        feat_sub = tight[[feat, "return_72bars"]].dropna()
        if len(feat_sub) < 10:
            tables["cross_quintiles"][feat] = []
            continue
        feat_sub = feat_sub.sort_values(feat).reset_index(drop=True)
        n = len(feat_sub)
        for q in range(5):
            sl = slice(q * (n // 5), (q + 1) * (n // 5) if q < 4 else n)
            chunk = feat_sub.iloc[sl]
            row = _econ(chunk["return_72bars"])
            row["quintile"] = q + 1
            row["feat_range"] = f"{chunk[feat].min():.4f}–{chunk[feat].max():.4f}"
            cross.append(row)
        tables["cross_quintiles"][feat] = cross

    return tables


def per_symbol_stability(df: pd.DataFrame) -> Dict:
    q20 = df["break_distance_atr"].quantile(0.20)
    tight = df[df["break_distance_atr"] <= q20]
    result = {}
    for sym in sorted(df["symbol"].unique()):
        sym_tight = tight[tight["symbol"] == sym]["return_72bars"].dropna()
        sym_all   = df[df["symbol"] == sym]["return_72bars"].dropna()
        result[sym] = {
            "baseline": _econ(sym_all),
            "tight_break": _econ(sym_tight),
        }
    return result


def per_side_stability(df: pd.DataFrame) -> Dict:
    q20 = df["break_distance_atr"].quantile(0.20)
    tight = df[df["break_distance_atr"] <= q20]
    result = {}
    for side in sorted(df["side"].unique()):
        s_tight = tight[tight["side"] == side]["return_72bars"].dropna()
        s_all   = df[df["side"] == side]["return_72bars"].dropna()
        result[side] = {
            "baseline": _econ(s_all),
            "tight_break": _econ(s_tight),
        }
    return result


def whipsaw_monotonicity(df: pd.DataFrame) -> Dict:
    """Quintile sweep of recent_cross_count_16bars vs return_72bars."""
    rows = _quintile_rows(df, "recent_cross_count_16bars")
    # Test monotonicity: do gt30_rates decline as cross count rises?
    rates = [r["gt30_rate"] for r in rows if r.get("gt30_rate") is not None]
    # Kendall tau: negative = monotone decreasing (higher freq → worse)
    if len(rates) >= 3:
        tau, p = stats.kendalltau(range(len(rates)), rates)
        confirmed = tau < -0.3 and p < 0.10
        verdict = "WHIPSAW_CONTEXT_CONFIRMED" if confirmed else "WHIPSAW_PLAUSIBLE_NOT_PRIMARY"
    else:
        tau, p, confirmed = 0.0, 1.0, False
        verdict = "INSUFFICIENT_DATA"

    return {
        "quintiles": rows,
        "kendall_tau": round(float(tau), 4),
        "p_value": round(float(p), 4),
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def build_report(corr: Dict, cond: Dict, sym: Dict, side_d: Dict,
                 whip: Dict) -> str:
    lines = ["# HMR-V2-G1.4: Compression Feature Redundancy Audit\n"]

    # 1. Correlation matrix
    lines += [
        "## 1. Spearman Correlation Matrix\n",
        "| Feature | break_dist | body_atr | ema_dist | cross16 | room | vol_ratio | slope50 |",
        "|:--------|:----------:|:--------:|:--------:|:-------:|:----:|:---------:|:-------:|",
    ]
    col_order = [
        "break_distance_atr", "candle_body_atr", "ema9_ema21_distance",
        "recent_cross_count_16bars", "room_to_structure_bps",
        "volume_ratio", "sma50_slope",
    ]
    short = ["break_dist", "body_atr", "ema_dist", "cross16", "room", "vol_ratio", "slope50"]
    for f, s in zip(col_order, short):
        vals = " | ".join(f"{corr.get(f, {}).get(c, float('nan')):+.2f}" for c in col_order)
        lines.append(f"| `{s}` | {vals} |")

    lines += [
        "\n> Values near ±1.0 indicate redundant proxies; values near 0 indicate independent information.\n",
    ]

    # 2. Conditional tables
    lines += ["\n## 2. Conditional Economic Tables (break_distance_atr Q1 × other features)\n"]
    lines.append(
        f"**Tight-break region** (`break_distance_atr` ≤ bottom 20%): "
        f"n={cond['overall_tight_n']}, "
        f"Mean={cond['overall_tight_econ']['mean_bps']:+.2f} bps, "
        f"Gross>30={cond['overall_tight_econ']['gt30_rate']:.1%}\n"
    )
    for feat, rows in cond.get("cross_quintiles", {}).items():
        if not rows:
            continue
        lines.append(f"### Within tight-break: `{feat}` quintile split")
        lines.append("| Q | Range | n | Mean @72 | >30% | >40% | Net+ |")
        lines.append("|:-:|:------|--:|---------:|-----:|-----:|-----:|")
        for r in rows:
            lines.append(
                f"| {r['quintile']} | {r['feat_range']} | {r['n']} | "
                f"{r['mean_bps']:+.2f} | {r['gt30_rate']:.1%} | "
                f"{r['gt40_rate']:.1%} | {r['net_pos_rate']:.1%} |"
            )
        lines.append("")

    # 3. Per-symbol
    lines += ["\n## 3. Per-Symbol Stability (break_distance_atr tight-break)\n"]
    lines.append("| Symbol | Baseline n | Baseline Gross>30 | Tight-break n | Tight-break Gross>30 | Delta |")
    lines.append("|:-------|:----------:|:-----------------:|:-------------:|:--------------------:|:-----:|")
    for sym_name, d in sym.items():
        bl = d["baseline"]
        tb = d["tight_break"]
        b_rate = bl["gt30_rate"] if bl["gt30_rate"] is not None else 0.0
        t_rate = tb["gt30_rate"] if tb["gt30_rate"] is not None else 0.0
        delta = t_rate - b_rate if (bl["gt30_rate"] is not None and tb["gt30_rate"] is not None) else float("nan")
        lines.append(
            f"| {sym_name} | {bl['n']} | {b_rate:.1%} | {tb['n']} | {t_rate:.1%} | {delta:+.1%} |"
        )

    # 4. Per-side
    lines += ["\n## 4. Per-Side Stability (break_distance_atr tight-break)\n"]
    lines.append("| Side | Baseline n | Baseline Gross>30 | Tight-break n | Tight-break Gross>30 | Delta |")
    lines.append("|:-----|:----------:|:-----------------:|:-------------:|:--------------------:|:-----:|")
    for side_name, d in side_d.items():
        bl = d["baseline"]
        tb = d["tight_break"]
        b_rate = bl["gt30_rate"] if bl["gt30_rate"] is not None else 0.0
        t_rate = tb["gt30_rate"] if tb["gt30_rate"] is not None else 0.0
        delta = t_rate - b_rate if (bl["gt30_rate"] is not None and tb["gt30_rate"] is not None) else float("nan")
        lines.append(
            f"| {side_name} | {bl['n']} | {b_rate:.1%} | {tb['n']} | {t_rate:.1%} | {delta:+.1%} |"
        )

    # 5. Whipsaw monotonicity
    lines += ["\n## 5. Whipsaw Monotonicity Test (recent_cross_count_16bars)\n"]
    lines.append("| Q | Cross-count range | n | Mean @72 | Gross>30 | Gross>40 | Net+ |")
    lines.append("|:-:|:------------------|--:|---------:|:--------:|:--------:|:----:|")
    for r in whip.get("quintiles", []):
        lines.append(
            f"| {r['quintile']} | {r['min_val']:.1f}–{r['max_val']:.1f} | {r['n']} | "
            f"{r['mean_bps']:+.2f} | {r['gt30_rate']:.1%} | "
            f"{r['gt40_rate']:.1%} | {r['net_pos_rate']:.1%} |"
        )
    lines += [
        f"\nKendall-τ = {whip['kendall_tau']:+.3f}, p = {whip['p_value']:.3f}  \n",
        f"**Verdict**: `{whip['verdict']}`\n",
        "> τ < −0.3 with p < 0.10 → monotone decline → WHIPSAW_CONTEXT_CONFIRMED  \n",
        "> otherwise → OVEREXTENSION_CONTEXT primary, whipsaw plausible\n",
    ]

    # 6. Redundancy verdict
    lines += ["\n## 6. Feature Redundancy Summary\n"]
    lines.append(
        "| Feature | Independent of break_dist? | Adds edge inside tight-break region? |\n"
        "|:--------|:---------------------------:|:------------------------------------:|"
    )
    # We derive these from the cross-quintile tables
    for feat, rows in cond.get("cross_quintiles", {}).items():
        if not rows:
            lines.append(f"| `{feat}` | ? | insufficient data |")
            continue
        rates = [r["gt30_rate"] for r in rows if r.get("gt30_rate") is not None]
        spread = max(rates) - min(rates) if rates else 0.0
        if len(rates) >= 3:
            tau_inner, _ = stats.kendalltau(range(len(rows)), rates)
        else:
            tau_inner = 0.0
        adds_edge = "YES (spread={:.1%})".format(spread) if spread > 0.08 else "NO (spread={:.1%})".format(spread)
        corr_val = corr.get("break_distance_atr", {}).get(feat, 0.0)
        independent = "NO (ρ={:+.2f})".format(corr_val) if abs(corr_val) > 0.5 else "YES (ρ={:+.2f})".format(corr_val)
        lines.append(f"| `{feat}` | {independent} | {adds_edge} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found.")
        return 1

    print("HMR-V2-G1.4: Compression Feature Redundancy Audit")
    print(f"  Input: {parquet_path}")

    # Load and filter
    df_raw = pd.read_parquet(parquet_path)
    df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
    df_raw["timestamp"] = (
        df_raw["timestamp"].dt.tz_localize("UTC")
        if df_raw["timestamp"].dt.tz is None
        else df_raw["timestamp"].dt.tz_convert("UTC")
    )
    sma50_df = df_raw[df_raw["technical_signal_family"] == "SMA50_BREAK"].copy().reset_index(drop=True)
    print(f"  SMA50_BREAK candidates: {len(sma50_df)}")

    # Load candles
    coins = list(sma50_df["symbol"].unique())
    t0 = sma50_df["timestamp"].min() - pd.Timedelta(days=5)
    t1 = sma50_df["timestamp"].max() + pd.Timedelta(days=1)
    print("  Loading closed candles...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, t0, t1, t1,
        warmup_bars=args.warmup_bars,
    )

    # Build feature dataframe
    print("  Computing PIT features...")
    feat_df = build_feature_df(sma50_df, candles_dict)
    print(f"  Feature rows: {len(feat_df)}, non-null break_dist: {feat_df['break_distance_atr'].notna().sum()}")

    # Run analyses
    print("  Running analyses...")
    corr = spearman_matrix(feat_df, FEATURES)
    cond = conditional_tables(feat_df)
    sym  = per_symbol_stability(feat_df)
    side_d = per_side_stability(feat_df)
    whip = whipsaw_monotonicity(feat_df)

    # Save outputs
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / "correlation_matrix.json").write_text(json.dumps(corr, indent=2))
    (out / "conditional_tables.json").write_text(json.dumps(cond, indent=2))
    (out / "per_symbol_stability.json").write_text(json.dumps(sym, indent=2))
    (out / "per_side_stability.json").write_text(json.dumps(side_d, indent=2))
    (out / "whipsaw_monotonicity.json").write_text(json.dumps(whip, indent=2))
    print("  ✓ Saved JSON outputs.")

    report_text = build_report(corr, cond, sym, side_d, whip)
    (out / "report.md").write_text(report_text, encoding="utf-8")
    print(f"  ✓ Saved MD report: {out / 'report.md'}")
    print()
    print(f"  WHIPSAW_VERDICT: {whip['verdict']}")
    print()
    print("  GATE: COMPRESSION_FEATURES_AUDITED = PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2-G1.4: Compression Feature Redundancy Audit")
    p.add_argument("--parquet",
                   default="research/historical_market_replay_v2/v2_1_candidate_decomposition/candidates.parquet")
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--warmup-bars", type=int, default=200)
    p.add_argument("--output-dir",
                   default="research/historical_market_replay_v2/v2_g1_event_architecture/g1_4_compression_audit")
    return p


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
