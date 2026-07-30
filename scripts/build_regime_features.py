#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from btc_scraper.core.io import smart_read_csv

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2
from btc_scraper.feature_engineering.regime_features import RegimeFeatureBuilder, RegimeFeatureConfig
from btc_scraper.regime.config import compute_regime_config_sha256


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build regime feature set for Phase 8")
    parser.add_argument("--input", default="logs/adaptive_signals_v2.json", help="Input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/regime/v2/regime_features_v2.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument("--store-name", default="regime_features_v2")
    parser.add_argument(
        "--manifest",
        default="data/feature_store/regime/v2/regime_features_v2.manifest.json",
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    input_rows: int,
    output_rows: int,
    store_path: Path,
) -> None:
    payload = {
        "artifact_version": "regime_features_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path.resolve()),
        "input_sha256": file_sha256(input_path),
        "input_rows": int(input_rows),
        "output_path": str(output_path.resolve()),
        "output_sha256": file_sha256(output_path),
        "output_rows": int(output_rows),
        "store_path": str(store_path.resolve()),
        "regime_config_sha256": compute_regime_config_sha256(),
        "taxonomy_version": "2.0",
        "mapping_version": "2.0",
        "promotion_status": "RESEARCH_ONLY",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)


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
        store_path = store.save_table(out, layer="regime", name=args.store_name, fmt=store_fmt)
    except Exception:
        store_path = store.save_table(out, layer="regime", name=args.store_name, fmt="csv")

    write_manifest(
        input_path=input_path,
        output_path=output_path,
        manifest_path=Path(args.manifest),
        input_rows=len(frame),
        output_rows=len(out),
        store_path=store_path,
    )

    print(f"Input rows: {len(frame)}")
    print(f"Output rows: {len(out)}")
    print(f"Saved regime features: {output_path}")
    print(f"Saved manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
