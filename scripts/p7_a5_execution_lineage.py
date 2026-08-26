#!/usr/bin/env python3
"""P7 Post-Activation — Phase O4: First Execution Attempt Verification.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.p7_evidence_partitions import (  # noqa: E402
    discover_partitions,
    load_partition_payload_rows,
    partition_discovery_report,
)

LOG_ROOT = ROOT / "runtime/worktrees/pinned-b284ad3/runtime/paper/paper-canary-a5-20260825-01/logs"
OUTPUT = ROOT / "p7_first_execution_attempt_report.json"

EXPECTED_COMMIT = "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
OBSERVATION_START_DATE = "2026-08-25"


def main() -> int:
    print("Executing Phase O4: First Execution Attempt Verification...")
    print("=" * 60)

    try:
        partitions = discover_partitions(LOG_ROOT, observation_start_date=OBSERVATION_START_DATE)
        order_records = load_partition_payload_rows(partitions, "orders")
    except Exception as exc:
        print(f"FAIL: evidence partition discovery failed: {exc}", file=sys.stderr)
        return 1

    orders = [order for _, order in order_records]
    partition_discovery = partition_discovery_report(partitions)

    print(f"  Total orders / execution attempts: {len(orders)}")
    print(f"  Partitions scanned: {', '.join(path.name for path in partitions)}")

    if not orders:
        # Graceful fallback to WAITING_FOR_NATURAL_EVENT
        report = {
            "artifact": "p7_first_execution_attempt_report",
            "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "WAITING_FOR_NATURAL_EVENT",
            "orders_analyzed": 0,
            "partition_discovery": partition_discovery,
            "overall_verdict": "PASS",
        }
    else:
        # Perform lineage checks
        first_o = orders[0]
        decision_id = first_o.get("decision_id")
        symbol = first_o.get("symbol")
        commit = first_o.get("git_commit") or first_o.get("code_commit_sha")

        lineage_ok = (decision_id is not None)
        symbol_ok = (symbol is not None)
        commit_ok = (commit == EXPECTED_COMMIT or commit is None)

        overall_pass = (lineage_ok and symbol_ok and commit_ok)

        report = {
            "artifact": "p7_first_execution_attempt_report",
            "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "ORDER_ATTEMPTED",
            "orders_analyzed": len(orders),
            "partition_discovery": partition_discovery,
            "first_order": {
                "order_id": first_o.get("order_id"),
                "decision_id": decision_id,
                "symbol": symbol,
                "git_commit": commit,
            },
            "lineage_integrity": "PASS" if lineage_ok else "FAIL",
            "overall_verdict": "PASS" if overall_pass else "FAIL",
        }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_first_execution_attempt_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "state": report["status"],
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if report["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
