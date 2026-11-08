from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
import pytest

from scripts.p7_r3a_supervised_child import (
    SupervisedChildRequest,
    classify_returncode,
    evaluate_g8,
    sha256_file,
    supervise_child,
)
from scripts.p7_safe_paper_canary_launcher import LaunchRequest


MANIFEST_SHA = "9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894"


def _request(tmp_path: Path, code: str, *, env: dict[str, str] | None = None) -> SupervisedChildRequest:
    return SupervisedChildRequest(
        argv=(sys.executable, "-c", code),
        cwd=Path.cwd(),
        env={**os.environ, **(env or {})},
        stdout_path=tmp_path / "child.stdout.log",
        stderr_path=tmp_path / "child.stderr.log",
        lifecycle_path=tmp_path / "lifecycle.json",
    )


def test_clean_exit_0_captures_stdout_and_exit_code(tmp_path):
    result = supervise_child(_request(tmp_path, "print('hello')"))

    assert result["status"] == "EXITED"
    assert result["process_result"]["classification"] == "NORMAL_EXIT"
    assert result["process_result"]["exit_code"] == 0
    assert result["spawn_attempt_count"] == 1
    assert result["restart_attempt_count"] == 0
    assert (tmp_path / "child.stdout.log").read_text().strip() == "hello"
    assert (tmp_path / "child.stderr.log").read_text() == ""
    assert json.loads((tmp_path / "lifecycle.json").read_text())["child_pid"] == result["child_pid"]


def test_nonzero_exit_captures_stderr(tmp_path):
    result = supervise_child(_request(tmp_path, "import sys; print('fatal', file=sys.stderr); sys.exit(7)"))

    assert result["process_result"]["classification"] == "NONZERO_EXIT"
    assert result["process_result"]["exit_code"] == 7
    assert "fatal" in (tmp_path / "child.stderr.log").read_text()


def test_uncaught_exception_is_captured_as_stderr_nonzero(tmp_path):
    result = supervise_child(_request(tmp_path, "raise RuntimeError('boom')"))

    assert result["process_result"]["classification"] == "NONZERO_EXIT"
    assert result["process_result"]["exit_code"] != 0
    assert "RuntimeError: boom" in (tmp_path / "child.stderr.log").read_text()
    assert result["restart_attempt_count"] == 0


def test_signal_exit_classification():
    assert classify_returncode(-signal.SIGTERM)["classification"] == "SIGNAL_EXIT"
    assert classify_returncode(-signal.SIGTERM)["signal_name"] == "SIGTERM"


def test_sigterm_child_exit_is_observable(tmp_path):
    if sys.platform == "win32":
        pytest.skip("SIGTERM returncode semantics are POSIX-specific")
    code = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    result = supervise_child(_request(tmp_path, code))

    assert result["process_result"]["classification"] == "SIGNAL_EXIT"
    assert result["process_result"]["signal_name"] == "SIGTERM"
    assert result["restart_attempt_count"] == 0


def test_long_running_child_reports_still_running_without_restart(tmp_path):
    result = supervise_child(_request(tmp_path, "import time; print('ready', flush=True); time.sleep(5)"), observation_timeout_seconds=0.05)

    assert result["status"] == "STILL_RUNNING"
    assert result["process_result"]["classification"] == "STILL_RUNNING"
    assert result["spawn_attempt_count"] == 1
    assert result["restart_attempt_count"] == 0
    assert result["running_observed_at"]
    os.kill(result["child_pid"], signal.SIGTERM)


def test_fast_exit_race_still_captures_pid_exit_and_files(tmp_path):
    result = supervise_child(_request(tmp_path, ""))

    assert result["child_pid"] is not None
    assert result["process_result"]["classification"] == "NORMAL_EXIT"
    assert result["stdout_sha256"] == sha256_file(tmp_path / "child.stdout.log")
    assert result["stderr_sha256"] == sha256_file(tmp_path / "child.stderr.log")


def test_large_stdout_stderr_uses_file_redirection_without_pipe_deadlock(tmp_path):
    code = (
        "import sys; "
        "sys.stdout.write('o' * 200000); sys.stdout.flush(); "
        "sys.stderr.write('e' * 200000); sys.stderr.flush()"
    )
    result = supervise_child(_request(tmp_path, code))

    assert result["process_result"]["classification"] == "NORMAL_EXIT"
    assert (tmp_path / "child.stdout.log").stat().st_size == 200000
    assert (tmp_path / "child.stderr.log").stat().st_size == 200000


def test_exact_argv_and_env_are_preserved(tmp_path):
    env = {"P7_R3A_DUMMY_ENV": "exact-value"}
    request = _request(tmp_path, "import os; print(os.environ['P7_R3A_DUMMY_ENV'])", env=env)
    result = supervise_child(request)

    assert result["request"]["argv"] == list(request.argv)
    assert result["request"]["env"]["P7_R3A_DUMMY_ENV"] == "exact-value"
    assert (tmp_path / "child.stdout.log").read_text().strip() == "exact-value"


def test_launcher_request_argv_env_can_be_consumed_without_reconstruction(tmp_path):
    launch_request = LaunchRequest.from_manifest(
        manifest_path=Path("runtime_activation_p7_manifest.json").resolve(),
        expected_manifest_sha256=MANIFEST_SHA,
        pinned_root=Path("runtime/worktrees/pinned-5e8d798").resolve(),
    )
    supervisor_request = SupervisedChildRequest(
        argv=launch_request.command(),
        cwd=launch_request.pinned_root,
        env={**os.environ, **launch_request.child_environment()},
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        lifecycle_path=tmp_path / "lifecycle.json",
    )

    assert supervisor_request.argv == launch_request.command()
    assert supervisor_request.env["PYTHONPATH"] == str(launch_request.pinned_root)
    assert supervisor_request.env["BTC_EVIDENCE_ELIGIBLE"] == "true"
    assert supervisor_request.env["LIVE_TRADING_ENABLED"] == "false"


def test_g8_transient_identity_is_not_active():
    result = evaluate_g8(
        identity_established=True,
        immutable_inputs_unchanged=True,
        execution_mode="PAPER",
        semantic_progress_observed=False,
        child_exited_before_liveness=True,
    )

    assert result["g8_a"] == "PASS"
    assert result["g8_b"] == "FAIL"
    assert result["runtime_activation"] == "ACTIVATION_NOT_SUSTAINED"
    assert result["paper_canary"] == "NOT_ACTIVE"


def test_g8_sustained_semantic_progress_is_active():
    result = evaluate_g8(
        identity_established=True,
        immutable_inputs_unchanged=True,
        execution_mode="PAPER",
        semantic_progress_observed=True,
        child_exited_before_liveness=False,
    )

    assert result["g8_a"] == "PASS"
    assert result["g8_b"] == "PASS"
    assert result["runtime_activation"] == "ACTIVE"
    assert result["paper_canary"] == "ACTIVE"
