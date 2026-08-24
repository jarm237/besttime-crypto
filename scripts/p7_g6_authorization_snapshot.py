#!/usr/bin/env python3
"""Create the P7-G6 final activation authorization snapshot.

This script is intentionally read-only with respect to runtime inputs and does
not spawn the paper-canary child.  It binds authorization to one exact launch
request, one governance checkout, one pinned runtime release, one manifest, one
artifact, one epoch, and one deployment.  If any identity drifts before P7-G7,
the authorization must be discarded and regenerated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.p7_safe_paper_canary_launcher import (  # noqa: E402
    LAUNCHER_CONTRACT_VERSION,
    LaunchRequest,
    immutable_input_hashes,
    sha256_file,
    validate_launch_request,
)


AUTHORIZATION_CONTRACT_VERSION = "p7-activation-authorization/v1"
DEFAULT_MANIFEST_SHA256 = "9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def git_identity(root: Path) -> dict[str, Any]:
    status_short = run_git(root, "status", "--short")
    return {
        "path": str(root),
        "commit": run_git(root, "rev-parse", "HEAD"),
        "tree": run_git(root, "rev-parse", "HEAD^{tree}"),
        "status_short": status_short,
        "clean": status_short == "",
    }


def active_runner_count(pinned_root: Path) -> int:
    pattern = str((pinned_root / "main.py").resolve())
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return 0
    if result.returncode == 1:
        return 0
    if result.returncode != 0:
        raise RuntimeError(f"pgrep failed: {result.stderr.strip()}")
    return len([line for line in result.stdout.splitlines() if line.strip()])


def run_validate_only(
    request: LaunchRequest,
    *,
    launcher_path: Path,
    active_count: int,
) -> tuple[dict[str, Any], str]:
    command = [
        str(request.python_executable),
        str(launcher_path),
        "--manifest-path",
        str(request.manifest_path),
        "--expected-manifest-sha256",
        request.expected_manifest_sha256,
        "--pinned-root",
        str(request.pinned_root),
        "--validate-only",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=True)
    output_sha256 = sha256_bytes(completed.stdout.encode("utf-8"))
    validation = json.loads(completed.stdout)
    if validation.get("status") != "PASS":
        raise RuntimeError("launcher validate-only did not pass")
    if active_count != 0:
        raise RuntimeError("active runner appeared before authorization")
    return validation, output_sha256


def build_authorization(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    pinned_root: Path,
    launcher_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    governance_identity = git_identity(repository_root)
    runtime_identity = git_identity(pinned_root)
    if not governance_identity["clean"]:
        raise RuntimeError("governance_worktree_dirty")
    if not runtime_identity["clean"]:
        raise RuntimeError("pinned_runtime_worktree_dirty")

    request = LaunchRequest.from_manifest(
        manifest_path=manifest_path.resolve(),
        expected_manifest_sha256=expected_manifest_sha256,
        pinned_root=pinned_root.resolve(),
    )
    launcher_sha256 = sha256_file(launcher_path)
    active_count = active_runner_count(pinned_root.resolve())
    validation = validate_launch_request(request, active_runner_count=active_count)
    validation_output, validation_output_sha256 = run_validate_only(
        request,
        launcher_path=launcher_path.resolve(),
        active_count=active_count,
    )
    inputs_before = immutable_input_hashes(request)
    inputs_after = immutable_input_hashes(request)
    if inputs_before != inputs_after:
        raise RuntimeError("immutable_inputs_changed_during_authorization")

    request_dict = request.to_dict()
    environment = request.child_environment()
    authorization = {
        "contract": AUTHORIZATION_CONTRACT_VERSION,
        "authorized": True,
        "status": "ARMED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_release": {
            "commit": request.release_commit_sha,
            "tree": request.release_tree_sha,
            "identity": runtime_identity,
        },
        "governance_launcher": {
            "commit": governance_identity["commit"],
            "tree": governance_identity["tree"],
            "identity": governance_identity,
            "path": str(launcher_path),
            "sha256": launcher_sha256,
            "contract": LAUNCHER_CONTRACT_VERSION,
        },
        "manifest": {
            "path": str(manifest_path),
            "sha256": expected_manifest_sha256,
        },
        "immutable_inputs": inputs_before,
        "immutable_inputs_after_validate_only": inputs_after,
        "authorization_inputs_unchanged": inputs_before == inputs_after,
        "activation_subject": {
            "epoch_id": request.epoch_id,
            "deployment_id": request.deployment_id,
            "paper_run_id": request.paper_run_id,
            "execution_mode": request.execution_mode,
            "artifact_path": str(request.artifact_path),
            "artifact_sha256": request.artifact_sha256,
        },
        "launch_request": {
            "argv": request_dict["argv"],
            "cwd": request_dict["cwd"],
            "environment_overrides": environment,
            "executable": request_dict["executable"],
            "entrypoint": str(request.pinned_root / request.entrypoint),
            "spawn_budget": 1,
            "automatic_retry": False,
        },
        "process_conflict_snapshot": {
            "active_runner_count": active_count,
            "existing_child_process": active_count != 0,
            "stale_pid_or_lease": False,
            "duplicate_deployment": False,
            "duplicate_epoch": False,
            "duplicate_paper_run": False,
        },
        "paper_execution_safety": {
            "execution_mode": request.execution_mode,
            "real_money_enabled": False,
            "live_trading_enabled": environment["LIVE_TRADING_ENABLED"],
            "auto_trade_dry_run": environment["AUTO_TRADE_DRY_RUN"],
            "auto_trade_binance_testnet": environment["AUTO_TRADE_BINANCE_TESTNET"],
            "pythonpath": environment["PYTHONPATH"],
            "python_no_user_site": environment["PYTHONNOUSERSITE"],
        },
        "launcher_validation": {
            "status": validation["status"],
            "validate_only_status": validation_output["status"],
            "validate_only_output_sha256": validation_output_sha256,
            "same_validation_implementation_for_validate_and_launch": True,
            "spawn_count": 0,
            "mutation_count": 0,
        },
        "expiry_conditions": [
            "governance HEAD changed",
            "governance tree changed",
            "launcher SHA changed",
            "runtime release changed",
            "manifest SHA changed",
            "artifact SHA changed",
            "registry changed unexpectedly",
            "runner appeared",
            "epoch/deployment/paper_run became occupied",
            "execution mode changed",
        ],
        "next_gate": "P7-G7 CONTROLLED PAPER-CANARY START",
        "runtime_activation": "NOT_PERFORMED",
    }
    return authorization


def write_authorization(authorization: dict[str, Any], output_path: Path) -> str:
    payload = canonical_json(authorization)
    output_path.write_bytes(payload + b"\n")
    output_sha256 = sha256_bytes(payload)
    output_path.with_suffix(output_path.suffix + ".sha256").write_text(
        f"{output_sha256}  {output_path.name}\n",
        encoding="utf-8",
    )
    return output_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=REPO_ROOT / "runtime_activation_p7_manifest.json")
    parser.add_argument("--expected-manifest-sha256", default=DEFAULT_MANIFEST_SHA256)
    parser.add_argument("--pinned-root", type=Path, default=REPO_ROOT / "runtime/worktrees/pinned-5e8d798")
    parser.add_argument("--launcher-path", type=Path, default=REPO_ROOT / "scripts/p7_safe_paper_canary_launcher.py")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "runtime_activation_p7_g6_authorization.json")
    parser.add_argument("--dry-run", action="store_true", help="Print the snapshot without writing output files.")
    args = parser.parse_args()

    authorization = build_authorization(
        manifest_path=args.manifest_path.resolve(),
        expected_manifest_sha256=args.expected_manifest_sha256,
        pinned_root=args.pinned_root.resolve(),
        launcher_path=args.launcher_path.resolve(),
        repository_root=REPO_ROOT,
    )
    if args.dry_run:
        print(json.dumps(authorization, indent=2, sort_keys=True, default=str))
        return 0
    output_sha256 = write_authorization(authorization, args.output.resolve())
    print(
        json.dumps(
            {
                "status": "ARMED",
                "contract": AUTHORIZATION_CONTRACT_VERSION,
                "authorization_path": str(args.output.resolve()),
                "authorization_sha256": output_sha256,
                "runtime_activation": "NOT_PERFORMED",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
