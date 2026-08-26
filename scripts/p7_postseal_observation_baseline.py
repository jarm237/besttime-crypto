#!/usr/bin/env python3
"""P7 Post-Seal baseline checkpoint for event-driven observation."""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "p7_postseal_observation_baseline.json"

IDENTITY_REPORT = ROOT / "p7_attempt5_runtime_identity_contract.json"
FINAL_VERDICT = ROOT / "p7_final_verdict.json"
ALLOWLIST = ROOT / "p7_o8_failure_allowlist.json"
PARTITION_DB = ROOT / "runtime/worktrees/pinned-b284ad3/runtime/paper/paper-canary-a5-20260825-01/logs/runtime_evidence_2026-08-25.sqlite"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def _json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    identity = _json(IDENTITY_REPORT)
    final_verdict = _json(FINAL_VERDICT)
    git_status = _run_git("status", "--short")

    required_hashes = {
        "runtime_identity_contract": _sha256_file(IDENTITY_REPORT),
        "final_seal_verdict": _sha256_file(FINAL_VERDICT),
        "allowlist_o8": _sha256_file(ALLOWLIST),
        "runtime_evidence_partition": _sha256_file(PARTITION_DB),
    }

    blockers = []
    if not IDENTITY_REPORT.exists():
        blockers.append("runtime identity contract missing")
    if not FINAL_VERDICT.exists():
        blockers.append("final seal verdict missing")
    if final_verdict.get("P7_FINAL_SEAL") != "PASS":
        blockers.append("P7 final seal is not PASS")
    if final_verdict.get("P7") != "OPEN":
        blockers.append("P7 is not OPEN for event-driven observation")
    if not PARTITION_DB.exists():
        blockers.append("runtime evidence partition missing")

    source_commit = identity.get("runtime_source_commit") or final_verdict.get("RUNTIME_SOURCE")
    if source_commit and source_commit != final_verdict.get("RUNTIME_SOURCE"):
        blockers.append("runtime source identity drift")

    report = {
        "artifact": "p7_postseal_observation_baseline",
        "generated_at": _utc_now(),
        "baseline_state": "FROZEN" if not blockers else "BLOCKED",
        "gate": "N0_POST_SEAL_BASELINE",
        "overall_verdict": "PASS" if not blockers else "FAIL",
        "observation_mode": "EVENT_DRIVEN",
        "runtime_change_policy": "FROZEN",
        "synthetic_trades": "NOT_AUTHORIZED",
        "p7": final_verdict.get("P7"),
        "p7_final_seal": final_verdict.get("P7_FINAL_SEAL"),
        "git": {
            "commit": _run_git("rev-parse", "HEAD"),
            "tree": _run_git("rev-parse", "HEAD^{tree}"),
            "branch": _run_git("branch", "--show-current") or "(detached HEAD)",
            "worktree_status": git_status,
        },
        "identity": {
            "release_id": identity.get("release_id") or final_verdict.get("P7_RELEASE"),
            "deployment_id": identity.get("deployment_id"),
            "epoch_id": identity.get("epoch_id"),
            "runtime_source_commit": source_commit,
            "release_identity_sha256": identity.get("release_identity_sha256"),
            "release_manifest_sha256": identity.get("release_manifest_sha256"),
            "feature_schema_version": identity.get("feature_schema_version"),
            "authorization_sha256": identity.get("authorization_sha256"),
            "child_pid": identity.get("child_pid"),
        },
        "artifact_hashes": required_hashes,
        "natural_event_gates": {
            "O3": "WAITING_FOR_NATURAL_EVENT",
            "O4": "WAITING_FOR_NATURAL_EVENT",
            "O5": "WAITING_FOR_NATURAL_EVENT",
            "O6": "WAITING_FOR_NATURAL_EVENT",
        },
        "blockers": blockers,
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    Path(str(OUTPUT) + ".sha256").write_text(digest + "\n", encoding="utf-8")

    print(json.dumps({"status": report["overall_verdict"], "output": str(OUTPUT), "sha256": digest}, indent=2))
    return 0 if report["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
