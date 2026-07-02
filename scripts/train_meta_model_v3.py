#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.ml_engine.meta_model_v3 import MetaModelV3Config, train_from_dataset_v3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Meta Model v3 using Dataset Builder v3 output")
    parser.add_argument(
        "--dataset",
        default="data/feature_store/training/ml_dataset_v3.parquet",
        help="Path to Sprint 9 dataset parquet",
    )
    parser.add_argument(
        "--output-dir",
        default="logs",
        help="Directory to write Sprint 10 deliverables",
    )
    parser.add_argument("--label-column", default="result")
    parser.add_argument("--positive-label", default="WIN")
    parser.add_argument("--time-column", default="entry_time")
    parser.add_argument("--coin-column", default="coin")
    parser.add_argument("--no-calibration", action="store_true")
    parser.add_argument("--walk-forward-splits", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset does not exist: {dataset_path}")

    cfg = MetaModelV3Config(
        label_column=args.label_column,
        positive_label=args.positive_label,
        time_column=args.time_column,
        coin_column=args.coin_column,
        calibration=not args.no_calibration,
        walk_forward_splits=int(args.walk_forward_splits),
    )
    out = train_from_dataset_v3(dataset_path=dataset_path, output_dir=output_dir, config=cfg)
    metrics = out["metrics"]

    print(f"Samples: {metrics['n_samples']}")
    print(f"Features: {metrics['n_features']}")
    print(f"Test ROC-AUC: {metrics['test_metrics']['roc_auc']}")
    print(f"Test Accuracy: {metrics['test_metrics']['accuracy']:.4f}")
    print(f"Walk-forward windows: {len(metrics['walk_forward'])}")
    print(f"Model comparison delta ROC-AUC: {metrics['model_comparison']['delta_roc_auc']}")
    print(f"Saved: {out['model_path']}")
    print(f"Saved: {out['metrics_path']}")
    print(f"Saved: {out['calibration_path']}")
    print(f"Saved: {out['importance_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
