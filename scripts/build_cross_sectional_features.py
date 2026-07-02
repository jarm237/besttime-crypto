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

from btc_scraper.feature_engineering.cross_sectional_features import (
    CrossSectionalFeatureBuilder,
    CrossSectionalFeatureConfig,
)
from btc_scraper.feature_engineering.feature_store import FeatureStoreV2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cross-sectional features for Phase 8")
    parser.add_argument("--input", default="logs/adaptive_signals_v2.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/derived/cross_sectional_features.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument("--return-window", type=int, default=4)
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
            raise ValueError("JSON input must be a dict/list or {records: [...]} payload")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return smart_read_csv(path)
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

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    frame = load_frame(input_path)
    builder = CrossSectionalFeatureBuilder(CrossSectionalFeatureConfig(return_window=args.return_window))
    out = builder.build(frame)

    resolved_fmt = persist_output(out, output_path, args.output_format)

    store = FeatureStoreV2()
    store.ensure_structure()
    try:
        store.save_table(out, layer="derived", name="cross_sectional_features", fmt=resolved_fmt)
    except Exception:
        store.save_table(out, layer="derived", name="cross_sectional_features", fmt="csv")

    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Saved cross-sectional features: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
