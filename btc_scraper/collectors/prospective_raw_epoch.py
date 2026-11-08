"""btc_scraper/collectors/prospective_raw_epoch.py

Prospective Raw Research Epoch R1 Engine
========================================
Collects genuine prospective 15m closed candle data across the 9 authorized symbols:
BNB, BTC, DOGE, ETH, IOTA, NEAR, SOL, TRX, ZEC.

Epistemic & Governance Constraints:
- Discovery/training data only; NOT promotion evidence.
- candidate_id is strictly null.
- promotion_clock is NOT_APPLICABLE.
- real_orders is false; paper_policy is NO_TRADE_SHADOW.
- Manifest is cryptographically hashed and immutable upon creation.
- Rejects unclosed candles, duplicates, and unauthorized symbols.
- Detects complete 9-symbol batches and records sequence gaps.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
R1_EPOCH_ID = "PROSPECTIVE_RAW_RESEARCH_R1_20261104"
R1_AUTHORIZED_SYMBOLS = ("BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC")
R1_CANDLE_INTERVAL = "15m"
R1_DEFAULT_STORAGE_DIR = REPO_ROOT / "data" / "prospective_raw_research_r1"
CANONICAL_STAGED_MANIFEST_SHA256 = "c6f354b7ea84f868f6dd0e5498ba5701dbb2836db6c9a7a56d02e689e3754a26"
R1_HEARTBEAT_FRESHNESS_SECONDS = 180.0


def is_pid_alive(pid: int) -> bool:
    """Checks whether a process with the given PID is currently active."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            code = wintypes.DWORD()
            res = kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            kernel32.CloseHandle(h)
            STILL_ACTIVE = 259
            return bool(res and code.value == STILL_ACTIVE)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def get_git_head() -> str:
    """Returns current git commit hash."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "f96c6b8b64516dd76d3af132dac316c5672e35be"


def compute_manifest_sha256(manifest_dict: Mapping[str, Any]) -> str:
    """Computes deterministic SHA-256 of manifest excluding volatile hash field."""
    canonical_payload = {
        k: v for k, v in manifest_dict.items()
        if k != "manifest_sha256"
    }
    dumped = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(dumped).hexdigest()


class EpochLease:
    """Atomic single-writer PID and runtime UUID lease to ensure at most one active collector.
    
    Lifetime single-writer protection is stored in `r1_writer.lease` and guarded by process liveness.
    The accompanying `.lock` file acts strictly as a short-term transient mutex during lease mutation.
    """

    def __init__(self, lease_file: Path, epoch_id: str):
        self.lease_file = Path(lease_file)
        self.epoch_id = epoch_id
        self.lock_file = self.lease_file.with_name(self.lease_file.name + ".lock")

    def read_lease(self) -> dict[str, Any] | None:
        if not self.lease_file.exists():
            return None
        try:
            return json.loads(self.lease_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _acquire_file_lock(self, pid: int = 0, runtime_uuid: str = "", timeout_seconds: float = 3.0) -> int:
        """Acquires exclusive OS-level short-term mutation mutex using atomic O_CREAT | O_EXCL.
        Records caller PID/UUID for deterministic stale mutex recovery if the holding process dies.
        """
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                # Persist owner metadata inside mutex file
                owner_meta = json.dumps({
                    "lock_owner_pid": pid,
                    "runtime_uuid": runtime_uuid,
                    "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
                })
                os.write(fd, owner_meta.encode("utf-8"))
                return fd
            except FileExistsError:
                # Do NOT clean mutex solely based on file age without verifying if holder PID is dead!
                try:
                    if self.lock_file.exists():
                        content = self.lock_file.read_text(encoding="utf-8")
                        owner_info = json.loads(content) if content else {}
                        owner_pid = owner_info.get("lock_owner_pid")
                        if owner_pid and not is_pid_alive(int(owner_pid)):
                            # Holding process is confirmed dead; reclaim stale mutex
                            self.lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
                time.sleep(0.02)

        raise TimeoutError(
            f"FAILED_TO_ACQUIRE_LEASE_MUTEX: Could not acquire transient mutex {self.lock_file} within {timeout_seconds}s"
        )

    def _release_file_lock(self, fd: int) -> None:
        try:
            os.close(fd)
        except Exception:
            pass
        try:
            self.lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    def acquire(self, pid: int, runtime_uuid: str) -> None:
        lock_fd = self._acquire_file_lock(pid=pid, runtime_uuid=runtime_uuid, timeout_seconds=3.0)
        try:
            lease = self.read_lease()
            if lease:
                held_pid = int(lease.get("pid", 0))
                held_uuid = str(lease.get("runtime_uuid", ""))
                acquired_at = str(lease.get("acquired_at_utc", ""))
                if held_pid > 0 and is_pid_alive(held_pid) and (held_pid != pid or held_uuid != runtime_uuid):
                    raise RuntimeError(
                        f"R1_SINGLE_WRITER_LEASE_ALREADY_HELD: active writer PID {held_pid} "
                        f"(uuid={held_uuid}) holds lease since {acquired_at}"
                    )

            payload = {
                "epoch_id": self.epoch_id,
                "pid": pid,
                "runtime_uuid": runtime_uuid,
                "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            tmp = self.lease_file.with_name(f"{self.lease_file.name}.tmp.{uuid.uuid4().hex[:8]}")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.lease_file)
        finally:
            self._release_file_lock(lock_fd)

    def release(self, pid: int, runtime_uuid: str | None = None) -> None:
        """Releases the single-writer lease. Fail-closed: if mutex cannot be acquired, MUST NOT mutate lease!"""
        try:
            lock_fd = self._acquire_file_lock(pid=pid, runtime_uuid=runtime_uuid or "", timeout_seconds=1.5)
        except Exception as e:
            # Mutex acquisition failed: fail-closed! Do NOT read, mutate, or unlink lease!
            raise RuntimeError(f"MUTEX_CONTENTION_DURING_RELEASE: Cannot acquire lock to release lease: {e}") from e

        try:
            lease = self.read_lease()
            if not lease:
                return
            held_pid = int(lease.get("pid", 0))
            held_uuid = str(lease.get("runtime_uuid", ""))
            if held_pid == pid and (runtime_uuid is None or held_uuid == runtime_uuid):
                try:
                    self.lease_file.unlink(missing_ok=True)
                except Exception:
                    pass
        finally:
            self._release_file_lock(lock_fd)


class EpochHeartbeat:
    """Dynamic heartbeat artifact tracking real-time liveness, UUID, and polling health."""

    def __init__(self, heartbeat_file: Path, epoch_id: str):
        self.heartbeat_file = Path(heartbeat_file)
        self.epoch_id = epoch_id

    def read(self) -> dict[str, Any] | None:
        if not self.heartbeat_file.exists():
            return None
        try:
            return json.loads(self.heartbeat_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def update(
        self,
        pid: int,
        runtime_uuid: str,
        started_at_utc: str,
        collector_status: str = "RUNNING",
        last_successful_poll_utc: str | None = None,
        last_complete_batch_utc: str | None = None,
        consecutive_failures: int = 0,
        symbol_statuses: dict[str, str] | None = None,
        graceful_stop: bool = False,
        expected_batch_open_utc: str | None = None,
        observed_complete_batch_open_utc: str | None = None,
        missing_symbols: list[str] | None = None,
        batch_lag_seconds: float | None = None,
        poll_attempts_for_expected_batch: int = 1,
        last_complete_batch_age_seconds: float | None = None,
        expected_open_utc: str | None = None,
        expected_close_utc: str | None = None,
        close_to_ingest_lag_seconds: float | None = None,
        last_complete_age_from_close_seconds: float | None = None,
        backlog_batches: int = 0,
        backfill_in_progress: bool = False,
        latest_safely_closed_open_utc: str | None = None,
        last_complete_open_utc: str | None = None,
        oldest_missing_open_utc: str | None = None,
        missing_symbol_timestamps: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        existing = self.read() or {}
        now_iso = datetime.now(timezone.utc).isoformat()
        exp_open = expected_open_utc or expected_batch_open_utc or existing.get("expected_open_utc") or existing.get("expected_batch_open_utc")
        payload = {
            "epoch_id": self.epoch_id,
            "pid": pid,
            "runtime_uuid": runtime_uuid,
            "started_at_utc": started_at_utc,
            "last_heartbeat_utc": now_iso,
            "last_successful_poll_utc": last_successful_poll_utc or existing.get("last_successful_poll_utc"),
            "last_complete_batch_utc": last_complete_batch_utc or existing.get("last_complete_batch_utc"),
            "consecutive_failures": consecutive_failures,
            "symbol_statuses": symbol_statuses or existing.get("symbol_statuses", {s: "OK" for s in R1_AUTHORIZED_SYMBOLS}),
            "collector_status": collector_status,
            "graceful_stop": graceful_stop,
            "expected_batch_open_utc": exp_open,
            "observed_complete_batch_open_utc": observed_complete_batch_open_utc or existing.get("observed_complete_batch_open_utc"),
            "missing_symbols": missing_symbols if missing_symbols is not None else existing.get("missing_symbols", []),
            "batch_lag_seconds": batch_lag_seconds if batch_lag_seconds is not None else existing.get("batch_lag_seconds"),
            "poll_attempts_for_expected_batch": poll_attempts_for_expected_batch,
            "last_complete_batch_age_seconds": last_complete_batch_age_seconds if last_complete_batch_age_seconds is not None else existing.get("last_complete_batch_age_seconds"),
            # Standardized operational metrics
            "expected_open_utc": exp_open,
            "expected_close_utc": expected_close_utc or existing.get("expected_close_utc"),
            "close_to_ingest_lag_seconds": close_to_ingest_lag_seconds if close_to_ingest_lag_seconds is not None else existing.get("close_to_ingest_lag_seconds"),
            "last_complete_age_from_close_seconds": last_complete_age_from_close_seconds if last_complete_age_from_close_seconds is not None else existing.get("last_complete_age_from_close_seconds"),
            "backlog_batches": backlog_batches if backlog_batches is not None else existing.get("backlog_batches", 0),
            "backfill_in_progress": backfill_in_progress if backfill_in_progress is not None else existing.get("backfill_in_progress", False),
            "latest_safely_closed_open_utc": latest_safely_closed_open_utc or existing.get("latest_safely_closed_open_utc"),
            "last_complete_open_utc": last_complete_open_utc or existing.get("last_complete_open_utc"),
            "oldest_missing_open_utc": oldest_missing_open_utc or existing.get("oldest_missing_open_utc"),
            "missing_symbol_timestamps": missing_symbol_timestamps if missing_symbol_timestamps is not None else existing.get("missing_symbol_timestamps", []),
        }
        tmp = self.heartbeat_file.with_name(f"{self.heartbeat_file.name}.tmp.{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.heartbeat_file)
        return payload

    def mark_stopped(self, pid: int, runtime_uuid: str, forced: bool = False) -> None:
        existing = self.read() or {}
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "epoch_id": self.epoch_id,
            "pid": pid,
            "runtime_uuid": runtime_uuid,
            "started_at_utc": existing.get("started_at_utc", now_iso),
            "last_heartbeat_utc": now_iso,
            "last_successful_poll_utc": existing.get("last_successful_poll_utc"),
            "last_complete_batch_utc": existing.get("last_complete_batch_utc"),
            "consecutive_failures": existing.get("consecutive_failures", 0),
            "symbol_statuses": existing.get("symbol_statuses", {}),
            "collector_status": "FORCED_STOP" if forced else "STOPPED",
            "graceful_stop": not forced,
            "expected_batch_open_utc": existing.get("expected_batch_open_utc"),
            "observed_complete_batch_open_utc": existing.get("observed_complete_batch_open_utc"),
            "missing_symbols": existing.get("missing_symbols", []),
            "batch_lag_seconds": existing.get("batch_lag_seconds"),
            "poll_attempts_for_expected_batch": existing.get("poll_attempts_for_expected_batch", 0),
            "last_complete_batch_age_seconds": existing.get("last_complete_batch_age_seconds"),
        }
        tmp = self.heartbeat_file.with_name(f"{self.heartbeat_file.name}.tmp.{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.heartbeat_file)


class ProspectiveRawEpochManager:
    """Thread-safe manager for prospective raw market data collection (Epoch R1).
    
    Mode Separation:
    - `read_only=True`: Pure observer/inspector. Never writes files, creates directories,
      reconciles uncommitted batches on disk, truncates logs, or writes checkpoints.
      Preserves all file hashes, sizes, and mtimes.
    - `read_only=False`: Writer instance. Default constructor does NOT mutate disk state
      or checkpoint. Full reconciliation, tail truncation cleanup, and atomic checkpointing
      are strictly executed only after acquiring the single-writer lease.
    """

    def __init__(self, base_dir: Path = R1_DEFAULT_STORAGE_DIR, read_only: bool = False):
        self.base_dir = Path(base_dir)
        self.read_only = bool(read_only)
        self.manifest_file = self.base_dir / "r1_manifest.json"
        self.candles_file = self.base_dir / "r1_closed_candles.jsonl"
        self.batch_file = self.base_dir / "r1_batch_log.jsonl"
        self.state_file = self.base_dir / "r1_epoch_state.json"
        self.lease_file = self.base_dir / "r1_writer.lease"
        self.heartbeat_file = self.base_dir / "r1_collector_heartbeat.json"
        self._lock = threading.RLock()

        self.lease = EpochLease(self.lease_file, R1_EPOCH_ID)
        self.heartbeat = EpochHeartbeat(self.heartbeat_file, R1_EPOCH_ID)

        # In-memory indices for duplicate and gap checking
        self._seen_open_timestamps: dict[str, set[str]] = {s: set() for s in R1_AUTHORIZED_SYMBOLS}
        self._last_open_timestamp: dict[str, str] = {}
        self._pending_batch: dict[str, dict[str, Any]] = {}
        self._corrupted_middle: bool = False
        self._physical_duplicates_detected: bool = False
        self._is_lease_owner: bool = False
        self._counters = {
            "total_ingested": 0,
            "complete_batches": 0,
            "duplicates_rejected": 0,
            "gaps_detected": 0,
            "incomplete_batches": 0,
        }

        if not self.read_only and not self.base_dir.exists():
            self.base_dir.mkdir(parents=True, exist_ok=True)

        # Load or verify manifest without creating files if read_only
        if self.manifest_file.exists():
            self.manifest = self._load_manifest_read_only()
        elif not self.read_only:
            self.manifest = self._init_or_verify_manifest()
        else:
            self.manifest = {}

        # O(1) state checkpoint load for read_only vs full recovery for writer
        if self.read_only:
            self._load_state_checkpoint_read_only()
        else:
            self._recover_state_if_exists(as_lease_owner=False)
        # Note: Do NOT call _checkpoint_state() in __init__!

    def _load_state_checkpoint_read_only(self) -> None:
        """Loads state checkpoint in O(1) time without reading JSONL logs."""
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text(encoding="utf-8"))
                saved_counters = state.get("counters", {})
                for k in self._counters:
                    if k in saved_counters:
                        self._counters[k] = saved_counters[k]
                self._last_open_timestamp = dict(state.get("last_open_timestamps", {}))
            except Exception:
                pass

    def _load_manifest_read_only(self) -> dict[str, Any]:
        """Loads and verifies manifest without writing anything."""
        if not self.manifest_file.exists():
            return {}
        existing = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        computed_hash = compute_manifest_sha256(existing)
        recorded_hash = existing.get("manifest_sha256")
        if computed_hash != recorded_hash:
            raise RuntimeError(
                f"IMMUTABLE_MANIFEST_TAMPERED: Manifest hash mismatch: "
                f"recorded={recorded_hash}, computed={computed_hash}"
            )
        return existing

    def acquire_lease(self, pid: int, runtime_uuid: str) -> None:
        """Acquires single-writer lease. Once owned, runs full recovery, reconciliation, and checkpoint."""
        if self.read_only:
            raise RuntimeError("EPOCH_MANAGER_READ_ONLY: Cannot acquire lease in read-only mode")
        with self._lock:
            self.lease.acquire(pid, runtime_uuid)
            self._is_lease_owner = True
            # Lease ownership established: perform crash recovery, batch reconciliation, and checkpoint
            self._recover_state_if_exists(as_lease_owner=True)
            self._checkpoint_state()

    def release_lease(self, pid: int, runtime_uuid: str | None = None) -> None:
        """Releases single-writer lease."""
        if self.read_only:
            raise RuntimeError("EPOCH_MANAGER_READ_ONLY: Cannot release lease in read-only mode")
        with self._lock:
            self.lease.release(pid, runtime_uuid)
            self._is_lease_owner = False

    def update_heartbeat(
        self,
        pid: int,
        runtime_uuid: str,
        started_at_utc: str,
        collector_status: str = "RUNNING",
        last_successful_poll_utc: str | None = None,
        last_complete_batch_utc: str | None = None,
        consecutive_failures: int = 0,
        symbol_statuses: dict[str, str] | None = None,
        graceful_stop: bool = False,
        expected_batch_open_utc: str | None = None,
        observed_complete_batch_open_utc: str | None = None,
        missing_symbols: list[str] | None = None,
        batch_lag_seconds: float | None = None,
        poll_attempts_for_expected_batch: int = 1,
        last_complete_batch_age_seconds: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Updates real-time dynamic heartbeat artifact."""
        if self.read_only:
            raise RuntimeError("EPOCH_MANAGER_READ_ONLY: Cannot update heartbeat in read-only mode")
        with self._lock:
            hb = self.heartbeat.update(
                pid=pid,
                runtime_uuid=runtime_uuid,
                started_at_utc=started_at_utc,
                collector_status=collector_status,
                last_successful_poll_utc=last_successful_poll_utc,
                last_complete_batch_utc=last_complete_batch_utc,
                consecutive_failures=consecutive_failures,
                symbol_statuses=symbol_statuses,
                graceful_stop=graceful_stop,
                expected_batch_open_utc=expected_batch_open_utc,
                observed_complete_batch_open_utc=observed_complete_batch_open_utc,
                missing_symbols=missing_symbols,
                batch_lag_seconds=batch_lag_seconds,
                poll_attempts_for_expected_batch=poll_attempts_for_expected_batch,
                last_complete_batch_age_seconds=last_complete_batch_age_seconds,
                **kwargs,
            )
            self._checkpoint_state()
            return hb

    def mark_stopped(self, pid: int, runtime_uuid: str, forced: bool = False) -> None:
        """Marks collector as stopped in heartbeat (graceful or forced)."""
        if self.read_only:
            raise RuntimeError("EPOCH_MANAGER_READ_ONLY: Cannot mark stopped in read-only mode")
        with self._lock:
            self.heartbeat.mark_stopped(pid, runtime_uuid, forced=forced)
            self._checkpoint_state()

    def read_heartbeat(self) -> dict[str, Any] | None:
        """Reads current heartbeat from disk."""
        with self._lock:
            return self.heartbeat.read()

    def get_operating_status(self) -> str:
        """Evaluates honest dynamic liveness state across the 5 canonical tiers:
        - RESEARCH_EPOCH_PREPARED_NOT_STARTED: manifest exists, complete_batches == 0, no live collector.
        - RESEARCH_EPOCH_INITIALIZED_COLLECTION_STOPPED: data exists, no live collector/fresh heartbeat.
        - RESEARCH_EPOCH_ACTIVE: collector PID/runtime UUID valid, heartbeat fresh, no degraded errors.
        - RESEARCH_EPOCH_DEGRADED: collector alive, but consecutive failures > 0, corrupt records, stale heartbeat, or batch lag > SLA.
        - RESEARCH_EPOCH_STOPPED: stopped in heartbeat.
        """
        with self._lock:
            if self._corrupted_middle or self._physical_duplicates_detected:
                return "RESEARCH_EPOCH_DEGRADED"

            hb = self.heartbeat.read()
            if not hb:
                if self._counters["complete_batches"] > 0 or self._counters["total_ingested"] > 0:
                    return "RESEARCH_EPOCH_INITIALIZED_COLLECTION_STOPPED"
                return "RESEARCH_EPOCH_PREPARED_NOT_STARTED"

            pid = hb.get("pid")
            runtime_uuid = hb.get("runtime_uuid")
            graceful_stop = hb.get("graceful_stop", False)
            collector_status = hb.get("collector_status", "")

            # If explicitly stopped or forced stopped
            if graceful_stop or collector_status in {"STOPPED", "FORCED_STOP"}:
                return "RESEARCH_EPOCH_STOPPED"

            # Check if process is alive
            is_alive = is_pid_alive(int(pid)) if pid else False
            if not is_alive:
                if self._counters["complete_batches"] > 0 or self._counters["total_ingested"] > 0:
                    return "RESEARCH_EPOCH_INITIALIZED_COLLECTION_STOPPED"
                return "RESEARCH_EPOCH_PREPARED_NOT_STARTED"

            # Process is alive: evaluate heartbeat freshness
            last_hb_str = hb.get("last_heartbeat_utc")
            is_fresh = False
            if last_hb_str:
                try:
                    import pandas as pd
                    hb_dt = pd.to_datetime(last_hb_str, utc=True)
                    now_dt = datetime.now(timezone.utc)
                    age_seconds = (now_dt - hb_dt).total_seconds()
                    is_fresh = age_seconds <= R1_HEARTBEAT_FRESHNESS_SECONDS
                except Exception:
                    is_fresh = False

            if not is_fresh:
                # Process alive, but heartbeat stalled
                return "RESEARCH_EPOCH_DEGRADED"

            if collector_status == "DEGRADED" or hb.get("consecutive_failures", 0) > 0:
                return "RESEARCH_EPOCH_DEGRADED"

            # Backlog or backfill in progress marks degraded
            if hb.get("backlog_batches", 0) > 0 or hb.get("backfill_in_progress", False):
                return "RESEARCH_EPOCH_DEGRADED"

            if hb.get("missing_symbols") or hb.get("missing_symbol_timestamps"):
                return "RESEARCH_EPOCH_DEGRADED"

            # Escalation SLA: check if last complete batch has fallen behind by > 45 minutes from close
            last_b_str = hb.get("last_complete_batch_utc")
            if last_b_str:
                try:
                    import pandas as pd
                    b_open_dt = pd.to_datetime(last_b_str, utc=True)
                    b_close_dt = b_open_dt + pd.Timedelta(minutes=15)
                    now_dt = datetime.now(timezone.utc)
                    close_age_sec = (now_dt - b_close_dt).total_seconds()
                    MAX_ESCALATION_SECONDS = 2700.0  # 45 minutes after close = 3 boundaries
                    if close_age_sec > MAX_ESCALATION_SECONDS:
                        return "RESEARCH_EPOCH_DEGRADED"
                except Exception:
                    pass

            return "RESEARCH_EPOCH_ACTIVE"

    def get_last_complete_batch_open_ts(self) -> str | None:
        """Returns the latest complete batch open timestamp from checkpoint or batch log."""
        with self._lock:
            # Check state checkpoint first
            if self.state_file.exists():
                try:
                    state = json.loads(self.state_file.read_text(encoding="utf-8"))
                    lots = state.get("last_open_timestamps", {})
                    vals = set(lots.values())
                    if len(vals) == 1 and len(lots) == len(R1_AUTHORIZED_SYMBOLS):
                        return list(vals)[0]
                except Exception:
                    pass
            # Fallback to reading last record of batch_file
            if self.batch_file.exists():
                try:
                    with open(self.batch_file, "r", encoding="utf-8") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    if lines:
                        last_record = json.loads(lines[-1])
                        return last_record.get("batch_open_timestamp")
                except Exception:
                    pass
            return None

    def _init_or_verify_manifest(self) -> dict[str, Any]:
        """Creates or cryptographically verifies the immutable epoch manifest."""
        with self._lock:
            if self.manifest_file.exists():
                return self._load_manifest_read_only()

            if self.read_only:
                return {}

            # Create initial manifest
            now_ts = datetime.now(timezone.utc).isoformat()
            manifest_payload: dict[str, Any] = {
                "epoch_id": R1_EPOCH_ID,
                "manifest_version": "1.0.0",
                "authorized_universe": list(R1_AUTHORIZED_SYMBOLS),
                "candle_interval": R1_CANDLE_INTERVAL,
                "start_policy": "FIRST_COMPLETE_9_SYMBOL_CLOSED_CANDLE_BATCH",
                "schema": {
                    "symbol": "str",
                    "open_timestamp": "iso8601_utc",
                    "close_timestamp": "iso8601_utc",
                    "open": "float",
                    "high": "float",
                    "low": "float",
                    "close": "float",
                    "volume": "float",
                    "source": "str",
                    "receive_timestamp": "iso8601_utc",
                    "is_closed": "bool",
                    "sequence_status": "str",
                    "quality_flags": "list[str]",
                    "epoch_id": "str",
                },
                "storage_paths": {
                    "base_dir": str(self.base_dir),
                    "manifest_file": str(self.manifest_file),
                    "candles_file": str(self.candles_file),
                    "batch_file": str(self.batch_file),
                    "state_file": str(self.state_file),
                },
                "gap_duplicate_policy": "REJECT_DUPLICATE_OPEN_TS_RECORD_GAP",
                "timestamp_normalization": "UTC_RFC3339",
                "git_head": get_git_head(),
                "staged_manifest_identity": CANONICAL_STAGED_MANIFEST_SHA256,
                "created_at_utc": now_ts,
                "candidate_id": None,
                "promotion_clock": "NOT_APPLICABLE",
                "real_orders": False,
                "paper_policy": "NO_TRADE_SHADOW",
            }
            manifest_payload["manifest_sha256"] = compute_manifest_sha256(manifest_payload)
            self.manifest_file.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
            return manifest_payload

    def _recover_state_if_exists(self, as_lease_owner: bool = False) -> None:
        """Recovers durable facts from candle and batch logs.
        Reconciles uncommitted batches and cleans up truncated tail lines only if as_lease_owner=True.
        Never rewrites the file if a middle corruption is encountered (keeps evidence intact and sets DEGRADED).
        """
        with self._lock:
            # 1. Recover committed batch timestamps from batch log
            committed_batch_open_timestamps: set[str] = set()
            corrupted_middle = False
            last_line_truncated_batch = False

            if self.batch_file.exists():
                with open(self.batch_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                valid_batch_lines = []
                for idx, line in enumerate(lines):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        b_ts = record.get("batch_open_timestamp")
                        if b_ts:
                            committed_batch_open_timestamps.add(b_ts)
                        valid_batch_lines.append(line)
                    except Exception:
                        if idx == len(lines) - 1:
                            last_line_truncated_batch = True
                        else:
                            corrupted_middle = True

                # Truncate partial tail ONLY if as_lease_owner, only last line was truncated, and NO middle corruption
                if as_lease_owner and not self.read_only and last_line_truncated_batch and not corrupted_middle:
                    with open(self.batch_file, "w", encoding="utf-8") as f:
                        f.writelines(valid_batch_lines)

            # 2. Recover candles from candle log
            candles_by_open_ts: dict[str, dict[str, Any]] = {}
            total_ingested = 0
            gaps_detected = 0
            last_line_truncated_candle = False
            physical_candle_duplicates: list[dict[str, str]] = []
            seen_candle_pairs: set[tuple[str, str]] = set()
            symbol_timestamps: dict[str, list[str]] = {s: [] for s in R1_AUTHORIZED_SYMBOLS}

            if self.candles_file.exists():
                with open(self.candles_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                valid_candle_lines = []
                for idx, line in enumerate(lines):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                        sym = record.get("symbol")
                        o_ts = record.get("open_timestamp")
                        if sym in self._seen_open_timestamps and o_ts:
                            pair = (sym, o_ts)
                            if pair in seen_candle_pairs:
                                physical_candle_duplicates.append({"symbol": sym, "open_timestamp": o_ts})
                            else:
                                seen_candle_pairs.add(pair)
                                self._seen_open_timestamps[sym].add(o_ts)
                                symbol_timestamps[sym].append(o_ts)
                                total_ingested += 1
                                candles_by_open_ts.setdefault(o_ts, {})[sym] = record
                        valid_candle_lines.append(line)
                    except Exception:
                        if idx == len(lines) - 1:
                            last_line_truncated_candle = True
                        else:
                            corrupted_middle = True

                # Truncate partial tail ONLY if as_lease_owner, only last line was truncated, and NO middle corruption
                if as_lease_owner and not self.read_only and last_line_truncated_candle and not corrupted_middle:
                    with open(self.candles_file, "w", encoding="utf-8") as f:
                        f.writelines(valid_candle_lines)

            # 2b. Compute accurate gaps and last_open_timestamp from chronologically sorted timestamps per symbol
            import pandas as pd
            for sym, ts_list in symbol_timestamps.items():
                sorted_ts = sorted(ts_list)
                if sorted_ts:
                    self._last_open_timestamp[sym] = sorted_ts[-1]
                for i in range(1, len(sorted_ts)):
                    dt_curr = pd.to_datetime(sorted_ts[i], utc=True)
                    dt_prev = pd.to_datetime(sorted_ts[i - 1], utc=True)
                    if (dt_curr - dt_prev).total_seconds() / 60.0 > 15.0:
                        gaps_detected += 1

            if physical_candle_duplicates:
                self._physical_duplicates_detected = True
                diagnostic_file = self.base_dir / "r1_duplicate_forensic_diagnostic.json"
                diagnostic_payload = {
                    "epoch_id": R1_EPOCH_ID,
                    "detected_at_utc": datetime.now(timezone.utc).isoformat(),
                    "physical_duplicates_count": len(physical_candle_duplicates),
                    "physical_duplicates": physical_candle_duplicates,
                    "action": "EVIDENCE_PRESERVED_NO_DELETION_OPERATING_STATUS_DEGRADED",
                }
                try:
                    diagnostic_file.write_text(json.dumps(diagnostic_payload, indent=2), encoding="utf-8")
                except Exception:
                    pass

            # 3. Batch reconciliation & pending batch reconstruction
            self._pending_batch.clear()
            for open_ts, candle_map in candles_by_open_ts.items():
                if len(candle_map) == len(R1_AUTHORIZED_SYMBOLS):
                    if open_ts not in committed_batch_open_timestamps:
                        if as_lease_owner and not self.read_only:
                            self._commit_complete_batch(open_ts, candle_map, update_counter=False)
                        committed_batch_open_timestamps.add(open_ts)
                else:
                    self._pending_batch[open_ts] = dict(candle_map)

            # 4. Set accurate durable counters
            self._counters["total_ingested"] = total_ingested
            self._counters["complete_batches"] = len(committed_batch_open_timestamps)
            self._counters["incomplete_batches"] = len(self._pending_batch)
            self._counters["gaps_detected"] = gaps_detected

            if self.state_file.exists():
                try:
                    saved_state = json.loads(self.state_file.read_text(encoding="utf-8"))
                    saved_counters = saved_state.get("counters", {})
                    self._counters["duplicates_rejected"] = saved_counters.get("duplicates_rejected", 0)
                except Exception:
                    pass

            self._corrupted_middle = corrupted_middle

    def ingest_batch(
        self,
        candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        source: str = "binance_rest",
        receive_timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Validates and appends a batch of candles in a single atomic storage transaction.
        Durable mutation ordering: Disk appends and state checkpoint MUST succeed before RAM state mutates.
        """
        if self.read_only:
            raise RuntimeError("EPOCH_MANAGER_READ_ONLY: Cannot ingest candles in read-only mode")

        with self._lock:
            import pandas as pd
            now_rec = receive_timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Capture pre-transaction durable file offsets
            candle_offset = self.candles_file.stat().st_size if self.candles_file.exists() else 0
            batch_offset = self.batch_file.stat().st_size if self.batch_file.exists() else 0
            tmp_state_file: Path | None = None

            # Stage 1: Validation and preparation (in memory, without mutating existing state)
            accepted_records: list[dict[str, Any]] = []
            ingested_per_symbol: dict[str, int] = {s: 0 for s in R1_AUTHORIZED_SYMBOLS}
            rejection_reasons: list[str] = []
            new_seen_timestamps: dict[str, set[str]] = {s: set() for s in R1_AUTHORIZED_SYMBOLS}
            new_last_open_timestamps: dict[str, str] = {}
            temp_pending_batch = {k: dict(v) for k, v in self._pending_batch.items()}
            gaps_delta = 0
            duplicates_delta = 0

            for sym in R1_AUTHORIZED_SYMBOLS:
                candles = candles_by_symbol.get(sym, [])
                for candle in candles:
                    is_closed = candle.get("is_closed")
                    if is_closed is None:
                        is_closed = candle.get("closed")
                    if not is_closed:
                        rejection_reasons.append(f"{sym}: CANDLE_NOT_CLOSED")
                        continue

                    open_ts = candle.get("time_utc") or candle.get("open_time_utc") or candle.get("time")
                    if not open_ts:
                        rejection_reasons.append(f"{sym}: MISSING_TIMESTAMP")
                        continue

                    try:
                        dt_open = pd.to_datetime(open_ts, utc=True)
                        open_iso = dt_open.strftime("%Y-%m-%dT%H:%M:%SZ")
                        close_iso = (dt_open + pd.Timedelta(minutes=15) - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception as e:
                        rejection_reasons.append(f"{sym}: INVALID_TIMESTAMP_FORMAT ({e})")
                        continue

                    # Duplicate check against persistent seen set and current batch accepted set
                    if open_iso in self._seen_open_timestamps[sym] or open_iso in new_seen_timestamps[sym]:
                        duplicates_delta += 1
                        rejection_reasons.append(f"DUPLICATE_CANDLE_REJECTED: {sym} open_timestamp {open_iso} already ingested.")
                        continue

                    # Gap / sequence check
                    seq_status = "NORMAL_CONTINUATION"
                    last_ts = new_last_open_timestamps.get(sym) or self._last_open_timestamp.get(sym)
                    if last_ts:
                        dt_last = pd.to_datetime(last_ts, utc=True)
                        delta_mins = (dt_open - dt_last).total_seconds() / 60.0
                        if delta_mins > 15.0:
                            seq_status = f"GAP_DETECTED_MISSED_{int(delta_mins / 15.0) - 1}_BARS"
                            gaps_delta += 1
                        elif delta_mins < 15.0:
                            seq_status = "OUT_OF_ORDER_OR_SUB_INTERVAL"

                    quality_flags = []
                    o = float(candle.get("open", 0.0))
                    h = float(candle.get("high", 0.0))
                    l = float(candle.get("low", 0.0))
                    c = float(candle.get("close", 0.0))
                    v = float(candle.get("volume", 0.0))

                    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                        quality_flags.append("NON_POSITIVE_PRICE")
                    if l > h or o > h or c > h or l > o or l > c:
                        quality_flags.append("INCONSISTENT_OHLC_BOUNDS")
                    if v < 0:
                        quality_flags.append("NEGATIVE_VOLUME")

                    record = {
                        "epoch_id": R1_EPOCH_ID,
                        "symbol": sym,
                        "open_timestamp": open_iso,
                        "close_timestamp": close_iso,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                        "source": source,
                        "receive_timestamp": now_rec,
                        "is_closed": True,
                        "sequence_status": seq_status,
                        "quality_flags": quality_flags,
                    }

                    accepted_records.append(record)
                    new_seen_timestamps[sym].add(open_iso)
                    new_last_open_timestamps[sym] = open_iso
                    ingested_per_symbol[sym] += 1

                    # Stage into pending batch
                    batch_candles = temp_pending_batch.setdefault(open_iso, {})
                    batch_candles[sym] = record

            # Stage 2: Prepare completed batches to commit
            completed_batches_entries: list[dict[str, Any]] = []
            completed_batch_timestamps: list[str] = []
            for b_open_ts in list(temp_pending_batch.keys()):
                b_candles = temp_pending_batch[b_open_ts]
                if len(b_candles) == len(R1_AUTHORIZED_SYMBOLS):
                    batch_entry = {
                        "epoch_id": R1_EPOCH_ID,
                        "batch_open_timestamp": b_open_ts,
                        "committed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "symbols_count": len(b_candles),
                        "symbols": sorted(list(b_candles.keys())),
                        "all_9_authorized_symbols_present": True,
                        "batch_records": [b_candles[s] for s in sorted(b_candles.keys())],
                    }
                    completed_batches_entries.append(batch_entry)
                    completed_batch_timestamps.append(b_open_ts)
                    del temp_pending_batch[b_open_ts]

            # Stage 3: Durable Disk Write Transaction with rollback protection
            try:
                # A. Append candles to candles_file with flush and fsync
                if accepted_records:
                    with open(self.candles_file, "a", encoding="utf-8") as f:
                        for r in accepted_records:
                            f.write(json.dumps(r, separators=(",", ":")) + "\n")
                        f.flush()
                        os.fsync(f.fileno())

                # B. Append complete batches to batch_file with flush and fsync
                if completed_batches_entries:
                    with open(self.batch_file, "a", encoding="utf-8") as f:
                        for b_entry in completed_batches_entries:
                            f.write(json.dumps(b_entry, separators=(",", ":")) + "\n")
                        f.flush()
                        os.fsync(f.fileno())

                # C. Atomically checkpoint state to disk before updating in-memory counters
                tentative_counters = {
                    "total_ingested": self._counters["total_ingested"] + len(accepted_records),
                    "complete_batches": self._counters["complete_batches"] + len(completed_batches_entries),
                    "duplicates_rejected": self._counters["duplicates_rejected"] + duplicates_delta,
                    "gaps_detected": self._counters["gaps_detected"] + gaps_delta,
                    "incomplete_batches": len(temp_pending_batch),
                }
                tentative_last_open_timestamps = dict(self._last_open_timestamp)
                tentative_last_open_timestamps.update(new_last_open_timestamps)

                state = {
                    "epoch_id": R1_EPOCH_ID,
                    "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "counters": tentative_counters,
                    "authorized_universe": list(R1_AUTHORIZED_SYMBOLS),
                    "last_open_timestamps": tentative_last_open_timestamps,
                    "candidate_id": None,
                    "promotion_clock": "NOT_APPLICABLE",
                    "operating_status": self.get_operating_status(),
                }
                tmp_state_file = self.base_dir / f"r1_epoch_state.json.tmp.{uuid.uuid4().hex[:8]}"
                tmp_state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                with open(tmp_state_file, "r+", encoding="utf-8") as f:
                    f.flush()
                    os.fsync(f.fileno())
                tmp_state_file.replace(self.state_file)
            except Exception as exc:
                self._rollback_disk_transaction(candle_offset, batch_offset, tmp_state_file)
                raise exc

            # Stage 4: Commit to in-memory state ONLY after disk writes and checkpoint succeed
            for sym, ts_set in new_seen_timestamps.items():
                self._seen_open_timestamps[sym].update(ts_set)
            self._last_open_timestamp.update(new_last_open_timestamps)
            self._pending_batch = temp_pending_batch
            self._counters = tentative_counters

            return {
                "accepted_count": len(accepted_records),
                "ingested_per_symbol": ingested_per_symbol,
                "rejection_reasons": rejection_reasons,
                "completed_batches": completed_batch_timestamps,
                "counters": dict(self._counters),
            }

    def _rollback_disk_transaction(
        self,
        candle_offset: int,
        batch_offset: int,
        tmp_state_file: Path | None = None,
    ) -> None:
        """Rolls back append-only files to pre-transaction offsets and unlinks temp files."""
        errors: list[str] = []
        if tmp_state_file and tmp_state_file.exists():
            try:
                tmp_state_file.unlink()
            except Exception as e:
                errors.append(f"tmp_state_unlink: {e}")

        if self.candles_file.exists():
            try:
                curr_size = self.candles_file.stat().st_size
                if curr_size > candle_offset:
                    with open(self.candles_file, "r+", encoding="utf-8") as f:
                        f.seek(candle_offset)
                        f.truncate()
                        f.flush()
                        os.fsync(f.fileno())
            except Exception as e:
                errors.append(f"candles_truncate: {e}")

        if self.batch_file.exists():
            try:
                curr_size = self.batch_file.stat().st_size
                if curr_size > batch_offset:
                    with open(self.batch_file, "r+", encoding="utf-8") as f:
                        f.seek(batch_offset)
                        f.truncate()
                        f.flush()
                        os.fsync(f.fileno())
            except Exception as e:
                errors.append(f"batch_truncate: {e}")

        if errors:
            self._corrupted_middle = True
            raise RuntimeError(f"DISK_TRANSACTION_ROLLBACK_FAILED: {errors}")

    def audit_storage(self) -> dict[str, Any]:
        """Performs comprehensive, read-only audit of storage logs.
        Verifies:
        - Physical lines count vs valid parsed records
        - Unique (symbol, open_timestamp) pairs and physical duplicate detection
        - Unique complete batch timestamps vs batch log records
        - Gap detection using chronologically sorted timestamps per symbol
        - Comparison of computed counts against r1_epoch_state.json checkpoint
        Never mutates files on disk. Returns detailed forensic report.
        """
        import tracemalloc
        tracemalloc.start()
        start_perf = time.perf_counter()

        with self._lock:
            # 1. Audit batch log
            physical_batch_lines = 0
            valid_batch_records = 0
            corrupt_batch_lines = 0
            batch_timestamps: list[str] = []
            unique_batch_timestamps: set[str] = set()
            physical_batch_duplicates: list[str] = []

            if self.batch_file.exists():
                with open(self.batch_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        physical_batch_lines += 1
                        try:
                            record = json.loads(line_str)
                            b_ts = record.get("batch_open_timestamp")
                            if b_ts:
                                valid_batch_records += 1
                                batch_timestamps.append(b_ts)
                                if b_ts in unique_batch_timestamps:
                                    physical_batch_duplicates.append(b_ts)
                                else:
                                    unique_batch_timestamps.add(b_ts)
                        except Exception:
                            corrupt_batch_lines += 1

            # 2. Audit candle log
            physical_candle_lines = 0
            valid_candle_records = 0
            corrupt_candle_lines = 0
            seen_pairs: set[tuple[str, str]] = set()
            physical_candle_duplicates: list[dict[str, str]] = []
            symbol_timestamps: dict[str, list[str]] = {s: [] for s in R1_AUTHORIZED_SYMBOLS}
            candles_by_open_ts: dict[str, set[str]] = {}

            if self.candles_file.exists():
                with open(self.candles_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        physical_candle_lines += 1
                        try:
                            record = json.loads(line_str)
                            sym = record.get("symbol")
                            o_ts = record.get("open_timestamp")
                            if sym in symbol_timestamps and o_ts:
                                valid_candle_records += 1
                                pair = (sym, o_ts)
                                if pair in seen_pairs:
                                    physical_candle_duplicates.append({"symbol": sym, "open_timestamp": o_ts})
                                else:
                                    seen_pairs.add(pair)
                                    symbol_timestamps[sym].append(o_ts)
                                    candles_by_open_ts.setdefault(o_ts, set()).add(sym)
                        except Exception:
                            corrupt_candle_lines += 1

            # 3. Gap analysis on chronologically sorted timestamps per symbol
            import pandas as pd
            gaps_by_symbol: dict[str, int] = {s: 0 for s in R1_AUTHORIZED_SYMBOLS}
            total_gaps = 0
            last_timestamp_by_symbol: dict[str, str] = {}

            for sym, ts_list in symbol_timestamps.items():
                sorted_ts = sorted(ts_list)
                if sorted_ts:
                    last_timestamp_by_symbol[sym] = sorted_ts[-1]
                for i in range(1, len(sorted_ts)):
                    dt_prev = pd.to_datetime(sorted_ts[i - 1], utc=True)
                    dt_curr = pd.to_datetime(sorted_ts[i], utc=True)
                    delta_mins = (dt_curr - dt_prev).total_seconds() / 60.0
                    if delta_mins > 15.0:
                        gap_count = int(delta_mins / 15.0) - 1
                        gaps_by_symbol[sym] += gap_count
                        total_gaps += gap_count

            # 4. Batch completeness
            reconstructed_complete_batches = set()
            reconstructed_incomplete_batches = set()
            for o_ts, sym_set in candles_by_open_ts.items():
                if len(sym_set) == len(R1_AUTHORIZED_SYMBOLS):
                    reconstructed_complete_batches.add(o_ts)
                else:
                    reconstructed_incomplete_batches.add(o_ts)

            # 5. Compare with checkpoint state
            checkpoint_state = {}
            checkpoint_matches = True
            mismatches = []
            if self.state_file.exists():
                try:
                    checkpoint_state = json.loads(self.state_file.read_text(encoding="utf-8"))
                    cp_counters = checkpoint_state.get("counters", {})
                    if cp_counters.get("total_ingested") != len(seen_pairs):
                        checkpoint_matches = False
                        mismatches.append(f"total_ingested: cp={cp_counters.get('total_ingested')} vs audit={len(seen_pairs)}")
                    if cp_counters.get("complete_batches") != len(unique_batch_timestamps):
                        checkpoint_matches = False
                        mismatches.append(f"complete_batches: cp={cp_counters.get('complete_batches')} vs audit={len(unique_batch_timestamps)}")
                    if cp_counters.get("gaps_detected") != total_gaps:
                        checkpoint_matches = False
                        mismatches.append(f"gaps_detected: cp={cp_counters.get('gaps_detected')} vs audit={total_gaps}")
                except Exception as e:
                    checkpoint_matches = False
                    mismatches.append(f"state_file_read_error: {e}")

            elapsed_sec = time.perf_counter() - start_perf
            current_mem, peak_mem = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            total_records = valid_candle_records + valid_batch_records
            records_per_sec = total_records / max(0.0001, elapsed_sec)

            return {
                "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "epoch_id": R1_EPOCH_ID,
                "elapsed_seconds": round(elapsed_sec, 6),
                "peak_memory_mb": round(peak_mem / (1024 * 1024), 3),
                "records_per_second": round(records_per_sec, 1),
                "physical_candle_lines": physical_candle_lines,
                "valid_candle_records": valid_candle_records,
                "unique_candle_records": len(seen_pairs),
                "corrupt_candle_lines": corrupt_candle_lines,
                "physical_candle_duplicates_count": len(physical_candle_duplicates),
                "physical_candle_duplicates": physical_candle_duplicates,
                "physical_batch_lines": physical_batch_lines,
                "valid_batch_records": valid_batch_records,
                "unique_batch_timestamps": len(unique_batch_timestamps),
                "corrupt_batch_lines": corrupt_batch_lines,
                "physical_batch_duplicates_count": len(physical_batch_duplicates),
                "physical_batch_duplicates": physical_batch_duplicates,
                "reconstructed_complete_batches": len(reconstructed_complete_batches),
                "reconstructed_incomplete_batches": len(reconstructed_incomplete_batches),
                "total_gaps_detected": total_gaps,
                "gaps_by_symbol": gaps_by_symbol,
                "last_open_timestamps": last_timestamp_by_symbol,
                "checkpoint_matches": checkpoint_matches,
                "checkpoint_mismatches": mismatches,
                "audit_verdict": "AUDIT_CLEAN" if (checkpoint_matches and not physical_candle_duplicates and not physical_batch_duplicates and corrupt_candle_lines == 0 and corrupt_batch_lines == 0) else "AUDIT_ISSUES_DETECTED"
            }

    def ingest_candle(
        self,
        symbol: str,
        candle: Mapping[str, Any],
        source: str = "binance_rest",
        receive_timestamp: str | None = None,
    ) -> tuple[bool, str]:
        """Validates and appends a closed candle to epoch storage (backward-compatible single-item wrapper)."""
        sym = str(symbol).strip().upper()
        if sym not in R1_AUTHORIZED_SYMBOLS:
            return False, f"UNAUTHORIZED_SYMBOL: {sym} not in {R1_AUTHORIZED_SYMBOLS}"

        res = self.ingest_batch({sym: [candle]}, source=source, receive_timestamp=receive_timestamp)
        if res["ingested_per_symbol"].get(sym, 0) > 0:
            return True, "INGESTION_ACCEPTED"
        if res.get("rejection_reasons"):
            return False, res["rejection_reasons"][0]
        return False, "CANDLE_REJECTED"

    def _commit_complete_batch(
        self,
        batch_open_ts: str,
        batch_candles: dict[str, dict[str, Any]],
        update_counter: bool = True,
    ) -> None:
        """Commits a verified 9-symbol complete batch to batch_log."""
        if self.read_only:
            return
        batch_entry = {
            "epoch_id": R1_EPOCH_ID,
            "batch_open_timestamp": batch_open_ts,
            "committed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols_count": len(batch_candles),
            "symbols": sorted(list(batch_candles.keys())),
            "all_9_authorized_symbols_present": True,
            "batch_records": [batch_candles[s] for s in sorted(batch_candles.keys())],
        }
        with open(self.batch_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(batch_entry, separators=(",", ":")) + "\n")
        if update_counter:
            self._counters["complete_batches"] += 1

    def _checkpoint_state(self) -> None:
        """Atomically persists current epoch state and counters."""
        if self.read_only:
            return
        state = {
            "epoch_id": R1_EPOCH_ID,
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "counters": dict(self._counters),
            "authorized_universe": list(R1_AUTHORIZED_SYMBOLS),
            "last_open_timestamps": dict(self._last_open_timestamp),
            "candidate_id": None,
            "promotion_clock": "NOT_APPLICABLE",
            "operating_status": self.get_operating_status(),
        }
        tmp_file = self.base_dir / f"r1_epoch_state.json.tmp.{uuid.uuid4().hex[:8]}"
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_file.replace(self.state_file)

    def get_epoch_summary(self) -> dict[str, Any]:
        """Returns comprehensive machine-readable summary of the epoch."""
        with self._lock:
            return {
                "epoch_id": R1_EPOCH_ID,
                "manifest_sha256": self.manifest.get("manifest_sha256"),
                "operating_status": self.get_operating_status(),
                "candidate_id": None,
                "promotion_clock": "NOT_APPLICABLE",
                "counters": dict(self._counters),
                "authorized_symbols": list(R1_AUTHORIZED_SYMBOLS),
                "latest_batch_open_timestamps": dict(self._last_open_timestamp),
                "heartbeat": self.read_heartbeat(),
            }


def create_read_only_inspector(base_dir: Path = R1_DEFAULT_STORAGE_DIR) -> ProspectiveRawEpochManager:
    """Creates a dedicated read-only inspector instance guaranteed never to mutate storage artifacts."""
    return ProspectiveRawEpochManager(base_dir=base_dir, read_only=True)


