"""Verify a prediction snapshot's feature hash and print replay input."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from btc_scraper.ml_engine.prediction_logger import feature_hash

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction_id")
    parser.add_argument("--dir", default="logs/prediction_audit")
    args = parser.parse_args()
    for path in sorted(Path(args.dir).glob("feature_snapshots_*.jsonl"), reverse=True):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("prediction_id") == args.prediction_id:
                if feature_hash(row["features"]) != row["feature_hash"]: raise SystemExit("feature hash mismatch")
                print(json.dumps(row, ensure_ascii=False, indent=2)); return
    raise SystemExit("prediction snapshot not found")
if __name__ == "__main__": main()
