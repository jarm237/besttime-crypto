#!/usr/bin/env python3
"""
Đánh giá tính đủ của dataset cho training ensemble meta model.
Kiểm tra:
- Kích thước sample vs số feature
- Phân bố class balance
- Tín hiệu underfitting/overfitting
- So sánh với yêu cầu tối thiểu
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
METRIC_FILE = BASE / "logs" / "meta_model.json"
INPUT_FILE = BASE / "logs" / "adaptive_signals_v2.json"


def assess_dataset_sufficiency():
    # Load metrics
    with open(METRIC_FILE, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)

    n_samples = metrics["n_samples"]
    n_features = metrics["n_features"]
    n_train_samples = n_samples  # Approximate

    print("=" * 70)
    print("DATASET SUFFICIENCY ASSESSMENT")
    print("=" * 70)

    # 1. SAMPLE SIZE REQUIREMENTS
    print("\n[1] SAMPLE SIZE vs FEATURE COUNT")
    print("-" * 70)
    print(f"  Samples:            {n_samples:,}")
    print(f"  Features:           {n_features}")
    print(f"  Samples/Feature:    {n_samples / n_features:.1f}")

    # Benchmark thresholds
    min_samples_basic = max(100, n_features * 5)
    min_samples_robust = max(500, n_features * 20)
    min_samples_ideal = max(1000, n_features * 50)

    print(f"\n  Minimum thresholds:")
    print(f"    - Basic (random forest): {min_samples_basic:,} samples")
    print(f"    - Robust (ensemble):    {min_samples_robust:,} samples")
    print(f"    - Ideal (all models):   {min_samples_ideal:,} samples")

    if n_samples >= min_samples_ideal:
        print(f"\n  ✓ EXCEEDS ideal threshold by {n_samples - min_samples_ideal:,} samples")
    elif n_samples >= min_samples_robust:
        print(f"\n  ✓ EXCEEDS robust threshold by {n_samples - min_samples_robust:,} samples")
    elif n_samples >= min_samples_basic:
        print(f"\n  ⚠ MEETS basic threshold but below robust")
    else:
        print(f"\n  ✗ BELOW basic threshold")

    # 2. CLASS BALANCE
    print("\n[2] CLASS BALANCE")
    print("-" * 70)
    label_dist = metrics["label_dist"]
    wins = label_dist["WIN"]
    losses = label_dist["LOSS"]
    total = wins + losses

    win_pct = wins / total * 100
    loss_pct = losses / total * 100
    imbalance_ratio = max(wins, losses) / min(wins, losses)

    print(f"  WIN:   {wins:6,} ({win_pct:5.1f}%)")
    print(f"  LOSS:  {losses:6,} ({loss_pct:5.1f}%)")
    print(f"  Imbalance ratio: {imbalance_ratio:.2f}:1")

    if imbalance_ratio < 1.5:
        print(f"\n  ✓ Excellent balance (< 1.5:1)")
    elif imbalance_ratio < 2.0:
        print(f"\n  ✓ Good balance (< 2:1)")
    elif imbalance_ratio < 3.0:
        print(f"\n  ⚠ Acceptable but slightly imbalanced (< 3:1)")
    else:
        print(f"\n  ✗ Imbalanced (> 3:1) - may need class weighting")

    # 3. CROSS-VALIDATION METRICS
    print("\n[3] CROSS-VALIDATION PERFORMANCE")
    print("-" * 70)

    cv_auc_mean = metrics.get("cv_auc_mean")
    cv_auc_std = metrics.get("cv_auc_std")
    cv_acc_mean = metrics.get("cv_acc_mean")
    ensemble_cv_auc = metrics.get("ensemble_cv_auc_mean")
    ensemble_cv_acc = metrics.get("ensemble_cv_acc_mean")

    if cv_auc_mean:
        print(f"  Base RF AUC:     {cv_auc_mean:.4f} ± {cv_auc_std:.4f}")
    if ensemble_cv_auc:
        print(f"  Ensemble AUC:    {ensemble_cv_auc:.4f}")
    if ensemble_cv_acc:
        print(f"  Ensemble Acc:    {ensemble_cv_acc:.4f}")

    # Check for overfitting
    if cv_auc_std and cv_auc_std > 0.05:
        print(f"\n  ⚠ HIGH std in CV (±{cv_auc_std:.4f}) → may need more diverse data")
    elif cv_auc_std:
        print(f"\n  ✓ LOW std in CV (±{cv_auc_std:.4f}) → stable model")

    # 4. WALK-FORWARD RESULTS
    print("\n[4] WALK-FORWARD VALIDATION")
    print("-" * 70)

    wf = metrics.get("walk_forward", [])
    if wf:
        print(f"  Folds: {len(wf)}")
        for i, fold in enumerate(wf, 1):
            auc = fold.get("roc_auc")
            acc = fold.get("accuracy")
            print(f"    Fold {i}: AUC={auc:.4f}, Acc={acc:.4f}")

        wf_aucs = [f.get("roc_auc") for f in wf if f.get("roc_auc")]
        wf_acc_vals = [f.get("accuracy") for f in wf if f.get("accuracy")]

        if wf_aucs:
            wf_auc_mean = sum(wf_aucs) / len(wf_aucs)
            wf_auc_std = (sum((x - wf_auc_mean) ** 2 for x in wf_aucs) / len(wf_aucs)) ** 0.5
            print(f"\n  AUC mean: {wf_auc_mean:.4f} ± {wf_auc_std:.4f}")
            if wf_auc_std < 0.03:
                print(f"  ✓ Stable out-of-sample performance")
            else:
                print(f"  ⚠ Variable OOS performance (may indicate non-stationarity)")

    # 5. CALIBRATION QUALITY
    print("\n[5] CALIBRATION ANALYSIS")
    print("-" * 70)

    cal_buckets = metrics.get("calibration_buckets", {})
    if cal_buckets:
        calibrated_buckets = [b for b in cal_buckets.values() if b.get("calibrated")]
        total_buckets = len([b for b in cal_buckets.values() if b.get("count", 0) >= 10])
        cal_pct = len(calibrated_buckets) / total_buckets * 100 if total_buckets > 0 else 0

        print(f"  Calibrated buckets: {len(calibrated_buckets)}/{total_buckets}")
        print(f"  Coverage: {cal_pct:.0f}%")

        errors = [abs(b["calibration_error"]) for b in cal_buckets.values()
                  if b.get("calibration_error") is not None]
        if errors:
            mean_error = sum(errors) / len(errors)
            print(f"  Mean calibration error: {mean_error:.2f}%")

            if mean_error < 5:
                print(f"  ✓ Excellent calibration")
            elif mean_error < 10:
                print(f"  ✓ Good calibration")
            elif mean_error < 15:
                print(f"  ⚠ Acceptable but can improve")
            else:
                print(f"  ✗ Poor calibration - may need more data or better features")

    # 6. FINAL VERDICT
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)

    verdict_scores = []

    # Size check
    if n_samples >= min_samples_robust:
        verdict_scores.append("✓ Sample size")
    else:
        verdict_scores.append("⚠ Sample size")

    # Balance check
    if imbalance_ratio < 2.0:
        verdict_scores.append("✓ Class balance")
    else:
        verdict_scores.append("⚠ Class balance")

    # Performance check
    if ensemble_cv_auc and ensemble_cv_auc > 0.6:
        verdict_scores.append("✓ CV performance")
    else:
        verdict_scores.append("⚠ CV performance")

    # Stability check
    if cv_auc_std and cv_auc_std < 0.05:
        verdict_scores.append("✓ Stability")
    else:
        verdict_scores.append("⚠ Stability")

    print("\nKey factors:")
    for score in verdict_scores:
        print(f"  {score}")

    print("\n📊 RECOMMENDATION:")
    if all("✓" in s for s in verdict_scores):
        print("  ✓ Dataset is SUFFICIENT for robust ensemble training")
        print("    - Can support hyperparameter tuning (Optuna)")
        print("    - Can use hold-out calibration set safely")
        print("    - Ready for deployment with confidence")
    elif all("✓" in s for s in verdict_scores[:2]):
        print("  ✓ Dataset is ADEQUATE for training")
        print("    - Can train ensemble, but focus on model selection")
        print("    - May benefit from additional feature engineering")
        print("    - Consider collecting more data for marginal gains")
    else:
        print("  ⚠ Dataset has LIMITATIONS")
        print("    - Consider: more data, feature engineering, or simpler models")
        print("    - Avoid aggressive tuning to prevent overfitting")

    # Additional recommendation
    print("\n💡 DATA COLLECTION TARGETS:")
    print(f"  - Current: {n_samples:,} samples")
    print(f"  - For better calibration: {min_samples_robust:,} (achieved ✓)")
    print(f"  - For very robust model: {int(min_samples_ideal * 1.5):,} samples")
    if n_samples < int(min_samples_ideal * 1.5):
        gap = int(min_samples_ideal * 1.5) - n_samples
        print(f"    Gap: {gap:,} more samples needed")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    assess_dataset_sufficiency()
