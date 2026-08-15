#!/usr/bin/env python3
"""HMR-V2.4.3: Baseline Economic Model Training.

Implements temporal walk-forward (V2.4.2) and runs two baseline classifiers
(LogisticRegression, GradientBoostingClassifier) on G1-B and G1-D datasets.

Primary question: Is P(Gross>30 @72) learnable from PIT context features?

Success criterion: NOT AUC > threshold.
Success criterion: OOS gross EV in top-selected cohort >= 25 bps.

Outputs:
  v2_4_economic_models/classifier_30/
    walk_forward_G1B.json
    walk_forward_G1D.json
    ablation_G1B.json
    ablation_G1D.json
    report.md
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COST_BPS  = 15.0
COST_FRAC = COST_BPS / 10_000.0
BARS_72   = 72
BAR_MINS  = 15          # 15-minute bars
MATURE_BUFFER = pd.Timedelta(minutes=BAR_MINS * BARS_72)

# ── Feature groups ────────────────────────────────────────────────────────────
FEATURE_GROUPS = {
    "A_MARKET_CONTEXT":   ["trend_regime_enc", "volatility_regime_enc"],
    "B_EVENT_GEOMETRY":   ["break_distance_atr", "candle_body_atr"],
    "C_STRUCTURAL":       ["room_to_structure_atr"],
    "D_WHIPSAW_CONTEXT":  ["recent_cross_count_16bars"],
    "E_LEGACY":           ["raw_model_score"],
    "F_OPTIONAL_MICRO":   ["volume_ratio"],
}
ALL_FEATURES = [f for g in FEATURE_GROUPS.values() for f in g]

# ── Temporal walk-forward folds ───────────────────────────────────────────────
FOLDS = [
    {"id": "F1",
     "train": ("2023-01-01", "2023-06-30"),
     "valid": ("2023-07-01", "2023-12-31")},
    {"id": "F2",
     "train": ("2023-01-01", "2023-12-31"),
     "valid": ("2024-01-01", "2024-06-30")},
    {"id": "F3",
     "train": ("2023-01-01", "2024-06-30"),
     "valid": ("2024-07-01", "2024-12-31")},
]

# ── Economic evaluation percentile cuts ──────────────────────────────────────
PCTS = [0.01, 0.025, 0.05, 0.10, 0.20]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _econ(rets: pd.Series) -> Dict[str, Any]:
    n = len(rets.dropna())
    if n == 0:
        return {"n": 0}
    r = rets.dropna()
    gross_ev = float(r.mean() * 10_000)
    net_ev   = gross_ev - COST_BPS
    return {
        "n": n,
        "mean_bps": round(gross_ev, 2),
        "median_bps": round(float(r.median() * 10_000), 2),
        "gross_gt30_rate": round(float((r > 0.003).mean()), 4),
        "gross_gt40_rate": round(float((r > 0.004).mean()), 4),
        "gross_ev_bps": round(gross_ev, 2),
        "net_ev_bps": round(net_ev, 2),
        "profit_factor": round(float(r[r > 0].sum() / max(abs(r[r < 0].sum()), 1e-8)), 3),
    }


def _econ_top(scores: pd.Series, rets: pd.Series, pct: float) -> Dict[str, Any]:
    n = len(scores)
    k = max(1, int(n * pct))
    top_idx = scores.nlargest(k).index
    return _econ(rets.loc[top_idx])


def _roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    try:
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return 0.5


def _pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score
    try:
        return float(average_precision_score(y_true, y_score))
    except Exception:
        return 0.0


def _brier(y_true: np.ndarray, y_score: np.ndarray) -> float:
    return float(np.mean((y_score - y_true) ** 2))


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

REGIME_ENC = {"uptrend": 1, "downtrend": 0,
               "high_vol": 1, "low_vol": 0,
               "BUY": 1, "SELL": 0}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["trend_regime_enc"] = df["trend_regime"].map(
        {"uptrend": 1, "downtrend": 0, "": 0}).fillna(0).astype(float)
    df["volatility_regime_enc"] = df["volatility_regime"].map(
        {"high_vol": 1, "low_vol": 0, "": 0}).fillna(0).astype(float)
    # Clip extreme raw_model_score NaN → 0 for now; ablation will compare vs dropped
    df["raw_model_score"] = pd.to_numeric(df["raw_model_score"], errors="coerce").fillna(0.0)
    df["volume_ratio"]    = pd.to_numeric(df["volume_ratio"],    errors="coerce").fillna(1.0)
    df["gross_return_72"] = pd.to_numeric(df["gross_return_72"], errors="coerce")
    df["gross_gt30_72"]   = pd.to_numeric(df["gross_gt30_72"],   errors="coerce")
    return df


def fold_split(df: pd.DataFrame, fold: Dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train_df, valid_df) with maturity gate applied."""
    train_start = pd.Timestamp(fold["train"][0], tz="UTC")
    train_end   = pd.Timestamp(fold["train"][1] + " 23:59:59", tz="UTC")
    valid_start = pd.Timestamp(fold["valid"][0], tz="UTC")
    valid_end   = pd.Timestamp(fold["valid"][1] + " 23:59:59", tz="UTC")

    # Maturity gate: event must be at least BARS_72 bars before fold boundary
    train_mature = train_end - MATURE_BUFFER
    valid_mature = valid_end - MATURE_BUFFER

    train = df[(df["timestamp"] >= train_start) &
               (df["timestamp"] <= train_mature) &
               df["gross_gt30_72"].notna()].copy()
    valid = df[(df["timestamp"] >= valid_start) &
               (df["timestamp"] <= valid_mature) &
               df["gross_gt30_72"].notna()].copy()
    return train, valid


