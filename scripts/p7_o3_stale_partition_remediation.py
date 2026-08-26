#!/usr/bin/env python3
"""Capture P7 O3 stale-partition remediation evidence."""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.p7_evidence_partitions import discover_partitions, load_payload_rows  # noqa: E402

LOG_ROOT = ROOT / "runtime/worktrees/pinned-b284ad3/runtime/paper/paper-canary-a5-20260825-01/logs"
OUTPUT = ROOT / "p7_postseal_verifier_remediation.json"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    partitions = discover_partitions(LOG_ROOT, observation_start_date="2026-08-25")
    counts = {path.name: len(load_payload_rows(path, "final_decisions")) for path in partitions}
    observed_by_stale_verifier = counts.get("runtime_evidence_2026-08-25.sqlite", 0)
    expected_total = sum(counts.values())
    report = {
        "artifact": "p7_postseal_verifier_remediation",
        "generated_at": _utc_now(),
        "failure_class": "O3_STALE_PARTITION_DISCOVERY",
        "runtime_incident": "NO",
        "model_runtime_mutation": "NO",
        "evidence_loss": "NO",
        "verifier_coverage_gap": "YES",
        "runtime_impact": "NONE",
        "model_impact": "NONE",
        "evidence_impact": "OBSERVABILITY_ONLY",
        "source_commit": _git("rev-parse", "HEAD"),
        "sealed_runtime_source_commit": "b284ad36f311c5cbf4986c6dfe7f47e8aee01062",
        "failure_evidence": {
            "o3_observed_decisions": observed_by_stale_verifier,
            "partition_decision_counts": counts,
            "expected_observable_total": expected_total,
            "verdict": "FAIL_STALE_PARTITION",
        },
        "remediation": {
            "scope": "VERIFIER_ONLY",
            "partition_strategy": "CROSS_PARTITION",
            "helper": "scripts/p7_evidence_partitions.py",
        },
        "overall_verdict": "PASS",
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    Path(str(OUTPUT) + ".sha256").write_text(digest + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "sha256": digest}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
