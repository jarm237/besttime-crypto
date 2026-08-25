#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G1 Phase C: Fresh Evidence Epoch Provision.

Synthesizes an A5-specific deployment manifest, copies the release-bundle artifact
files into the gitignored pinned-worktree logs/ directory, and calls
p7_r2_provision_evidence_epoch to create and activate an ACTIVE evidence epoch.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PINNED           = ROOT / "runtime" / "worktrees" / "pinned-b284ad3"
RELEASE          = ROOT / "runtime" / "releases" / "model-coverage-v1-r1"
RESUME_CONTRACT  = ROOT / "p7_attempt5_resume_contract.json"
AUTH_PATH        = ROOT / "p7_attempt5_authorization.json"
P7_MANIFEST_ORIG = ROOT / "runtime_activation_p7_manifest.json"
A5_MANIFEST      = ROOT / "p7_a5_manifest.json"
OUTPUT           = ROOT / "p7_attempt5_epoch_provision.json"

ATTEMPT_ID     = "p7-attempt-5"
DEPLOYMENT_ID  = "paper-canary-a5-20260825-01"
PAPER_RUN_ID   = "paper-canary-a5-20260825-01"
EPOCH_ID       = "canary-mc9-v1-a5-20260825-01"
SOURCE_COMMIT  = "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def preflight_checks() -> None:
    """Fail-closed checks before any mutation."""
    if not RESUME_CONTRACT.exists():
        fail("Resume contract missing — run p7_a5_resume_contract.py first")
    contract = json.loads(RESUME_CONTRACT.read_bytes())
    if contract.get("overall_verdict") != "PASS":
        fail(f"Resume contract not PASS: {contract.get('overall_verdict')!r}")
    if contract.get("authorization_state") != "ARMED":
        fail("Authorization is not ARMED in resume contract")
    if contract.get("authorization_consumed") is not False:
        fail("Authorization already consumed in resume contract")

    # Re-verify live authorization state
    auth = json.loads(AUTH_PATH.read_bytes())
    if auth.get("state") != "ARMED":
        fail(f"Live authorization is not ARMED: {auth.get('state')!r}")
    if auth.get("consumed") is not False:
        fail("Live authorization already consumed")

    # Verify pinned worktree is at correct commit
    pinned_commit = git(PINNED, "rev-parse", "HEAD")
    if pinned_commit != SOURCE_COMMIT:
        fail(f"Pinned worktree commit mismatch: {pinned_commit[:12]} != {SOURCE_COMMIT[:12]}")


def populate_pinned_logs() -> dict[str, str]:
    """Copy release bundle artifacts into gitignored pinned logs/."""
    logs = PINNED / "logs"
    logs.mkdir(exist_ok=True)
    copied: dict[str, str] = {}
    for fname in ("meta_model.json", "model_registry.json", "meta_model.joblib"):
        src = RELEASE / "logs" / fname
        dst = logs / fname
        if not src.exists():
            fail(f"Release bundle missing required file: {src.name}")
        if not dst.exists():
            shutil.copy2(src, dst)
        copied[fname] = sha256_file(dst)
    # Verify worktree stays clean
    status = git(PINNED, "status", "--short")
    if status:
        fail(f"Pinned worktree dirty after log copy: {status!r}")
    return copied


def build_a5_manifest(orig: dict[str, Any]) -> tuple[Path, str]:
    """Build an A5-specific manifest and return (path, sha256)."""
    a5 = dict(orig)
    a5["deployment_id"] = DEPLOYMENT_ID
    a5["paper_run_id"]  = PAPER_RUN_ID
    a5["epoch_id"]      = EPOCH_ID
    release_tree = git(ROOT, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}")
    a5["release"] = {
        "commit_sha": SOURCE_COMMIT,
        "source": "MC9_SEALED_RELEASE",
        "tree_sha": release_tree,
    }
    a5["artifact"]["path"] = "logs/meta_model.joblib"
    A5_MANIFEST.write_text(json.dumps(a5, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = sha256_file(A5_MANIFEST)
    return A5_MANIFEST, manifest_sha


def main() -> int:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("P7-A5-G1: Fresh Evidence Epoch Provision")
    print("=" * 50)

    # ── Preflight ─────────────────────────────────────────────────────────────
    preflight_checks()
    print("  Preflight: PASS")

    # ── Populate pinned logs/ from release bundle ─────────────────────────────
    copied = populate_pinned_logs()
    print(f"  Logs populated: {list(copied)}")

    # ── Build A5 manifest ─────────────────────────────────────────────────────
    orig_manifest = json.loads(P7_MANIFEST_ORIG.read_bytes())
    a5_manifest_path, a5_manifest_sha = build_a5_manifest(orig_manifest)
    print(f"  A5 manifest sha: {a5_manifest_sha[:16]}…")

    # ── Run provision (operational, not dry_run) ──────────────────────────────
    from scripts.p7_r2_provision_evidence_epoch import provision
    provision_result = provision(
        manifest_path=a5_manifest_path.resolve(),
        expected_manifest_sha256=a5_manifest_sha,
        pinned_root=PINNED.resolve(),
        dry_run=False,
    )

    status = provision_result.get("status", "")
    expected_status = "PASS_OPERATIONAL_STATE_PROVISIONED"
    if status != expected_status:
        fail(f"Provision failed: status={status!r}")

    epoch_id_out   = provision_result["epoch_identity"]["epoch_id"]
    deploy_id_out  = provision_result["epoch_identity"]["deployment_id"]
    active_count   = provision_result["evidence_store"]["active_epoch_count"]

    if epoch_id_out != EPOCH_ID:
        fail(f"epoch_id mismatch: {epoch_id_out!r}")
    if deploy_id_out != DEPLOYMENT_ID:
        fail(f"deployment_id mismatch: {deploy_id_out!r}")
    if active_count != 1:
        fail(f"Expected exactly 1 active epoch, got {active_count}")

    print(f"  Status: {status}")
    print(f"  epoch_id: {epoch_id_out}")
    print(f"  active_epoch_count: {active_count}")

    # ── Write report ──────────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "artifact": "p7_attempt5_epoch_provision",
        "generated_at": now,
        "attempt_id": ATTEMPT_ID,
        "deployment_id": DEPLOYMENT_ID,
        "paper_run_id": PAPER_RUN_ID,
        "epoch_id": EPOCH_ID,
        "source_commit": SOURCE_COMMIT,
        "pinned_worktree": str(PINNED),
        "a5_manifest_sha256": a5_manifest_sha,
        "release_bundle": str(RELEASE),
        "logs_copied": copied,
        "provision_status": status,
        "active_epoch_count": active_count,
        "epoch_identity": provision_result["epoch_identity"],
        "release_manifest": provision_result.get("release_manifest", {}),
        "startup_precondition_probe": provision_result.get("startup_precondition_probe", {}),
        "overall_verdict": "PASS",
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_epoch_provision.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "epoch_id": EPOCH_ID,
        "active_epoch_count": active_count,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