# ---------------------------------------------------------------------------
# Model training utilities
# ---------------------------------------------------------------------------

def get_models():
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    return {
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=500, C=0.1, class_weight="balanced",
                                       random_state=42)),
        ]),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, min_samples_leaf=30, random_state=42
        ),
    }


def train_eval_fold(model_name: str, model,
                    train: pd.DataFrame, valid: pd.DataFrame,
                    features: List[str]) -> Dict[str, Any]:
    X_tr = train[features].fillna(0).values
    y_tr = train["gross_gt30_72"].values.astype(int)
    X_va = valid[features].fillna(0).values
    y_va = valid["gross_gt30_72"].values.astype(int)
    rets = valid["gross_return_72"]

    import copy
    m = copy.deepcopy(model)
    m.fit(X_tr, y_tr)
    scores = m.predict_proba(X_va)[:, 1]

    result: Dict[str, Any] = {
        "model": model_name,
        "train_n": len(train),
        "train_pos": int(y_tr.sum()),
        "valid_n": len(valid),
        "valid_pos": int(y_va.sum()),
        "roc_auc": round(_roc_auc(y_va, scores), 4),
        "pr_auc":  round(_pr_auc(y_va, scores), 4),
        "brier":   round(_brier(y_va, scores), 4),
        "baseline_economics": _econ(rets),
        "top_percentile_economics": {},
    }
    sc = pd.Series(scores, index=valid.index)
    for pct in PCTS:
        result["top_percentile_economics"][f"top_{int(pct*100)}pct"] = _econ_top(sc, rets, pct)

    return result


# ---------------------------------------------------------------------------
# Walk-forward runner
# ---------------------------------------------------------------------------

def run_walk_forward(df: pd.DataFrame, arch_label: str, features: List[str],
                     run_label: str = "") -> Dict[str, Any]:
    models = get_models()
    all_results: Dict[str, Any] = {
        "architecture": arch_label,
        "run_label": run_label,
        "features": features,
        "folds": {}
    }

    for fold in FOLDS:
        train, valid = fold_split(df, fold)
        if len(train) < 50 or len(valid) < 20:
            print(f"      Fold {fold['id']}: insufficient data (train={len(train)}, valid={len(valid)})")
            continue
        fold_results: Dict[str, Any] = {"train_n": len(train), "valid_n": len(valid)}
        for mname, model in models.items():
            try:
                fold_results[mname] = train_eval_fold(mname, model, train, valid, features)
            except Exception as e:
                fold_results[mname] = {"error": str(e)}
        all_results["folds"][fold["id"]] = fold_results
        for mname in models:
            if mname in fold_results and "roc_auc" in fold_results[mname]:
                r = fold_results[mname]
                print(f"      {fold['id']} {mname}: "
                      f"AUC={r['roc_auc']:.3f}  "
                      f"Top5%_GrossEV={r['top_percentile_economics'].get('top_5pct',{}).get('gross_ev_bps','?'):+.1f} bps  "
                      f"Top10%={r['top_percentile_economics'].get('top_10pct',{}).get('gross_ev_bps','?'):+.1f} bps")

    return all_results


