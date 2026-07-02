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
from btc_scraper.feature_engineering.fractional_diff import FractionalDiffBuilder, FractionalDiffConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build fractional differencing features for Phase 8")
    parser.add_argument("--input", default="logs/adaptive_signals_v2.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/derived/fracdiff_features.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument(
        "--report",
        default="data/feature_store/derived/fracdiff_report.json",
        help="Stationarity report output path",
    )
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--d-candidates", default="0.0,0.2,0.4,0.6,0.8")
    parser.add_argument("--adf-critical", type=float, default=-2.86)
    parser.add_argument("--disable", action="store_true", help="Disable fractional differencing and pass through input")
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
    report_path = Path(args.report)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")

    frame = load_frame(input_path)
    d_candidates = [float(x.strip()) for x in args.d_candidates.split(",") if x.strip()]

    builder = FractionalDiffBuilder(
        FractionalDiffConfig(
            enabled=not bool(args.disable),
            d_candidates=d_candidates,
            adf_critical_value=float(args.adf_critical),
        )
    )
    out = builder.build(frame, timeframe=args.timeframe)

    resolved_fmt = persist_output(out, output_path, args.output_format)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(builder.get_report(), indent=2), encoding="utf-8")

    store = FeatureStoreV2()
    store.ensure_structure()
    try:
        store.save_table(out, layer="derived", name="fracdiff_features", fmt=resolved_fmt)
    except Exception:
        store.save_table(out, layer="derived", name="fracdiff_features", fmt="csv")

    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Saved fracdiff features: {output_path}")
    print(f"Saved fracdiff report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
