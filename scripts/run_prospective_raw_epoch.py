"""scripts/run_prospective_raw_epoch.py

Prospective Raw Research Epoch R1 Runner
========================================
Collects genuine prospective 15m closed candles across the 9 authorized symbols:
BNB, BTC, DOGE, ETH, IOTA, NEAR, SOL, TRX, ZEC.

Epistemic & Governance Constraints:
- Epoch ID: PROSPECTIVE_RAW_RESEARCH_R1_20261104
- candidate_id: strictly None
- promotion_clock: NOT_APPLICABLE
- real_orders: False
- paper_policy: NO_TRADE_SHADOW
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.collectors.prospective_raw_epoch import (
    ProspectiveRawEpochManager,
    R1_AUTHORIZED_SYMBOLS,
    R1_DEFAULT_STORAGE_DIR,
    R1_EPOCH_ID,
    create_read_only_inspector,
    is_pid_alive,
)
from btc_scraper.exchanges.binance import create_robust_client_session, fetch_ohlcv


def compute_expected_batch_open_utc(now_dt: datetime | None = None) -> str:
    """Computes expected 15m closed candle open timestamp UTC for the most recently completed boundary."""
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    minute = (now_dt.minute // 15) * 15
    boundary_dt = now_dt.replace(minute=minute, second=0, microsecond=0)
    expected_open_dt = boundary_dt - timedelta(minutes=15)
    return expected_open_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def determine_missing_batch_open_timestamps(
    epoch_mgr: ProspectiveRawEpochManager,
    now_dt: datetime | None = None,
) -> list[str]:
    """Determines chronological sequence of missing 15m closed batch open timestamps up to latest safely closed boundary."""
    import pandas as pd
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    latest_safely_closed_open = compute_expected_batch_open_utc(now_dt)
    target_dt = pd.to_datetime(latest_safely_closed_open, utc=True)

    last_complete_open = epoch_mgr.get_last_complete_batch_open_ts()
    if not last_complete_open:
        return [latest_safely_closed_open]

    last_dt = pd.to_datetime(last_complete_open, utc=True)
    if last_dt >= target_dt:
        return []

    missing = []
    curr_dt = last_dt + pd.Timedelta(minutes=15)
    while curr_dt <= target_dt:
        missing.append(curr_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
        curr_dt += pd.Timedelta(minutes=15)

    return missing


def compute_seconds_to_next_boundary(grace_seconds: float = 5.0) -> float:
    """Computes float seconds until next 15-minute candle boundary (:00, :15, :30, :45) + grace."""
    now = datetime.now(timezone.utc)
    current_minute = now.minute
    current_second = now.second + now.microsecond / 1_000_000.0

    next_boundary_minute = ((current_minute // 15) + 1) * 15
    minutes_to_wait = next_boundary_minute - current_minute
    seconds_to_wait = (minutes_to_wait * 60.0) - current_second + grace_seconds
    if seconds_to_wait <= 0:
        seconds_to_wait += 15.0 * 60.0
    return seconds_to_wait


async def fetch_symbol_with_retry(
    symbol: str,
    session: Any,
    limit: int = 2,
    max_retries: int = 2,
    expected_open_utc: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Fetches closed candles for a single symbol with bounded retry and backoff under a semaphore.
    If expected_open_utc is provided, validates that the returned closed candle matches that timestamp.
    """
    sem = semaphore or asyncio.Semaphore(5)
    async with sem:
        for attempt in range(max_retries + 1):
            try:
                candles = await fetch_ohlcv(symbol, session, limit=limit)
                closed_candles = [c for c in candles if c.get("is_closed") or c.get("closed")]
                if expected_open_utc:
                    matching = [
                        c for c in closed_candles
                        if (c.get("time_utc") or c.get("open_time_utc") or c.get("time")) == expected_open_utc
                    ]
                    if matching:
                        return symbol, matching, None
                    if attempt == max_retries:
                        return symbol, [], f"MISSING_EXPECTED_CANDLE_{expected_open_utc}"
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue

                # Fallback: take latest closed candle
                return symbol, closed_candles[-1:] if closed_candles else [], None
            except Exception as e:
                if attempt == max_retries:
                    return symbol, [], str(e)
                await asyncio.sleep(0.5 * (2 ** attempt))
    return symbol, [], "UNKNOWN_ERROR"