# ---------------------------------------------------------------------------
# Feature ablation
# ---------------------------------------------------------------------------

def run_ablation(df: pd.DataFrame, arch_label: str) -> Dict[str, Any]:
    print(f"    Feature ablation for {arch_label}...")
    ablation_results: Dict[str, Any] = {}

    # Baseline: all features
    ablation_results["ALL"] = run_walk_forward(df, arch_label, ALL_FEATURES, "ALL")

    # Group ablations
    for group_name, group_feats in FEATURE_GROUPS.items():
        remaining = [f for f in ALL_FEATURES if f not in group_feats]
        if len(remaining) < 2:
            continue
        label = f"MINUS_{group_name}"
        print(f"      Running {label}...")
        ablation_results[label] = run_walk_forward(df, arch_label, remaining, label)

    return ablation_results


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def summarise_fold_metric(results: Dict, model: str, pct_key: str, metric: str) -> str:
    vals = []
    for fid, fold_data in results.get("folds", {}).items():
        m = fold_data.get(model, {})
        v = m.get("top_percentile_economics", {}).get(pct_key, {}).get(metric)
        if v is not None:
            vals.append(v)
    if not vals:
        return "—"
    mean = np.mean(vals)
    return f"{mean:+.1f}" if metric.endswith("bps") else f"{mean:.3f}"


