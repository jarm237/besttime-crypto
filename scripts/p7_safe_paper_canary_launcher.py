#!/usr/bin/env python3
"""External governance launcher for a pinned paper-canary runtime.

The launcher consumes a frozen P7 manifest and a pinned runtime worktree.  It
must not prepare artifacts, rewrite sidecars, mutate the model registry, or
choose activation identities.  Successful launch is limited to one child spawn
and deployment-specific operational state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


LAUNCHER_CONTRACT_VERSION = "paper-canary-launcher/v1"
FORBIDDEN_MODE_VALUES = {"", "LIVE", "REAL", "PRODUCTION", "MAINNET"}


class LauncherContractError(RuntimeError):
    """Fail-closed launcher validation error raised before child creation."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@dataclass(frozen=True)
class LaunchRequest:
    manifest_path: Path
    expected_manifest_sha256: str
    pinned_root: Path
    release_commit_sha: str
    release_tree_sha: str
    artifact_path: Path
    artifact_sha256: str
    epoch_id: str
    deployment_id: str
    paper_run_id: str
    execution_mode: str
    python_executable: Path = Path(sys.executable)
    entrypoint: str = "main.py"

    @classmethod
    def from_manifest(
        cls,
        *,
        manifest_path: Path,
        expected_manifest_sha256: str,
        pinned_root: Path,
        python_executable: Path | None = None,
    ) -> "LaunchRequest":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = manifest["artifact"]
        release = manifest["release"]
        runtime = manifest["runtime"]
        return cls(
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
            pinned_root=pinned_root,
            release_commit_sha=str(release["commit_sha"]),
            release_tree_sha=str(release["tree_sha"]),
            artifact_path=pinned_root / str(artifact["path"]),
            artifact_sha256=str(artifact["sha256"]),
            epoch_id=str(manifest["epoch_id"]),
            deployment_id=str(manifest["deployment_id"]),
            paper_run_id=str(manifest["paper_run_id"]),
            execution_mode=str(runtime.get("mode") or ""),
            python_executable=python_executable or Path(sys.executable),
        )

    def command(self) -> tuple[str, ...]:
        return (str(self.python_executable), str(self.pinned_root / self.entrypoint))

    def child_environment(self) -> dict[str, str]:
        environment = {
            "PYTHONPATH": str(self.pinned_root),
            "PYTHONNOUSERSITE": "1",
            "BTC_RUNTIME_ENVIRONMENT": "paper",
            "BTC_DEPLOYMENT_ID": self.deployment_id,
            "BTC_PAPER_RUN_ID": self.paper_run_id,
            "BTC_EVIDENCE_ELIGIBLE": "true",
            "AUTO_TRADE_DRY_RUN": "true",
            "AUTO_TRADE_BINANCE_TESTNET": "true",
            "LIVE_TRADING_ENABLED": "false",
            "P7_MANIFEST_PATH": str(self.manifest_path.resolve()),
            "P7_MANIFEST_SHA256": self.expected_manifest_sha256,
            "P7_RELEASE_COMMIT_SHA": self.release_commit_sha,
            "P7_RELEASE_TREE_SHA": self.release_tree_sha,
            "P7_ARTIFACT_SHA256": self.artifact_sha256,
            "P7_LAUNCHER_CONTRACT": LAUNCHER_CONTRACT_VERSION,
        }
        return environment

    def to_dict(self) -> dict[str, Any]:
        return {
            "launcher_contract": LAUNCHER_CONTRACT_VERSION,
            "manifest_path": str(self.manifest_path),
            "expected_manifest_sha256": self.expected_manifest_sha256,
            "pinned_root": str(self.pinned_root),
            "release_commit_sha": self.release_commit_sha,
            "release_tree_sha": self.release_tree_sha,
            "artifact_path": str(self.artifact_path),
            "artifact_sha256": self.artifact_sha256,
            "epoch_id": self.epoch_id,
            "deployment_id": self.deployment_id,
            "paper_run_id": self.paper_run_id,
            "execution_mode": self.execution_mode,
            "executable": str(self.python_executable),
            "argv": list(self.command()),
            "cwd": str(self.pinned_root),
            "environment": self.child_environment(),
        }


