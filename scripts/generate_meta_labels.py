#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from btc_scraper.core.io import smart_read_csv

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2
from btc_scraper.feature_engineering.meta_labeling import MetaLabeler, MetaLabelingConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate meta labels and trade quality labels for Phase 8")
    parser.add_argument(
        "--input",
        default="data/feature_store/labels/triple_barrier_labels.parquet",
        help="Input labeled dataset from triple barrier step (.json/.csv/.parquet)",
    )
    parser.add_argument(
        "--output-meta",
        default="data/feature_store/labels/meta_labels.parquet",
        help="Meta labels output path (.parquet/.csv)",
    )
    parser.add_argument(
        "--output-trade-quality",
        default="data/feature_store/labels/trade_quality_labels.parquet",
        help="Trade quality labels output path (.parquet/.csv)",
    )
    parser.add_argument(
        "--exclude-neutral",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude neutral/non-executable signals from meta_label training target",
    )
    parser.add_argument("--max-holding-bars", type=int, default=48)
    parser.add_argument(
        "--output-format",
        choices=["auto", "parquet", "csv"],
        default="auto",
        help="Persist format for outputs and feature store",
    )
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
    output_meta_path = Path(args.output_meta)
    output_trade_quality_path = Path(args.output_trade_quality)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    data = load_frame(input_path)
    required = {"triple_barrier_label"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Input missing required columns: {sorted(missing)}")

    labeler = MetaLabeler(
        MetaLabelingConfig(
            exclude_neutral=bool(args.exclude_neutral),
            max_holding_bars=int(args.max_holding_bars),
        )
    )
    labeled = labeler.label(data)

    meta_cols = [
        "coin",
        "entry_time",
        "primary_signal",
        "primary_direction",
        "triple_barrier_label",
        "meta_label",
        "meta_label_reason",
    ]
    trade_quality_cols = [
        "coin",
        "entry_time",
        "primary_signal",
        "primary_direction",
        "trade_quality_score",
        "trade_quality_bucket",
        "barrier_return_pct",
        "barrier_mae_pct",
        "barrier_hold_bars",
    ]

    meta_out = labeled[[c for c in meta_cols if c in labeled.columns]].copy()
    trade_quality_out = labeled[[c for c in trade_quality_cols if c in labeled.columns]].copy()

    persist_output(meta_out, output_meta_path, args.output_format)
    persist_output(trade_quality_out, output_trade_quality_path, args.output_format)

    store = FeatureStoreV2()
    store.ensure_structure()

    store_fmt = args.output_format if args.output_format != "auto" else "parquet"
    try:
        store.save_table(meta_out, layer="labels", name="meta_labels", fmt=store_fmt)
        store.save_table(trade_quality_out, layer="labels", name="trade_quality_labels", fmt=store_fmt)
    except Exception:
        store.save_table(meta_out, layer="labels", name="meta_labels", fmt="csv")
        store.save_table(trade_quality_out, layer="labels", name="trade_quality_labels", fmt="csv")

    meta_dist = meta_out["meta_label"].value_counts(dropna=False).to_dict() if "meta_label" in meta_out.columns else {}
    bucket_dist = (
        trade_quality_out["trade_quality_bucket"].value_counts(dropna=False).to_dict()
        if "trade_quality_bucket" in trade_quality_out.columns
        else {}
    )

    print(f"Input rows: {len(data)}")
    print(f"Meta label rows: {len(meta_out)}")
    print(f"Trade quality rows: {len(trade_quality_out)}")
    print(f"Saved meta labels: {output_meta_path}")
    print(f"Saved trade quality labels: {output_trade_quality_path}")
    print(f"Meta label distribution: {meta_dist}")
    print(f"Trade quality bucket distribution: {bucket_dist}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
