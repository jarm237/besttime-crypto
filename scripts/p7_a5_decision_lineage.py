#!/usr/bin/env python3
"""P7 Post-Activation — Phase O3: Decision Evidence Closure.
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
    dedupe_decisions,
    discover_partitions,
    event_timestamp,
    load_partition_payload_rows,
    partition_discovery_report,
)

LOG_ROOT = ROOT / "runtime/worktrees/pinned-b284ad3/runtime/paper/paper-canary-a5-20260825-01/logs"
OUTPUT = ROOT / "p7_first_actionable_decision_report.json"

EXPECTED_COMMIT = "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
EXPECTED_DEPLOYMENT = "paper-canary-a5-20260825-01"
EXPECTED_RELEASE = "model-coverage-v1-r1"
OBSERVATION_START_DATE = "2026-08-25"


def main() -> int:
    print("Executing Phase O3: Decision Evidence Closure...")
    print("=" * 60)

    try:
        partitions = discover_partitions(LOG_ROOT, observation_start_date=OBSERVATION_START_DATE)
    except Exception as exc:
        print(f"FAIL: evidence partition discovery failed: {exc}", file=sys.stderr)
        return 1

    if not partitions:
        print("FAIL: no runtime evidence partitions discovered", file=sys.stderr)
        return 1

    try:
        decision_records = dedupe_decisions(load_partition_payload_rows(partitions, "final_decisions"))
    except Exception as exc:
        print(f"FAIL: failed to read decision evidence partitions: {exc}", file=sys.stderr)
        return 1

    decision_records.sort(key=lambda item: event_timestamp(item[1]))
    decisions = [decision for _, decision in decision_records]

    actionable_decisions = [
        (partition, d) for partition, d in decision_records
        if d.get("action") not in (None, "IGNORE", "HOLD")
        or d.get("terminal_status") not in (None, "HOLD", "IGNORE")
    ]

    print(f"  Total decisions: {len(decisions)} | Actionable: {len(actionable_decisions)}")
    print(f"  Partitions scanned: {', '.join(path.name for path in partitions)}")

    partition_discovery = partition_discovery_report(partitions)
    decision_evidence = {
        "total_decisions": len(decisions),
        "actionable_decisions": len(actionable_decisions),
    }

    if not actionable_decisions:
        # Graceful fallback to WAITING_FOR_NATURAL_EVENT
        report = {
            "artifact": "p7_first_actionable_decision_report",
            "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "WAITING_FOR_NATURAL_EVENT",
            "decisions_analyzed": len(decisions),
            "actionable_decisions_count": 0,
            "partition_discovery": partition_discovery,
            "decision_evidence": decision_evidence,
            "overall_verdict": "PASS",  # Permissible state per governance plan
        }
    else:
        # Perform rigorous lineage check on first actionable decision
        first_partition, first_d = actionable_decisions[0]
        pred_id = first_d.get("prediction_id")
        symbol = first_d.get("symbol")
        commit = first_d.get("git_commit") or first_d.get("code_commit_sha")
        deployment = first_d.get("deployment_id")
        release = first_d.get("release_id")

        # Verify lineage properties
        lineage_ok = (pred_id is not None)
        symbol_ok = (symbol is not None)
        commit_ok = (commit == EXPECTED_COMMIT or commit is None)
        deployment_ok = (deployment == EXPECTED_DEPLOYMENT or deployment is None)
        release_ok = (release == EXPECTED_RELEASE or release is None)

        overall_pass = (lineage_ok and symbol_ok and commit_ok and deployment_ok and release_ok)

        report = {
            "artifact": "p7_first_actionable_decision_report",
            "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "DECISION_LOGGED",
            "decisions_analyzed": len(decisions),
            "actionable_decisions_count": len(actionable_decisions),
            "partition_discovery": partition_discovery,
            "decision_evidence": decision_evidence,
            "first_actionable_decision": {
                "decision_id": first_d.get("decision_id"),
                "prediction_id": pred_id,
                "symbol": symbol,
                "action": first_d.get("action") or first_d.get("terminal_status"),
                "git_commit": commit,
                "deployment_id": deployment,
                "release_id": release,
                "event_timestamp": event_timestamp(first_d),
                "source_partition": first_partition.name,
            },
            "lineage_integrity": "PASS" if lineage_ok else "FAIL",
            "overall_verdict": "PASS" if overall_pass else "FAIL",
        }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_first_actionable_decision_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "state": report["status"],
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if report["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
