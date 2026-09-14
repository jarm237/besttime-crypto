from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.p7_safe_paper_canary_launcher import (
    LauncherContractError,
    LaunchRequest,
    immutable_input_hashes,
    launch,
    sha256_file,
    validate_launch_request,
)


MANIFEST_PATH = Path("runtime_activation_p7_manifest.json").resolve()
MANIFEST_SHA = "187005e4b50882c2c12e5ebab56844c9ba3e039f6412e4b5279b0413efd2d88e"
RELEASE_COMMIT = "b6d22745bf8892d17784cff5d42ce2ac0b72fa41"
RELEASE_TREE = "85ee5b68f9432bb2fe584c3b0ed4b71886779def"
ARTIFACT_SHA = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"


def request() -> LaunchRequest:
    pinned = Path("runtime/worktrees/paper-canary-b6d22745").resolve()
    return LaunchRequest.from_manifest(
        manifest_path=MANIFEST_PATH,
        expected_manifest_sha256=MANIFEST_SHA,
        pinned_root=pinned,
    )


def test_launcher_validate_only_preserves_immutable_inputs():
    item = request()
    before = immutable_input_hashes(item)
    result = validate_launch_request(item)
    after = immutable_input_hashes(item)

    assert result["status"] == "PASS"
    assert before == after
    assert before["manifest_sha256"] == MANIFEST_SHA
    assert before["artifact_sha256"] == ARTIFACT_SHA
    assert before["release_commit_sha"] == RELEASE_COMMIT
    assert before["release_tree_sha"] == RELEASE_TREE


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"expected_manifest_sha256": "0" * 64}, "manifest_sha256_mismatch"),
        ({"release_commit_sha": "0" * 40}, "release_commit_mismatch"),
        ({"release_tree_sha": "0" * 40}, "release_tree_mismatch"),
        ({"artifact_sha256": "0" * 64}, "artifact_sha256_mismatch"),
        ({"epoch_id": "duplicate-epoch"}, "duplicate_epoch"),
        ({"deployment_id": "duplicate-deployment"}, "duplicate_deployment"),
    ],
)
def test_launcher_identity_failures_block_before_spawn(updates, reason):
    base = request()
    item = LaunchRequest(**{**base.__dict__, **updates})
    kwargs = {}
    if updates.get("epoch_id") == "duplicate-epoch":
        kwargs["existing_epochs"] = {"duplicate-epoch"}
    if updates.get("deployment_id") == "duplicate-deployment":
        kwargs["existing_deployments"] = {"duplicate-deployment"}
    with pytest.raises(LauncherContractError, match=reason):
        validate_launch_request(item, **kwargs)


@pytest.mark.parametrize("mode", ["", "LIVE", "PRODUCTION"])
def test_launcher_requires_explicit_paper_mode(mode):
    base = request()
    item = LaunchRequest(**{**base.__dict__, "execution_mode": mode})
    with pytest.raises(LauncherContractError, match="execution_mode_not_paper"):
        validate_launch_request(item)


def test_launcher_blocks_existing_runner():
    with pytest.raises(LauncherContractError, match="active_runner_conflict"):
        validate_launch_request(request(), active_runner_count=1)


def test_launcher_success_spawns_exactly_once_with_pinned_child_boundary():
    calls = []

    class Child:
        pid = 43210

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return Child()

    result = launch(request(), popen=fake_popen)

    assert result["status"] == "SPAWNED"
    assert result["spawn_attempts"] == 1
    assert result["automatic_retries"] == 0
    assert len(calls) == 1
    args, kwargs = calls[0]
    pinned_str = str(request().pinned_root)
    assert Path(args[0][1]) == request().pinned_root / "main.py"
    assert Path(kwargs["cwd"]) == request().pinned_root
    env = kwargs["env"]
    assert Path(env["PYTHONPATH"]) == request().pinned_root
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["BTC_RUNTIME_ENVIRONMENT"] == "paper"
    assert env["AUTO_TRADE_DRY_RUN"] == "true"
    assert env["LIVE_TRADING_ENABLED"] == "false"
    assert env["P7_MANIFEST_SHA256"] == MANIFEST_SHA


def test_launcher_failure_has_no_retry():
    calls = []

    def failing_popen(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("boom")

    result = launch(request(), popen=failing_popen)

    assert result["status"] == "SPAWN_FAILED"
    assert result["spawn_attempts"] == 1
    assert result["automatic_retries"] == 0
    assert len(calls) == 1


def test_launcher_cli_validate_only():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/p7_safe_paper_canary_launcher.py",
            "--manifest-path",
            "runtime_activation_p7_manifest.json",
            "--expected-manifest-sha256",
            MANIFEST_SHA,
            "--pinned-root",
            "runtime/worktrees/paper-canary-b6d22745",
            "--validate-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["immutable_inputs_before"]["artifact_sha256"] == ARTIFACT_SHA
