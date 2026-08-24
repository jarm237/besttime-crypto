from __future__ import annotations

from pathlib import Path

import pytest

from scripts import p7_g6_authorization_snapshot as g6
from scripts.p7_safe_paper_canary_launcher import LaunchRequest


def test_authorization_binds_exact_launch_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request = LaunchRequest.from_manifest(
        manifest_path=Path("runtime_activation_p7_manifest.json").resolve(),
        expected_manifest_sha256=g6.DEFAULT_MANIFEST_SHA256,
        pinned_root=Path("runtime/worktrees/pinned-5e8d798").resolve(),
    )
    governance_identity = {
        "path": str(Path.cwd()),
        "commit": "governance-commit",
        "tree": "governance-tree",
        "status_short": "",
        "clean": True,
    }
    runtime_identity = {
        "path": str(request.pinned_root),
        "commit": request.release_commit_sha,
        "tree": request.release_tree_sha,
        "status_short": "",
        "clean": True,
    }
    immutable = {
        "manifest_sha256": g6.DEFAULT_MANIFEST_SHA256,
        "artifact_sha256": request.artifact_sha256,
        "artifact_sidecar_sha256": "sidecar",
        "model_registry_sha256": "registry",
        "release_commit_sha": request.release_commit_sha,
        "release_tree_sha": request.release_tree_sha,
    }

    monkeypatch.setattr(g6, "git_identity", lambda root: runtime_identity if "pinned" in str(root) else governance_identity)
    monkeypatch.setattr(g6, "active_runner_count", lambda pinned_root: 0)
    monkeypatch.setattr(g6, "sha256_file", lambda path: "launcher-sha")
    monkeypatch.setattr(g6, "immutable_input_hashes", lambda launch_request: immutable)
    monkeypatch.setattr(
        g6,
        "validate_launch_request",
        lambda launch_request, active_runner_count=0: {"status": "PASS", "request": launch_request.to_dict()},
    )
    monkeypatch.setattr(
        g6,
        "run_validate_only",
        lambda launch_request, launcher_path, active_count: ({"status": "PASS"}, "validate-output-sha"),
    )

    authorization = g6.build_authorization(
        manifest_path=request.manifest_path,
        expected_manifest_sha256=request.expected_manifest_sha256,
        pinned_root=request.pinned_root,
        launcher_path=tmp_path / "launcher.py",
        repository_root=Path.cwd(),
    )

    assert authorization["status"] == "ARMED"
    assert authorization["authorized"] is True
    assert authorization["runtime_activation"] == "NOT_PERFORMED"
    assert authorization["runtime_release"]["commit"] == request.release_commit_sha
    assert authorization["governance_launcher"]["commit"] == "governance-commit"
    assert authorization["governance_launcher"]["sha256"] == "launcher-sha"
    assert authorization["manifest"]["sha256"] == g6.DEFAULT_MANIFEST_SHA256
    assert authorization["activation_subject"]["epoch_id"] == request.epoch_id
    assert authorization["activation_subject"]["execution_mode"] == "PAPER"
    assert authorization["launch_request"]["spawn_budget"] == 1
    assert authorization["launch_request"]["automatic_retry"] is False
    assert authorization["launcher_validation"]["spawn_count"] == 0
    assert authorization["process_conflict_snapshot"]["active_runner_count"] == 0
    assert authorization["paper_execution_safety"]["real_money_enabled"] is False
    assert authorization["paper_execution_safety"]["pythonpath"] == str(request.pinned_root)


def test_authorization_fails_closed_on_dirty_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    request = LaunchRequest.from_manifest(
        manifest_path=Path("runtime_activation_p7_manifest.json").resolve(),
        expected_manifest_sha256=g6.DEFAULT_MANIFEST_SHA256,
        pinned_root=Path("runtime/worktrees/pinned-5e8d798").resolve(),
    )
    monkeypatch.setattr(
        g6,
        "git_identity",
        lambda root: {"path": str(root), "commit": "c", "tree": "t", "status_short": " M file", "clean": False},
    )

    with pytest.raises(RuntimeError, match="governance_worktree_dirty"):
        g6.build_authorization(
            manifest_path=request.manifest_path,
            expected_manifest_sha256=request.expected_manifest_sha256,
            pinned_root=request.pinned_root,
            launcher_path=Path("scripts/p7_safe_paper_canary_launcher.py"),
            repository_root=Path.cwd(),
        )


def test_write_authorization_hashes_canonical_payload(tmp_path: Path) -> None:
    output = tmp_path / "authorization.json"
    payload = {"contract": g6.AUTHORIZATION_CONTRACT_VERSION, "authorized": True}

    digest = g6.write_authorization(payload, output)

    assert output.exists()
    assert output.with_suffix(".json.sha256").read_text(encoding="utf-8").startswith(digest)
    assert digest == g6.sha256_bytes(g6.canonical_json(payload))
