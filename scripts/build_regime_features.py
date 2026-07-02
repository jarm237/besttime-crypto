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

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2
from btc_scraper.feature_engineering.regime_features import RegimeFeatureBuilder, RegimeFeatureConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build regime feature set for Phase 8")
    parser.add_argument("--input", default="logs/adaptive_signals_v2.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/regime/regime_features.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument("--transition-window", type=int, default=8)
    parser.add_argument("--high-vol-threshold", type=float, default=2.0)
    parser.add_argument("--low-vol-threshold", type=float, default=0.8)
    parser.add_argument("--output-format", choices=["auto", "parquet", "csv"], default="auto")
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        if not isinstance(raw, list):
            raise ValueError("JSON input must be a list of records")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def persist_output(frame: pd.DataFrame, output_path: Path, output_format: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format
    if fmt == "auto":
        fmt = "parquet" if output_path.suffix.lower() == ".parquet" else "csv"

    if fmt == "parquet":
        frame.to_parquet(output_path, index=False)
    else:
        frame.to_csv(output_path, index=False)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    frame = load_frame(input_path)

    builder = RegimeFeatureBuilder(
        RegimeFeatureConfig(
            transition_window=args.transition_window,
            high_vol_threshold=args.high_vol_threshold,
            low_vol_threshold=args.low_vol_threshold,
        )
    )
    out = builder.build(frame)

    persist_output(out, output_path, args.output_format)

    store = FeatureStoreV2()
    store.ensure_structure()
    store_fmt = args.output_format if args.output_format != "auto" else "parquet"
    try:
        store.save_table(out, layer="regime", name="regime_features", fmt=store_fmt)
    except Exception:
        store.save_table(out, layer="regime", name="regime_features", fmt="csv")

    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Saved regime features: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
