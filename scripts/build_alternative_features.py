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

from btc_scraper.feature_engineering.alternative_features import AlternativeFeatureBuilder, AlternativeFeatureConfig
from btc_scraper.feature_engineering.feature_store import FeatureStoreV2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build alternative-data features for Phase 8")
    parser.add_argument("--input", default="data/alternative_data.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/derived/alternative_features.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument(
        "--quality-report",
        default="data/feature_store/derived/alternative_feature_quality_report.json",
        help="Quality report JSON path",
    )
    parser.add_argument("--zscore-window", type=int, default=24)
    parser.add_argument("--momentum-window", type=int, default=4)
    parser.add_argument("--output-format", choices=["auto", "parquet", "csv"], default="auto")
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("JSON input must be a dict or a list of records")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def persist_output(frame: pd.DataFrame, output_path: Path, output_format: str) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format
    if fmt == "auto":
        fmt = "parquet" if output_path.suffix.lower() == ".parquet" else "csv"

    if fmt == "parquet":
        frame.to_parquet(output_path, index=False)
    else:
        frame.to_csv(output_path, index=False)
    return fmt


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    quality_report_path = Path(args.quality_report)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    frame = load_frame(input_path)

    builder = AlternativeFeatureBuilder(
        AlternativeFeatureConfig(
            zscore_window=args.zscore_window,
            momentum_window=args.momentum_window,
        )
    )
    out = builder.build(frame)

    resolved_fmt = persist_output(out, output_path, args.output_format)

    quality_report_path.parent.mkdir(parents=True, exist_ok=True)
    quality_report = builder.get_quality_report()
    quality_report_path.write_text(json.dumps(quality_report, indent=2), encoding="utf-8")

    store = FeatureStoreV2()
    store.ensure_structure()
    store_fmt = resolved_fmt
    try:
        store.save_table(out, layer="derived", name="alternative_features", fmt=store_fmt)
    except Exception:
        store.save_table(out, layer="derived", name="alternative_features", fmt="csv")

    generated = len([col for col in out.columns if col.startswith("alt_")])
    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Generated alternative features: {generated}")
    print(f"Saved alternative features: {output_path}")
    print(f"Saved quality report: {quality_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
