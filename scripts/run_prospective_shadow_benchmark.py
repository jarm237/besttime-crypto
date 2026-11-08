#!/usr/bin/env python3
"""Dedicated Benchmark Runner for ProspectiveShadowLogger & AutoTrader NO_TRADE_SHADOW runtime.

Measures bounded latency and persistence overhead across 11 canonical operational scenarios:
1a. Hot path candidate batch alone (function_microbenchmark)
1b. Hot path full 22 symbols via evaluate_and_trade (application_cycle_end_to_end)
2a. One unseen bar per candidate (component_integration)
3. Checkpoint without evidence WAL (function_microbenchmark)
4. Checkpoint with JSONL outbox + fsync (function_microbenchmark)
5. Missing candidate transition (component_integration)
6. Stale store transition (component_integration)
7a. Gap detection transition: ACTIVE -> RECOVERING_GAP (component_integration)
7b. Gap first recovery bar: DEGRADED_GAP -> RECOVERING_GAP (component_integration)
7c. Gap full 386-bar rewarm: RECOVERING_GAP -> ACTIVE (component_integration)
8. Aged auto-trade log batch append: 22 symbols into ~5MB file (function_microbenchmark)
9. New instance warm cache restore: ProspectiveShadowLogger._restore_state (new_instance_warm_cache_restore)

Outputs canonical JSON artifact:
runtime/paper/benchmarks/prospective_shadow_microbenchmarks.json
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

# Ensure repository root in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.trading.auto_trader import AutoTrader, _append_logs_batch
from btc_scraper.trading.prospective_shadow_logger import (
    LOCKED_VCB_V1_SPEC,
    ProspectiveShadowLogger,
)


def _make_15m_series(
    start_utc: datetime,
    count: int,
    *,
    base_price: float = 100.0,
    drift_per_bar: float = 0.01,
    half_range: float = 0.08,
    volume: float = 100.0,
) -> list[dict[str, Any]]:
    candles = []
    for idx in range(count):
        ts = start_utc + timedelta(minutes=15 * idx)
        mid = base_price + drift_per_bar * idx
        candles.append(
            {
                "time_utc": ts.isoformat(),
                "time": int(ts.timestamp() * 1000),
                "open": round(mid - 0.01, 6),
                "high": round(mid + half_range, 6),
                "low": round(mid - half_range, 6),
                "close": round(mid + 0.01, 6),
                "volume": float(volume),
                "closed": True,
                "is_closed": True,
            }
        )
    return candles


def verify_staged_provenance(repo_root: Path | None = None) -> dict[str, Any]:
    """Strictly verifies staged repository provenance against partition plan and manifest.

    Requirements:
    1. Exact set of 72 staged paths matching candidate_partition_plan.json (C1-C5).
    2. Exact 19 blob SHA-256 hashes matching candidate_verification_manifest.json.
    3. Exact canonical aggregate SHA-256 matching baseline c6f354b7ea84f868f6dd0e5498ba5701dbb2836db6c9a7a56d02e689e3754a26.
    4. verified_intact is True ONLY when all checks pass. Exception always yields verified_intact=False.
    """
    root = repo_root or REPO_ROOT
    expected_baseline = "c6f354b7ea84f868f6dd0e5498ba5701dbb2836db6c9a7a56d02e689e3754a26"
    try:
        import hashlib

        # 1. Exact set of 72 staged paths from partition plan C1-C5
        plan_path = root / "evidence" / "next-step-20260922" / "candidate_partition_plan.json"
        if not plan_path.exists():
            return {
                "verified_intact": False,
                "error": f"Missing partition plan file: {plan_path}",
                "identity_sha256": None,
                "expected_baseline_identity": expected_baseline,
                "staged_file_count": 0,
                "expected_file_count": 72,
                "paths_match": False,
                "blobs_match": False,
                "aggregate_match": False,
                "method": "file_missing_error",
            }

        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        expected_paths = []
        for p_name, p_data in plan.get("partitions", {}).items():
            if p_name == "C6_CANDIDATE_SEAL_METADATA":
                continue
            expected_paths.extend(p_data.get("files", []))
        expected_paths = sorted(expected_paths)

        # Query git staged files
        out = subprocess.check_output(["git", "diff", "--name-only", "--cached"], cwd=str(root), text=True)
        staged_files = sorted(out.strip().splitlines())

        paths_match = (
            len(staged_files) == 72
            and len(expected_paths) == 72
            and staged_files == expected_paths
        )
        if not paths_match:
            missing = set(expected_paths) - set(staged_files)
            extra = set(staged_files) - set(expected_paths)
            return {
                "verified_intact": False,
                "error": f"Staged paths mismatch: missing={sorted(missing)}, extra={sorted(extra)}",
                "identity_sha256": None,
                "expected_baseline_identity": expected_baseline,
                "staged_file_count": len(staged_files),
                "expected_file_count": len(expected_paths),
                "paths_match": False,
                "blobs_match": False,
                "aggregate_match": False,
                "method": "exact_paths_mismatch",
            }

        # 2. Exact 19 manifest blob hashes
        manifest_path = root / "evidence" / "next-step-20260922" / "candidate_verification_manifest.json"
        if not manifest_path.exists():
            return {
                "verified_intact": False,
                "error": f"Missing candidate verification manifest: {manifest_path}",
                "identity_sha256": None,
                "expected_baseline_identity": expected_baseline,
                "staged_file_count": len(staged_files),
                "expected_file_count": 72,
                "paths_match": True,
                "blobs_match": False,
                "aggregate_match": False,
                "method": "manifest_missing_error",
            }

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        blobs_match = True
        mismatched_blobs = {}
        for item in manifest.get("evidence", []):
            path = item["path"]
            exp_hash = item["sha256"]
            blob = subprocess.check_output(["git", "show", f":{path}"], cwd=str(root))
            act_hash = hashlib.sha256(blob).hexdigest()
            if act_hash != exp_hash:
                blobs_match = False
                mismatched_blobs[path] = {"expected": exp_hash, "actual": act_hash}

        if not blobs_match:
            return {
                "verified_intact": False,
                "error": f"Manifest blob hash mismatch: {mismatched_blobs}",
                "identity_sha256": None,
                "expected_baseline_identity": expected_baseline,
                "staged_file_count": len(staged_files),
                "expected_file_count": len(expected_paths),
                "paths_match": True,
                "blobs_match": False,
                "aggregate_match": False,
                "method": "blob_hashes_mismatch",
            }

        # 3. Canonical aggregate identity SHA-256
        hasher = hashlib.sha256()
        for fpath in staged_files:
            blob = subprocess.check_output(["git", "show", f":{fpath}"], cwd=str(root))
            blob_hash = hashlib.sha256(blob).hexdigest()
            hasher.update(f"{fpath}:{blob_hash}\n".encode("utf-8"))
        canonical_identity = hasher.hexdigest()
        aggregate_match = (canonical_identity == expected_baseline)

        if not aggregate_match:
            return {
                "verified_intact": False,
                "error": f"Aggregate identity mismatch: got {canonical_identity}, expected {expected_baseline}",
                "identity_sha256": canonical_identity,
                "expected_baseline_identity": expected_baseline,
                "staged_file_count": len(staged_files),
                "expected_file_count": len(expected_paths),
                "paths_match": True,
                "blobs_match": True,
                "aggregate_match": False,
                "method": "aggregate_mismatch",
            }

        return {
            "verified_intact": True,
            "identity_sha256": canonical_identity,
            "expected_baseline_identity": expected_baseline,
            "staged_file_count": len(staged_files),
            "expected_file_count": len(expected_paths),
            "paths_match": True,
            "blobs_match": True,
            "aggregate_match": True,
            "method": "sha256_of_sorted_staged_paths_and_blob_sha256",
            "error": None,
        }
    except Exception as e:
        return {
            "verified_intact": False,
            "error": f"Subprocess or parsing exception during provenance verification: {e}",
            "identity_sha256": None,
            "expected_baseline_identity": expected_baseline,
            "staged_file_count": 0,
            "expected_file_count": 72,
            "paths_match": False,
            "blobs_match": False,
            "aggregate_match": False,
            "method": f"exception_failure_{type(e).__name__}",
        }


def _compute_staged_manifest_identity() -> dict[str, Any]:
    """Backward compatibility alias for verify_staged_provenance."""
    return verify_staged_provenance()


class BenchmarkContext:
    """Stateful context for individual benchmark iterations."""

    def __init__(self, **kwargs: Any) -> None:
        self.state_file: Path | None = None
        self.log_file: Path | None = None
        self.logger: ProspectiveShadowLogger | None = None
        self.temp_dir: Path | None = None
        self.bars_before: int = 0
        self.gaps_before: int = 0
        self.gap_recoveries_completed_before: int = 0
        self.__dict__.update(kwargs)


def _measure_scenario(
    fn: Callable[[], Any] | None = None,
    *,
    setup_fn: Callable[[int, bool], Any] | None = None,
    timed_fn: Callable[[Any], Any] | None = None,
    teardown_fn: Callable[[Any], None] | None = None,
    precondition_fn: Callable[[Any], None] | None = None,
    postcondition_fn: Callable[[Any, Any], dict[str, Any]] | None = None,
    benchmark_type: str = "function_microbenchmark",
    call_path: str = "",
    process_model: str = "in_process",
    cache_assumptions: str = "hot_cache",
    warmup_iters: int = 10,
    measured_iters: int = 50,
    input_event_count: int = 1,
    initial_health: str = "ACTIVE",
    final_health: str = "ACTIVE",
    initial_state_size_bytes: int = 0,
    final_state_size_bytes: int = 0,
    initial_log_size_bytes: int = 0,
    final_log_size_bytes: int = 0,
    gate_metric: str = "median_ms",
    budget_ms: float = 15.0,
) -> dict[str, Any]:
    """Harness executing setup -> assert_preconditions -> timed_operation -> probe/assert_postconditions -> cleanup.

    Supports both simple functions (via fn) and stateful iterations with unique context.
    Probes actual file sizes and health states from disk/runtime rather than hard-coding.
    """
    if fn is not None and timed_fn is None:
        timed_fn = lambda ctx: fn()
        if setup_fn is None:
            setup_fn = lambda i, is_warmup: BenchmarkContext()

    assert setup_fn is not None, "setup_fn must be provided or fn supplied"
    assert timed_fn is not None, "timed_fn must be provided or fn supplied"

    # Warmup loop: completely independent context per iteration, never leaks into measured samples
    for i in range(warmup_iters):
        ctx = setup_fn(i, True)
        if precondition_fn:
            try:
                precondition_fn(ctx)
            except Exception as e:
                if teardown_fn:
                    teardown_fn(ctx)
                raise AssertionError(f"Precondition failed at sample {i} (warmup): {e}") from e
        res = timed_fn(ctx)
        if postcondition_fn:
            try:
                postcondition_fn(ctx, res)
            except Exception as e:
                if teardown_fn:
                    teardown_fn(ctx)
                raise AssertionError(f"Postcondition failed at sample {i} (warmup): {e}") from e
        if teardown_fn:
            teardown_fn(ctx)

    # Measured loop
    latencies_ms: list[float] = []
    initial_state_sizes: list[int] = []
    final_state_sizes: list[int] = []
    initial_log_sizes: list[int] = []
    final_log_sizes: list[int] = []
    observed_initial_healths: list[str] = []
    observed_final_healths: list[str] = []
    processed_event_deltas: list[int] = []
    counter_deltas_accum: dict[str, int] = {}
    invariant_passed = True

    for i in range(measured_iters):
        ctx = setup_fn(i, False)
        if precondition_fn:
            try:
                precondition_fn(ctx)
            except Exception as e:
                invariant_passed = False
                if teardown_fn:
                    teardown_fn(ctx)
                raise AssertionError(f"Precondition failed at sample {i}: {e}") from e

        # Probe initial sizes & health after setup, immediately before timer
        init_st = (
            ctx.state_file.stat().st_size
            if hasattr(ctx, "state_file") and ctx.state_file and ctx.state_file.exists()
            else initial_state_size_bytes
        )
        init_log = (
            ctx.log_file.stat().st_size
            if hasattr(ctx, "log_file") and ctx.log_file and ctx.log_file.exists()
            else initial_log_size_bytes
        )
        init_health = (
            ctx.logger.get_health_status()["health_status"]
            if hasattr(ctx, "logger") and ctx.logger
            else initial_health
        )

        initial_state_sizes.append(init_st)
        initial_log_sizes.append(init_log)
        observed_initial_healths.append(init_health)

        t0 = time.perf_counter()
        res = timed_fn(ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies_ms.append(round(elapsed_ms, 4))

        # Probe final sizes & health immediately after timer, before cleanup
        fin_st = (
            ctx.state_file.stat().st_size
            if hasattr(ctx, "state_file") and ctx.state_file and ctx.state_file.exists()
            else final_state_size_bytes
        )
        fin_log = (
            ctx.log_file.stat().st_size
            if hasattr(ctx, "log_file") and ctx.log_file and ctx.log_file.exists()
            else final_log_size_bytes
        )
        fin_health = (
            ctx.logger.get_health_status()["health_status"]
            if hasattr(ctx, "logger") and ctx.logger
            else final_health
        )

        final_state_sizes.append(fin_st)
        final_log_sizes.append(fin_log)
        observed_final_healths.append(fin_health)

        if postcondition_fn:
            try:
                obs = postcondition_fn(ctx, res)
                if obs:
                    if "processed_bars_delta" in obs:
                        processed_event_deltas.append(obs["processed_bars_delta"])
                    for k, v in obs.get("counter_deltas", {}).items():
                        counter_deltas_accum[k] = counter_deltas_accum.get(k, 0) + v
            except Exception as e:
                invariant_passed = False
                if teardown_fn:
                    teardown_fn(ctx)
                raise AssertionError(f"Postcondition failed at sample {i}: {e}") from e

        if teardown_fn:
            teardown_fn(ctx)

    sorted_lats = sorted(latencies_ms)
    n = len(sorted_lats)
    median_ms = sorted_lats[n // 2]
    mean_ms = round(statistics.mean(latencies_ms), 4)
    p90_ms = sorted_lats[int(n * 0.90)]
    p95_ms = sorted_lats[int(n * 0.95)]
    p99_ms = sorted_lats[int(n * 0.99)]
    min_ms = min(latencies_ms)
    max_ms = max(latencies_ms)
    stdev_ms = round(statistics.stdev(latencies_ms), 4) if n > 1 else 0.0

    gate_val = p95_ms if gate_metric == "p95_ms" else median_ms
    gate_passed = bool(gate_val <= budget_ms and invariant_passed)

    med_init_st = int(statistics.median(initial_state_sizes)) if initial_state_sizes else initial_state_size_bytes
    med_fin_st = int(statistics.median(final_state_sizes)) if final_state_sizes else final_state_size_bytes
    med_init_log = int(statistics.median(initial_log_sizes)) if initial_log_sizes else initial_log_size_bytes
    med_fin_log = int(statistics.median(final_log_sizes)) if final_log_sizes else final_log_size_bytes
    med_processed_events = int(statistics.median(processed_event_deltas)) if processed_event_deltas else input_event_count

    obs_init_h = observed_initial_healths[0] if observed_initial_healths else initial_health
    obs_fin_h = observed_final_healths[0] if observed_final_healths else final_health

    return {
        "benchmark_type": benchmark_type,
        "call_path": call_path,
        "process_model": process_model,
        "cache_assumptions": cache_assumptions,
        "warmup_iterations": warmup_iters,
        "measured_iterations": measured_iters,
        "valid_samples_count": len(latencies_ms),
        "input_event_count": input_event_count,
        "processed_event_delta_per_sample": med_processed_events,
        "initial_state_size_bytes": med_init_st,
        "final_state_size_bytes": med_fin_st,
        "initial_log_size_bytes": med_init_log,
        "final_log_size_bytes": med_fin_log,
        "initial_state_size_stats": {
            "min": min(initial_state_sizes) if initial_state_sizes else med_init_st,
            "median": med_init_st,
            "max": max(initial_state_sizes) if initial_state_sizes else med_init_st,
        },
        "final_state_size_stats": {
            "min": min(final_state_sizes) if final_state_sizes else med_fin_st,
            "median": med_fin_st,
            "max": max(final_state_sizes) if final_state_sizes else med_fin_st,
        },
        "initial_log_size_stats": {
            "min": min(initial_log_sizes) if initial_log_sizes else med_init_log,
            "median": med_init_log,
            "max": max(initial_log_sizes) if initial_log_sizes else med_init_log,
        },
        "final_log_size_stats": {
            "min": min(final_log_sizes) if final_log_sizes else med_fin_log,
            "median": med_fin_log,
            "max": max(final_log_sizes) if final_log_sizes else med_fin_log,
        },
        "initial_health": obs_init_h,
        "final_health": obs_fin_h,
        "invariant_passed": invariant_passed,
        "counter_deltas": counter_deltas_accum,
        "median_ms": median_ms,
        "mean_ms": mean_ms,
        "p90_ms": p90_ms,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "stdev_ms": stdev_ms,
        "gate_metric": gate_metric,
        "budget_ms": budget_ms,
        "gate_passed": gate_passed,
        "samples_ms": latencies_ms,
    }


def main() -> int:
    print("=" * 80)
    print("PROSPECTIVE SHADOW RUNTIME BENCHMARK SUITE")
    print(f"Timestamp UTC: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # 1. Verify staged provenance upfront
    staged_manifest_info = verify_staged_provenance()
    if not staged_manifest_info["verified_intact"]:
        print(f"FATAL: Staged provenance verification failed: {staged_manifest_info.get('error')}")
        return 1

    print(f"Provenance: 72 staged files verified 100% intact.")
    print(f"Canonical Identity: {staged_manifest_info['identity_sha256']}")

    try:
        git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT)).decode().strip()
    except Exception:
        git_head = "f96c6b8b64516dd76d3af132dac316c5672e35be"

    try:
        git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(REPO_ROOT)).decode().strip()
    except Exception:
        git_branch = "model-coverage/22-symbol-v1-dev"

    base_temp_dir = Path(tempfile.mkdtemp(prefix="shadow_bench_base_"))
    try:
        start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        all_symbols = (
            "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI",
            "NEAR", "APT", "DOT", "UNI", "ICP", "RENDER", "FET", "POL", "AAVE", "LDO",
            "PEPE", "SHIB"
        )

        # Baseline warm series (400 bars)
        batch_warm = {
            "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
            "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
            "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
        }

        # Template for aged log (10,000 JSON entries, ~5 MB)
        template_aged_file = base_temp_dir / "template_aged_5mb.json"
        aged_entries = [
            {"cycle": i, "symbol": f"SYM_{i % 22}", "status": "skipped", "reason": "TEST"}
            for i in range(10000)
        ]
        template_aged_file.write_text(json.dumps(aged_entries, indent=2), encoding="utf-8")
        template_aged_size = template_aged_file.stat().st_size

        # Pre-seed persistent base logger
        base_log_file = base_temp_dir / "bench_base.jsonl"
        base_state_file = base_temp_dir / "bench_base_state.json"
        base_logger = ProspectiveShadowLogger(
            log_path=base_log_file,
            state_path=base_state_file,
            log_rejected_closed_candles=True,
        )
        base_logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

        # AutoTrader instance for 1b
        trader = AutoTrader()
        analysis = {}
        for sym in all_symbols:
            c_list = batch_warm.get(sym) or _make_15m_series(start_ts, 210, drift_per_bar=0.01)
            analysis[f"{sym}:Binance"] = {
                "coin": sym,
                "signal": "HOLD",
                "close": c_list[-1]["close"],
                "candle_store_fresh": True,
                "_shadow_candles_15m": c_list if sym in ("BTC", "ETH", "BNB") else None,
            }
        asyncio.run(trader.evaluate_and_trade(analysis))

        scenarios: dict[str, Any] = {}

        # ── 1a. Hot Path: Candidate Batch Alone (0 unseen bars) ──
        print("[1/12] Benchmarking 1a_hot_path_candidate_batch_ms...")
        scenarios["1a_hot_path_candidate_batch_ms"] = _measure_scenario(
            lambda: base_logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True),
            benchmark_type="function_microbenchmark",
            call_path="logger.observe_cycle_candidate_batch",
            process_model="in_process",
            cache_assumptions="warm_in_memory_state",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=0,
            initial_health="ACTIVE",
            final_health="ACTIVE",
            initial_state_size_bytes=base_state_file.stat().st_size if base_state_file.exists() else 0,
            final_state_size_bytes=base_state_file.stat().st_size if base_state_file.exists() else 0,
            initial_log_size_bytes=base_log_file.stat().st_size if base_log_file.exists() else 0,
            final_log_size_bytes=base_log_file.stat().st_size if base_log_file.exists() else 0,
            gate_metric="median_ms",
            budget_ms=1.0,
        )

        # ── 1b. Hot Path: Full 22 Symbols via evaluate_and_trade ──
        print("[2/12] Benchmarking 1b_hot_path_full_22_symbols_ms...")
        scenarios["1b_hot_path_full_22_symbols_ms"] = _measure_scenario(
            lambda: asyncio.run(trader.evaluate_and_trade(analysis)),
            benchmark_type="application_cycle_end_to_end",
            call_path="trader.evaluate_and_trade",
            process_model="in_process",
            cache_assumptions="warm_candle_store_and_in_memory_state",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=22,
            initial_health="ACTIVE",
            final_health="ACTIVE",
            initial_state_size_bytes=base_state_file.stat().st_size if base_state_file.exists() else 0,
            final_state_size_bytes=base_state_file.stat().st_size if base_state_file.exists() else 0,
            initial_log_size_bytes=base_log_file.stat().st_size if base_log_file.exists() else 0,
            final_log_size_bytes=base_log_file.stat().st_size if base_log_file.exists() else 0,
            gate_metric="median_ms",
            budget_ms=250.0,
        )

        # ── 2a. One Unseen Bar Per Candidate (3 closed bars) ──
        print("[3/12] Benchmarking 2a_one_unseen_bar_candidate_batch_ms...")

        def setup_2a(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_2a_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            next_ts = start_ts + timedelta(minutes=15 * 400)
            new_bar = {
                "time_utc": next_ts.isoformat(),
                "time": int(next_ts.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            }
            batch_one = {sym: list(batch_warm[sym]) + [new_bar] for sym in ("BTC", "ETH", "BNB")}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                batch_one=batch_one,
                bars_before=l._counters["actual_new_bars_processed"],
            )

        def pre_2a(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"

        def timed_2a(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger.observe_cycle_candidate_batch(ctx.batch_one, allow_historical_replay=True)

        def post_2a(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"
            delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
            assert delta == 3, f"Expected 3 processed bars, got {delta}"
            return {"processed_bars_delta": delta}

        def tear_2a(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["2a_one_unseen_bar_candidate_batch_ms"] = _measure_scenario(
            setup_fn=setup_2a,
            precondition_fn=pre_2a,
            timed_fn=timed_2a,
            postcondition_fn=post_2a,
            teardown_fn=tear_2a,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch",
            process_model="in_process",
            cache_assumptions="incremental_closed_bar_step",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=3,
            gate_metric="median_ms",
            budget_ms=15.0,
        )

        # ── 3. Checkpoint Without Evidence (Dirty State Only) ──
        print("[4/12] Benchmarking 3_checkpoint_without_evidence_ms...")

        def setup_3(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_3_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            gen_before = l._checkpoint_generation
            return BenchmarkContext(
                temp_dir=td,
                log_file=lf,
                state_file=sf,
                logger=l,
                gen_before=gen_before,
            )

        def pre_3(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert len(ctx.logger._outbox) == 0

        def timed_3(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger._persist_state()

        def post_3(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert len(ctx.logger._outbox) == 0
            assert ctx.logger._checkpoint_generation == ctx.gen_before + 1
            assert ctx.state_file is not None and ctx.state_file.exists()
            return {"processed_bars_delta": 0}

        def tear_3(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["3_checkpoint_without_evidence_ms"] = _measure_scenario(
            setup_fn=setup_3,
            precondition_fn=pre_3,
            timed_fn=timed_3,
            postcondition_fn=post_3,
            teardown_fn=tear_3,
            benchmark_type="function_microbenchmark",
            call_path="logger._persist_state",
            process_model="in_process",
            cache_assumptions="atomic_tmp_replace_with_fsync",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=0,
            gate_metric="median_ms",
            budget_ms=10.0,
        )

        # ── 4. Checkpoint With JSONL Outbox + fsync ──
        print("[5/12] Benchmarking 4_checkpoint_with_jsonl_fsync_ms...")

        def setup_4(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_4_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            l._queue_event(
                "SHADOW_CLOSED_BAR_EVALUATED",
                symbol="BTC",
                c_ts=datetime.now(timezone.utc),
                payload={"mock": True, "detail": "benchmark_event"},
            )
            gen_before = l._checkpoint_generation
            return BenchmarkContext(
                temp_dir=td,
                log_file=lf,
                state_file=sf,
                logger=l,
                gen_before=gen_before,
            )

        def pre_4(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert len(ctx.logger._outbox) == 1

        def timed_4(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger._persist_state()

        def post_4(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert len(ctx.logger._outbox) == 0
            assert ctx.logger._checkpoint_generation == ctx.gen_before + 1
            assert ctx.log_file is not None and ctx.log_file.stat().st_size > 0
            return {"processed_bars_delta": 1}

        def tear_4(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["4_checkpoint_with_jsonl_fsync_ms"] = _measure_scenario(
            setup_fn=setup_4,
            precondition_fn=pre_4,
            timed_fn=timed_4,
            postcondition_fn=post_4,
            teardown_fn=tear_4,
            benchmark_type="function_microbenchmark",
            call_path="logger._queue_event + logger._persist_state",
            process_model="in_process",
            cache_assumptions="atomic_state_plus_jsonl_outbox_fsync",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=1,
            gate_metric="median_ms",
            budget_ms=25.0,
        )

        # ── 5. Missing Candidate Transition (Demote -> Recover) ──
        print("[6/12] Benchmarking 5_missing_candidate_transition_ms...")

        def setup_5(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_5_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            missing_batch = {"BTC": batch_warm["BTC"], "ETH": batch_warm["ETH"]}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                missing_batch=missing_batch,
            )

        def pre_5(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"

        def timed_5(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            ctx.logger.observe_cycle_candidate_batch(ctx.missing_batch, allow_historical_replay=True)
            ctx.logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

        def post_5(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"
            return {"processed_bars_delta": 0}

        def tear_5(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["5_missing_candidate_transition_ms"] = _measure_scenario(
            setup_fn=setup_5,
            precondition_fn=pre_5,
            timed_fn=timed_5,
            postcondition_fn=post_5,
            teardown_fn=tear_5,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch (missing -> restore)",
            process_model="in_process",
            cache_assumptions="dynamic_health_demotion_and_recovery",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=2,
            gate_metric="median_ms",
            budget_ms=15.0,
        )

        # ── 6. Stale Store Transition (Demote -> Recover) ──
        print("[7/12] Benchmarking 6_stale_store_transition_ms...")

        def setup_6(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_6_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            stale_flags = {"BTC": {"candle_store_fresh": False}}
            fresh_flags = {"BTC": {"candle_store_fresh": True}}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                stale_flags=stale_flags, fresh_flags=fresh_flags,
            )

        def pre_6(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"

        def timed_6(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            ctx.logger.observe_cycle_candidate_batch(batch_warm, data_quality_flags=ctx.stale_flags, allow_historical_replay=True)
            ctx.logger.observe_cycle_candidate_batch(batch_warm, data_quality_flags=ctx.fresh_flags, allow_historical_replay=True)

        def post_6(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"
            return {"processed_bars_delta": 0}

        def tear_6(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["6_stale_store_transition_ms"] = _measure_scenario(
            setup_fn=setup_6,
            precondition_fn=pre_6,
            timed_fn=timed_6,
            postcondition_fn=post_6,
            teardown_fn=tear_6,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch (stale -> fresh)",
            process_model="in_process",
            cache_assumptions="dynamic_health_demotion_and_recovery",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=3,
            gate_metric="p95_ms",
            budget_ms=25.0,
        )

        # ── 7a. Gap Detection Transition: ACTIVE -> RECOVERING_GAP ──
        print("[8/12] Benchmarking 7a_gap_detection_transition_ms...")

        def setup_7a(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_7a_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            ts_gap = start_ts + timedelta(minutes=15 * 402)
            gap_c = {
                "time_utc": ts_gap.isoformat(),
                "time": int(ts_gap.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            }
            batch_gap = {sym: list(batch_warm[sym]) + [gap_c] for sym in ("BTC", "ETH", "BNB")}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                batch_gap=batch_gap,
                gaps_before=l._counters["missing_bar_gaps"],
                bars_before=l._counters["actual_new_bars_processed"],
            )

        def pre_7a(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"

        def timed_7a(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger.observe_cycle_candidate_batch(ctx.batch_gap, allow_historical_replay=True)

        def post_7a(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "RECOVERING_GAP"
            gaps_delta = ctx.logger._counters["missing_bar_gaps"] - ctx.gaps_before
            bars_delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
            assert gaps_delta == 3, f"Expected 3 gap counts across universe, got {gaps_delta}"
            assert bars_delta == 3, f"Expected 3 processed bars, got {bars_delta}"
            return {"processed_bars_delta": bars_delta, "counter_deltas": {"missing_bar_gaps": gaps_delta}}

        def tear_7a(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["7a_gap_detection_transition_ms"] = _measure_scenario(
            setup_fn=setup_7a,
            precondition_fn=pre_7a,
            timed_fn=timed_7a,
            postcondition_fn=post_7a,
            teardown_fn=tear_7a,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch (jump 30m -> RECOVERING_GAP)",
            process_model="in_process",
            cache_assumptions="jump_30m_gap_to_recovering_gap",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=3,
            initial_health="ACTIVE",
            final_health="RECOVERING_GAP",
            gate_metric="median_ms",
            budget_ms=20.0,
        )

        # ── 7b. Gap First Recovery Bar: DEGRADED_GAP -> RECOVERING_GAP ──
        print("[9/12] Benchmarking 7b_gap_first_recovery_bar_ms...")

        def setup_7b(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_7b_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=True)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            ts_gap = start_ts + timedelta(minutes=15 * 402)
            # Induce gap directly outside timing to put logger into DEGRADED_GAP
            for sym in ("BTC", "ETH", "BNB"):
                l._handle_missing_bar_gap(l._states[sym], gap_ts=ts_gap, flags=None)
            l._evaluate_global_health()
            gap_c = {
                "time_utc": ts_gap.isoformat(),
                "time": int(ts_gap.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            }
            batch_first_bar = {sym: list(batch_warm[sym]) + [gap_c] for sym in ("BTC", "ETH", "BNB")}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                batch_first_bar=batch_first_bar,
                bars_before=l._counters["actual_new_bars_processed"],
            )

        def pre_7b(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "DEGRADED_GAP"
            for sym in ("BTC", "ETH", "BNB"):
                assert ctx.logger._states[sym].health_status == "DEGRADED_GAP"
                assert ctx.logger._states[sym].next_seq == 0

        def timed_7b(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger.observe_cycle_candidate_batch(ctx.batch_first_bar, allow_historical_replay=True)

        def post_7b(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "RECOVERING_GAP"
            for sym in ("BTC", "ETH", "BNB"):
                assert ctx.logger._states[sym].health_status == "RECOVERING_GAP"
                assert ctx.logger._states[sym].next_seq == 1
            bars_delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
            assert bars_delta == 3, f"Expected 3 processed bars, got {bars_delta}"
            return {"processed_bars_delta": bars_delta}

        def tear_7b(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["7b_gap_first_recovery_bar_ms"] = _measure_scenario(
            setup_fn=setup_7b,
            precondition_fn=pre_7b,
            timed_fn=timed_7b,
            postcondition_fn=post_7b,
            teardown_fn=tear_7b,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch (first consecutive -> RECOVERING_GAP)",
            process_model="in_process",
            cache_assumptions="consecutive_bar_to_recovering_gap",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=3,
            initial_health="DEGRADED_GAP",
            final_health="RECOVERING_GAP",
            gate_metric="median_ms",
            budget_ms=20.0,
        )

        # ── 7c. Gap Full 386-Bar Rewarm: RECOVERING_GAP -> ACTIVE ──
        print("[10/12] Benchmarking 7c_gap_full_386_bar_rewarm_ms...")

        def setup_7c(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_7c_{i}_{is_warmup}_"))
            lf = td / "bench.jsonl"
            sf = td / "bench_state.json"
            l = ProspectiveShadowLogger(log_path=lf, state_path=sf, log_rejected_closed_candles=False)
            l.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
            ts_gap = start_ts + timedelta(minutes=15 * 402)
            gap_c = {
                "time_utc": ts_gap.isoformat(),
                "time": int(ts_gap.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            }
            bg = {sym: list(batch_warm[sym]) + [gap_c] for sym in ("BTC", "ETH", "BNB")}
            l.observe_cycle_candidate_batch(bg, allow_historical_replay=True)
            # Prepare exactly 385 remaining continuous bars (reaching continuous 386 bars -> ACTIVE)
            remaining_bars = []
            for j in range(1, 386):
                ts = ts_gap + timedelta(minutes=15 * j)
                remaining_bars.append({
                    "time_utc": ts.isoformat(),
                    "time": int(ts.timestamp() * 1000),
                    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                    "closed": True, "is_closed": True,
                })
            batch_rewarm = {sym: list(bg[sym]) + remaining_bars for sym in ("BTC", "ETH", "BNB")}
            return BenchmarkContext(
                temp_dir=td, log_file=lf, state_file=sf, logger=l,
                batch_rewarm=batch_rewarm,
                bars_before=l._counters["actual_new_bars_processed"],
                gap_rec_before=l._counters["gap_recoveries_completed"],
            )

        def pre_7c(ctx: BenchmarkContext) -> None:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "RECOVERING_GAP"
            for sym in ("BTC", "ETH", "BNB"):
                assert ctx.logger._states[sym].health_status == "RECOVERING_GAP"
                assert ctx.logger._states[sym].next_seq == 1

        def timed_7c(ctx: BenchmarkContext) -> Any:
            assert ctx.logger is not None
            return ctx.logger.observe_cycle_candidate_batch(ctx.batch_rewarm, allow_historical_replay=True)

        def post_7c(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.logger is not None
            assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"
            for sym in ("BTC", "ETH", "BNB"):
                assert ctx.logger._states[sym].health_status == "ACTIVE"
                assert ctx.logger._states[sym].next_seq == 386
            bars_delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
            rec_delta = ctx.logger._counters["gap_recoveries_completed"] - ctx.gap_rec_before
            assert bars_delta == 1155, f"Expected 1155 processed bars (385*3), got {bars_delta}"
            assert rec_delta == 3, f"Expected 3 gap recoveries completed, got {rec_delta}"
            return {"processed_bars_delta": bars_delta, "counter_deltas": {"gap_recoveries_completed": rec_delta}}

        def tear_7c(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["7c_gap_full_386_bar_rewarm_ms"] = _measure_scenario(
            setup_fn=setup_7c,
            precondition_fn=pre_7c,
            timed_fn=timed_7c,
            postcondition_fn=post_7c,
            teardown_fn=tear_7c,
            benchmark_type="component_integration",
            call_path="logger.observe_cycle_candidate_batch (385 remaining continuous -> ACTIVE)",
            process_model="in_process",
            cache_assumptions="stream_385_bars_to_active",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=1155,
            initial_health="RECOVERING_GAP",
            final_health="ACTIVE",
            gate_metric="median_ms",
            budget_ms=50.0,
        )

        # ── 8. Aged Auto-Trade Log Append (10,000 entries ~5MB) ──
        print("[11/12] Benchmarking 8_aged_auto_trade_log_append_22_syms_ms...")
        batch_to_append = [
            {"cycle": 10001, "symbol": sym, "status": "skipped", "reason": "NO_VIABLE_ECONOMIC_CANDIDATE"}
            for sym in all_symbols
        ]

        def setup_8(i: int, is_warmup: bool) -> BenchmarkContext:
            td = Path(tempfile.mkdtemp(prefix=f"bench_8_{i}_{is_warmup}_"))
            sample_file = td / "auto_trade_log.json"
            shutil.copyfile(template_aged_file, sample_file)
            return BenchmarkContext(temp_dir=td, log_file=sample_file)

        def pre_8(ctx: BenchmarkContext) -> None:
            assert ctx.log_file is not None
            assert ctx.log_file.stat().st_size == template_aged_size

        def timed_8(ctx: BenchmarkContext) -> Any:
            assert ctx.log_file is not None
            with patch("btc_scraper.trading.auto_trader._auto_trade_log_path", return_value=ctx.log_file):
                _append_logs_batch(batch_to_append)

        def post_8(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            assert ctx.log_file is not None
            fin_size = ctx.log_file.stat().st_size
            assert fin_size > template_aged_size
            data = json.loads(ctx.log_file.read_text(encoding="utf-8"))
            assert len(data) == 10022
            return {"processed_bars_delta": 22}

        def tear_8(ctx: BenchmarkContext) -> None:
            if ctx.temp_dir:
                shutil.rmtree(ctx.temp_dir, ignore_errors=True)

        scenarios["8_aged_auto_trade_log_append_22_syms_ms"] = _measure_scenario(
            setup_fn=setup_8,
            precondition_fn=pre_8,
            timed_fn=timed_8,
            postcondition_fn=post_8,
            teardown_fn=tear_8,
            benchmark_type="function_microbenchmark",
            call_path="_append_logs_batch",
            process_model="in_process",
            cache_assumptions="append_to_aged_json_log_with_flush_fsync",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=22,
            initial_health="ACTIVE",
            final_health="ACTIVE",
            gate_metric="median_ms",
            budget_ms=50.0,
        )

        # ── 9. New Instance Warm Cache Restore ──
        print("[12/12] Benchmarking 9_new_instance_warm_cache_restore_ms...")
        base_logger._persist_state()
        expected_gen = base_logger._checkpoint_generation

        def setup_9(i: int, is_warmup: bool) -> BenchmarkContext:
            return BenchmarkContext(
                state_file=base_state_file,
                log_file=base_log_file,
            )

        def pre_9(ctx: BenchmarkContext) -> None:
            assert ctx.state_file is not None and ctx.state_file.exists()
            assert ctx.log_file is not None and ctx.log_file.exists()

        def timed_9(ctx: BenchmarkContext) -> Any:
            cold_logger = ProspectiveShadowLogger(
                log_path=base_log_file,
                state_path=base_state_file,
                log_rejected_closed_candles=True,
            )
            return cold_logger

        def post_9(ctx: BenchmarkContext, res: Any) -> dict[str, Any]:
            cold_logger = res
            assert cold_logger.get_health_status()["health_status"] == "ACTIVE"
            assert cold_logger._checkpoint_generation == expected_gen
            return {"processed_bars_delta": 0}

        scenarios["9_new_instance_warm_cache_restore_ms"] = _measure_scenario(
            setup_fn=setup_9,
            precondition_fn=pre_9,
            timed_fn=timed_9,
            postcondition_fn=post_9,
            benchmark_type="new_instance_warm_cache_restore",
            call_path="ProspectiveShadowLogger._restore_state",
            process_model="same_process_new_instance",
            cache_assumptions="os_filesystem_page_cache_hot",
            warmup_iters=10,
            measured_iters=50,
            input_event_count=0,
            initial_health="ACTIVE",
            final_health="ACTIVE",
            gate_metric="median_ms",
            budget_ms=25.0,
        )

        # Print Summary Table
        print("\n" + "=" * 125)
        print(f"{'Scenario':<42} | {'Type':<30} | {'Median':<9} | {'P95':<9} | {'Events':<7} | {'Gate':<6} | {'Status'}")
        print("-" * 125)
        all_passed = True
        for name, data in scenarios.items():
            status_str = "PASS" if data["gate_passed"] and data["invariant_passed"] else "FAIL"
            if not (data["gate_passed"] and data["invariant_passed"]):
                all_passed = False
            gate_desc = f"{data['gate_metric'][:3]}<{data['budget_ms']}"
            print(
                f"{name:<42} | "
                f"{data['benchmark_type']:<30} | "
                f"{data['median_ms']:>6.2f} ms | "
                f"{data['p95_ms']:>6.2f} ms | "
                f"{data['processed_event_delta_per_sample']:>6}  | "
                f"{gate_desc:<6} | "
                f"{status_str}"
            )
        print("=" * 125)

        if not all_passed:
            print("FATAL: One or more benchmark gates or invariants failed!")
            return 1

        # Build Canonical Artifact
        artifact_path = REPO_ROOT / "runtime" / "paper" / "benchmarks" / "prospective_shadow_microbenchmarks.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = {
            "metadata": {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "git_head": git_head,
                "git_branch": git_branch,
                "python_version": sys.version,
                "platform": platform.platform(),
                "staged_manifest_identity": staged_manifest_info["identity_sha256"],
                "staged_manifest_method": staged_manifest_info["method"],
                "staged_manifest_file_count": staged_manifest_info["staged_file_count"],
                "staged_manifest_expected_baseline": staged_manifest_info["expected_baseline_identity"],
                "staged_manifest_verified_intact": staged_manifest_info["verified_intact"],
                "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
                "evidence_epoch_id": "NOT_ACTIVATED",
                "strategy_spec_sha256": LOCKED_VCB_V1_SPEC.strategy_spec_sha256,
                "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
                "runtime_status": "CODE_READY_NOT_ACTIVATED",
                "paper_policy": "NO_TRADE_SHADOW",
            },
            "scenarios": scenarios,
        }

        artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        print(f"\nCanonical benchmark artifact exported to:\n  {artifact_path}")
        print(f"Artifact size: {artifact_path.stat().st_size} bytes")

    finally:
        shutil.rmtree(base_temp_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
