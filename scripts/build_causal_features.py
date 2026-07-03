#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from btc_scraper.core.io import smart_read_csv

from btc_scraper.feature_engineering.causal_features import CausalFeatureBuilder, CausalFeatureConfig
from btc_scraper.feature_engineering.feature_store import FeatureStoreV2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build causal feature set for Phase 8")
    parser.add_argument("--input", default="logs/adaptive_signals_v2.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/causal/causal_features.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument("--default-causal-alpha", type=float, default=0.0)
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
        return smart_read_csv(path)
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

    builder = CausalFeatureBuilder(CausalFeatureConfig(default_causal_alpha=args.default_causal_alpha))
    out = builder.build(frame)

    persist_output(out, output_path, args.output_format)

    store = FeatureStoreV2()
    store.ensure_structure()
    store_fmt = args.output_format if args.output_format != "auto" else "parquet"
    try:
        store.save_table(out, layer="causal", name="causal_features", fmt=store_fmt)
    except Exception:
        store.save_table(out, layer="causal", name="causal_features", fmt="csv")

    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Saved causal features: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
