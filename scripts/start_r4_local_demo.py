"""
Start R4 Local Demo Paper Runner.
Initializes isolated runtime environment under runtime/local-demo/r4-<timestamp>/
and starts exactly one background runner process locked to BTC, ETH, BNB.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

def get_running_main_pids():
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*main.py*' } | Select-Object -ExpandProperty ProcessId"],
            text=True
        ).strip()
        return [int(p.strip()) for p in out.splitlines() if p.strip()]
    except Exception:
        return []

def main():
    running_pids = get_running_main_pids()
    if running_pids:
        print(f"[ERROR] Found running main.py process(es): {running_pids}. Aborting startup.", file=sys.stderr)
        sys.exit(1)

    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    r4_root = (REPO_ROOT / "runtime" / "local-demo" / f"r4-{ts_str}").resolve()
    
    data_dir = r4_root / "data" / "execution"
    logs_dir = r4_root / "logs" / "prediction_audit"
    state_dir = r4_root / "state"
    models_dir = r4_root / "models"

    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["BTC_RUNTIME_ROOT"] = str(r4_root)
    env["BTC_RUNTIME_ENVIRONMENT"] = "paper"
    env["BTC_DEPLOYMENT_ID"] = "local-demo-r4"
    env["BTC_EPOCH_ID"] = f"p8-local-demo-r4-{ts_str}"
    env["BTC_PAPER_RUN_ID"] = f"local-demo-r4-{ts_str}"
    env["BTC_ANALYSIS_UNIVERSE"] = "BTC,ETH,BNB"
    env["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    env["LIVE_TRADING_ENABLED"] = "false"
    env["AUTO_TRADE_DRY_RUN"] = "true"
    env["BTC_EVIDENCE_ELIGIBLE"] = "false"
    env["BTC_DISABLE_RUNTIME_LOCK"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)

    commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()

    manifest = {
        "epoch_id": f"p8-local-demo-r4-{ts_str}",
        "paper_run_id": f"local-demo-r4-{ts_str}",
        "deployment_id": "local-demo-r4",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "code_commit_sha": commit_sha,
        "runtime_root": str(r4_root),
        "universe": ["BTC", "ETH", "BNB"],
        "mode": "paper_dry_run",
        "live_trading_enabled": False,
        "single_runner_lock_enabled": True,
    }

    manifest_path = r4_root / "r4_startup_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    runner_log_path = r4_root / "logs" / "r4_runner.log"
    log_file = open(runner_log_path, "a", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    print("=" * 75)
    print("   BESTTIME CRYPTO — R4 LOCAL DEMO RUNNER LAUNCHED")
    print("=" * 75)
    print(f"PID:           {proc.pid}")
    print(f"Epoch ID:      {manifest['epoch_id']}")
    print(f"Paper Run ID:  {manifest['paper_run_id']}")
    print(f"Runtime Root:  {manifest['runtime_root']}")
    print(f"Commit SHA:    {commit_sha}")
    print(f"Universe:      BTC, ETH, BNB")
    print(f"Log File:      {runner_log_path}")
    print("=" * 75)

if __name__ == "__main__":
    main()
