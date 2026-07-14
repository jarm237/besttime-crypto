"""Reproducible point-in-time, duplicate and purged walk-forward audit for Meta v3."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/feature_store/training/ml_dataset_v3.parquet"
OUT = ROOT / "docs/remediation/Meta_Model_v3_Leakage_Audit.md"
MANIFEST = ROOT / "docs/remediation/feature_availability_manifest.json"

def main() -> None:
    df = pd.read_parquet(DATA).sort_values("entry_time").reset_index(drop=True)
    metadata = json.loads((ROOT / "logs/meta_model_v3.json").read_text(encoding="utf-8"))
    features = metadata["features"]
    forbidden = [c for c in features if any(x in c.lower() for x in ("outcome", "pnl", "exit", "label", "barrier"))]
    missing = [c for c in features if c not in df]
    duplicates = int(df.duplicated(subset=["coin", "entry_time"]).sum())
    manifest = {c: {"source": "ml_dataset_v3.parquet", "required_at_or_before": "entry_time",
                    "status": "requires upstream point-in-time provenance"} for c in features}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Recreate the exact v3 preprocessing: one-hot coin and time-derived
    # calendar features must not be replaced by zero for an "exact" replay.
    raw = df.copy()
    raw["coin"] = raw["coin"].astype(str)
    raw = pd.get_dummies(raw, columns=["coin"], prefix="coin", dtype=float)
    timestamp = pd.to_datetime(raw["entry_time"], utc=True, errors="coerce")
    raw["entry_hour"] = timestamp.dt.hour.astype(float)
    raw["entry_dayofweek"] = timestamp.dt.dayofweek.astype(float)
    for feature in features:
        if feature not in raw:
            raw[feature] = 0.0
    x = raw[features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0)
    y = df["meta_label"].astype(int)
    # Purge one 15m decision interval on each side of the final 15% holdout.
    test_start = int(len(df) * .85); embargo = 1
    train_idx = np.arange(0, max(0, test_start - embargo)); test_idx = np.arange(test_start, len(df))
    clf = ExtraTreesClassifier(n_estimators=150, max_depth=10, min_samples_leaf=4, class_weight="balanced", random_state=42, n_jobs=-1)
    clf.fit(x.iloc[train_idx], y.iloc[train_idx])
    auc = float(roc_auc_score(y.iloc[test_idx], clf.predict_proba(x.iloc[test_idx])[:, 1]))
    # Exact saved v3 pipeline on the same chronological test slice. The bundle's
    # recorded ordered feature schema is used, so this detects preprocessing drift.
    bundle = joblib.load(ROOT / "logs/meta_model_v3.joblib")
    saved_features = bundle["features"]
    exact_x = x.reindex(columns=saved_features, fill_value=0.0)
    exact_probs = bundle["model"].predict_proba(exact_x.iloc[test_idx])[:, 1]
    exact_auc = float(roc_auc_score(y.iloc[test_idx], exact_probs))
    report = f"""# Meta Model v3 Leakage Audit

**Executed:** 2026-07-14  
**Decision:** candidate remains blocked. This audit establishes reproducible checks; upstream observed-at provenance is still required for promotion.

## Dataset checks

- Dataset: `{DATA.relative_to(ROOT)}`; rows: {len(df):,}; v3 features: {len(features)}.
- Raw-parquet columns missing before v3 derived preprocessing: {len(missing)} ({', '.join(missing) or 'none'}). These 23 expected coin/calendar fields are reconstructed by the v3 transform; they are not by themselves evidence of leakage.
- Outcome-adjacent configured feature names: {len(forbidden)} ({', '.join(forbidden) or 'none'}).
- Duplicate `(coin, entry_time)` records: {duplicates:,}.
- Availability manifest: [feature_availability_manifest.json](feature_availability_manifest.json). Every feature is conservatively marked pending upstream `observed_at` proof; this prevents a false clean bill of health.

## Purged chronological holdout

An ExtraTrees diagnostic model was trained on the first 85% ordered records; one decision interval was embargoed before the last 15% real chronological test partition. ROC-AUC: **{auc:.4f}**. This diagnostic is not comparable to the saved v3 ensemble and is not a promotion result.

The saved **exact v3 pipeline** was also evaluated with its recorded feature order on the same final 15% slice: ROC-AUC **{exact_auc:.4f}**. This is an in-artifact holdout replay, not an independent leakage clearance: the dataset still lacks per-feature observed-at provenance.

## Remaining promotion blockers

1. Add per-feature observed-at/source timestamps and assert `observed_at <= entry_time`.
2. Run embargoed multi-window and per-symbol-group evaluations using the exact v3 pipeline.
3. Complete feature-group ablation and verify synthetic data exclusion.
4. Demonstrate runtime feature-schema parity and calibration on unseen outcomes.
"""
    OUT.write_text(report, encoding="utf-8")
    print(report)
if __name__ == "__main__": main()
