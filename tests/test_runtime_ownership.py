from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from btc_scraper.core.paths import REPO_ROOT, get_runtime_paths
from btc_scraper.core.runtime_ownership import (
    RuntimeLock,
    RuntimeLockError,
    describe_runtime_changes,
    snapshot_runtime_roots,
    write_owner_sidecar,
)


OWNERSHIP_ENV_KEYS = [
    "BTC_RUNTIME_ROOT",
    "BTC_DATA_DIR",
    "BTC_LOG_DIR",
    "BTC_MODEL_DIR",
    "BTC_STATE_DIR",
    "BTC_EXECUTION_DATA_DIR",
    "BTC_PREDICTION_AUDIT_DIR",
    "BTC_RUNTIME_EVIDENCE_PATH",
    "BTC_RESERVATION_DB_PATH",
    "BTC_RUNTIME_LOCK_PATH",
    "CATBOOST_INFO_DIR",
]


def _clear_path_overrides(monkeypatch):
    for key in OWNERSHIP_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_owned_runtime_roots_are_scoped_by_environment_and_deployment(monkeypatch, tmp_path):
    _clear_path_overrides(monkeypatch)
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "paper-a")
    monkeypatch.setenv("BTC_RUNTIME_ID", "runtime-paper-a")
    monkeypatch.setenv("BTC_RUNTIME_ROOT", str(tmp_path / "runtime" / "paper" / "paper-a"))

    first = get_runtime_paths()

    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "paper-b")
    monkeypatch.setenv("BTC_RUNTIME_ID", "runtime-paper-b")
    monkeypatch.setenv("BTC_RUNTIME_ROOT", str(tmp_path / "runtime" / "paper" / "paper-b"))
    second = get_runtime_paths()

    assert first.environment == "paper"
    assert first.deployment_id == "paper-a"
    assert first.runtime_id == "runtime-paper-a"
    assert first.data_root != REPO_ROOT / "data"
    assert first.logs_root != REPO_ROOT / "logs"
    assert first.runtime_evidence_path != second.runtime_evidence_path
    assert first.reservation_db_path != second.reservation_db_path
    assert first.runtime_lock_path != second.runtime_lock_path


def test_runtime_lock_blocks_same_deployment_and_recovers_stale_lock(monkeypatch, tmp_path):
    _clear_path_overrides(monkeypatch)
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "lock-a")
    monkeypatch.setenv("BTC_RUNTIME_ID", "runtime-lock-a")
    monkeypatch.setenv("BTC_RUNTIME_ROOT", str(tmp_path / "runtime" / "paper" / "lock-a"))

    first = RuntimeLock()
    lock_info = first.acquire()
    assert lock_info["deployment_id"] == "lock-a"
    with pytest.raises(RuntimeLockError):
        RuntimeLock().acquire()
    assert first.release() is True

    stale = {
        **lock_info,
        "runtime_id": "dead-runtime",
        "process_id": 999999999,
    }
    first.lock_path.parent.mkdir(parents=True, exist_ok=True)
    first.lock_path.write_text(json.dumps(stale), encoding="utf-8")
    recovered = RuntimeLock().acquire()

    assert recovered["runtime_id"] == "runtime-lock-a"
    audit = (get_runtime_paths().state_root / "runtime_lock_events.jsonl").read_text(encoding="utf-8")
    assert "stale_lock_recovered" in audit


def test_subprocess_deployments_are_isolated_and_same_deployment_conflicts(tmp_path):
    base_env = os.environ.copy()
    for key in OWNERSHIP_ENV_KEYS:
        base_env.pop(key, None)
    base_env["PYTHONPATH"] = str(REPO_ROOT)
    base_env["BTC_RUNTIME_ENVIRONMENT"] = "paper"

    query_script = """
import json
from btc_scraper.core.paths import get_runtime_paths
p = get_runtime_paths()
print(json.dumps({
    "data_root": str(p.data_root),
    "logs_root": str(p.logs_root),
    "runtime_evidence_path": str(p.runtime_evidence_path),
    "reservation_db_path": str(p.reservation_db_path),
    "runtime_lock_path": str(p.runtime_lock_path),
}))
"""
    env_a = {**base_env, "BTC_DEPLOYMENT_ID": "deploy-a", "BTC_RUNTIME_ID": "runtime-a", "BTC_RUNTIME_ROOT": str(tmp_path / "runtime" / "paper" / "deploy-a")}
    env_b = {**base_env, "BTC_DEPLOYMENT_ID": "deploy-b", "BTC_RUNTIME_ID": "runtime-b", "BTC_RUNTIME_ROOT": str(tmp_path / "runtime" / "paper" / "deploy-b")}
    paths_a = json.loads(subprocess.check_output([sys.executable, "-c", query_script], cwd=REPO_ROOT, env=env_a, text=True))
    paths_b = json.loads(subprocess.check_output([sys.executable, "-c", query_script], cwd=REPO_ROOT, env=env_b, text=True))

    assert paths_a["data_root"] != paths_b["data_root"]
    assert paths_a["logs_root"] != paths_b["logs_root"]
    assert paths_a["runtime_evidence_path"] != paths_b["runtime_evidence_path"]
    assert paths_a["reservation_db_path"] != paths_b["reservation_db_path"]

    holder_script = """
import json, time
from btc_scraper.core.runtime_ownership import RuntimeLock
lock = RuntimeLock()
payload = lock.acquire()
print(json.dumps({"status": "ready", "lock_path": str(lock.lock_path), "runtime_id": payload["runtime_id"]}), flush=True)
time.sleep(10)
"""
    conflict_script = """
from btc_scraper.core.runtime_ownership import RuntimeLock, RuntimeLockError
try:
    RuntimeLock().acquire()
except RuntimeLockError:
    print("blocked")
else:
    print("unexpected-acquired")
"""
    holder_env = {**base_env, "BTC_DEPLOYMENT_ID": "deploy-conflict", "BTC_RUNTIME_ID": "runtime-holder", "BTC_RUNTIME_ROOT": str(tmp_path / "runtime" / "paper" / "deploy-conflict")}
    contender_env = {**holder_env, "BTC_RUNTIME_ID": "runtime-contender"}
    holder = subprocess.Popen([sys.executable, "-c", holder_script], cwd=REPO_ROOT, env=holder_env, text=True, stdout=subprocess.PIPE)
    try:
        ready = json.loads(holder.stdout.readline())
        assert ready["status"] == "ready"
        result = subprocess.check_output([sys.executable, "-c", conflict_script], cwd=REPO_ROOT, env=contender_env, text=True).strip()
        assert result == "blocked"
    finally:
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()


def test_runtime_guard_fingerprint_reports_hash_and_owner(tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    target = watched / "state.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    before = snapshot_runtime_roots([watched])

    target.write_text('{"version": 2}', encoding="utf-8")
    write_owner_sidecar(target, {"runtime_id": "runtime-writer", "process_id": 12345})
    after = snapshot_runtime_roots([watched])
    changes = describe_runtime_changes(before, after, repo_root=tmp_path)

    state_change = next(change for change in changes if change["path"] == "watched/state.json")
    assert state_change["before_hash"] != state_change["after_hash"]
    assert state_change["suspected_writer_runtime_id"] == "runtime-writer"
    assert state_change["suspected_writer_process_id"] == 12345
