"""tests/fixtures/fake_r1_collector.py

Deterministic Fake Collector Fixture for Prospective R1 Supervisor Tests
========================================================================
Simulates genuine collector lifecycle events without calling Binance network:
- Writes valid lease, heartbeat, and state checkpoint using its own PID.
- Supports daemon mode, --status, and --stop.
- Configurable modes: active, degraded, stale_heartbeat, delayed_startup, fail_startup.
- Exits cooperatively and cleanly in < 1 second upon receiving r1_stop.request.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

R1_EPOCH_ID = "PROSPECTIVE_RAW_RESEARCH_R1_20261104"
R1_AUTHORIZED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]


def get_now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        still_active = 259
        res = kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        kernel32.CloseHandle(h)
        return bool(res and exit_code.value == still_active)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Fake R1 Collector Fixture")
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--mode", choices=["active", "degraded", "stale_heartbeat", "delayed_startup", "fail_startup"], default="active")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args()

    storage_dir = args.storage_dir.resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)

    lease_file = storage_dir / "r1_writer.lease"
    hb_file = storage_dir / "r1_collector_heartbeat.json"
    state_file = storage_dir / "r1_epoch_state.json"
    manifest_file = storage_dir / "r1_manifest.json"
    stop_file = storage_dir / "r1_stop.request"

    if args.status:
        # Read status and output json matching supervisor contract
        op_status = "RESEARCH_EPOCH_STOPPED"
        lease_data = None
        hb_data = None
        state_data = None

        if lease_file.exists():
            try:
                lease_data = json.loads(lease_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if hb_file.exists():
            try:
                hb_data = json.loads(hb_file.read_text(encoding="utf-8"))
                op_status = hb_data.get("operating_status", "RESEARCH_EPOCH_ACTIVE")
            except Exception:
                pass

        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
                if not hb_data:
                    op_status = state_data.get("operating_status", op_status)
            except Exception:
                pass

        # If lease exists but PID is dead, mark dead
        if lease_data and lease_data.get("pid"):
            if not is_pid_alive(int(lease_data["pid"])):
                op_status = "RESEARCH_EPOCH_STOPPED"

        out = {
            "operating_status": op_status,
            "epoch_summary": {
                "epoch_id": R1_EPOCH_ID,
                "manifest_sha256": "fake_manifest_hash_12345",
                "operating_status": op_status,
                "candidate_id": None,
                "promotion_clock": "NOT_APPLICABLE",
                "counters": (state_data and state_data.get("counters")) or {
                    "total_ingested": 9,
                    "complete_batches": 1,
                    "duplicates_rejected": 0,
                    "gaps_detected": 0,
                    "incomplete_batches": 0,
                },
                "authorized_symbols": R1_AUTHORIZED_SYMBOLS,
            },
            "heartbeat": hb_data,
            "lease": lease_data,
        }
        print(json.dumps(out, indent=2))
        return

    if args.stop:
        # Issue cooperative stop request
        pid = None
        ruuid = ""
        if lease_file.exists():
            try:
                ld = json.loads(lease_file.read_text(encoding="utf-8"))
                pid = ld.get("pid")
                ruuid = ld.get("runtime_uuid", "")
            except Exception:
                pass
        if not pid and hb_file.exists():
            try:
                hd = json.loads(hb_file.read_text(encoding="utf-8"))
                pid = hd.get("pid")
                ruuid = hd.get("runtime_uuid", "")
            except Exception:
                pass

        if not pid or not is_pid_alive(int(pid)):
            print(f"Fake collector is not actively running (PID: {pid}).")
            return

        stop_payload = {
            "epoch_id": R1_EPOCH_ID,
            "requested_at_utc": get_now_utc_iso(),
            "target_pid": int(pid),
            "target_runtime_uuid": ruuid,
        }
        tmp_stop = storage_dir / f"r1_stop.request.tmp.{uuid.uuid4().hex[:8]}"
        tmp_stop.write_text(json.dumps(stop_payload, indent=2), encoding="utf-8")
        tmp_stop.replace(stop_file)

        start_w = time.time()
        while time.time() - start_w < args.timeout:
            if not is_pid_alive(int(pid)):
                print(f"Cooperative stop confirmed. Fake PID {pid} exited.")
                return
            time.sleep(0.1)

        print(f"TIMEOUT waiting for PID {pid} to stop.", file=sys.stderr)
        sys.exit(1)

    # Daemon mode
    if args.mode == "fail_startup":
        sys.exit(1)

    if args.mode == "delayed_startup" and args.delay_seconds > 0:
        time.sleep(args.delay_seconds)

    my_pid = os.getpid()
    my_uuid = str(uuid.uuid4())
    started_iso = get_now_utc_iso()

    # 1. Acquire lease
    lease_payload = {
        "epoch_id": R1_EPOCH_ID,
        "pid": my_pid,
        "runtime_uuid": my_uuid,
        "acquired_at_utc": started_iso,
    }
    lease_file.write_text(json.dumps(lease_payload, indent=2), encoding="utf-8")

    # 2. Write initial state checkpoint
    op_status = "RESEARCH_EPOCH_DEGRADED" if args.mode == "degraded" else "RESEARCH_EPOCH_ACTIVE"
    state_payload = {
        "epoch_id": R1_EPOCH_ID,
        "operating_status": op_status,
        "counters": {
            "total_ingested": 9,
            "complete_batches": 1,
            "duplicates_rejected": 0,
            "gaps_detected": 0,
            "incomplete_batches": 0,
        },
    }
    state_file.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")

    # 3. Write initial heartbeat
    hb_payload = {
        "epoch_id": R1_EPOCH_ID,
        "pid": my_pid,
        "runtime_uuid": my_uuid,
        "started_at_utc": started_iso,
        "last_heartbeat_utc": started_iso,
        "last_successful_poll_utc": started_iso,
        "collector_status": "RUNNING",
        "operating_status": op_status,
        "consecutive_failures": 3 if args.mode == "degraded" else 0,
        "missing_symbols": ["BTC"] if args.mode == "degraded" else [],
        "symbol_statuses": {s: ("MISSING" if s == "BTC" and args.mode == "degraded" else "OK") for s in R1_AUTHORIZED_SYMBOLS},
        "backlog_batches": 0,
        "backfill_in_progress": False,
    }
    hb_file.write_text(json.dumps(hb_payload, indent=2), encoding="utf-8")

    # Handle graceful termination signals
    def sig_handler(signum, frame):
        cleanup_and_exit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    def cleanup_and_exit():
        try:
            if lease_file.exists():
                lease_file.unlink()
            if hb_file.exists():
                hb = json.loads(hb_file.read_text(encoding="utf-8"))
                hb["collector_status"] = "STOPPED"
                hb_file.write_text(json.dumps(hb, indent=2), encoding="utf-8")
            if state_file.exists():
                st = json.loads(state_file.read_text(encoding="utf-8"))
                st["operating_status"] = "RESEARCH_EPOCH_STOPPED"
                state_file.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except Exception:
            pass
        sys.exit(0)

    # Main run loop
    last_hb_update = time.time()
    while True:
        # Check stop request
        if stop_file.exists():
            try:
                s_data = json.loads(stop_file.read_text(encoding="utf-8"))
                if s_data.get("target_pid") == my_pid:
                    try:
                        stop_file.unlink()
                    except Exception:
                        pass
                    cleanup_and_exit()
            except Exception:
                pass

        time.sleep(0.2)

        # Update heartbeat periodically unless in stale_heartbeat mode
        if args.mode != "stale_heartbeat" and (time.time() - last_hb_update >= 1.0):
            try:
                hb_payload["last_heartbeat_utc"] = get_now_utc_iso()
                hb_file.write_text(json.dumps(hb_payload, indent=2), encoding="utf-8")
                last_hb_update = time.time()
            except Exception:
                pass


if __name__ == "__main__":
    main()