def build_report(wf_b: Dict, wf_d: Dict, abl_b: Dict, abl_d: Dict) -> str:
    lines = ["# HMR-V2.4.3: Baseline Economic Model — Walk-Forward Results\n"]

    # Economic summary table (GBT, top 5% and 10%)
    lines += [
        "## 1. OOS Economic Summary (GradientBoosting — mean across folds)\n",
        "| Architecture | Top 1% GrossEV | Top 5% GrossEV | Top 10% GrossEV | Top 20% GrossEV |",
        "|:-------------|:--------------:|:--------------:|:---------------:|:---------------:|",
    ]
    for arch, wf in [("G1-B", wf_b), ("G1-D", wf_d)]:
        cells = [summarise_fold_metric(wf, "GradientBoosting", f"top_{int(p*100)}pct", "gross_ev_bps")
                 for p in PCTS]
        lines.append(f"| {arch} | " + " | ".join(cells) + " |")

    # AUC table
    lines += [
        "\n## 2. OOS ROC-AUC (mean across folds)\n",
        "| Architecture | LogisticRegression | GradientBoosting |",
        "|:-------------|:------------------:|:----------------:|",
    ]
    for arch, wf in [("G1-B", wf_b), ("G1-D", wf_d)]:
        lr_auc  = summarise_fold_metric(wf, "LogisticRegression", "top_5pct", "gross_ev_bps")
        gbt_auc = summarise_fold_metric(wf, "GradientBoosting",   "top_5pct", "gross_ev_bps")
        # ROC-AUC from fold data
        lr_roc  = np.mean([wf["folds"][f].get("LogisticRegression", {}).get("roc_auc", 0)
                           for f in wf["folds"]]) if wf.get("folds") else 0.0
        gbt_roc = np.mean([wf["folds"][f].get("GradientBoosting", {}).get("roc_auc", 0)
                           for f in wf["folds"]]) if wf.get("folds") else 0.0
        lines.append(f"| {arch} | {lr_roc:.3f} | {gbt_roc:.3f} |")

    # Ablation summary
    lines += ["\n## 3. Feature Ablation Summary (GradientBoosting Top 5% GrossEV, mean)\n"]
    lines.append("| Feature Group Removed | G1-B GrossEV | G1-D GrossEV |")
    lines.append("|:----------------------|:------------:|:------------:|")
    for key in list(abl_b.keys()):
        b_val = summarise_fold_metric(abl_b[key], "GradientBoosting", "top_5pct", "gross_ev_bps")
        d_val = summarise_fold_metric(abl_d.get(key, {}), "GradientBoosting", "top_5pct", "gross_ev_bps")
        label = key.replace("MINUS_", "").replace("_", " ")
        lines.append(f"| {label} | {b_val} | {d_val} |")

    # Economic gate verdict
    lines += ["\n## 4. Economic Gate Verdicts\n"]
    for arch, wf in [("G1-B", wf_b), ("G1-D", wf_d)]:
        top5_evs = []
        for fid, fd in wf.get("folds", {}).items():
            v = fd.get("GradientBoosting", {}).get(
                "top_percentile_economics", {}).get("top_5pct", {}).get("gross_ev_bps")
            if v is not None:
                top5_evs.append(v)
        if top5_evs:
            mean_ev = np.mean(top5_evs)
            gate = ("ECONOMICALLY_PROMISING" if mean_ev >= 25
                    else "MARGINAL" if mean_ev >= 15
                    else "REJECT")
            lines.append(f"* **{arch}** Top-5% mean GrossEV = {mean_ev:+.1f} bps → `{gate}`")
        else:
            lines.append(f"* **{arch}** insufficient data for verdict")

    lines += [
        "\n> Success criterion: OOS gross EV in top-selected cohort >= 25 bps.",
        "> NOT: AUC > threshold.",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args) -> int:
    base = REPO_ROOT / "research/historical_market_replay_v2/v2_4_economic_models"
    ds   = base / "datasets"

    path_b = ds / "g1_b_pre2025.parquet"
    path_d = ds / "g1_d_pre2025.parquet"
    for p in [path_b, path_d]:
        if not p.exists():
            print(f"ERROR: Dataset not found: {p}")
            print("  Run hmr_v2_4_1_build_datasets.py first.")
            return 1

    print("HMR-V2.4.3: Baseline Economic Model Training")
    df_b = prepare(pd.read_parquet(path_b))
    df_d = prepare(pd.read_parquet(path_d))
    print(f"  G1-B: {len(df_b)} events, Gross>30: {df_b['gross_gt30_72'].mean():.1%}")
    print(f"  G1-D: {len(df_d)} events, Gross>30: {df_d['gross_gt30_72'].mean():.1%}")

    out = base / "classifier_30"
    out.mkdir(parents=True, exist_ok=True)

    # Walk-forward runs
    print("\n  G1-B Walk-Forward:")
    wf_b = run_walk_forward(df_b, "G1-B", ALL_FEATURES)
    print("\n  G1-D Walk-Forward:")
    wf_d = run_walk_forward(df_d, "G1-D", ALL_FEATURES)

    # Feature ablation
    print("\n  Ablation (G1-B):")
    abl_b = run_ablation(df_b, "G1-B")
    print("\n  Ablation (G1-D):")
    abl_d = run_ablation(df_d, "G1-D")

    # Save
    (out / "walk_forward_G1B.json").write_text(json.dumps(wf_b, indent=2, default=str))
    (out / "walk_forward_G1D.json").write_text(json.dumps(wf_d, indent=2, default=str))
    (out / "ablation_G1B.json").write_text(json.dumps(abl_b, indent=2, default=str))
    (out / "ablation_G1D.json").write_text(json.dumps(abl_d, indent=2, default=str))

    report = build_report(wf_b, wf_d, abl_b, abl_d)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"\n  ✓ Saved report: {out / 'report.md'}")
    print("\n  GATE: V2_4_3_BASELINE_MODELS_COMPLETE = PASS")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2.4.3: Baseline Economic Model Training")
    return p


if __name__ == "__main__":
    # Check dependencies
    try:
        import sklearn
    except ImportError:
        print("ERROR: scikit-learn not installed. Run: pip install scikit-learn")
        sys.exit(1)
    sys.exit(run(_parser().parse_args()))
