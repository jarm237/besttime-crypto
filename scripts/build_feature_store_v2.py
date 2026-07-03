#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize Phase 8 Feature Store v2 folders and metadata")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Optional feature store root path (default: data/feature_store)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = FeatureStoreV2(root=args.root)
    store.ensure_structure()

    bootstrap_metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": "phase8_feature_store_v2",
        "layers": sorted(
            [
                "raw",
                "clean",
                "normalized",
                "labels",
                "derived",
                "causal",
                "regime",
                "training",
            ]
        ),
    }

    bootstrap_path = store.root / "feature_store_v2.bootstrap.json"
    bootstrap_path.write_text(json.dumps(bootstrap_metadata, indent=2), encoding="utf-8")

    print(f"Feature Store v2 ready at: {store.root}")
    print(f"Bootstrap metadata: {bootstrap_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
