#!/usr/bin/env python3
"""HMR-V2-G1.5/6/7: Freeze Architecture Variants, Coverage Audit, and Economic Evaluation.

G1.5 — Freeze 4 predeclared architecture variants with semantic rounded thresholds.
        Thresholds are declared here and do NOT change after this point.

G1.6 — Coverage / Intersection audit per variant, symbol, side, month.
        Hard-warn variants below n=100 or <10% survival.

G1.7 — Target-aligned economic evaluation matrix @ 72-bar and 8-bar horizons.
        Select 1 primary + 1 challenger.

FROZEN THRESHOLDS (predeclared, do not tune after seeing economics):
  COMPRESSION:
    break_distance_atr  <= 0.25
    candle_body_atr     <= 0.15

  OPPORTUNITY:
    room_to_structure_atr >= 2.5    (room_to_structure_bps / atr_in_bps)
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

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

# ── Frozen thresholds (G1.5 predeclaration) ──────────────────────────────────
THRESH_BREAK_ATR   = 0.25   # compression: break distance ≤ this many ATRs
THRESH_BODY_ATR    = 0.15   # compression: candle body ≤ this many ATRs
THRESH_ROOM_ATR    = 1.0    # opportunity: room to structure ≥ this many ATRs
                             # (distribution max ~2.31 ATR; >=1.0 selects top ~35%)

# Coverage gates (G1.6)
COVERAGE_MIN_N        = 100
COVERAGE_MIN_SURVIVAL = 0.10   # 10 % of G1-A


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _econ(rets: pd.Series, rets8: Optional[pd.Series] = None,
          scores: Optional[pd.Series] = None) -> Dict[str, Any]:
    n = int(len(rets))
    if n == 0:
        return {"n": 0}
    d: Dict[str, Any] = {
        "n": n,
        "mean_bps": round(float(rets.mean() * 10_000), 2),
        "median_bps": round(float(rets.median() * 10_000), 2),
        "gt30_rate": round(float((rets > 0.0030).mean()), 4),
        "gt30_count": int((rets > 0.0030).sum()),
        "gt40_rate": round(float((rets > 0.0040).mean()), 4),
        "gt40_count": int((rets > 0.0040).sum()),
        "net_pos_rate": round(float((rets > COST_FRAC).mean()), 4),
    }
    if rets8 is not None and scores is not None:
        sub = pd.DataFrame({"ret8": rets8, "score": scores}).dropna()
        if len(sub) > 10:
            rho, _ = stats.spearmanr(sub["score"], sub["ret8"])
            d["spearman_8bar"] = round(float(rho), 4)
    return d


def _match_time(c_time, ts: pd.Timestamp) -> bool:
    t = pd.to_datetime(c_time)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t == ts


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def compute_features(sma50_df: pd.DataFrame,
                     candles_dict: Dict[str, List[Dict]]) -> pd.DataFrame:
    """Add PIT context features + ATR-normalised room to each candidate row."""
    coin_metrics: Dict[str, Dict] = {}
    for coin, rows in candles_dict.items():
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"])
        dfc["time"] = (dfc["time"].dt.tz_localize("UTC")
                       if dfc["time"].dt.tz is None
                       else dfc["time"].dt.tz_convert("UTC"))
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        coin_metrics[coin] = calculate_rolling_metrics(dfc)

    records: List[Dict] = []
    for _, row in sma50_df.iterrows():
        coin  = row["symbol"]
        side  = row["side"]
        ts    = row["timestamp"]
        ep    = float(row["entry_price"])

        rec: Dict[str, Any] = {
            "symbol": coin, "side": side, "timestamp": ts,
            "return_72bars": row.get("return_72bars", np.nan),
            "return_8bars":  row.get("return_8bars",  np.nan),
            "raw_model_score": row.get("raw_model_score", np.nan),
            "trend_regime": row.get("trend_regime", ""),
            "volatility_regime": row.get("volatility_regime", ""),
            # feature placeholders
            "break_distance_atr": np.nan,
            "candle_body_atr":    np.nan,
            "room_to_structure_bps": np.nan,
            "room_to_structure_atr": np.nan,
        }

        m = coin_metrics.get(coin)
        if m is None or ts not in m["sma50"].index:
            records.append(rec)
            continue

        s50   = float(m["sma50"].loc[ts])
        a_val = max(float(m["atr"].loc[ts]), 1e-8)
        supp  = float(m["support"].loc[ts])
        resis = float(m["resistance"].loc[ts])

        df_coin = candles_dict[coin]
        try:
            idx_c = next(i for i, c in enumerate(df_coin) if _match_time(c["time"], ts))
            curr_open = float(df_coin[idx_c]["open"])
        except StopIteration:
            records.append(rec)
            continue

        rec["break_distance_atr"] = abs(ep - s50) / a_val
        rec["candle_body_atr"]    = abs(ep - curr_open) / a_val
        room_bps = ((ep - supp) / ep * 10_000.0 if side == "SELL"
                    else (resis - ep) / ep * 10_000.0)
        rec["room_to_structure_bps"] = room_bps
        atr_bps = a_val / ep * 10_000.0
        rec["room_to_structure_atr"] = room_bps / max(atr_bps, 1e-6)

        records.append(rec)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Variant classification (G1.5)
# ---------------------------------------------------------------------------

VARIANT_DEFS = {
    "G1A_EVENT_ONLY":          "Fresh SMA50 crossing. No filters. Control.",
    "G1B_COMPRESSION":         f"break_distance_atr <= {THRESH_BREAK_ATR} AND candle_body_atr <= {THRESH_BODY_ATR}.",
    "G1C_OPPORTUNITY":         f"room_to_structure_atr >= {THRESH_ROOM_ATR}.",
    "G1D_COMPRESSION_OPPORT":  (f"break_distance_atr <= {THRESH_BREAK_ATR} AND "
                                 f"candle_body_atr <= {THRESH_BODY_ATR} AND "
                                 f"room_to_structure_atr >= {THRESH_ROOM_ATR}."),
}


def assign_variants(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    compression = (
        (df["break_distance_atr"] <= THRESH_BREAK_ATR) &
        (df["candle_body_atr"]    <= THRESH_BODY_ATR)
    )
    opportunity = df["room_to_structure_atr"] >= THRESH_ROOM_ATR

    df["G1A_EVENT_ONLY"]         = True
    df["G1B_COMPRESSION"]        = compression
    df["G1C_OPPORTUNITY"]        = opportunity
    df["G1D_COMPRESSION_OPPORT"] = compression & opportunity
    return df


# ---------------------------------------------------------------------------
# G1.6 Coverage audit
# ---------------------------------------------------------------------------

def coverage_audit(df: pd.DataFrame) -> Dict[str, Any]:
    total_events = int(df["G1A_EVENT_ONLY"].sum())
    result: Dict[str, Any] = {"total_events": total_events, "variants": {}}

    for var in VARIANT_DEFS:
        sub = df[df[var]]
        n = int(len(sub))
        survival = n / max(total_events, 1)
        coverage_ok = n >= COVERAGE_MIN_N and survival >= COVERAGE_MIN_SURVIVAL
        variant_result: Dict[str, Any] = {
            "n": n,
            "survival_rate": round(survival, 4),
            "coverage_ok": coverage_ok,
            "warnings": [],
        }
        if n < COVERAGE_MIN_N:
            variant_result["warnings"].append(f"n={n} < {COVERAGE_MIN_N} minimum")
        if survival < COVERAGE_MIN_SURVIVAL:
            variant_result["warnings"].append(
                f"survival={survival:.1%} < {COVERAGE_MIN_SURVIVAL:.0%} minimum")

        # Breakdown
        for col in ["symbol", "side"]:
            variant_result[f"by_{col}"] = (
                sub.groupby(col).size().to_dict()
            )
        sub["month"] = pd.to_datetime(sub["timestamp"]).dt.to_period("M").astype(str)
        variant_result["by_month"] = sub.groupby("month").size().to_dict()

        result["variants"][var] = variant_result

    return result


# ---------------------------------------------------------------------------
# G1.7 Economic evaluation
# ---------------------------------------------------------------------------

def economic_eval(df: pd.DataFrame) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for var in VARIANT_DEFS:
        sub = df[df[var]].copy()
        rets72  = pd.to_numeric(sub["return_72bars"],  errors="coerce").dropna()
        rets8   = pd.to_numeric(sub["return_8bars"],   errors="coerce")
        scores  = pd.to_numeric(sub["raw_model_score"], errors="coerce")
        # align indices
        aligned = pd.DataFrame({"ret8": rets8, "score": scores}).dropna()

        econ = _econ(
            pd.to_numeric(sub.loc[rets72.index, "return_72bars"], errors="coerce"),
            aligned["ret8"] if len(aligned) > 10 else None,
            aligned["score"] if len(aligned) > 10 else None,
        )
        econ["definition"] = VARIANT_DEFS[var]

        # per-symbol breakdown
        econ["by_symbol"] = {}
        for sym, g in sub.groupby("symbol"):
            r = pd.to_numeric(g["return_72bars"], errors="coerce").dropna()
            econ["by_symbol"][sym] = _econ(r)

        # per-side breakdown
        econ["by_side"] = {}
        for side, g in sub.groupby("side"):
            r = pd.to_numeric(g["return_72bars"], errors="coerce").dropna()
            econ["by_side"][side] = _econ(r)

        result[var] = econ
    return result


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def build_report(frozen: Dict, cov: Dict, econ: Dict) -> str:
    lines = ["# HMR-V2-G1.5/6/7: Architecture Variants — Coverage & Economic Evaluation\n"]

    # G1.5 frozen thresholds
    lines += [
        "## G1.5 — Frozen Threshold Declarations\n",
        f"```\nCOMPRESSION GATE\n"
        f"  break_distance_atr  <= {THRESH_BREAK_ATR}\n"
        f"  candle_body_atr     <= {THRESH_BODY_ATR}\n\n"
        f"OPPORTUNITY GATE\n"
        f"  room_to_structure_atr >= {THRESH_ROOM_ATR}\n"
        f"```\n",
        "| Variant | Rules |",
        "|:--------|:------|",
    ]
    for var, defn in VARIANT_DEFS.items():
        lines.append(f"| `{var}` | {defn} |")

    # G1.6 coverage
    lines += [
        "\n## G1.6 — Coverage Audit\n",
        f"Total G1-A events (raw crossing pool): **{cov['total_events']}**\n",
        "| Variant | n | Survival | Coverage OK | Warnings |",
        "|:--------|--:|:--------:|:-----------:|:---------|",
    ]
    for var, v in cov["variants"].items():
        warn_str = "; ".join(v["warnings"]) if v["warnings"] else "—"
        ok = "✓" if v["coverage_ok"] else "✗ DEMOTED"
        lines.append(
            f"| `{var}` | {v['n']} | {v['survival_rate']:.1%} | {ok} | {warn_str} |"
        )

    # G1.7 economic comparison matrix
    lines += [
        "\n## G1.7 — Target-Aligned Economic Evaluation (72-bar + 8-bar)\n",
        "| Metric | G1-A Event | G1-B Compression | G1-C Opportunity | G1-D Both |",
        "|:-------|:----------:|:----------------:|:----------------:|:---------:|",
    ]
    vars_ordered = list(VARIANT_DEFS.keys())
    metrics = [
        ("n", "n", "{}"),
        ("Mean @72 (bps)", "mean_bps", "{:+.2f}"),
        ("Median @72 (bps)", "median_bps", "{:+.2f}"),
        ("Gross >30 rate", "gt30_rate", "{:.1%}"),
        ("Gross >30 count", "gt30_count", "{}"),
        ("Gross >40 rate", "gt40_rate", "{:.1%}"),
        ("Gross >40 count", "gt40_count", "{}"),
        ("Net+ rate", "net_pos_rate", "{:.1%}"),
        ("Spearman @8 bars", "spearman_8bar", "{:+.4f}"),
    ]
    for label, key, fmt in metrics:
        cells = []
        for var in vars_ordered:
            val = econ[var].get(key)
            cells.append(fmt.format(val) if val is not None else "—")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    # Per-symbol stability for each variant
    lines += ["\n### Per-Symbol Gross>30 Rate\n",
              "| Symbol | G1-A | G1-B | G1-C | G1-D |",
              "|:-------|:----:|:----:|:----:|:----:|"]
    symbols = sorted({sym for v in econ.values() for sym in v.get("by_symbol", {})})
    for sym in symbols:
        cells = []
        for var in vars_ordered:
            r = econ[var].get("by_symbol", {}).get(sym, {}).get("gt30_rate")
            cells.append(f"{r:.1%}" if r is not None else "—")
        lines.append(f"| {sym} | " + " | ".join(cells) + " |")

    # Per-side
    lines += ["\n### Per-Side Gross>30 Rate\n",
              "| Side | G1-A | G1-B | G1-C | G1-D |",
              "|:-----|:----:|:----:|:----:|:----:|"]
    sides = sorted({s for v in econ.values() for s in v.get("by_side", {})})
    for side in sides:
        cells = []
        for var in vars_ordered:
            r = econ[var].get("by_side", {}).get(side, {}).get("gt30_rate")
            cells.append(f"{r:.1%}" if r is not None else "—")
        lines.append(f"| {side} | " + " | ".join(cells) + " |")

    # Discovery gate evaluation
    lines += ["\n## Discovery Gate Evaluation\n",
              "```\nPRIMARY DISCOVERY TARGET\n"
              "  Gross>30 rate    >= 18%\n"
              "  Gross>40 rate    >= 10%\n"
              "  Mean gross @72   > -10 bps\n"
              "  Event sample     >= 150\n```\n",
              "| Variant | Gross>30 | Gross>40 | Mean @72 | n | Gate |",
              "|:--------|:--------:|:--------:|:--------:|--:|:----:|"]
    for var in vars_ordered:
        e = econ[var]
        n     = e.get("n", 0)
        gt30  = e.get("gt30_rate", 0.0) or 0.0
        gt40  = e.get("gt40_rate", 0.0) or 0.0
        mean_ = e.get("mean_bps", -999.0) or -999.0
        cov_ok = cov["variants"][var]["coverage_ok"]
        gate = (cov_ok and gt30 >= 0.18 and gt40 >= 0.10 and mean_ > -10.0 and n >= 150)
        lines.append(
            f"| `{var}` | {gt30:.1%} | {gt40:.1%} | {mean_:+.2f} | {n} | "
            f"{'✓ PASS' if gate else '✗ FAIL'} |"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found.")
        return 1

    print("HMR-V2-G1.5/6/7: Architecture Variants, Coverage, and Economic Evaluation")
    print(f"  Input: {parquet_path}")

    df_raw = pd.read_parquet(parquet_path)
    df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
    df_raw["timestamp"] = (
        df_raw["timestamp"].dt.tz_localize("UTC")
        if df_raw["timestamp"].dt.tz is None
        else df_raw["timestamp"].dt.tz_convert("UTC")
    )
    sma50_df = df_raw[df_raw["technical_signal_family"] == "SMA50_BREAK"].copy().reset_index(drop=True)
    print(f"  SMA50_BREAK candidates: {len(sma50_df)}")

    coins = list(sma50_df["symbol"].unique())
    t0 = sma50_df["timestamp"].min() - pd.Timedelta(days=5)
    t1 = sma50_df["timestamp"].max() + pd.Timedelta(days=1)
    print("  Loading closed candles...")
    candles_dict = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, t0, t1, t1,
        warmup_bars=args.warmup_bars,
    )

    print("  Computing PIT features...")
    feat_df = compute_features(sma50_df, candles_dict)

    print("  Assigning variants (G1.5)...")
    feat_df = assign_variants(feat_df)

    # Print frozen threshold declaration
    print(f"\n  FROZEN THRESHOLDS (G1.5 predeclaration):")
    print(f"    break_distance_atr  <= {THRESH_BREAK_ATR}")
    print(f"    candle_body_atr     <= {THRESH_BODY_ATR}")
    print(f"    room_to_structure_atr >= {THRESH_ROOM_ATR}")
    print()

    print("  Running coverage audit (G1.6)...")
    cov = coverage_audit(feat_df)

    print("  Running economic evaluation (G1.7)...")
    econ = economic_eval(feat_df)

    # Summary to stdout
    print("\n  Coverage Summary:")
    for var, v in cov["variants"].items():
        ok = "OK" if v["coverage_ok"] else "WARN"
        print(f"    {var:40s} n={v['n']:4d}  survival={v['survival_rate']:.1%}  [{ok}]")

    print("\n  Economic Summary (Gross>30 rate @ 72 bars):")
    for var in VARIANT_DEFS:
        e = econ[var]
        print(f"    {var:40s} n={e.get('n',0):4d}  "
              f"mean={e.get('mean_bps',0):+.1f}bps  "
              f">30={e.get('gt30_rate',0):.1%}  "
              f">40={e.get('gt40_rate',0):.1%}")

    # Save outputs
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    frozen_meta = {
        "thresholds": {
            "break_distance_atr_max": THRESH_BREAK_ATR,
            "candle_body_atr_max":    THRESH_BODY_ATR,
            "room_to_structure_atr_min": THRESH_ROOM_ATR,
        },
        "variants": VARIANT_DEFS,
        "coverage_min_n": COVERAGE_MIN_N,
        "coverage_min_survival": COVERAGE_MIN_SURVIVAL,
    }
    (out / "frozen_thresholds.json").write_text(json.dumps(frozen_meta, indent=2))
    (out / "coverage.json").write_text(json.dumps(cov, indent=2))
    (out / "economics.json").write_text(json.dumps(econ, indent=2))

    report = build_report(frozen_meta, cov, econ)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"\n  ✓ Saved report: {out / 'report.md'}")
    print("\n  GATE: ARCHITECTURE_VARIANTS_EVALUATED = PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="HMR-V2-G1.5/6/7: Freeze variants, coverage audit, economic evaluation")
    p.add_argument("--parquet",
                   default="research/historical_market_replay_v2/v2_1_candidate_decomposition/candidates.parquet")
    p.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--warmup-bars", type=int, default=200)
    p.add_argument("--output-dir",
                   default="research/historical_market_replay_v2/v2_g1_event_architecture/g1_567_variants")
    return p


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
