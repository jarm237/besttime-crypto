#!/usr/bin/env python3
"""Retrain twice on identical inputs and compare deterministic evidence fields."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.ml_engine.meta_model_v3 import MetaModelV3Config, train_from_dataset_v3

NUMERIC_TOLERANCE = 1e-12


def _projection(metrics: dict) -> dict:
    return {
        "training_fingerprint": metrics["training_fingerprint"],
        "feature_schema_version": metrics["feature_schema_version"],
        "split_manifest_sha256": metrics["split_manifest_sha256"],
        "calibration_method": metrics["calibration_method"],
        "calibration_selection_metrics": metrics["calibration_selection_metrics"],
        "test_metrics": metrics["test_metrics"],
        "calibration_evidence": metrics["calibration_evidence"],
        "walk_forward": metrics["walk_forward"],
        "cv_holdout_gap": metrics["cv_holdout_gap"],
    }


def _numeric_deltas(first: object, second: object, path: str = "") -> tuple[list[str], list[float]]:
    mismatches: list[str] = []
    deltas: list[float] = []
    if isinstance(first, dict) and isinstance(second, dict):
        if set(first) != set(second):
            return [f"{path}:keys"], deltas
        for key in first:
            child_mismatches, child_deltas = _numeric_deltas(first[key], second[key], f"{path}.{key}")
            mismatches.extend(child_mismatches)
            deltas.extend(child_deltas)
    elif isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            return [f"{path}:length"], deltas
        for index, (left, right) in enumerate(zip(first, second)):
            child_mismatches, child_deltas = _numeric_deltas(left, right, f"{path}[{index}]")
            mismatches.extend(child_mismatches)
            deltas.extend(child_deltas)
    elif (
        isinstance(first, (int, float)) and not isinstance(first, bool)
        and isinstance(second, (int, float)) and not isinstance(second, bool)
    ):
        delta = abs(float(first) - float(second))
        deltas.append(delta)
        if delta > NUMERIC_TOLERANCE:
            mismatches.append(f"{path}:{first!r}!={second!r}")
    elif first != second:
        mismatches.append(f"{path}:{first!r}!={second!r}")
    return mismatches, deltas


def _apply_comparison(report: dict) -> dict:
    mismatches, deltas = _numeric_deltas(report["run_1"], report["run_2"])
    report["repeatable"] = not mismatches
    report["numeric_tolerance"] = NUMERIC_TOLERANCE
    report["maximum_numeric_delta"] = max(deltas, default=0.0)
    report["material_mismatches"] = mismatches
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/feature_store/training/ml_dataset_v3.parquet")
    parser.add_argument("--label-column", default="meta_label")
    parser.add_argument("--positive-label", default="1")
    parser.add_argument(
        "--report",
        default="evaluations/ml_engine_remediation_20260723/meta_model_repeatability_report.json",
    )
    parser.add_argument(
        "--recheck-existing",
        action="store_true",
        help="Re-evaluate the two already persisted runs without retraining",
    )
    args = parser.parse_args()
    report_path = Path(args.report)
    if args.recheck_existing:
        report = _apply_comparison(json.loads(report_path.read_text(encoding="utf-8")))
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "repeatable": report["repeatable"],
            "maximum_numeric_delta": report["maximum_numeric_delta"],
            "report": str(report_path),
        }, indent=2))
        return 0 if report["repeatable"] else 1
    dataset = Path(args.dataset)
    config = MetaModelV3Config(
        label_column=args.label_column,
        positive_label=args.positive_label,
    )
    with tempfile.TemporaryDirectory(prefix="meta-v3-repeatability-") as temp:
        root = Path(temp)
        first = train_from_dataset_v3(dataset, root / "run-1", config)["metrics"]
        second = train_from_dataset_v3(dataset, root / "run-2", config)["metrics"]
    first_projection, second_projection = _projection(first), _projection(second)
    report = _apply_comparison({
        "comparison_scope": "deterministic metrics, splits, schemas and training fingerprint",
        "dataset_sha256": first["dataset_sha256"],
        "training_fingerprint": first["training_fingerprint"],
        "run_1_artifact_sha256": first["artifact_sha256"],
        "run_2_artifact_sha256": second["artifact_sha256"],
        "artifact_byte_identity_expected": False,
        "reason_artifact_bytes_may_differ": "UTC creation metadata is embedded in each governed bundle",
        "run_1": first_projection,
        "run_2": second_projection,
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "repeatable": report["repeatable"],
        "training_fingerprint": report["training_fingerprint"],
        "report": str(report_path),
    }, indent=2))
    return 0 if report["repeatable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