async def fetch_and_ingest_latest_batch(
    epoch_mgr: ProspectiveRawEpochManager,
    expected_batch_open_utc: str | None = None,
    limit: int = 2,
    max_concurrency: int = 5,
) -> dict[str, Any]:
    """Concurrently fetches closed 15m candles for all 9 symbols and ingests as a single batch transaction.
    Enforces data-freshness SLA by validating expected boundary candles and retrying missing symbols only.
    """
    sem = asyncio.Semaphore(max_concurrency)
    poll_attempts = 1

    async with create_robust_client_session() as session:
        # Initial concurrent pass across all authorized symbols
        tasks = [
            fetch_symbol_with_retry(
                sym,
                session,
                limit=limit,
                expected_open_utc=expected_batch_open_utc,
                semaphore=sem,
            )
            for sym in R1_AUTHORIZED_SYMBOLS
        ]
        results = await asyncio.gather(*tasks)

        candles_by_symbol: dict[str, list[dict[str, Any]]] = {sym: [] for sym in R1_AUTHORIZED_SYMBOLS}
        symbol_statuses: dict[str, str] = {}
        missing_symbols: list[str] = []
        errors: list[str] = []

        for sym, closed_candles, err in results:
            if err or not closed_candles:
                err_msg = err or "EMPTY_CANDLE_SET"
                errors.append(f"{sym}: {err_msg}")
                symbol_statuses[sym] = f"ERROR: {err_msg}"
                missing_symbols.append(sym)
            else:
                candles_by_symbol[sym] = closed_candles
                symbol_statuses[sym] = "OK"

        # Bounded retry ONLY for missing symbols
        if missing_symbols:
            for retry_round in range(2):
                poll_attempts += 1
                await asyncio.sleep(1.0 * (retry_round + 1))
                retry_tasks = [
                    fetch_symbol_with_retry(
                        sym,
                        session,
                        limit=max(limit, 3),
                        expected_open_utc=expected_batch_open_utc,
                        semaphore=sem,
                    )
                    for sym in missing_symbols
                ]
                retry_results = await asyncio.gather(*retry_tasks)
                still_missing: list[str] = []
                for sym, closed_candles, err in retry_results:
                    if not err and closed_candles:
                        candles_by_symbol[sym] = closed_candles
                        symbol_statuses[sym] = "OK"
                    else:
                        still_missing.append(sym)
                missing_symbols = still_missing
                if not missing_symbols:
                    break

    # Ingest entire batch in a single atomic storage transaction
    batch_res = epoch_mgr.ingest_batch(candles_by_symbol, source="binance_rest")
    now_dt = datetime.now(timezone.utc)

    # Compute batch lag seconds
    batch_lag_seconds: float | None = None
    expected_open_utc = expected_batch_open_utc
    expected_close_utc: str | None = None
    close_to_ingest_lag_seconds: float | None = None
    last_complete_age_from_close_seconds: float | None = None

    if expected_batch_open_utc:
        try:
            import pandas as pd
            exp_open_dt = pd.to_datetime(expected_batch_open_utc, utc=True)
            exp_close_dt = exp_open_dt + pd.Timedelta(minutes=15)
            expected_close_utc = (exp_close_dt - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            batch_lag_seconds = max(0.0, (now_dt - exp_open_dt).total_seconds() - 900.0)
            close_to_ingest_lag_seconds = max(0.0, (now_dt - exp_close_dt).total_seconds())
        except Exception:
            pass

    summary = epoch_mgr.get_epoch_summary()
    latest_btc_open = summary["latest_batch_open_timestamps"].get("BTC")
    last_complete_age_seconds: float | None = None
    if latest_btc_open:
        try:
            import pandas as pd
            b_open_dt = pd.to_datetime(latest_btc_open, utc=True)
            b_close_dt = b_open_dt + pd.Timedelta(minutes=15)
            last_complete_age_seconds = max(0.0, (now_dt - b_open_dt).total_seconds())
            last_complete_age_from_close_seconds = max(0.0, (now_dt - b_close_dt).total_seconds())
        except Exception:
            pass

    return {
        "timestamp_utc": now_dt.isoformat(),
        "expected_batch_open_utc": expected_batch_open_utc,
        "observed_complete_batch_open_utc": latest_btc_open,
        "missing_symbols": missing_symbols,
        "batch_lag_seconds": batch_lag_seconds,
        "poll_attempts": poll_attempts,
        "last_complete_batch_age_seconds": last_complete_age_seconds,
        "expected_open_utc": expected_open_utc,
        "expected_close_utc": expected_close_utc,
        "close_to_ingest_lag_seconds": close_to_ingest_lag_seconds,
        "last_complete_age_from_close_seconds": last_complete_age_from_close_seconds,
        "ingested_per_symbol": batch_res["ingested_per_symbol"],
        "symbol_statuses": symbol_statuses,
        "errors": errors,
        "epoch_summary": summary,
        "batch_res": batch_res,
    }


async def poll_and_ingest_cycle(
    epoch_mgr: ProspectiveRawEpochManager,
    pid: int,
    runtime_uuid: str,
    started_at_utc: str,
    max_catchup_batches: int = 4,
) -> tuple[dict[str, Any], int, bool]:
    """Polls any missing boundaries up to the latest safely closed boundary in chronological order.
    Returns: (last_batch_result, remaining_backlog_count, any_missing_symbols).
    """
    now_dt = datetime.now(timezone.utc)
    missing_timestamps = determine_missing_batch_open_timestamps(epoch_mgr, now_dt)
    latest_safely_closed_open = compute_expected_batch_open_utc(now_dt)

    if not missing_timestamps:
        missing_timestamps = [latest_safely_closed_open]

    batch_slice = missing_timestamps[:max_catchup_batches]
    last_res: dict[str, Any] = {}
    any_missing_symbols = False

    for target_open in batch_slice:
        res = await fetch_and_ingest_latest_batch(
            epoch_mgr,
            expected_batch_open_utc=target_open,
            limit=min(50, len(missing_timestamps) + 2),
        )
        last_res = res
        if res.get("missing_symbols"):
            any_missing_symbols = True

    # Check remaining backlog after slice ingestion
    remaining = determine_missing_batch_open_timestamps(epoch_mgr, datetime.now(timezone.utc))
    backlog_count = len(remaining)
    backfill_active = backlog_count > 0

    last_complete_open = epoch_mgr.get_last_complete_batch_open_ts()
    collector_status = "DEGRADED" if (any_missing_symbols or backfill_active) else "RUNNING"

    epoch_mgr.update_heartbeat(
        pid=pid,
        runtime_uuid=runtime_uuid,
        started_at_utc=started_at_utc,
        collector_status=collector_status,
        last_successful_poll_utc=datetime.now(timezone.utc).isoformat() if not any_missing_symbols else None,
        last_complete_batch_utc=last_complete_open,
        consecutive_failures=1 if any_missing_symbols else 0,
        symbol_statuses=last_res.get("symbol_statuses"),
        graceful_stop=False,
        expected_batch_open_utc=last_res.get("expected_batch_open_utc"),
        observed_complete_batch_open_utc=last_complete_open,
        missing_symbols=last_res.get("missing_symbols", []),
        batch_lag_seconds=last_res.get("batch_lag_seconds"),
        poll_attempts_for_expected_batch=last_res.get("poll_attempts", 1),
        last_complete_batch_age_seconds=last_res.get("last_complete_batch_age_seconds"),
        expected_open_utc=last_res.get("expected_open_utc"),
        expected_close_utc=last_res.get("expected_close_utc"),
        close_to_ingest_lag_seconds=last_res.get("close_to_ingest_lag_seconds"),
        last_complete_age_from_close_seconds=last_res.get("last_complete_age_from_close_seconds"),
        backlog_batches=backlog_count,
        backfill_in_progress=backfill_active,
        latest_safely_closed_open_utc=latest_safely_closed_open,
        last_complete_open_utc=last_complete_open,
        oldest_missing_open_utc=remaining[0] if remaining else None,
    )

    return last_res, backlog_count, any_missing_symbols


async def run_collector_daemon(
    epoch_mgr: ProspectiveRawEpochManager,
    poll_interval_seconds: float | None = None,
    max_cycles: int | None = None,
    grace_seconds: float = 5.0,
) -> None:
    """Runs continuous background polling daemon for closed candles with single-writer lease and heartbeat."""
    pid = os.getpid()
    runtime_uuid = str(uuid.uuid4())
    started_at_utc = datetime.now(timezone.utc).isoformat()

    print(f"Acquiring single-writer lease for PID {pid} (UUID: {runtime_uuid})...")
    epoch_mgr.acquire_lease(pid, runtime_uuid)
    print("Lease acquired successfully.")

    # Graceful shutdown flag
    stop_event = asyncio.Event()

    def _signal_handler(*_args: Any) -> None:
        print(f"\nReceived termination signal. Initiating graceful shutdown for PID {pid}...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            pass

    collector_status = "RUNNING"
    cycle = 0

    print(f"Starting Prospective Raw Epoch R1 Collector daemon (PID: {pid})")
    print(f"Epoch ID: {R1_EPOCH_ID}")
    print(f"Runtime UUID: {runtime_uuid}")
    print(f"Storage Dir: {epoch_mgr.base_dir}")
    print(f"Authorized Symbols ({len(R1_AUTHORIZED_SYMBOLS)}): {list(R1_AUTHORIZED_SYMBOLS)}")
    mode_str = f"fixed {poll_interval_seconds}s interval" if poll_interval_seconds else f"15m candle close boundaries (+{grace_seconds}s grace)"
    print(f"Scheduling Mode: {mode_str}")

    try:
        # Initial poll immediately on startup
        cycle += 1
        res, backlog_count, has_missing = await poll_and_ingest_cycle(
            epoch_mgr, pid, runtime_uuid, started_at_utc, max_catchup_batches=4
        )
        summary = epoch_mgr.get_epoch_summary()
        counters = summary["counters"]

        print(
            f"Cycle {cycle} (initial): {res.get('timestamp_utc')} | Status: {epoch_mgr.get_operating_status()} | "
            f"Backlog Batches: {backlog_count} | "
            f"Total Ingested: {counters['total_ingested']} | "
            f"Complete Batches: {counters['complete_batches']} | "
            f"Duplicates Rejected: {counters['duplicates_rejected']} | "
            f"Missing Symbols: {res.get('missing_symbols', [])}"
        )

        while not stop_event.is_set():
            if max_cycles is not None and cycle >= max_cycles:
                print(f"Reached max_cycles ({max_cycles}). Exiting poll loop.")
                break

            if backlog_count > 0:
                # Catch-up remaining backlog without waiting 15m
                await asyncio.sleep(1.0)
                cycle += 1
                res, backlog_count, has_missing = await poll_and_ingest_cycle(
                    epoch_mgr, pid, runtime_uuid, started_at_utc, max_catchup_batches=4
                )
                continue

            if poll_interval_seconds is not None:
                sleep_target = poll_interval_seconds
            else:
                sleep_target = compute_seconds_to_next_boundary(grace_seconds=grace_seconds)

            next_wake_time = time.time() + sleep_target
            wake_iso = datetime.fromtimestamp(next_wake_time, tz=timezone.utc).strftime("%H:%M:%S UTC")
            print(f"Sleeping {sleep_target:.1f}s until next poll window ({wake_iso})...")

            # Sleep in intervals of at most 15 seconds to keep heartbeat fresh and check identified stop requests
            stop_request_file = epoch_mgr.base_dir / "r1_stop.request"
            while time.time() < next_wake_time and not stop_event.is_set():
                if stop_request_file.exists():
                    try:
                        req_data = json.loads(stop_request_file.read_text(encoding="utf-8"))
                        req_epoch = req_data.get("epoch_id")
                        req_pid = int(req_data.get("target_pid", 0))
                        req_uuid = str(req_data.get("target_runtime_uuid", ""))

                        if req_epoch == R1_EPOCH_ID and req_pid == pid and req_uuid == runtime_uuid:
                            print(f"Identified cooperative stop request matched PID {pid} (UUID: {runtime_uuid}). Exiting loop...")
                            stop_request_file.unlink(missing_ok=True)
                            stop_event.set()
                            break
                        else:
                            print(
                                f"WARNING: Ignoring mismatched/stale stop request (epoch={req_epoch}, target_pid={req_pid}, "
                                f"target_uuid={req_uuid}) against active daemon (pid={pid}, uuid={runtime_uuid}).",
                                file=sys.stderr,
                            )
                            # Quarantine stale request file
                            stale_path = stop_request_file.with_name(f"r1_stop.request.stale.{uuid.uuid4().hex[:8]}")
                            try:
                                stop_request_file.replace(stale_path)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"WARNING: Malformed stop request in {stop_request_file}: {e}. Quarantining.", file=sys.stderr)
                        bad_path = stop_request_file.with_name(f"r1_stop.request.malformed.{uuid.uuid4().hex[:8]}")
                        try:
                            stop_request_file.replace(bad_path)
                        except Exception:
                            pass

                epoch_mgr.update_heartbeat(
                    pid=pid,
                    runtime_uuid=runtime_uuid,
                    started_at_utc=started_at_utc,
                    collector_status=collector_status,
                    graceful_stop=False,
                )
                remaining = next_wake_time - time.time()
                await asyncio.sleep(min(15.0, max(0.5, remaining)))

            if stop_event.is_set():
                break

            # Boundary reached -> poll batch for expected candle boundary
            cycle += 1
            res, backlog_count, has_missing = await poll_and_ingest_cycle(
                epoch_mgr, pid, runtime_uuid, started_at_utc, max_catchup_batches=4
            )
            summary = epoch_mgr.get_epoch_summary()
            counters = summary["counters"]

            print(
                f"Cycle {cycle}: {res.get('timestamp_utc')} | Status: {epoch_mgr.get_operating_status()} | "
                f"Backlog Batches: {backlog_count} | "
                f"Total Ingested: {counters['total_ingested']} | "
                f"Complete Batches: {counters['complete_batches']} | "
                f"Duplicates Rejected: {counters['duplicates_rejected']} | "
                f"Missing Symbols: {res.get('missing_symbols', [])}"
            )

    finally:
        print(f"\nFinalizing shutdown: marking STOPPED and releasing lease for PID {pid}...")
        epoch_mgr.mark_stopped(pid, runtime_uuid)
        try:
            epoch_mgr.release_lease(pid, runtime_uuid)
        except Exception as e:
            print(f"Warning during lease release: {e}", file=sys.stderr)
        epoch_mgr._checkpoint_state()
        print(f"Shutdown complete. Final operating status: {epoch_mgr.get_operating_status()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prospective Raw Research Epoch R1 Collector")
    parser.add_argument("--storage-dir", type=Path, default=R1_DEFAULT_STORAGE_DIR)
    parser.add_argument("--status", action="store_true", help="Print read-only status JSON without mutating any files")
    parser.add_argument("--audit-storage", action="store_true", help="Perform comprehensive read-only audit of storage logs")
    parser.add_argument("--once", action="store_true", help="Run a single fetch/ingest pass and exit")
    parser.add_argument("--stop", action="store_true", help="Cooperatively stop active collector daemon using identified request")
    parser.add_argument("--force-stop", action="store_true", help="Forcefully terminate active collector process (FORCED_STOP)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds when waiting for stop (default: 30.0)")
    parser.add_argument("--cycles", type=int, default=None, help="Maximum poll cycles to run")
    parser.add_argument("--interval", type=float, default=None, help="Explicit poll interval in seconds (default: align to 15m candle close boundaries)")
    parser.add_argument("--grace", type=float, default=5.0, help="Grace seconds past 15m boundary (default: 5.0)")
    args = parser.parse_args()

    if args.status:
        inspector = create_read_only_inspector(args.storage_dir)
        status = inspector.get_operating_status()
        summary = inspector.get_epoch_summary()
        hb = inspector.read_heartbeat()
        lease = inspector.lease.read_lease()
        print(json.dumps({
            "operating_status": status,
            "epoch_summary": summary,
            "heartbeat": hb,
            "lease": lease,
        }, indent=2))
        return

    if args.audit_storage:
        inspector = create_read_only_inspector(args.storage_dir)
        audit_res = inspector.audit_storage()
        print(json.dumps(audit_res, indent=2))
        if audit_res.get("audit_verdict") != "AUDIT_CLEAN":
            sys.exit(1)
        return

    if args.stop:
        inspector = create_read_only_inspector(args.storage_dir)
        hb = inspector.read_heartbeat()
        lease = inspector.lease.read_lease()
        pid = (lease and lease.get("pid")) or (hb and hb.get("pid"))
        ruuid = (lease and lease.get("runtime_uuid")) or (hb and hb.get("runtime_uuid")) or ""
        if not pid or not is_pid_alive(int(pid)):
            print(f"Collector is not actively running (PID: {pid}).")
            return

        print(f"Requesting identified cooperative graceful stop for active collector PID {pid} (UUID: {ruuid})...")
        stop_file = inspector.base_dir / "r1_stop.request"
        stop_payload = {
            "epoch_id": R1_EPOCH_ID,
            "requested_at_utc": datetime.now(timezone.utc).isoformat(),
            "target_pid": int(pid),
            "target_runtime_uuid": ruuid,
        }
        # Atomic file creation via tmp file rename
        tmp_stop_file = inspector.base_dir / f"r1_stop.request.tmp.{uuid.uuid4().hex[:8]}"
        tmp_stop_file.write_text(json.dumps(stop_payload, indent=2), encoding="utf-8")
        tmp_stop_file.replace(stop_file)

        # Wait with timeout for process to exit cooperatively
        timeout_seconds = args.timeout
        start_wait = time.time()
        while time.time() - start_wait < timeout_seconds:
            if not is_pid_alive(int(pid)):
                print(f"Cooperative stop confirmed. Collector PID {pid} exited cleanly after {time.time() - start_wait:.2f}s.")
                # Verify final status with read-only inspector
                print(f"Operating status: {inspector.get_operating_status()}")
                return
            time.sleep(0.5)

        # Timed out! Do NOT falsely claim STOPPED or release lease!
        print(f"TIMEOUT: Collector PID {pid} did not exit within {timeout_seconds}s.", file=sys.stderr)
        print("Lease and heartbeat remain intact. Use --force-stop if termination is required.", file=sys.stderr)
        sys.exit(1)

    if args.force_stop:
        inspector = create_read_only_inspector(args.storage_dir)
        hb = inspector.read_heartbeat()
        lease = inspector.lease.read_lease()
        pid = (lease and lease.get("pid")) or (hb and hb.get("pid"))
        ruuid = (lease and lease.get("runtime_uuid")) or (hb and hb.get("runtime_uuid")) or ""
        if pid and is_pid_alive(int(pid)):
            print(f"Executing FORCED_STOP on PID {pid}...")
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_TERMINATE = 0x0001
                h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
                if h:
                    kernel32.TerminateProcess(h, 0)
                    kernel32.CloseHandle(h)
            else:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
            time.sleep(0.5)

        # Cleanup lease and heartbeat using writer instance
        writer_mgr = ProspectiveRawEpochManager(args.storage_dir, read_only=False)
        writer_mgr.mark_stopped(int(pid or 0), ruuid, forced=True)
        try:
            writer_mgr.release_lease(int(pid or 0), ruuid)
        except Exception:
            pass
        writer_mgr._checkpoint_state()
        print(f"FORCED_STOP complete. Operating status: {writer_mgr.get_operating_status()}")
        return

    mgr = ProspectiveRawEpochManager(args.storage_dir, read_only=False)

    if args.once:
        pid = os.getpid()
        ruuid = str(uuid.uuid4())
        mgr.acquire_lease(pid, ruuid)
        try:
            mgr.update_heartbeat(pid, ruuid, started_at_utc=datetime.now(timezone.utc).isoformat(), collector_status="RUNNING")
            res = asyncio.run(fetch_and_ingest_latest_batch(mgr, limit=2))
            summary = res["epoch_summary"]
            print(f"Single pass complete. Operating status during run: {summary['operating_status']}")
            print(f"Counters: {summary['counters']}")
        finally:
            mgr.mark_stopped(pid, ruuid)
            mgr.release_lease(pid, ruuid)
            mgr._checkpoint_state()
            print(f"Final status after exit: {mgr.get_operating_status()}")
    else:
        asyncio.run(
            run_collector_daemon(
                mgr,
                poll_interval_seconds=args.interval,
                max_cycles=args.cycles,
                grace_seconds=args.grace,
            )
        )


if __name__ == "__main__":
    main()


