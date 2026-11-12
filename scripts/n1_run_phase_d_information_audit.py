"""
scripts/n1_run_phase_d_information_audit.py

Executes Phase D pre-training information evaluation on the fresh, checksum-
verified N1 datasets:
  - H1: 13-pair Binance Spot 1h panel (2017-08 .. 2025-12; dev = 2018-01 .. 2024-12)
  - H2: BTCUSDT & ETHUSDT USD-M bookDepth 1h panel (2023-01 .. 2025-12; dev = 2023-01 .. 2024-12)
Applies Benjamini-Hochberg FDR across all tested (feature, horizon) pairs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

from neural_trading.n1.pit_dataset import (
    SPOT_SYMBOLS, DEPTH_SYMBOLS, build_spot_panel, build_bookdepth_hourly,
)
from neural_trading.n1.information_tests import (
    compute_h1_features, evaluate_feature_panel,
)

RAW_ROOT = REPO / "data" / "historical" / "neural_n1" / "raw"
CACHE_DIR = REPO / "data" / "historical" / "neural_n1" / "pit_cache"
OUT_DIR = REPO / "research" / "neural_n1"


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = np.argsort(p_values)
    ranked = np.array(p_values, dtype=float)[order]
    q = np.minimum(1.0, ranked * m / (np.arange(1, m + 1)))
    for i in range(m - 2, -1, -1):
        q[i] = min(q[i], q[i + 1])
    out = np.empty(m, dtype=float)
    out[order] = q
    return [round(float(x), 4) for x in out]


def main() -> None:
    print("Building PIT-aligned Spot 1h panel (13 symbols, 2017-2025)...", flush=True)
    spot_panel = build_spot_panel(RAW_ROOT, SPOT_SYMBOLS, CACHE_DIR / "spot_panel_1h.parquet")
    h1_feats = compute_h1_features(spot_panel)
    close = h1_feats["close"]
    active = h1_feats["active"]

    print("Building PIT-aligned bookDepth 1h panel (BTCUSDT & ETHUSDT, 2023-2025)...", flush=True)
    bd_panel = build_bookdepth_hourly(RAW_ROOT, DEPTH_SYMBOLS, CACHE_DIR / "bookdepth_1h.parquet")

    h1_segments = {
        "S1_2018_2019": ("2018-01-01", "2019-12-31 23:00:00"),
        "S2_2020_2021": ("2020-01-01", "2021-12-31 23:00:00"),
        "S3_2022": ("2022-01-01", "2022-12-31 23:00:00"),
        "S4_2023_2024": ("2023-01-01", "2024-12-31 23:00:00"),
    }
    h2_segments = {
        "D1_2023_H1": ("2023-01-01", "2023-06-30 23:00:00"),
        "D2_2023_H2": ("2023-07-01", "2023-12-31 23:00:00"),
        "D3_2024_H1": ("2024-01-01", "2024-06-30 23:00:00"),
        "D4_2024_H2": ("2024-07-01", "2024-12-31 23:00:00"),
    }

    h1_names = [k for k in h1_feats.keys() if k.startswith("H1_")]
    results = {"H1": {}, "H2": {}}
    all_tests = []

    print("\n=== Evaluating H1 Features (2018-2024 Development across 4 Regimes) ===", flush=True)
    for fname in h1_names:
        results["H1"][fname] = {}
        for h in (4, 12, 24):
            res = evaluate_feature_panel(h1_feats[fname], close, active, h, h1_segments)
            results["H1"][fname][f"{h}h"] = res
            all_tests.append(("H1", fname, f"{h}h", res["overall_dev"]["boot_p_value"]))
            ov = res["overall_dev"]
            print(
                f"  {fname:24s} {h:2d}h | raw={ov['raw_spread_bps']:+6.2f}bp "
                f"log={ov['log_spread_bps']:+6.2f}bp betaLog={ov['beta_adj_log_spread_bps']:+6.2f}bp "
                f"win={ov['winsor_spread_bps']:+6.2f}bp CI=[{ov['ci95_lo_bps']:+6.2f},{ov['ci95_hi_bps']:+6.2f}] p={ov['boot_p_value']:.3f} "
                f"cost={ov['implied_cost_bps']:5.2f}bp netLog={ov['net_log_spread_after_cost_bps']:+6.2f}bp "
                f"volQ5/Q1={ov['fwd_vol_ratio_q5_q1']:.2f} segStab={ov['segment_sign_stability']:.2f}",
                flush=True,
            )

    print("\n=== Evaluating H2 Features (bookDepth 2023-2024 Development across 4 Half-Year Segments) ===", flush=True)
    close_bd = close[list(DEPTH_SYMBOLS)].reindex(bd_panel["BTCUSDT"].index)
    active_bd = active[list(DEPTH_SYMBOLS)].reindex(bd_panel["BTCUSDT"].index).fillna(False)
    h2_feat_cols = [
        "imb_1pct_mean", "imb_1pct_last", "imb_5pct_mean",
        "imb_1pct_ma4h", "imb_5pct_ma4h", "slope_1_5_mean", "depth_thinning_z168h",
    ]
    for col in h2_feat_cols:
        fname = f"H2_{col}"
        df_col = pd.DataFrame({s: bd_panel[s][col] for s in DEPTH_SYMBOLS}, index=close_bd.index)
        results["H2"][fname] = {}
        for h in (4, 12, 24):
            res = evaluate_feature_panel(df_col, close_bd, active_bd, h, h2_segments)
            results["H2"][fname][f"{h}h"] = res
            all_tests.append(("H2", fname, f"{h}h", res["overall_dev"]["boot_p_value"]))
            ov = res["overall_dev"]
            print(
                f"  {fname:26s} {h:2d}h | raw={ov['raw_spread_bps']:+6.2f}bp "
                f"log={ov['log_spread_bps']:+6.2f}bp betaLog={ov['beta_adj_log_spread_bps']:+6.2f}bp "
                f"win={ov['winsor_spread_bps']:+6.2f}bp CI=[{ov['ci95_lo_bps']:+6.2f},{ov['ci95_hi_bps']:+6.2f}] p={ov['boot_p_value']:.3f} "
                f"cost={ov['implied_cost_bps']:5.2f}bp netLog={ov['net_log_spread_after_cost_bps']:+6.2f}bp "
                f"volQ5/Q1={ov['fwd_vol_ratio_q5_q1']:.2f} segStab={ov['segment_sign_stability']:.2f}",
                flush=True,
            )

    q_vals = benjamini_hochberg([t[3] for t in all_tests])
    for (hyp, fname, hstr, _), qv in zip(all_tests, q_vals):
        results[hyp][fname][hstr]["overall_dev"]["bh_fdr_q_value"] = qv

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "n1_phase_d_information_audit.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nSaved Phase D audit to {out_path}", flush=True)


if __name__ == "__main__":
    main()
