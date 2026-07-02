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

from btc_scraper.feature_engineering.label_quality import LabelQualityConfig, LabelQualityReporter


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("JSON input must be dict/list or {records:[...]}")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return smart_read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase 8 label quality report")
    parser.add_argument("--triple", default="data/feature_store/labels/triple_barrier_labels.parquet")
    parser.add_argument("--meta", default="data/feature_store/labels/meta_labels.parquet")
    parser.add_argument("--trade-quality", default="data/feature_store/labels/trade_quality_labels.parquet")
    parser.add_argument("--fallback", default="data/feature_store/training/ml_dataset_v3.parquet")
    parser.add_argument("--output", default="data/feature_store/labels/label_quality_report.json")
    parser.add_argument("--min-samples-warning", type=int, default=50)
    parser.add_argument("--severe-imbalance-ratio", type=float, default=4.0)
    return parser.parse_args()


def _read_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return load_frame(path)


def main() -> int:
    args = parse_args()
    triple_path = Path(args.triple)
    meta_path = Path(args.meta)
    tq_path = Path(args.trade_quality)
    fallback_path = Path(args.fallback)
    output_path = Path(args.output)

    triple = _read_if_exists(triple_path)
    meta = _read_if_exists(meta_path)
    trade_q = _read_if_exists(tq_path)
    fallback = _read_if_exists(fallback_path)

    if triple is None and meta is None and trade_q is None and fallback is None:
        raise FileNotFoundError("No label or fallback input found for report generation")

    reporter = LabelQualityReporter(
        LabelQualityConfig(
            min_samples_warning=int(args.min_samples_warning),
            severe_imbalance_ratio=float(args.severe_imbalance_ratio),
        )
    )
    report = reporter.build_report(
        triple_labels=triple,
        meta_labels=meta,
        trade_quality=trade_q,
        fallback_frame=fallback,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Saved report: {output_path}")
    print(f"Triple rows: {report['counts']['triple_barrier_rows']}")
    print(f"Meta rows: {report['counts']['meta_label_rows']}")
    print(f"Warnings: {len(report.get('warnings', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
