#!/usr/bin/env python3
"""S4-P1C Forecasting CLI: Preflight Verification, 2022 Development, and One-Shot 2023 Screening.

Pre-registration: research/s4_forecast_information_screening/s4_p0_executable_preregistration.md
Frozen commit: 7b5a97becbd6da1249a484ed588133761cc57bd0
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_START,
    indexed_panel,
    load_binance_archives,
    sha256_file,
)
from btc_scraper.research.s4_evaluation import (
    EXPECTED_FROZEN_HASHES,
    EXPECTED_NEURAL_PARAMS,
    EXPECTED_RIDGE_ALPHA,
    SPREAD_THRESHOLD_BPS,
    btc_relative_spread_diagnostics,
    compute_pearson_ic,
    compute_primary_statistics,
    decompose_common_and_relative,
    evaluate_scientific_verdict,
    extreme_day_sensitivity,
    fisher_z_aggregate,
    mincer_zarnowitz_calibration,
    paired_stationary_bootstrap,
    verify_and_load_frozen_artifacts,
)
from btc_scraper.research.s4_forecast import (
    INPUT_ASSETS,
    INPUT_FEATURES,
    INPUT_HOURS,
    LAST_2022_DEV_DECISION,
    LAST_SCREEN_DECISION,
    MAX_TRAINABLE_PARAMETERS,
    RIDGE_ALPHAS,
    S4_PREREGISTRATION_COMMIT,
    UNIVERSE,
    CausalSigmaNormalizer,
    ChronologicalSplitter,
    FeatureScaler,
    ForecastError,
    ProtocolViolationError,
    RidgeBaseline,
    TrainingConfig,
    UnifiedNeuralForecaster,
    build_causal_partitions,
    build_neural_forecaster,
    select_ridge_alpha,
    set_seed,
)


def run_preflight(repo_root: Path, audit_json_path: Path) -> dict[str, object]:
    """Execute preflight technical checks on model architectures, data contracts, and audit evidence."""
    results: dict[str, object] = {
        "preregistration_commit": S4_PREREGISTRATION_COMMIT,
        "mode": "preflight",
        "verdict": "FAIL",
    }

    # 1. Audit artifact check
    if not audit_json_path.is_file():
        raise ForecastError(f"Dataset audit artifact not found: {audit_json_path}")
    audit_data = json.loads(audit_json_path.read_text(encoding="utf-8"))

    if audit_data.get("verdict") != "DATASET_READY":
        raise ForecastError(f"Dataset audit verdict is not DATASET_READY: {audit_data.get('verdict')}")
    if audit_data.get("preregistration_commit") != S4_PREREGISTRATION_COMMIT:
        raise ForecastError(f"Pre-registration commit mismatch in audit JSON: {audit_data.get('preregistration_commit')}")

    source_files = audit_data.get("source_selection", {}).get("source_files", [])
    if len(source_files) != 104 or not all(s.get("sidecar_verified") for s in source_files):
        raise ForecastError(f"Invalid canonical source file verification in audit: {len(source_files)} files")

    screen_phase = next(
        (p for p in audit_data.get("effective_dataset", []) if p.get("phase") == "2023 Screen"),
        {},
    )
    common_dates_2023 = screen_phase.get("common_complete_case_decisions", 0)
    if common_dates_2023 < 300:
        raise ForecastError(f"Insufficient 2023 common dates: {common_dates_2023} < 300")

    results["dataset_audit"] = {
        "status": "PASS",
        "verdict": audit_data["verdict"],
        "canonical_archives_count": len(source_files),
        "common_dates_2023": common_dates_2023,
    }

    # 2. Neural forecaster verification
    model = build_neural_forecaster(seed=42)
    param_count = model.count_parameters()
    if param_count > MAX_TRAINABLE_PARAMETERS:
        raise ForecastError(f"Neural parameter count {param_count} exceeds budget {MAX_TRAINABLE_PARAMETERS}")

    # Synthetic forward test
    x_synth = torch.randn(2, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES)
    out_synth = model(x_synth)
    if out_synth.shape != (2, INPUT_ASSETS):
        raise ForecastError(f"Neural forward output shape mismatch: {out_synth.shape} != (2, 4)")

    # Synthetic backward test (finite gradients)
    loss = nn.functional.mse_loss(out_synth, torch.zeros(2, INPUT_ASSETS))
    loss.backward()
    for name, param in model.named_parameters():
        if param.grad is None or not torch.isfinite(param.grad).all():
            raise ForecastError(f"Neural backward produced non-finite gradients on {name}")

    # Determinism test
    model_2 = build_neural_forecaster(seed=42)
    out_synth_2 = model_2(x_synth)
    if not torch.allclose(out_synth, out_synth_2, rtol=1e-6, atol=1e-6):
        raise ForecastError("Neural forecaster initialization is not deterministic")

    results["neural_forecaster"] = {
        "status": "PASS",
        "trainable_parameters": param_count,
        "budget_limit": MAX_TRAINABLE_PARAMETERS,
        "input_shape": [2, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES],
        "output_shape": list(out_synth.shape),
        "gradients_finite": True,
        "deterministic": True,
    }

    # 3. Ridge baseline verification
    ridge = RidgeBaseline(alpha=1.0)
    x_flat = ridge.flatten_tensor(x_synth.detach().numpy())
    if x_flat.shape != (2, INPUT_HOURS * INPUT_ASSETS * INPUT_FEATURES):
        raise ForecastError(f"Ridge flattened shape mismatch: {x_flat.shape}")

    # Synthetic fit and predict
    y_synth = np.zeros((2, INPUT_ASSETS))
    ridge.fit(x_flat, y_synth)
    preds_synth = ridge.predict(x_flat)
    if preds_synth.shape != (2, INPUT_ASSETS):
        raise ForecastError(f"Ridge prediction shape mismatch: {preds_synth.shape}")

    results["ridge_baseline"] = {
        "status": "PASS",
        "flattened_shape": list(x_flat.shape),
        "alpha_grid": list(RIDGE_ALPHAS),
        "predict_shape": list(preds_synth.shape),
    }

    # 4. Chronological folds and purging checks
    folds = ChronologicalSplitter.get_folds()
    purged_counts = {}
    val_counts = {}
    for fold in folds:
        purged = ChronologicalSplitter.get_purged_fit_dates(fold)
        purged_counts[fold.name] = len(purged)
        val_dates = ChronologicalSplitter.get_validation_dates(fold)
        val_counts[fold.name] = len(val_dates)

    full_dev = ChronologicalSplitter.get_full_dev_dates()
    screen_dates = ChronologicalSplitter.get_screen_dates()

    if any(d > LAST_2022_DEV_DECISION for d in full_dev):
        raise ForecastError("2022 full development includes post-2022-12-30 decision")
    if any(d > LAST_SCREEN_DECISION for d in screen_dates):
        raise ForecastError("2023 screen includes post-2023-12-30 decision")

    results["chronological_cv"] = {
        "status": "PASS",
        "folds": [f.name for f in folds],
        "purged_fit_counts": purged_counts,
        "validation_counts": val_counts,
        "full_dev_count": len(full_dev),
        "last_dev_decision": str(full_dev[-1]),
        "screen_count": len(screen_dates),
        "last_screen_decision": str(screen_dates[-1]),
    }

    results["verdict"] = "PASS"
    results["next_step"] = "S4-P1C_ONE_SHOT_2023_SCREENING (ready for authorized execution)"
    return results


def run_development_2022(
    repo_root: Path,
    audit_json_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Execute bounded 2022 development:

    1. Verify audit artifact & pre-registration.
    2. Load canonical Binance Spot archives.
    3. Build complete-case 2022 dataset with 2021 warmup.
    4. Cross-validate Ridge alpha across 4 folds.
    5. Fit final Ridge model on full 2022 dev set.
    6. Fit single shared neural model on full 2022 dev set.
    7. Save frozen artifacts (weights, ridge, scaler, sigma floors, trace).
    8. Reload and verify finite predictions.
    9. Freeze SHA-256 identities and generate evidence report.
    """
    if (output_dir / "neural_forecaster.pt").is_file():
        raise ProtocolViolationError(
            f"Frozen model artifacts already exist in {output_dir}. "
            "Development overwrite is prohibited to preserve frozen checkpoint integrity."
        )

    print("=== S4-P1B: 2022-ONLY DEVELOPMENT & FROZEN MODEL FITTING ===")
    print(f"Pre-registration commit: {S4_PREREGISTRATION_COMMIT}")
    set_seed(42)

    # 1. Audit artifact check
    if not audit_json_path.is_file():
        raise ForecastError(f"Dataset audit artifact not found: {audit_json_path}")
    audit_data = json.loads(audit_json_path.read_text(encoding="utf-8"))
    if audit_data.get("verdict") != "DATASET_READY":
        raise ForecastError(f"Dataset audit verdict is not DATASET_READY: {audit_data.get('verdict')}")

    # 2. Load canonical Binance archives
    raw_root = repo_root / "data/historical/neural_n1/raw/binance_spot_klines_1h"
    print(f"Loading canonical Binance Spot archives from: {raw_root}")
    panels: dict[str, pd.DataFrame] = {}
    sources_summary: list[dict[str, object]] = []
    for symbol in UNIVERSE:
        frame, sources = load_binance_archives(raw_root, symbol)
        panels[symbol] = indexed_panel(frame)
        sources_summary.extend(sources)
        print(f"  [{symbol}] Loaded {len(frame)} hourly bars ({frame['timestamp'].min()} to {frame['timestamp'].max()})")

    # 3. Build complete-case 2022 development dataset with 2021 warmup
    dev_decisions = ChronologicalSplitter.get_full_dev_dates()
    print(f"Building 2022 complete-case partitions ({len(dev_decisions)} nominal decisions, warmup from {AUDIT_START})...")
    partitions = build_causal_partitions(panels, dev_decisions, warmup_start=AUDIT_START)

    if len(partitions.eligible_decisions) != len(dev_decisions):
        raise ForecastError(
            f"Expected {len(dev_decisions)} eligible decisions, got {len(partitions.eligible_decisions)}; "
            f"exclusions: {partitions.excluded_decisions}"
        )

    # Confirm 2021 warmup availability at 2022-01-01 00:00 UTC
    first_dev_ts = pd.Timestamp("2022-01-01", tz="UTC")
    for symbol in UNIVERSE:
        count = partitions.sigma_normalizer.get_completed_count(symbol, first_dev_ts)
        if count != 60:
            raise ForecastError(f"Expected 60 warmup labels for {symbol} at {first_dev_ts}, got {count}")
        latest_c = partitions.sigma_normalizer.get_latest_completion(symbol, first_dev_ts)
        if latest_c > first_dev_ts:
            raise ForecastError(f"Warmup label completion {latest_c} violates cutoff {first_dev_ts}")
    print(f"  Warmup verified: exactly 60 completed labels available per asset at {first_dev_ts}")

    # 4. Cross-validate Ridge alpha across 4 folds
    print("Executing 4-fold Ridge alpha cross-validation...")
    folds = ChronologicalSplitter.get_folds()
    best_alpha, mean_mses, fold_mses = select_ridge_alpha(
        partitions.features,
        partitions.raw_labels,
        partitions.sigma_normalizer,
        folds=folds,
        alphas=RIDGE_ALPHAS,
    )
    print("  Ridge CV results across 4 folds:")
    for alpha in RIDGE_ALPHAS:
        fold_str = ", ".join(f"{f.name}: {fold_mses[f.name][alpha]:.6f}" for f in folds)
        print(f"    alpha={alpha:<7}: mean_MSE={mean_mses[alpha]:.6f} ({fold_str})")
    print(f"  Selected Ridge alpha: {best_alpha}")

    # 5. Fit final Ridge on full 2022 development set
    print("Fitting final Ridge on full 2022 development set...")
    X_dev_raw = np.stack([partitions.features[d] for d in dev_decisions], axis=0)  # [364, 168, 4, 6]
    dev_scaler = FeatureScaler().fit(X_dev_raw)
    X_dev_norm = dev_scaler.transform(X_dev_raw)
    X_dev_flat = RidgeBaseline.flatten_tensor(X_dev_norm)  # [364, 4032]

    dev_sigma_normalizer = CausalSigmaNormalizer(partitions.sigma_normalizer.raw_sigma_df)
    dev_floors = dev_sigma_normalizer.fit_floors(dev_decisions)
    print(f"  Fitted 2022 sigma floors: {dev_floors}")

    y_dev_clipped = np.stack([
        dev_sigma_normalizer.standardize_target_vector(partitions.raw_labels[d], d, clip=True)
        for d in dev_decisions
    ], axis=0)  # [364, 4]

    final_ridge = Ridge(alpha=best_alpha, fit_intercept=True)
    final_ridge.fit(X_dev_flat, y_dev_clipped)
    ridge_in_sample_mse = float(np.mean((y_dev_clipped - final_ridge.predict(X_dev_flat)) ** 2))
    print(f"  Final Ridge fitted (in-sample MSE: {ridge_in_sample_mse:.6f})")

    # 6. Fit the one shared neural model on full 2022 development set
    print("Fitting unified shared neural forecaster on full 2022 development set...")
    set_seed(42)
    neural_model = build_neural_forecaster(seed=42)
    neural_model.to("cpu")
    optimizer = torch.optim.AdamW(neural_model.parameters(), lr=0.001, weight_decay=0.001)
    criterion = nn.MSELoss()

    X_torch = torch.tensor(X_dev_norm, dtype=torch.float32)
    y_torch = torch.tensor(y_dev_clipped, dtype=torch.float32)

    batch_size = 32
    epochs = 30
    loss_trace: list[dict[str, object]] = []

    neural_model.train()
    for epoch in range(1, epochs + 1):
        epoch_loss_sum = 0.0
        for start_idx in range(0, len(dev_decisions), batch_size):
            end_idx = min(start_idx + batch_size, len(dev_decisions))
            xb = X_torch[start_idx:end_idx]
            yb = y_torch[start_idx:end_idx]
            optimizer.zero_grad()
            out = neural_model(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
            epoch_loss_sum += loss.item() * (end_idx - start_idx)

        epoch_loss = epoch_loss_sum / len(dev_decisions)
        loss_trace.append({"epoch": epoch, "loss": epoch_loss})
        if epoch % 5 == 0 or epoch == 1 or epoch == epochs:
            print(f"  Epoch {epoch:2d}/{epochs}: loss = {epoch_loss:.6f}")

    neural_model.eval()
    with torch.no_grad():
        final_neural_preds = neural_model(X_torch).numpy()
    neural_in_sample_mse = float(np.mean((y_dev_clipped - final_neural_preds) ** 2))
    print(f"  Final Neural model fitted (in-sample MSE: {neural_in_sample_mse:.6f})")

    # 7. Save frozen artifacts
    output_dir.mkdir(parents=True, exist_ok=True)
    neural_artifact_path = output_dir / "neural_forecaster.pt"
    ridge_artifact_path = output_dir / "ridge_baseline.joblib"
    scaler_artifact_path = output_dir / "feature_scaler.json"
    floors_artifact_path = output_dir / "sigma_floors.json"
    trace_artifact_path = output_dir / "training_trace.json"

    torch.save(neural_model.state_dict(), neural_artifact_path)
    joblib.dump(final_ridge, ridge_artifact_path)
    scaler_artifact_path.write_text(json.dumps(dev_scaler.to_dict(), indent=2), encoding="utf-8")
    floors_artifact_path.write_text(json.dumps(dev_floors, indent=2), encoding="utf-8")

    trace_data = {
        "preregistration_commit": S4_PREREGISTRATION_COMMIT,
        "seed": 42,
        "device": "cpu",
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": 0.001,
        "weight_decay": 0.001,
        "shuffle": False,
        "checkpoint": "final_epoch",
        "neural_trainable_parameters": neural_model.count_parameters(),
        "loss_trace": loss_trace,
        "initial_loss": loss_trace[0]["loss"],
        "final_loss": loss_trace[-1]["loss"],
        "ridge_alphas": list(RIDGE_ALPHAS),
        "ridge_fold_mses": fold_mses,
        "ridge_mean_mses": mean_mses,
        "selected_ridge_alpha": best_alpha,
    }
    trace_artifact_path.write_text(json.dumps(trace_data, indent=2), encoding="utf-8")

    # 8. Reload and verify finite predictions
    print("Reloading saved artifacts and verifying predictions...")
    reloaded_neural = build_neural_forecaster(seed=42)
    reloaded_neural.load_state_dict(torch.load(neural_artifact_path, weights_only=True))
    reloaded_neural.eval()

    reloaded_ridge = joblib.load(ridge_artifact_path)
    reloaded_scaler = FeatureScaler.from_dict(json.loads(scaler_artifact_path.read_text(encoding="utf-8")))

    sample_raw = X_dev_raw[:5]
    sample_norm = reloaded_scaler.transform(sample_raw)
    sample_flat = RidgeBaseline.flatten_tensor(sample_norm)
    sample_torch = torch.tensor(sample_norm, dtype=torch.float32)

    with torch.no_grad():
        reloaded_neural_preds = reloaded_neural(sample_torch).numpy()
    reloaded_ridge_preds = reloaded_ridge.predict(sample_flat)

    if not np.allclose(reloaded_neural_preds, final_neural_preds[:5], atol=1e-6):
        raise ForecastError("Reloaded neural model predictions mismatch original model")
    if not np.allclose(reloaded_ridge_preds, final_ridge.predict(X_dev_flat[:5]), atol=1e-6):
        raise ForecastError("Reloaded Ridge model predictions mismatch original model")
    if not np.isfinite(reloaded_neural_preds).all() or not np.isfinite(reloaded_ridge_preds).all():
        raise ForecastError("Reloaded predictions contain non-finite values")
    print("  Artifact reload verification: PASS (exact match, finite values)")

    # 9. Compute artifact SHA-256 hashes
    artifact_hashes = {
        "neural_forecaster.pt": {
            "path": str(neural_artifact_path),
            "sha256": sha256_file(neural_artifact_path),
            "size_bytes": neural_artifact_path.stat().st_size,
        },
        "ridge_baseline.joblib": {
            "path": str(ridge_artifact_path),
            "sha256": sha256_file(ridge_artifact_path),
            "size_bytes": ridge_artifact_path.stat().st_size,
        },
        "feature_scaler.json": {
            "path": str(scaler_artifact_path),
            "sha256": sha256_file(scaler_artifact_path),
            "size_bytes": scaler_artifact_path.stat().st_size,
        },
        "sigma_floors.json": {
            "path": str(floors_artifact_path),
            "sha256": sha256_file(floors_artifact_path),
            "size_bytes": floors_artifact_path.stat().st_size,
        },
        "training_trace.json": {
            "path": str(trace_artifact_path),
            "sha256": sha256_file(trace_artifact_path),
            "size_bytes": trace_artifact_path.stat().st_size,
        },
    }

    evidence: dict[str, object] = {
        "preregistration_commit": S4_PREREGISTRATION_COMMIT,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "COMPLETED",
        "verdict": "FROZEN_MODELS_READY",
        "data_provenance": {
            "canonical_source": "monthly Binance Spot archives with verified SHA-256 sidecars",
            "archives_count": len(sources_summary),
            "universe": list(UNIVERSE),
            "authorized_window": "2021-11-01 00:00 UTC through 2023-12-31 23:00 UTC",
        },
        "warmup": {
            "start": str(AUDIT_START),
            "completed_labels_at_2022_01_01": 60,
            "min_required": 30,
            "warmup_valid": True,
        },
        "dataset_2022": {
            "nominal_decisions": len(dev_decisions),
            "eligible_decisions": len(partitions.eligible_decisions),
            "excluded_decisions": len(partitions.excluded_decisions),
            "start_decision": str(dev_decisions[0]),
            "end_decision": str(dev_decisions[-1]),
        },
        "ridge_selection": {
            "folds": [f.name for f in folds],
            "alphas": list(RIDGE_ALPHAS),
            "fold_mses": fold_mses,
            "mean_mses": mean_mses,
            "selected_alpha": best_alpha,
            "tie_breaking_applied": False,
            "in_sample_mse": ridge_in_sample_mse,
        },
        "neural_training": {
            "architecture": "Shared GRU(6, 16) + Cross-asset MHA(16, 2) + LayerNorm + Linear(16, 1)",
            "trainable_parameters": neural_model.count_parameters(),
            "parameter_budget": MAX_TRAINABLE_PARAMETERS,
            "seed": 42,
            "device": "cpu",
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": 0.001,
            "weight_decay": 0.001,
            "initial_loss": loss_trace[0]["loss"],
            "final_loss": loss_trace[-1]["loss"],
            "in_sample_mse": neural_in_sample_mse,
        },
        "artifacts": artifact_hashes,
        "reload_verification": {
            "status": "PASS",
            "sample_predictions_finite": True,
            "reloaded_exact_match": True,
        },
        "boundary_protections": {
            "s4_2023_screen": "NOT_PERFORMED",
            "s4_2024_2026_access": "NOT_AUTHORIZED",
            "s4_stage2_allocator": "NOT_AUTHORIZED",
            "production_promotion": "NOT_AUTHORIZED",
        },
    }

    evidence_json_path = output_dir / "s4_stage1_2022_development_evidence.json"
    evidence_json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    evidence_md_path = output_dir / "s4_stage1_2022_development.md"
    evidence_md_path.write_text(render_development_markdown(evidence), encoding="utf-8")

    print(f"Development evidence written to:")
    print(f"  JSON: {evidence_json_path}")
    print(f"  MD:   {evidence_md_path}")
    print("=== 2022 DEVELOPMENT COMPLETED & MODELS FROZEN ===")
    return evidence


def render_development_markdown(evidence: dict[str, object]) -> str:
    artifacts = evidence.get("artifacts", {})
    ridge_sel = evidence.get("ridge_selection", {})
    neural_tr = evidence.get("neural_training", {})
    warmup = evidence.get("warmup", {})
    dataset = evidence.get("dataset_2022", {})

    lines = [
        "# S4-P1B: 2022 Development & Frozen Model Fitting Report",
        "",
        f"- **Pre-registration Commit:** `{evidence.get('preregistration_commit')}`",
        f"- **Generated At (UTC):** `{evidence.get('generated_at_utc')}`",
        f"- **Status:** `{evidence.get('status')}`",
        f"- **Verdict:** `{evidence.get('verdict')}`",
        "",
        "## 1. Data Provenance & 2021 Warmup",
        "",
        f"- **Canonical Source:** {evidence.get('data_provenance', {}).get('canonical_source')}",
        f"- **Archives Count:** {evidence.get('data_provenance', {}).get('archives_count')} monthly Binance Spot archives verified via SHA-256 sidecars.",
        f"- **Universe:** {', '.join(evidence.get('data_provenance', {}).get('universe', []))}",
        f"- **2021 Warmup Completed Labels at 2022-01-01 00:00 UTC:** {warmup.get('completed_labels_at_2022_01_01')} (minimum required: {warmup.get('min_required')}).",
        f"- **2022 Development Decisions:** {dataset.get('eligible_decisions')} eligible decisions ({dataset.get('start_decision')} through {dataset.get('end_decision')}), 0 excluded.",
        "",
        "## 2. Ridge Alpha Cross-Validation (4 Expanding Folds)",
        "",
        "| Alpha | Mean Validation MSE | F1 MSE | F2 MSE | F3 MSE | F4 MSE |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    alphas = ridge_sel.get("alphas", [])
    mean_mses = ridge_sel.get("mean_mses", {})
    fold_mses = ridge_sel.get("fold_mses", {})
    for a in alphas:
        a_key = float(a)
        m_val = mean_mses.get(a_key, mean_mses.get(str(a_key), 0.0))
        f1_m = fold_mses.get("F1", {}).get(a_key, fold_mses.get("F1", {}).get(str(a_key), 0.0))
        f2_m = fold_mses.get("F2", {}).get(a_key, fold_mses.get("F2", {}).get(str(a_key), 0.0))
        f3_m = fold_mses.get("F3", {}).get(a_key, fold_mses.get("F3", {}).get(str(a_key), 0.0))
        f4_m = fold_mses.get("F4", {}).get(a_key, fold_mses.get("F4", {}).get(str(a_key), 0.0))
        lines.append(f"| {a} | {m_val:.6f} | {f1_m:.6f} | {f2_m:.6f} | {f3_m:.6f} | {f4_m:.6f} |")

    lines.extend([
        "",
        f"- **Selected Ridge Alpha:** `{ridge_sel.get('selected_alpha')}`",
        f"- **2022 In-Sample MSE:** `{ridge_sel.get('in_sample_mse'):.6f}`",
        "",
        "## 3. Shared Neural Forecaster Training (2022 Development)",
        "",
        f"- **Architecture:** `{neural_tr.get('architecture')}`",
        f"- **Trainable Parameters:** {neural_tr.get('trainable_parameters')} (budget: <= {neural_tr.get('parameter_budget')})",
        f"- **Optimizer:** AdamW (lr={neural_tr.get('learning_rate')}, weight_decay={neural_tr.get('weight_decay')})",
        f"- **Batch Size / Epochs:** batch_size={neural_tr.get('batch_size')}, epochs={neural_tr.get('epochs')}, shuffle={neural_tr.get('shuffle', False)}",
        f"- **Device / Seed:** {neural_tr.get('device')}, seed={neural_tr.get('seed')}",
        f"- **Initial Epoch Loss:** `{neural_tr.get('initial_loss'):.6f}`",
        f"- **Final Epoch Loss (Epoch 30):** `{neural_tr.get('final_loss'):.6f}`",
        f"- **2022 In-Sample MSE:** `{neural_tr.get('in_sample_mse'):.6f}`",
        "",
        "## 4. Frozen Model Artifacts & SHA-256",
        "",
        "| Artifact File | Size (Bytes) | SHA-256 Digest |",
        "|---|---:|---|",
    ])

    for fname, meta in artifacts.items():
        lines.append(f"| `{fname}` | {meta.get('size_bytes')} | `{meta.get('sha256')}` |")

    lines.extend([
        "",
        "## 5. Reload & Finite Output Verification",
        "",
        f"- **Status:** `{evidence.get('reload_verification', {}).get('status')}`",
        f"- **Sample Predictions Finite:** `{evidence.get('reload_verification', {}).get('sample_predictions_finite')}`",
        f"- **Reloaded Exact Match:** `{evidence.get('reload_verification', {}).get('reloaded_exact_match')}`",
        "",
        "## 6. Research Boundaries",
        "",
        "```text",
        "S4_DATASET_READINESS   = DATASET_READY",
        "S4_2022_DEVELOPMENT    = COMPLETED",
        "S4_RIDGE_MODEL         = FROZEN",
        "S4_NEURAL_MODEL        = FROZEN",
        "S4_PREPROCESSING       = FROZEN",
        "S4_2023_SCREEN         = NOT_PERFORMED",
        "S4_2024_2026_ACCESS    = NOT_AUTHORIZED",
        "S4_STAGE2_ALLOCATOR    = NOT_AUTHORIZED",
        "PRODUCTION_PROMOTION   = NOT_AUTHORIZED",
        "```",
        "",
    ])

    return "\n".join(lines)


def run_screen_2023(
    repo_root: Path,
    audit_json_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Execute the pre-registered one-shot 2023 predictive screen on frozen models.

    Strictly fail-closed: requires authentic 2023 data, exact frozen artifacts,
    common date intersection across all 4 assets, and produces primary IC, bootstrap CI,
    and preregistered diagnostics.
    """
    print("=== S4-P1C: ONE-SHOT 2023 FORECAST INFORMATION SCREENING ===")
    print(f"Pre-registration commit: {S4_PREREGISTRATION_COMMIT}")

    # 1. Verify and load frozen models
    print(f"Verifying and loading frozen model artifacts from: {output_dir}")
    frozen = verify_and_load_frozen_artifacts(output_dir)
    print("  Frozen artifacts verified and loaded (SHA-256 hashes matched, parameters=2289, alpha=10000.0)")

    # 2. Check audit artifact
    if not audit_json_path.is_file():
        raise ForecastError(f"Dataset audit artifact not found: {audit_json_path}")
    audit_data = json.loads(audit_json_path.read_text(encoding="utf-8"))
    if audit_data.get("verdict") != "DATASET_READY":
        raise ForecastError(f"Dataset audit verdict is not DATASET_READY: {audit_data.get('verdict')}")

    # 3. Load canonical Binance Spot archives
    raw_root = repo_root / "data/historical/neural_n1/raw/binance_spot_klines_1h"
    print(f"Loading canonical Binance Spot archives from: {raw_root}")
    panels: dict[str, pd.DataFrame] = {}
    sources_summary: list[dict[str, object]] = []
    for symbol in UNIVERSE:
        frame, sources = load_binance_archives(raw_root, symbol)
        panels[symbol] = indexed_panel(frame)
        sources_summary.extend(sources)
        print(f"  [{symbol}] Loaded {len(frame)} hourly bars ({frame['timestamp'].min()} to {frame['timestamp'].max()})")

    # 4. Build 2023 complete-case screen dataset
    screen_decisions = ChronologicalSplitter.get_screen_dates()
    print(f"Building 2023 complete-case screen partitions ({len(screen_decisions)} nominal decisions, warmup from {AUDIT_START})...")
    partitions = build_causal_partitions(panels, screen_decisions, warmup_start=AUDIT_START)

    common_dates = partitions.eligible_decisions
    n_common = len(common_dates)
    print(f"  2023 Common eligible decisions: {n_common} (expected from audit: 349)")
    if n_common < 300:
        raise ForecastError(f"INCONCLUSIVE / DATA_INSUFFICIENT: common dates {n_common} < 300")
    if n_common != 349:
        print(f"  WARNING: Common dates count {n_common} deviates from expected 349. Exclusions: {partitions.excluded_decisions}")

    # 5. Paired Inference & Causal Volatility Normalization
    print("Generating paired forecasts and causal realized targets across common 2023 dates...")
    realized_y_list: list[np.ndarray] = []
    realized_z_raw_list: list[np.ndarray] = []
    realized_z_clipped_list: list[np.ndarray] = []
    neural_zhat_list: list[np.ndarray] = []
    ridge_zhat_list: list[np.ndarray] = []
    neural_yhat_list: list[np.ndarray] = []
    ridge_yhat_list: list[np.ndarray] = []
    effective_sigmas_list: list[np.ndarray] = []
    raw_sigmas_list: list[np.ndarray] = []
    prediction_records: list[dict[str, object]] = []

    # Apply frozen 2022 floors
    frozen_floors = frozen.sigma_floors

    for d in common_dates:
        # Features
        raw_x = partitions.features[d]  # [168, 4, 6]
        norm_x = frozen.scaler.transform(raw_x[None, ...])[0]  # [168, 4, 6]
        flat_x = RidgeBaseline.flatten_tensor(norm_x[None, ...])  # [1, 4032]
        torch_x = torch.tensor(norm_x[None, ...], dtype=torch.float32)

        # Predictions (standardized scale)
        with torch.no_grad():
            zn_hat = frozen.neural_model(torch_x).numpy()[0]  # [4]
        zr_hat = frozen.ridge_model.predict(flat_x)[0]  # [4]

        # Realized labels and causal volatility
        y_raw = partitions.raw_labels[d]  # [4]
        eff_sigmas = []
        raw_sigmas = []
        for symbol in UNIVERSE:
            raw_sig = partitions.sigma_normalizer.get_raw_sigma(symbol, d)
            raw_sigmas.append(raw_sig)
            eff_sig = max(raw_sig, frozen_floors[symbol])
            eff_sigmas.append(eff_sig)

        eff_sigmas_arr = np.array(eff_sigmas, dtype=float)
        raw_sigmas_arr = np.array(raw_sigmas, dtype=float)

        z_raw = y_raw / eff_sigmas_arr
        z_clipped = np.clip(z_raw, -4.0, 4.0)

        # Return scale predictions
        yn_hat = zn_hat * eff_sigmas_arr
        yr_hat = zr_hat * eff_sigmas_arr

        realized_y_list.append(y_raw)
        realized_z_raw_list.append(z_raw)
        realized_z_clipped_list.append(z_clipped)
        neural_zhat_list.append(zn_hat)
        ridge_zhat_list.append(zr_hat)
        neural_yhat_list.append(yn_hat)
        ridge_yhat_list.append(yr_hat)
        effective_sigmas_list.append(eff_sigmas_arr)
        raw_sigmas_list.append(raw_sigmas_arr)

        record: dict[str, object] = {
            "decision": d.isoformat(),
            "execution_entry": (d + pd.Timedelta(hours=1)).isoformat(),
            "label_exit": (d + pd.Timedelta(days=1, hours=1)).isoformat(),
        }
        for idx, sym in enumerate(UNIVERSE):
            record[f"{sym}_realized_y"] = float(y_raw[idx])
            record[f"{sym}_raw_sigma"] = float(raw_sigmas_arr[idx])
            record[f"{sym}_effective_sigma"] = float(eff_sigmas_arr[idx])
            record[f"{sym}_realized_z_raw"] = float(z_raw[idx])
            record[f"{sym}_realized_z_clipped"] = float(z_clipped[idx])
            record[f"{sym}_neural_zhat"] = float(zn_hat[idx])
            record[f"{sym}_ridge_zhat"] = float(zr_hat[idx])
            record[f"{sym}_neural_yhat"] = float(yn_hat[idx])
            record[f"{sym}_ridge_yhat"] = float(yr_hat[idx])
        prediction_records.append(record)

    realized_y = np.stack(realized_y_list, axis=0)  # [N, 4]
    realized_z = np.stack(realized_z_raw_list, axis=0)  # [N, 4] raw unclipped
    realized_z_clipped = np.stack(realized_z_clipped_list, axis=0)  # [N, 4]
    neural_zhat = np.stack(neural_zhat_list, axis=0)  # [N, 4]
    ridge_zhat = np.stack(ridge_zhat_list, axis=0)  # [N, 4]
    neural_yhat = np.stack(neural_yhat_list, axis=0)  # [N, 4]
    ridge_yhat = np.stack(ridge_yhat_list, axis=0)  # [N, 4]

    # 6. Primary Statistics
    print("Computing primary statistics (Pearson IC and Fisher-z aggregate)...")
    primary_stats = compute_primary_statistics(realized_z, neural_zhat, ridge_zhat)
    print(f"  Per-asset Neural IC: {primary_stats.per_asset_neural_ic}")
    print(f"  Per-asset Ridge IC:  {primary_stats.per_asset_ridge_ic}")
    print(f"  S(Neural) = {primary_stats.s_neural:.6f}")
    print(f"  S(Ridge)  = {primary_stats.s_ridge:.6f}")
    print(f"  Delta S   = {primary_stats.delta_s:.6f}")

    # Clipped target secondary IC
    clipped_stats = compute_primary_statistics(realized_z_clipped, neural_zhat, ridge_zhat)

    # 7. Paired Stationary Bootstrap
    print("Executing paired stationary bootstrap (2,000 draws, seed=42)...")
    boot_14d = paired_stationary_bootstrap(realized_z, neural_zhat, ridge_zhat, block_length=14.0, n_draws=2000, seed=42)
    boot_7d = paired_stationary_bootstrap(realized_z, neural_zhat, ridge_zhat, block_length=7.0, n_draws=2000, seed=42)
    boot_21d = paired_stationary_bootstrap(realized_z, neural_zhat, ridge_zhat, block_length=21.0, n_draws=2000, seed=42)
    print(f"  Primary 14-day 95% CI: [{boot_14d.ci_lower_95:.6f}, {boot_14d.ci_upper_95:.6f}] (mean={boot_14d.mean_delta_s:.6f}, std={boot_14d.std_delta_s:.6f})")
    print(f"  Sensitivity 7-day 95% CI: [{boot_7d.ci_lower_95:.6f}, {boot_7d.ci_upper_95:.6f}]")
    print(f"  Sensitivity 21-day 95% CI: [{boot_21d.ci_lower_95:.6f}, {boot_21d.ci_upper_95:.6f}]")

    # 8. Diagnostics
    print("Computing preregistered secondary diagnostics...")
    # Common/relative decomposition
    common_rel = decompose_common_and_relative(realized_z, neural_zhat, ridge_zhat)

    # Mincer-Zarnowitz calibration
    mz_neural = mincer_zarnowitz_calibration(realized_y, neural_yhat)
    mz_ridge = mincer_zarnowitz_calibration(realized_y, ridge_yhat)
    mz_neural_slopes = [mz_neural[s]["beta"] for s in UNIVERSE]

    # BTC-relative spread accuracy
    spread_diag = btc_relative_spread_diagnostics(realized_y, neural_yhat, ridge_yhat, threshold=SPREAD_THRESHOLD_BPS)

    # Extreme day sensitivity (drop top 5% = 18 days)
    extreme_diag = extreme_day_sensitivity(common_dates, realized_y, realized_z, neural_zhat, ridge_zhat, drop_pct=0.05)

    # First half vs Second half
    h1_mask = [d < pd.Timestamp("2023-07-01", tz="UTC") for d in common_dates]
    h2_mask = [d >= pd.Timestamp("2023-07-01", tz="UTC") for d in common_dates]

    stats_h1 = compute_primary_statistics(realized_z[h1_mask], neural_zhat[h1_mask], ridge_zhat[h1_mask])
    stats_h2 = compute_primary_statistics(realized_z[h2_mask], neural_zhat[h2_mask], ridge_zhat[h2_mask])

    # 9. Evaluate Scientific Verdict
    verdict, verdict_checks = evaluate_scientific_verdict(
        n_common=n_common,
        s_neural=primary_stats.s_neural,
        ci_lower_14d=boot_14d.ci_lower_95,
        ci_upper_14d=boot_14d.ci_upper_95,
        mz_slopes=mz_neural_slopes,
        extreme_excluded_delta_s=extreme_diag["delta_s"],
        protocol_valid=True,
    )
    print(f"  VERDICT: {verdict}")
    print(f"  Verdict checks: {verdict_checks}")

    # 10. Save Evidence Artifacts
    # Predictions JSON
    pred_path = output_dir / "s4_stage1_2023_screen_paired_predictions.json"
    pred_path.write_text(json.dumps(prediction_records, indent=2), encoding="utf-8")

    # Structured Evidence JSON
    evidence: dict[str, object] = {
        "preregistration_commit": S4_PREREGISTRATION_COMMIT,
        "evaluation_phase": "2023_REUSED_INTERNAL_SCREEN",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verdict": verdict,
        "verdict_checks": verdict_checks,
        "population": {
            "authorized_window": "2023-01-01 through 2023-12-30",
            "nominal_dates": len(screen_decisions),
            "common_dates_count": n_common,
            "min_required": 300,
            "gap_excluded_dates_count": len(partitions.excluded_decisions),
            "excluded_decisions": {d.isoformat(): r for d, r in partitions.excluded_decisions.items()},
        },
        "primary_statistics": {
            "s_neural": primary_stats.s_neural,
            "s_ridge": primary_stats.s_ridge,
            "delta_s": primary_stats.delta_s,
            "per_asset_neural_ic": primary_stats.per_asset_neural_ic,
            "per_asset_ridge_ic": primary_stats.per_asset_ridge_ic,
        },
        "secondary_clipped_target_statistics": {
            "s_neural": clipped_stats.s_neural,
            "s_ridge": clipped_stats.s_ridge,
            "delta_s": clipped_stats.delta_s,
            "per_asset_neural_ic": clipped_stats.per_asset_neural_ic,
            "per_asset_ridge_ic": clipped_stats.per_asset_ridge_ic,
        },
        "paired_stationary_bootstrap": {
            "primary_14d": {
                "block_length": boot_14d.block_length,
                "n_draws": boot_14d.n_draws,
                "valid_draws": boot_14d.valid_draws_count,
                "mean_delta_s": boot_14d.mean_delta_s,
                "std_delta_s": boot_14d.std_delta_s,
                "ci_lower_95": boot_14d.ci_lower_95,
                "ci_upper_95": boot_14d.ci_upper_95,
            },
            "sensitivity_7d": {
                "block_length": boot_7d.block_length,
                "n_draws": boot_7d.n_draws,
                "ci_lower_95": boot_7d.ci_lower_95,
                "ci_upper_95": boot_7d.ci_upper_95,
            },
            "sensitivity_21d": {
                "block_length": boot_21d.block_length,
                "n_draws": boot_21d.n_draws,
                "ci_lower_95": boot_21d.ci_lower_95,
                "ci_upper_95": boot_21d.ci_upper_95,
            },
        },
        "diagnostics": {
            "common_and_relative": common_rel,
            "mincer_zarnowitz_neural": mz_neural,
            "mincer_zarnowitz_ridge": mz_ridge,
            "btc_relative_spread": spread_diag,
            "extreme_day_sensitivity": extreme_diag,
            "half_year_stability": {
                "h1_count": int(sum(h1_mask)),
                "h1_s_neural": stats_h1.s_neural,
                "h1_s_ridge": stats_h1.s_ridge,
                "h1_delta_s": stats_h1.delta_s,
                "h2_count": int(sum(h2_mask)),
                "h2_s_neural": stats_h2.s_neural,
                "h2_s_ridge": stats_h2.s_ridge,
                "h2_delta_s": stats_h2.delta_s,
            },
        },
        "frozen_artifacts_verified": frozen.artifact_hashes,
        "boundary_protections": {
            "s4_2024_2026_access": "NOT_AUTHORIZED",
            "s4_stage2_allocator": "NOT_AUTHORIZED",
            "production_promotion": "NOT_AUTHORIZED",
            "re_tuning_or_rerun": "PROHIBITED",
        },
    }

    evidence_json_path = output_dir / "s4_stage1_2023_screen_evidence.json"
    evidence_json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    evidence_md_path = output_dir / "s4_stage1_2023_screen.md"
    evidence_md_path.write_text(render_screen_markdown(evidence), encoding="utf-8")

    print(f"Screen evidence saved to:")
    print(f"  Predictions: {pred_path}")
    print(f"  JSON:        {evidence_json_path}")
    print(f"  Report MD:   {evidence_md_path}")
    print("=== ONE-SHOT SCREEN COMPLETED ===")
    return evidence


def render_screen_markdown(evidence: dict[str, object]) -> str:
    pop = evidence.get("population", {})
    prim = evidence.get("primary_statistics", {})
    boot = evidence.get("paired_stationary_bootstrap", {}).get("primary_14d", {})
    boot7 = evidence.get("paired_stationary_bootstrap", {}).get("sensitivity_7d", {})
    boot21 = evidence.get("paired_stationary_bootstrap", {}).get("sensitivity_21d", {})
    diag = evidence.get("diagnostics", {})
    mz_n = diag.get("mincer_zarnowitz_neural", {})
    mz_r = diag.get("mincer_zarnowitz_ridge", {})
    spread = diag.get("btc_relative_spread", {})
    extreme = diag.get("extreme_day_sensitivity", {})
    half = diag.get("half_year_stability", {})
    com_rel = diag.get("common_and_relative", {})

    lines = [
        "# S4-P1C: One-Shot 2023 Forecast Information Screening Report",
        "",
        f"- **Pre-registration Commit:** `{evidence.get('preregistration_commit')}`",
        f"- **Evaluation Phase:** `{evidence.get('evaluation_phase')}`",
        f"- **Generated At (UTC):** `{evidence.get('generated_at_utc')}`",
        f"- **Scientific Verdict:** **`{evidence.get('verdict')}`**",
        "",
        "## 1. Primary Screening Result",
        "",
        f"- **Eligible Common Dates:** {pop.get('common_dates_count')} (Nominal: {pop.get('nominal_dates')}, Excluded: {pop.get('gap_excluded_dates_count')})",
        f"- **Fisher-z S(Neural):** `{prim.get('s_neural'):.6f}`",
        f"- **Fisher-z S(Ridge):**  `{prim.get('s_ridge'):.6f}`",
        f"- **Primary Delta S [S(Neural) - S(Ridge)]:** `{prim.get('delta_s'):.6f}`",
        f"- **Primary 14-day Paired 95% Percentile CI:** `[{boot.get('ci_lower_95'):.6f}, {boot.get('ci_upper_95'):.6f}]` (Mean: `{boot.get('mean_delta_s'):.6f}`, Std: `{boot.get('std_delta_s'):.6f}`)",
        f"- **Block-Length Sensitivity CIs:**",
        f"  - 7-day:  `[{boot7.get('ci_lower_95'):.6f}, {boot7.get('ci_upper_95'):.6f}]`",
        f"  - 21-day: `[{boot21.get('ci_lower_95'):.6f}, {boot21.get('ci_upper_95'):.6f}]`",
        "",
        "### Per-Asset Correlation (Raw Unclipped Standardized Target)",
        "",
        "| Asset | Neural IC | Ridge IC | Delta IC |",
        "|---|---:|---:|---:|",
    ]

    for sym in UNIVERSE:
        nic = prim.get("per_asset_neural_ic", {}).get(sym, 0.0)
        ric = prim.get("per_asset_ridge_ic", {}).get(sym, 0.0)
        lines.append(f"| `{sym}` | {nic:.6f} | {ric:.6f} | {(nic - ric):.6f} |")

    lines.extend([
        "",
        "## 2. Verdict Decision Criteria Checks",
        "",
        f"- **(a) N_common >= 300:** `{evidence.get('verdict_checks', {}).get('n_common_gte_300')}` ({pop.get('common_dates_count')})",
        f"- **(b) S(Neural) > 0:** `{evidence.get('verdict_checks', {}).get('s_neural_gt_zero')}` ({prim.get('s_neural'):.6f})",
        f"- **(c) Primary 14d 95% CI Lower Bound > 0:** `{evidence.get('verdict_checks', {}).get('ci_lower_14d_gt_zero')}` ({boot.get('ci_lower_95'):.6f})",
        f"- **(d) MZ Slopes Corroborated (>=3/4 > 0 and median > 0):** `{evidence.get('verdict_checks', {}).get('mz_slopes_corroborated')}`",
        f"- **(e) Extreme-Day-Excluded Delta S > 0:** `{evidence.get('verdict_checks', {}).get('extreme_excluded_delta_s_gt_zero')}` ({extreme.get('delta_s'):.6f})",
        f"- **(f) Protocol Integrity Valid:** `{evidence.get('verdict_checks', {}).get('protocol_integrity_valid')}`",
        "",
        "## 3. Preregistered Diagnostics",
        "",
        "### 3.1. Common Market vs. Relative Decomposition",
        "",
        f"- **Common Market IC (Neural):** `{com_rel.get('common_market_ic_neural'):.6f}`",
        f"- **Common Market IC (Ridge):**  `{com_rel.get('common_market_ic_ridge'):.6f}`",
        f"- **Common Market Delta IC:**     `{com_rel.get('common_market_delta_ic'):.6f}`",
        f"- **Relative Fisher-z S (Neural):** `{com_rel.get('relative_s_neural'):.6f}`",
        f"- **Relative Fisher-z S (Ridge):**  `{com_rel.get('relative_s_ridge'):.6f}`",
        f"- **Relative Delta S:**              `{com_rel.get('relative_delta_s'):.6f}`",
        "",
        "### 3.2. Mincer-Zarnowitz Regression (Unclipped Return Scale)",
        "",
        "| Asset | Neural Alpha (bps) | Neural Beta | SE(Beta) | Neural R² | Ridge Beta | Ridge R² |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])

    for sym in UNIVERSE:
        mn = mz_n.get(sym, {})
        mr = mz_r.get(sym, {})
        lines.append(
            f"| `{sym}` | {mn.get('alpha', 0.0)*10000:.2f} | {mn.get('beta', 0.0):.4f} | {mn.get('se_beta', 0.0):.4f} | {mn.get('r_squared', 0.0):.4f} | {mr.get('beta', 0.0):.4f} | {mr.get('r_squared', 0.0):.4f} |"
        )

    lines.extend([
        "",
        "### 3.3. BTC-Relative Spread Sign Accuracy (|Spread| > 24 bps)",
        "",
        "| Pair | Total Dates | Neural Eligible | Neural Accuracy | Ridge Eligible | Ridge Accuracy |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for pair, data in spread.items():
        n_data = data.get("neural", {})
        r_data = data.get("ridge", {})
        n_acc_str = f"{n_data.get('sign_accuracy_pct'):.2f}%" if n_data.get("sign_accuracy_pct") is not None else "N/A"
        r_acc_str = f"{r_data.get('sign_accuracy_pct'):.2f}%" if r_data.get("sign_accuracy_pct") is not None else "N/A"
        lines.append(
            f"| `{pair}` | {data.get('total_dates')} | {n_data.get('eligible_dates')} ({n_data.get('coverage_pct'):.1f}%) | {n_acc_str} | {r_data.get('eligible_dates')} ({r_data.get('coverage_pct'):.1f}%) | {r_acc_str} |"
        )

    lines.extend([
        "",
        "### 3.4. Extreme-Day Exclusion Sensitivity",
        "",
        f"- **Dropped Days Count:** {extreme.get('dropped_count')} days (top 5% absolute market moves)",
        f"- **Kept Days Count:** {extreme.get('kept_count')} days",
        f"- **S(Neural) on Kept Days:** `{extreme.get('s_neural'):.6f}`",
        f"- **S(Ridge) on Kept Days:**  `{extreme.get('s_ridge'):.6f}`",
        f"- **Delta S on Kept Days:**   `{extreme.get('delta_s'):.6f}`",
        "",
        "### 3.5. First Half vs. Second Half Stability",
        "",
        f"- **H1 (Jan-Jun):** N={half.get('h1_count')}, S(Neural)=`{half.get('h1_s_neural'):.6f}`, S(Ridge)=`{half.get('h1_s_ridge'):.6f}`, Delta S=`{half.get('h1_delta_s'):.6f}`",
        f"- **H2 (Jul-Dec):** N={half.get('h2_count')}, S(Neural)=`{half.get('h2_s_neural'):.6f}`, S(Ridge)=`{half.get('h2_s_ridge'):.6f}`, Delta S=`{half.get('h2_delta_s'):.6f}`",
        "",
        "## 4. Frozen Artifact Integrity & Boundaries",
        "",
        "| Artifact File | Verified SHA-256 Digest |",
        "|---|---|",
    ])

    for fname, sha in evidence.get("frozen_artifacts_verified", {}).items():
        lines.append(f"| `{fname}` | `{sha}` |")

    lines.extend([
        "",
        "```text",
        "S4_DATASET_READINESS   = DATASET_READY",
        f"S4_2023_SCREEN         = COMPLETED ({evidence.get('verdict')})",
        "S4_2024_2026_ACCESS    = NOT_AUTHORIZED",
        "S4_STAGE2_ALLOCATOR    = NOT_AUTHORIZED",
        "PRODUCTION_PROMOTION   = NOT_AUTHORIZED",
        "RE_TUNING_OR_RERUN     = PROHIBITED",
        "```",
        "",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["preflight", "development-2022", "screen-2023"],
        default="preflight",
        help="Operational mode: preflight (default), development-2022, or screen-2023",
    )
    parser.add_argument(
        "--audit-json",
        type=Path,
        default=REPO_ROOT / "research/s4_forecast_information_screening/s4_stage1_dataset_audit.json",
        help="Path to dataset audit structured JSON",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "research/s4_forecast_information_screening/stage1_evidence",
        help="Directory to store stage 1 output artifacts",
    )
    parser.add_argument(
        "--authorize-development",
        action="store_true",
        default=False,
        help="Explicit flag required to run 2022 development training",
    )
    parser.add_argument(
        "--authorize-one-shot-2023-screen",
        action="store_true",
        default=False,
        help="Explicit flag required to unlock the one-shot 2023 predictive screen",
    )

    args = parser.parse_args()

    if args.mode == "preflight":
        print(f"=== S4-P1C PREFLIGHT VERIFICATION ===")
        print(f"Pre-registration commit: {S4_PREREGISTRATION_COMMIT}")
        result = run_preflight(REPO_ROOT, args.audit_json)
        print(json.dumps(result, indent=2))
        print("PREFLIGHT_STATUS = PASS")
        print("STOP RULE ACTIVE: No model training or 2023 screening executed in preflight mode.")
        return 0

    elif args.mode == "development-2022":
        if not args.authorize_development:
            print("ERROR: Mode development-2022 requires --authorize-development flag.", file=sys.stderr)
            return 2
        run_development_2022(REPO_ROOT, args.audit_json, args.output_dir)
        return 0

    elif args.mode == "screen-2023":
        if not args.authorize_one_shot_2023_screen:
            print("ERROR: Mode screen-2023 requires --authorize-one-shot-2023-screen flag.", file=sys.stderr)
            return 2
        evidence_file = args.output_dir / "s4_stage1_2023_screen_evidence.json"
        if evidence_file.is_file():
            print(
                f"ERROR: Screen evidence {evidence_file} already exists. "
                f"Screen evidence is immutable and overwrite is prohibited to protect one-shot integrity.",
                file=sys.stderr,
            )
            return 2
        run_screen_2023(REPO_ROOT, args.audit_json, args.output_dir)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
