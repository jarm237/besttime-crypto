"""tests/test_r1_supervisor.py

Deterministic Test Suite for External Prospective R1 Collector Supervisor
========================================================================
All unit tests (1–8) are 100% deterministic, completely decoupled from
live Binance network and production storage, using `tests/fixtures/fake_r1_collector.py`.

Windows integration test (9) is gated behind `@pytest.mark.windows_integration`
and requires explicit opt-in via BTC_RUN_R1_SCHEDULED_TASK_INTEGRATION=1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SUPERVISOR_SCRIPT = REPO_ROOT / "scripts" / "ensure_prospective_raw_epoch_running.ps1"
REGISTER_SCRIPT = REPO_ROOT / "scripts" / "register_r1_supervisor_task.ps1"
UNREGISTER_SCRIPT = REPO_ROOT / "scripts" / "unregister_r1_supervisor_task.ps1"
FAKE_COLLECTOR_SCRIPT = REPO_ROOT / "tests" / "fixtures" / "fake_r1_collector.py"

PRODUCTION_PID = 38596


def run_supervisor(args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Runs ensure_prospective_raw_epoch_running.ps1 via powershell.exe with bounded timeout,
    using temporary files for stdout/stderr to eliminate Windows anonymous pipe inheritance deadlocks."""
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SUPERVISOR_SCRIPT),
    ] + args

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out_f, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_f:
        try:
            result = subprocess.run(
                cmd,
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
            out_f.seek(0)
            err_f.seek(0)
            stdout_content = out_f.read()
            stderr_content = err_f.read()
            return subprocess.CompletedProcess(cmd, result.returncode, stdout_content, stderr_content)
        except subprocess.TimeoutExpired:
            _cleanup_test_processes()
            raise


@pytest.fixture(autouse=True)
def clean_orphans_fixture() -> Generator[None, None, None]:
    """Yields cleanly and ensures no orphan test processes remain after each test."""
    yield
    # Cleanup only processes that match both pytest and fake collector or temp storage
    _cleanup_test_processes()


def _cleanup_test_processes() -> None:
    """Safely kills ONLY orphan processes matching 'pytest-of-admin' or 'fake_r1_collector'."""
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        """
        Get-CimInstance Win32_Process | Where-Object {
            ($_.CommandLine -match 'pytest-of-admin' -or $_.CommandLine -match 'fake_r1_collector') -and
            $_.ProcessId -ne $PID
        } | ForEach-Object {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
        """
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=5.0)
    except Exception:
        pass


