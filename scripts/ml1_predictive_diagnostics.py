"""
scripts/ml1_predictive_diagnostics.py

Executes Phase C: Comprehensive Predictive Diagnostics for M4-ML1.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import brier_score_loss, roc_auc_score

with open("data/historical/quality_reports/m4_ml1_pilot_results.json", "r") as f:
    pilot_data = json.load(f)

oof_preds = pilot_data["purged_walk_forward_evaluation"]["predictions"]
df = pd.DataFrame(oof_preds)

print("=== 1. PREDICTED PROBABILITY DISTRIBUTION ===")
probs = df["pred_probability"].values
print(f"Count: {len(probs)}")
print(f"Mean: {np.mean(probs):.4f}, Std: {np.std(probs):.4f}")
print(f"Min: {np.min(probs):.4f}, 25%: {np.percentile(probs, 25):.4f}, Median: {np.median(probs):.4f}, 75%: {np.percentile(probs, 75):.4f}, Max: {np.max(probs):.4f}")

print("\n=== 2. WIN-RATE CALIBRATION & BRIER SCORE COMPARISON ===")
# Constant-probability baseline fitted on training data:
# Train win rate across folds was ~26.77%
train_win_rate = pilot_data["dataset_manifest"]["class_balance_win_pct"] / 100.0
y_true = df["actual_label"].values

brier_model = brier_score_loss(y_true, probs)
brier_baseline = brier_score_loss(y_true, np.full_like(probs, train_win_rate))
print(f"Model Brier Score: {brier_model:.4f}")
print(f"Constant Training Baseline Brier Score: {brier_baseline:.4f}")
print(f"Brier Skill Score (BSS): {1.0 - (brier_model / brier_baseline):.4f} (positive means better than naive baseline)")

# Calibration bins
bins = [0.15, 0.20, 0.25, 0.30, 0.35, 1.0]
df["prob_bin"] = pd.cut(df["pred_probability"], bins=bins)
calib_grp = df.groupby("prob_bin", observed=False).agg(
    count=("actual_label", "count"),
    mean_pred=("pred_probability", "mean"),
    realized_win_rate=("actual_label", "mean"),
    mean_net_pnl=("net_pnl_14bps", "mean"),
    sum_net_pnl=("net_pnl_14bps", "sum"),
)
print("\nCalibration by Probability Bin:")
print(calib_grp)

print("\n=== 3. NET PAYOFF DISTRIBUTION BY PREDICTION QUANTILES ===")
df["quantile"] = pd.qcut(df["pred_probability"], q=4, labels=["Q1 (Lowest)", "Q2", "Q3", "Q4 (Highest)"])
quantile_grp = df.groupby("quantile", observed=False).agg(
    trades=("actual_label", "count"),
    win_rate=("actual_label", lambda x: round(np.mean(x) * 100, 1)),
    mean_pnl=("net_pnl_14bps", "mean"),
    median_pnl=("net_pnl_14bps", "median"),
    sum_pnl=("net_pnl_14bps", "sum"),
    min_pnl=("net_pnl_14bps", "min"),
    max_pnl=("net_pnl_14bps", "max"),
)
print(quantile_grp)

print("\n=== 4. TRADE ACCEPTANCE VS REJECTED TRADE PAYOFF ===")
acc = df[df["accepted"]]
rej = df[~df["accepted"]]
print(f"Accepted Trades: {len(acc)} | Wins: {sum(acc['actual_label'] == 1)} ({np.mean(acc['actual_label'])*100:.1f}%) | Net PnL: ${acc['net_pnl_14bps'].sum():.2f} | Exp: ${acc['net_pnl_14bps'].mean():.2f}")
print(f"Rejected Trades: {len(rej)} | Wins: {sum(rej['actual_label'] == 1)} ({np.mean(rej['actual_label'])*100:.1f}%) | Net PnL: ${rej['net_pnl_14bps'].sum():.2f} | Exp: ${rej['net_pnl_14bps'].mean():.2f}")

print("\n=== 5. CONTRIBUTION OF LARGEST WINNERS ===")
top_10_winners = df.sort_values(by="net_pnl_14bps", ascending=False).head(10)
print("Top 10 Largest Winners in 2025 Validation:")
for idx, r in top_10_winners.iterrows():
    print(f"  {r['symbol']} {r['entry_time']} | Net PnL: ${r['net_pnl_14bps']:.2f} | Pred Prob: {r['pred_probability']:.4f} | Accepted: {r['accepted']}")

# Check if any top winners were rejected
rej_winners = rej[rej["actual_label"] == 1]
print("\nRejected Winners:")
for idx, r in rej_winners.iterrows():
    print(f"  {r['symbol']} {r['entry_time']} | Net PnL: ${r['net_pnl_14bps']:.2f} | Pred Prob: {r['pred_probability']:.4f}")

print("\n=== 6. VARIATION BY ASSET AND FOLD ===")
asset_fold_grp = df.groupby(["fold_id", "symbol"]).agg(
    trades=("actual_label", "count"),
    accepted=("accepted", "sum"),
    win_rate=("actual_label", lambda x: round(np.mean(x) * 100, 1)),
    sum_net_pnl=("net_pnl_14bps", "sum"),
    mean_prob=("pred_probability", "mean"),
)
print(asset_fold_grp)

print("\n=== 7. CORRELATION BETWEEN PREDICTED PROBABILITY AND REALIZED NET PNL ===")
spearman_corr, sp_pval = stats.spearmanr(df["pred_probability"], df["net_pnl_14bps"])
pearson_corr, pe_pval = stats.pearsonr(df["pred_probability"], df["net_pnl_14bps"])
print(f"Pearson Correlation (prob vs net PnL): {pearson_corr:.4f} (p={pe_pval:.4f})")
print(f"Spearman Rank Correlation: {spearman_corr:.4f} (p={sp_pval:.4f})")
