#!/usr/bin/env python3
"""S4-P1A Forecasting CLI: Preflight Verification, 2022 Development, and 2023 Screening.

Pre-registration: research/s4_forecast_information_screening/s4_p0_executable_preregistration.md
Frozen commit: 7b5a97becbd6da1249a484ed588133761cc57bd0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    ChronologicalSplitter,
    FeatureScaler,
    ForecastError,
    ProtocolViolationError,
    RidgeBaseline,
    TrainingConfig,
    build_neural_forecaster,
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
    for fold in folds:
        purged = ChronologicalSplitter.get_purged_fit_dates(fold)
        purged_counts[fold.name] = len(purged)

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
        "full_dev_count": len(full_dev),
        "last_dev_decision": str(full_dev[-1]),
        "screen_count": len(screen_dates),
        "last_screen_decision": str(screen_dates[-1]),
    }

    results["verdict"] = "PASS"
    results["next_step"] = "S4-P1B_2022_DEVELOPMENT_AND_FITTING (not executed in this task)"
    return results


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
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow overwriting completed screen evidence",
    )

    args = parser.parse_args()

    if args.mode == "preflight":
        print(f"=== S4-P1A PREFLIGHT VERIFICATION ===")
        print(f"Pre-registration commit: {S4_PREREGISTRATION_COMMIT}")
        result = run_preflight(REPO_ROOT, args.audit_json)
        print(json.dumps(result, indent=2))
        print("PREFLIGHT_STATUS = PASS")
        print("STOP RULE ACTIVE: No model training or 2023 screening executed.")
        return 0

    elif args.mode == "development-2022":
        if not args.authorize_development:
            print("ERROR: Mode development-2022 requires --authorize-development flag.", file=sys.stderr)
            print("Under S4-P1A scope, real model training is NOT authorized.", file=sys.stderr)
            return 2
        print("ERROR: 2022 development run belongs to task S4-P1B.", file=sys.stderr)
        return 2

    elif args.mode == "screen-2023":
        if not args.authorize_one-shot-2023-screen:
            print("ERROR: Mode screen-2023 requires --authorize-one-shot-2023-screen flag.", file=sys.stderr)
            return 2
        evidence_file = args.output_dir / "s4_stage1_2023_screen_evidence.json"
        if evidence_file.is_file() and not args.force:
            print(f"ERROR: Screen evidence {evidence_file} already exists. Refusing to overwrite.", file=sys.stderr)
            return 2
        print("ERROR: 2023 screening requires frozen model artifacts from S4-P1B.", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
