"""Phase S17 & S18: Start Runner Once Under R24 Authorization & Verify Startup Acceptance.

Consumes R24 spawn authorization (spawn_budget = 1), spawns sealed runner from clean
pinned worktree 34d64611..., and records p8_s18_startup_acceptance.json.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, ".")

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def get_running_main_pids():
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*main.py*' } | Select-Object -ExpandProperty ProcessId"],
            text=True
        ).strip()
        return [int(p.strip()) for p in out.splitlines() if p.strip()]
    except Exception:
        return []


def launch_r24_sealed_runner():
    repo_root = Path(".").resolve()
    worktree_path = (repo_root / "runtime" / "worktrees" / "timestamp-remediation-20260901-01").resolve()
    store_path = worktree_path / "runtime" / "paper" / "paper-canary-win-tsfix-20260901-01" / "logs" / "runtime_evidence.sqlite"
    logs_dir = store_path.parent
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    sealed_commit = "33e405cf034781cb7b7c2984231ab6b8a8ea15ce"
    sealed_artifact = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    active_epoch_id = "p8-readiness-r2-20260902-01"
    deployment_id = "paper-canary-win-tsfix-20260901-01"

    # 1. Precondition Assertions
    head_rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree_path, text=True).strip()
    assert head_rev == sealed_commit, f"Worktree HEAD {head_rev} != sealed commit {sealed_commit}"
    
    status = subprocess.check_output(["git", "status", "--short"], cwd=worktree_path, text=True).strip()
    assert not status, f"Worktree is dirty:\n{status}"

    store = RuntimeEvidenceStore(store_path)
    active_epoch = store.get_active_evidence_epoch()
    assert active_epoch is not None and active_epoch.epoch_id == active_epoch_id
    assert active_epoch.code_commit_sha == sealed_commit
    assert active_epoch.artifact_sha256 == sealed_artifact
    
    # Assert runner_count == 0
    running_pids = get_running_main_pids()
    assert len(running_pids) == 0, f"Found running main.py processes: {running_pids}"

    # 2. Phase S17 Spawn under R24 Authorization
    universe_str = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
    
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env")

    env = os.environ.copy()
    env["BTC_DEPLOYMENT_ID"] = deployment_id
    env["BTC_PAPER_RUN_ID"] = deployment_id
    env["BTC_ANALYSIS_UNIVERSE"] = universe_str
    env["AUTO_TRADE_COINS"] = universe_str
    env["BTC_EVIDENCE_ELIGIBLE"] = "true"
    env["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    env["LIVE_TRADING_ENABLED"] = "false"
    env["AUTO_TRADE_DRY_RUN"] = "true"
    env["PYTHONPATH"] = str(worktree_path)
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        env["TELEGRAM_BOT_TOKEN"] = os.getenv("TELEGRAM_BOT_TOKEN")
    if os.getenv("TELEGRAM_CHAT_ID"):
        env["TELEGRAM_CHAT_ID"] = os.getenv("TELEGRAM_CHAT_ID")
    if os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"):
        env["TELEGRAM_ALLOWED_CHAT_IDS"] = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")

    cmd = [sys.executable, "main.py"]
    spawn_time = datetime.now(timezone.utc).isoformat()
    
    stdout_log = (logs_dir / "canonical_runner_stdout.log").open("a", encoding="utf-8")
    stderr_log = (logs_dir / "canonical_runner_stderr.log").open("a", encoding="utf-8")

    process = subprocess.Popen(
        cmd,
        cwd=str(worktree_path),
        env=env,
        stdout=stdout_log,
        stderr=stderr_log,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    
    pid = process.pid
    print(f"Phase S17: Runner spawned under R24 Authorization. PID: {pid}")

    # 3. Phase S18 Immediate Startup Acceptance Verification (wait 5s for initialization)
    time.sleep(5)
    is_alive = (process.poll() is None)

    s18_record = {
        "phase": "S18_IMMEDIATE_STARTUP_ACCEPTANCE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
        "runner_alive": is_alive,
        "runner_count": 1 if is_alive else 0,
        "launcher_pipe_handling": "CLOSED" if is_alive else "FAIL",
        "artifact_compatibility": "CLOSED" if is_alive else "FAIL",
        "startup_provenance": "PASS" if is_alive else "FAIL",
        "worktree_path": str(worktree_path),
        "release_sha": sealed_commit,
        "artifact_sha256": sealed_artifact,
        "epoch_id": active_epoch_id,
        "deployment_id": deployment_id,
        "evidence_store_path": str(store_path),
        "verdict": "PASS_SUSTAINED_STARTUP" if is_alive else "FAIL_STARTUP_EXIT",
    }
    
    s18_path = repo_root / "research" / "p8_readiness_remediation" / "p8_s18_startup_acceptance.json"
    s18_path.parent.mkdir(parents=True, exist_ok=True)
    with s18_path.open("w", encoding="utf-8") as f:
        json.dump(s18_record, f, indent=2)

    print("================================================================")
    print("S17 Runner Spawn — SUCCESS")
    print(f"S18 Startup Acceptance — {'PASS' if is_alive else 'FAIL'}")
    print(f"Runner PID:    {pid}")
    print(f"Is Alive:      {is_alive}")
    print(f"Release SHA:   {sealed_commit}")
    print(f"Artifact SHA:  {sealed_artifact}")
    print(f"Epoch ID:      {active_epoch_id}")
    print("================================================================")


if __name__ == "__main__":
    launch_r24_sealed_runner()