def immutable_input_hashes(request: LaunchRequest) -> dict[str, str]:
    registry = request.pinned_root / "logs/model_registry.json"
    sidecar = request.pinned_root / "logs/meta_model.json"
    return {
        "manifest_sha256": sha256_file(request.manifest_path),
        "artifact_sha256": sha256_file(request.artifact_path),
        "artifact_sidecar_sha256": sha256_file(sidecar),
        "model_registry_sha256": sha256_file(registry),
        "release_commit_sha": _git(request.pinned_root, "rev-parse", "HEAD"),
        "release_tree_sha": _git(request.pinned_root, "rev-parse", "HEAD^{tree}"),
    }


def validate_launch_request(
    request: LaunchRequest,
    *,
    active_runner_count: int = 0,
    existing_deployments: set[str] | None = None,
    existing_epochs: set[str] | None = None,
) -> dict[str, Any]:
    if request.execution_mode.upper() in FORBIDDEN_MODE_VALUES or request.execution_mode.upper() != "PAPER":
        raise LauncherContractError("execution_mode_not_paper")
    if sha256_file(request.manifest_path) != request.expected_manifest_sha256:
        raise LauncherContractError("manifest_sha256_mismatch")
    if _git(request.pinned_root, "rev-parse", "HEAD") != request.release_commit_sha:
        raise LauncherContractError("release_commit_mismatch")
    if _git(request.pinned_root, "rev-parse", "HEAD^{tree}") != request.release_tree_sha:
        raise LauncherContractError("release_tree_mismatch")
    if _git(request.pinned_root, "status", "--short"):
        raise LauncherContractError("pinned_worktree_dirty")
    if not request.artifact_path.is_file():
        raise LauncherContractError("artifact_missing")
    if sha256_file(request.artifact_path) != request.artifact_sha256:
        raise LauncherContractError("artifact_sha256_mismatch")
    if not (request.pinned_root / request.entrypoint).is_file():
        raise LauncherContractError("entrypoint_missing")
    if active_runner_count != 0:
        raise LauncherContractError("active_runner_conflict")
    if request.deployment_id in (existing_deployments or set()):
        raise LauncherContractError("duplicate_deployment")
    if request.epoch_id in (existing_epochs or set()):
        raise LauncherContractError("duplicate_epoch")
    environment = request.child_environment()
    if environment["PYTHONPATH"] != str(request.pinned_root):
        raise LauncherContractError("unpinned_pythonpath")
    if environment["LIVE_TRADING_ENABLED"].lower() != "false":
        raise LauncherContractError("live_trading_not_disabled")
    if environment["AUTO_TRADE_DRY_RUN"].lower() != "true":
        raise LauncherContractError("paper_dry_run_not_enforced")
    return {
        "status": "PASS",
        "launcher_contract": LAUNCHER_CONTRACT_VERSION,
        "request": request.to_dict(),
        "immutable_inputs_before": immutable_input_hashes(request),
    }


def launch(
    request: LaunchRequest,
    *,
    active_runner_count: int = 0,
    existing_deployments: set[str] | None = None,
    existing_epochs: set[str] | None = None,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> dict[str, Any]:
    validation = validate_launch_request(
        request,
        active_runner_count=active_runner_count,
        existing_deployments=existing_deployments,
        existing_epochs=existing_epochs,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        child = popen(
            list(request.command()),
            cwd=str(request.pinned_root),
            env={**os.environ, **request.child_environment()},
            start_new_session=True,
        )
    except Exception as exc:
        return {
            "status": "SPAWN_FAILED",
            "launcher_contract": LAUNCHER_CONTRACT_VERSION,
            "started_at": started_at,
            "spawn_attempts": 1,
            "automatic_retries": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "validation": validation,
        }
    return {
        "status": "SPAWNED",
        "launcher_contract": LAUNCHER_CONTRACT_VERSION,
        "started_at": started_at,
        "spawn_attempts": 1,
        "automatic_retries": 0,
        "child_pid": child.pid,
        "argv": list(request.command()),
        "cwd": str(request.pinned_root),
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--pinned-root", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    request = LaunchRequest.from_manifest(
        manifest_path=args.manifest_path.resolve(),
        expected_manifest_sha256=args.expected_manifest_sha256,
        pinned_root=args.pinned_root.resolve(),
    )
    if args.validate_only:
        result = validate_launch_request(request)
    else:
        result = launch(request)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] in {"PASS", "SPAWNED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
