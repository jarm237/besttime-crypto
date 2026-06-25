#!/usr/bin/env python3
"""Compute feature diagnostics: variance, missingness, Pearson correlation with label,
and per-feature AUC (univariate ROC AUC). Outputs JSON and CSV under `logs/`.
"""
import json
from pathlib import Path
import math

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


LOGS = Path("logs")
SRC = LOGS / "adaptive_signals_v2.json"
OUT_JSON = LOGS / "feature_diagnostics.json"
OUT_CSV = LOGS / "feature_diagnostics.csv"


def is_number_series(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s)


def main():
    if not SRC.exists():
        print(f"Dataset not found: {SRC}")
        return 2

    print(f"Loading dataset {SRC}...")
    df = pd.read_json(SRC, convert_dates=False)
    print(f"Records: {len(df)} | Columns: {len(df.columns)}")

    # Label
    if "result" not in df.columns:
        print("No 'result' column found.")
        return 3
    y = df["result"].astype(str).str.upper().map(lambda x: 1 if x == "WIN" else 0)

    # Exclude meta columns
    exclude = {"coin", "entry_time", "exit_time", "result", "pnl_pct", "signal_raw"}
    features = [c for c in df.columns if c not in exclude]

    rows = []
    for feat in features:
        ser = df[feat]
        # Try convert booleans and numerics
        if ser.dtype == object:
            # attempt numeric coercion
            ser_conv = pd.to_numeric(ser, errors="coerce")
        else:
            ser_conv = ser

        n_missing = int(ser_conv.isna().sum())
        n_total = int(len(ser_conv))
        pct_missing = round(n_missing / n_total * 100, 3)
        n_unique = int(ser_conv.nunique(dropna=True))

        stats = {
            "feature": feat,
            "n_total": n_total,
            "n_missing": n_missing,
            "pct_missing": pct_missing,
            "n_unique": n_unique,
        }

        if is_number_series(ser_conv):
            arr = ser_conv.astype(float)
            stats.update({
                "mean": float(np.nanmean(arr)),
                "std": float(np.nanstd(arr, ddof=1)),
                "min": float(np.nanmin(arr)),
                "max": float(np.nanmax(arr)),
                "variance": float(np.nanvar(arr, ddof=1)),
            })
            # Pearson corr with label
            try:
                if arr.isna().all():
                    corr = None
                else:
                    corr = float(arr.corr(y))
            except Exception:
                corr = None
            stats["pearson_corr_with_target"] = corr if corr is not None and not math.isnan(corr) else None

            # Per-feature AUC (if variance exists)
            try:
                if arr.nunique(dropna=True) <= 1:
                    auc = None
                else:
                    mask = ~arr.isna()
                    if mask.sum() < 10:
                        auc = None
                    else:
                        auc = float(roc_auc_score(y[mask], arr[mask]))
            except Exception:
                auc = None
            stats["univariate_auc"] = auc
        else:
            # Non-numeric: attempt binary classification stats
            stats.update({"mean": None, "std": None, "min": None, "max": None, "variance": None})
            stats["pearson_corr_with_target"] = None
            stats["univariate_auc"] = None

        rows.append(stats)

    # Save results
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    pd.DataFrame(rows).sort_values(by=["univariate_auc"], ascending=False).to_csv(OUT_CSV, index=False)

    # Print top features by AUC and by correlation
    dfres = pd.DataFrame(rows)
    df_auc = dfres[dfres["univariate_auc"].notna()].sort_values("univariate_auc", ascending=False)
    df_corr = dfres[dfres["pearson_corr_with_target"].notna()].sort_values("pearson_corr_with_target", key=lambda s: s.abs(), ascending=False)

    print("\nTop features by univariate AUC:")
    for i, r in df_auc.head(10).iterrows():
        print(f"  {r['feature']:30} auc={r['univariate_auc']:.4f} missing={r['pct_missing']}% uniq={r['n_unique']}")

    print("\nTop features by absolute Pearson correlation with target:")
    for i, r in df_corr.head(10).iterrows():
        print(f"  {r['feature']:30} corr={r['pearson_corr_with_target']:.4f} missing={r['pct_missing']}% uniq={r['n_unique']}")

    print(f"\nDiagnostics saved: {OUT_JSON}, {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
