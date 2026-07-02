#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from btc_scraper.core.io import smart_read_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.feature_engineering.dataset_builder_v3 import DatasetBuilderV3, DatasetBuilderV3Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase 8 training dataset v3")
    parser.add_argument("--base", default="data/feature_store/derived/cross_sectional_features.parquet", help="Base frame path")
    parser.add_argument("--features", default="data/feature_store/derived/fracdiff_features.parquet,data/feature_store/derived/alternative_features.parquet", help="Comma-separated feature frame paths")
    parser.add_argument("--labels", default="", help="Optional labels frame path")
    parser.add_argument("--output", default="data/feature_store/training/ml_dataset_v3.parquet", help="Output dataset path")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--lookahead-bars", type=int, default=48)
    parser.add_argument("--label-type", default="triple_barrier_meta")
    parser.add_argument("--output-format", choices=["auto", "parquet", "csv"], default="auto")
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
            raise ValueError("JSON input must be dict/list or {records: [...]}")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return smart_read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def main() -> int:
    args = parse_args()
    base_path = Path(args.base)
    output_path = Path(args.output)

    if not base_path.exists():
        raise FileNotFoundError(f"Base frame does not exist: {base_path}")

    base_frame = load_frame(base_path)
    feature_frames: dict[str, pd.DataFrame] = {}
    for idx, raw_path in enumerate([p.strip() for p in args.features.split(",") if p.strip()]):
        p = Path(raw_path)
        if not p.exists():
            continue
        feature_frames[f"group_{idx + 1}_{p.stem}"] = load_frame(p)

    labels_frame = None
    if args.labels:
        labels_path = Path(args.labels)
        if not labels_path.exists():
            raise FileNotFoundError(f"Labels frame does not exist: {labels_path}")
        labels_frame = load_frame(labels_path)

    builder = DatasetBuilderV3(
        DatasetBuilderV3Config(
            timeframe=args.timeframe,
            lookahead_bars=int(args.lookahead_bars),
            label_type=args.label_type,
        )
    )

    dataset = builder.build(base_frame, feature_frames, labels_frame=labels_frame)
    dataset_path, metadata_path, metadata = builder.persist(dataset, output_path=output_path, output_format=args.output_format)

    print(f"Input base rows: {len(base_frame)}")
    print(f"Output rows: {len(dataset)}")
    print(f"Output cols: {len(dataset.columns)}")
    print(f"Saved dataset: {dataset_path}")
    print(f"Saved metadata: {metadata_path}")
    print(f"Dataset version: {metadata.get('dataset_version', {}).get('dataset_version', 'n/a')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