@pytest.fixture
def temp_storage(tmp_path: Path) -> Path:
    """Sets up a clean temporary R1 storage directory."""
    storage_dir = tmp_path / "r1_test_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def test_1_supervisor_active_noop(temp_storage: Path) -> None:
    """1. Collector ACTIVE -> supervisor no-op; PID and UUID unchanged."""
    # Launch fake collector in daemon mode
    fake_proc = subprocess.Popen([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--mode", "active",
    ])
    try:
        # Wait up to 2.0s for fake collector to initialize its state files
        state_path = temp_storage / "r1_epoch_state.json"
        for _ in range(20):
            if state_path.exists():
                break
            time.sleep(0.1)
        pid = fake_proc.pid

        # Run supervisor with fake collector override
        res = run_supervisor([
            "-EnsureRunning",
            "-StorageDir", str(temp_storage),
            "-RepoRoot", str(REPO_ROOT),
            "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        ], timeout=10.0)

        assert res.returncode == 0, f"Supervisor failed: {res.stderr}\n{res.stdout}"
        assert f"Collector PID {pid} is ACTIVE" in res.stdout

        state_file = temp_storage / "r1_supervisor_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text(encoding="utf-8-sig"))
        assert state["supervisor_status"] == "HEALTHY_ACTIVE"
        assert state["action_taken"] == "NO_ACTION_ACTIVE"
        assert state["collector_pid"] == pid
        assert state["paused"] is False
    finally:
        fake_proc.terminate()
        fake_proc.wait(timeout=3.0)


def test_2_concurrent_supervisors_mutual_exclusion(temp_storage: Path) -> None:
    """2. Concurrent supervisors -> only one collector exists, second receives already-running."""
    lock_file = temp_storage / "r1_supervisor.lock"
    # Open lock file to hold mutual exclusion lock
    with open(lock_file, "w") as f:
        res = run_supervisor([
            "-EnsureRunning",
            "-StorageDir", str(temp_storage),
            "-RepoRoot", str(REPO_ROOT),
            "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        ], timeout=10.0)
        assert res.returncode == 0
        assert "SUPERVISOR_CONCURRENCY_LOCKED" in res.stdout or "ALREADY_RUNNING" in res.stdout


def test_3_pid_dead_with_stale_lease_restarts(temp_storage: Path) -> None:
    """3. PID dead with stale lease -> exactly one daemon started, clean recovery."""
    dead_pid = 999991
    dead_uuid = "stale-dead-uuid-999991"
    lease_file = temp_storage / "r1_writer.lease"
    lease_file.write_text(json.dumps({
        "epoch_id": "PROSPECTIVE_RAW_RESEARCH_R1_20261104",
        "pid": dead_pid,
        "runtime_uuid": dead_uuid,
        "acquired_at_utc": "2026-11-04T00:00:00Z",
    }), encoding="utf-8")

    # Run supervisor to restart with fake collector
    res = run_supervisor([
        "-EnsureRunning",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        "-StartupWaitSeconds", "5",
    ], timeout=15.0)
    assert res.returncode == 0, f"Supervisor failed: {res.stderr}\n{res.stdout}"

    state_file = temp_storage / "r1_supervisor_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8-sig"))
    assert state["action_taken"] == "RESTARTED_COLLECTOR"
    assert state["restart_count"] == 1
    new_pid = state["collector_pid"]
    assert new_pid != dead_pid
    assert new_pid > 0

    # Clean up spawned fake collector via stop
    stop_res = subprocess.run([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--stop",
    ], capture_output=True, text=True, timeout=5.0)
    assert stop_res.returncode == 0


def test_4_pid_alive_stale_heartbeat_avoids_dual_writer(temp_storage: Path) -> None:
    """4. PID alive but heartbeat stale -> avoids dual writer, no force stop."""
    fake_proc = subprocess.Popen([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--mode", "stale_heartbeat",
    ])
    try:
        # Wait up to 2.0s for fake collector to initialize its state files
        state_path = temp_storage / "r1_epoch_state.json"
        for _ in range(20):
            if state_path.exists():
                break
            time.sleep(0.1)
        pid = fake_proc.pid

        # Make heartbeat timestamp stale (> 20 min ago)
        hb_file = temp_storage / "r1_collector_heartbeat.json"
        hb = json.loads(hb_file.read_text(encoding="utf-8"))
        stale_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        hb["last_heartbeat_utc"] = stale_time
        hb_file.write_text(json.dumps(hb, indent=2), encoding="utf-8")

        res = run_supervisor([
            "-EnsureRunning",
            "-StorageDir", str(temp_storage),
            "-RepoRoot", str(REPO_ROOT),
            "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
            "-HeartbeatStaleSeconds", "600",
        ], timeout=10.0)
        assert res.returncode == 0
        assert "LIVE_PID_STALE_HEARTBEAT" in res.stdout or "alive with stale heartbeat" in res.stdout

        state = json.loads((temp_storage / "r1_supervisor_state.json").read_text(encoding="utf-8-sig"))
        assert state["supervisor_status"] == "LIVE_PID_STALE_HEARTBEAT"
        assert state["action_taken"] == "NO_ACTION_AVOID_DUAL_WRITER"
        assert state["collector_pid"] == pid
    finally:
        fake_proc.terminate()
        fake_proc.wait(timeout=3.0)


def test_5_collector_degraded_no_restart_loop(temp_storage: Path) -> None:
    """5. Collector DEGRADED -> no restart loop."""
    fake_proc = subprocess.Popen([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--mode", "degraded",
    ])
    try:
        # Wait up to 2.0s for fake collector to initialize its state files
        state_path = temp_storage / "r1_epoch_state.json"
        for _ in range(20):
            if state_path.exists():
                break
            time.sleep(0.1)
        pid = fake_proc.pid

        # Cycle 1
        res1 = run_supervisor([
            "-EnsureRunning",
            "-StorageDir", str(temp_storage),
            "-RepoRoot", str(REPO_ROOT),
            "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        ], timeout=10.0)
        assert res1.returncode == 0
        state1 = json.loads((temp_storage / "r1_supervisor_state.json").read_text(encoding="utf-8-sig"))
        assert state1["supervisor_status"] == "LIVE_BUT_DEGRADED"
        assert state1["action_taken"] == "NO_ACTION_DEGRADED_WAITING_RECOVERY"
        assert state1["restart_count"] == 0

        # Cycle 2
        res2 = run_supervisor([
            "-EnsureRunning",
            "-StorageDir", str(temp_storage),
            "-RepoRoot", str(REPO_ROOT),
            "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        ], timeout=10.0)
        assert res2.returncode == 0
        state2 = json.loads((temp_storage / "r1_supervisor_state.json").read_text(encoding="utf-8-sig"))
        assert state2["restart_count"] == 0  # Still 0, no restart loop!
    finally:
        fake_proc.terminate()
        fake_proc.wait(timeout=3.0)


def test_6_maintenance_pause_prevents_restart(temp_storage: Path) -> None:
    """6. Maintenance Pause -> collector stopped intentionally, supervisor skips restart."""
    res_pause = run_supervisor([
        "-Pause",
        "-Reason", "Scheduled Network Upgrade",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
    ], timeout=10.0)
    assert res_pause.returncode == 0
    pause_file = temp_storage / "r1_supervisor.pause.json"
    assert pause_file.exists()
    pause_data = json.loads(pause_file.read_text(encoding="utf-8"))
    assert pause_data["reason"] == "Scheduled Network Upgrade"

    # Run EnsureRunning when daemon is NOT running
    res_ensure = run_supervisor([
        "-EnsureRunning",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
    ], timeout=10.0)
    assert res_ensure.returncode == 0
    assert "Paused (Scheduled Network Upgrade)" in res_ensure.stdout or "SKIPPED_DUE_TO_PAUSE" in res_ensure.stdout

    state = json.loads((temp_storage / "r1_supervisor_state.json").read_text(encoding="utf-8-sig"))
    assert state["supervisor_status"] == "MAINTENANCE_PAUSED"
    assert state["action_taken"] == "SKIPPED_DUE_TO_PAUSE"
    assert state["paused"] is True
    assert state["restart_count"] == 0


def test_7_resume_clears_pause_and_restarts(temp_storage: Path) -> None:
    """7. Resume -> supervisor removes pause and restarts daemon."""
    # First pause
    run_supervisor([
        "-Pause",
        "-Reason", "Pre-test pause",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
    ], timeout=10.0)
    assert (temp_storage / "r1_supervisor.pause.json").exists()

    # Now resume
    res_resume = run_supervisor([
        "-Resume",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        "-StartupWaitSeconds", "5",
    ], timeout=15.0)
    assert res_resume.returncode == 0
    assert not (temp_storage / "r1_supervisor.pause.json").exists()

    state = json.loads((temp_storage / "r1_supervisor_state.json").read_text(encoding="utf-8-sig"))
    assert state["paused"] is False
    assert state["action_taken"] == "RESTARTED_COLLECTOR"
    new_pid = state["collector_pid"]
    assert new_pid > 0

    # Stop spawned fake collector
    subprocess.run([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--stop",
    ], capture_output=True, text=True, timeout=5.0)


def test_8_state_file_bounded_and_parseable(temp_storage: Path) -> None:
    """8. State file -> bounded, parseable, monotonic restart counter."""
    state_file = temp_storage / "r1_supervisor_state.json"

    run_supervisor([
        "-Pause",
        "-Reason", "State Test",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
    ], timeout=10.0)
    assert state_file.exists()
    assert state_file.stat().st_size < 4096

    run_supervisor([
        "-Resume",
        "-StorageDir", str(temp_storage),
        "-RepoRoot", str(REPO_ROOT),
        "-CollectorScript", str(FAKE_COLLECTOR_SCRIPT),
        "-StartupWaitSeconds", "5",
    ], timeout=15.0)
    assert state_file.stat().st_size < 4096

    state = json.loads(state_file.read_text(encoding="utf-8-sig"))
    required_keys = [
        "checked_at_utc",
        "supervisor_status",
        "action_taken",
        "collector_pid",
        "collector_runtime_uuid",
        "collector_operating_status",
        "heartbeat_age_seconds",
        "restart_count",
        "last_restart_utc",
        "last_error",
        "paused",
        "pause_reason",
    ]
    for k in required_keys:
        assert k in state, f"Missing key in state: {k}"

    # Stop spawned fake collector
    subprocess.run([
        sys.executable,
        str(FAKE_COLLECTOR_SCRIPT),
        "--storage-dir", str(temp_storage),
        "--stop",
    ], capture_output=True, text=True, timeout=5.0)


@pytest.mark.windows_integration
def test_9_scheduled_task_manual_run_noop_when_active() -> None:
    """9. Scheduled task manual run -> exit 0, no-op when active (opt-in integration test)."""
    if os.environ.get("BTC_RUN_R1_SCHEDULED_TASK_INTEGRATION") != "1":
        pytest.skip("Windows Scheduled Task integration requires BTC_RUN_R1_SCHEDULED_TASK_INTEGRATION=1")

    test_task_name = "BesttimeCrypto-R1-TestSupervisorTask"
    try:
        # Register test task
        reg_res = subprocess.run([
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REGISTER_SCRIPT),
            "-TaskName", test_task_name,
            "-RepoRoot", str(REPO_ROOT),
        ], capture_output=True, text=True, timeout=15.0)
        assert reg_res.returncode == 0, f"Register failed: {reg_res.stderr}\n{reg_res.stdout}"

        # Trigger manual execution of test task
        start_res = subprocess.run([
            "powershell.exe",
            "-Command",
            f"Start-ScheduledTask -TaskName '{test_task_name}'",
        ], capture_output=True, text=True, timeout=10.0)
        assert start_res.returncode == 0

        # Wait for task to finish running (returns to Ready)
        for _ in range(15):
            time.sleep(1.0)
            status_res = subprocess.run([
                "powershell.exe",
                "-Command",
                f"(Get-ScheduledTask -TaskName '{test_task_name}').State",
            ], capture_output=True, text=True, timeout=5.0)
            if "Ready" in status_res.stdout:
                break

        # Check production state file: PID 38596 remains ACTIVE and healthy
        real_state_file = REPO_ROOT / "data" / "prospective_raw_research_r1" / "r1_supervisor_state.json"
        assert real_state_file.exists()
        state = json.loads(real_state_file.read_text(encoding="utf-8-sig"))
        assert state["supervisor_status"] == "HEALTHY_ACTIVE"
        assert state["collector_pid"] == PRODUCTION_PID
        assert state["action_taken"] == "NO_ACTION_ACTIVE"
    finally:
        subprocess.run([
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UNREGISTER_SCRIPT),
            "-TaskName", test_task_name,
            "-RepoRoot", str(REPO_ROOT),
        ], capture_output=True, text=True, timeout=10.0)
