#!/usr/bin/env python3
"""Generate Gate A runtime evidence from paper producer JSON/JSONL exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from btc_scraper.ml_engine.gate_a_runtime_evidence import (
    evaluate_gate_a_runtime_evidence,
    write_gate_a_runtime_evidence,
)


PRODUCER_ARGS = {
    "prediction": "prediction",
    "entry-decision": "entry_decision",
    "reservation": "reservation",
    "submitted-order": "submitted_order",
    "fill": "fill",
    "open-position": "open_position",
    "closed-outcome": "closed_outcome",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in PRODUCER_ARGS:
        parser.add_argument(f"--{flag}", action="append", default=[], help="JSON or JSONL file for this producer; may be repeated")
    parser.add_argument("--prediction-events", action="append", default=[], help="Prediction rows for runtime outcome linkage")
    parser.add_argument("--outcomes", action="append", default=[], help="Outcome rows for runtime outcome linkage")
    parser.add_argument("--min-closed-positions", type=int, default=20)
    parser.add_argument("--lifecycle-e2e-passed", action="store_true")
    parser.add_argument("--recovery-tests-passed", action="store_true")
    parser.add_argument("--output-dir", default="logs/runtime_linkage")
    args = parser.parse_args()

    events_by_producer = {
        producer: _load_many(getattr(args, flag.replace("-", "_")))
        for flag, producer in PRODUCER_ARGS.items()
    }
    result = evaluate_gate_a_runtime_evidence(
        events_by_producer=events_by_producer,
        predictions=_load_many(args.prediction_events or args.prediction),
        outcomes=_load_many(args.outcomes or args.closed_outcome),
        lifecycle_e2e_passed=args.lifecycle_e2e_passed,
        recovery_tests_passed=args.recovery_tests_passed,
        min_closed_positions=args.min_closed_positions,
    )
    output_path = write_gate_a_runtime_evidence(result, args.output_dir)
    print(json.dumps({
        "ready": result.ready,
        "blockers": list(result.blockers),
        "output_path": str(output_path),
        "gate_snapshot_hash": result.gate_snapshot.snapshot_hash() if result.gate_snapshot else None,
    }, indent=2, ensure_ascii=False))
    return 0 if result.ready else 2


def _load_many(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_load_file(Path(path)))
    return rows


def _load_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return [dict(row) for row in json.loads(text)]
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(dict(json.loads(line)))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
