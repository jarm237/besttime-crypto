#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.feature_engineering.feature_validator import FeatureValidationConfig, FeatureValidator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Phase 8 feature quality and rejection reports")
    parser.add_argument("--input", default="data/feature_store/derived/fracdiff_features.parquet", help="Input dataset")
    parser.add_argument("--reference", default="", help="Optional reference dataset for PSI")
    parser.add_argument(
        "--quality-output",
        default="data/feature_store/derived/feature_quality_report.json",
        help="Feature quality report path",
    )
    parser.add_argument(
        "--rejection-output",
        default="data/feature_store/derived/feature_rejection_report.json",
        help="Feature rejection report path",
    )
    parser.add_argument("--time-col", default="entry_time")
    parser.add_argument("--missing-threshold", type=float, default=0.30)
    parser.add_argument("--corr-threshold", type=float, default=0.95)
    parser.add_argument("--leakage-corr-threshold", type=float, default=0.995)
    parser.add_argument("--psi-threshold", type=float, default=0.20)
    parser.add_argument("--psi-reject-threshold", type=float, default=0.40)
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("JSON input must be a dict/list or {records: [...]} payload")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    quality_output = Path(args.quality_output)
    rejection_output = Path(args.rejection_output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    frame = load_frame(input_path)
    reference_frame = None
    if args.reference:
        reference_path = Path(args.reference)
        if not reference_path.exists():
            raise FileNotFoundError(f"Reference does not exist: {reference_path}")
        reference_frame = load_frame(reference_path)

    validator = FeatureValidator(
        FeatureValidationConfig(
            max_missing_rate=args.missing_threshold,
            correlation_threshold=args.corr_threshold,
            leakage_corr_threshold=args.leakage_corr_threshold,
            psi_threshold=args.psi_threshold,
            psi_reject_threshold=args.psi_reject_threshold,
        )
    )
    quality_report, rejection_report = validator.validate(
        frame,
        time_col=args.time_col,
        reference_frame=reference_frame,
    )

    quality_output.parent.mkdir(parents=True, exist_ok=True)
    rejection_output.parent.mkdir(parents=True, exist_ok=True)
    quality_output.write_text(json.dumps(quality_report, indent=2), encoding="utf-8")
    rejection_output.write_text(json.dumps(rejection_report, indent=2), encoding="utf-8")

    print(f"Input rows: {len(frame)}")
    print(f"Quality report: {quality_output}")
    print(f"Rejection report: {rejection_output}")
    print(f"Rejected features: {rejection_report.get('rejected_feature_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
