from __future__ import annotations

import json
import subprocess
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


RELEASE_COMMIT = "5e8d798e4d06d6abd21ade99c79caaa93307dd5b"
RELEASE_TREE = "48ef10b27488468d294a5e223cb95a4aebfc3f01"
ARTIFACT_SHA = "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c"
MANIFEST_SHA = "9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894"


def request() -> LaunchRequest:
    return LaunchRequest.from_manifest(
        manifest_path=Path("runtime_activation_p7_manifest.json").resolve(),
        expected_manifest_sha256=MANIFEST_SHA,
        pinned_root=Path("runtime/worktrees/pinned-5e8d798").resolve(),
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
    assert args[0][1].endswith("/runtime/worktrees/pinned-5e8d798/main.py")
    assert kwargs["cwd"].endswith("/runtime/worktrees/pinned-5e8d798")
    env = kwargs["env"]
    assert env["PYTHONPATH"].endswith("/runtime/worktrees/pinned-5e8d798")
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
            ".venv/bin/python",
            "scripts/p7_safe_paper_canary_launcher.py",
            "--manifest-path",
            "runtime_activation_p7_manifest.json",
            "--expected-manifest-sha256",
            MANIFEST_SHA,
            "--pinned-root",
            "runtime/worktrees/pinned-5e8d798",
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
