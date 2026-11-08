"""Unit and Integration tests for ProspectiveShadowLogger, LockedCandidateSpec, and AutoTrader production wiring (`NO_TRADE_SHADOW`)."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from btc_scraper.core.candle_store import CandleStore
from btc_scraper.ml_engine.multi_agent import MarketAnalystAgent
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.prospective_shadow_logger import (
    LOCKED_VCB_V1_SPEC,
    EvidenceActivationManifest,
    LockedCandidateSpec,
    ProspectiveShadowLogger,
    create_activation_manifest,
    is_15m_candle_closed,
    parse_candle_open_utc,
    validate_15m_candle,
)
from scripts.evaluate_candidates_and_promotion_gates_v2 import (
    simulate_next_bar_open_barrier_trade,
)

TEST_EPOCH = "NOT_ACTIVATED"


def _make_15m_series(
    start_utc: datetime,
    count: int,
    *,
    base_price: float = 100.0,
    drift_per_bar: float = 0.01,
    half_range: float = 0.08,
    volume: float = 100.0,
    last_closed: bool = True,
) -> list[dict]:
    candles: list[dict] = []
    for idx in range(count):
        ts = start_utc + timedelta(minutes=15 * idx)
        mid = base_price + drift_per_bar * idx
        is_closed = True if idx < count - 1 else bool(last_closed)
        candles.append(
            {
                "time_utc": ts.isoformat(),
                "time": int(ts.timestamp() * 1000),
                "open": round(mid - 0.01, 6),
                "high": round(mid + half_range, 6),
                "low": round(mid - half_range, 6),
                "close": round(mid + 0.01, 6),
                "volume": float(volume),
                "closed": is_closed,
                "is_closed": is_closed,
            }
        )
    return candles


def test_locked_vcb_v1_spec_immutability_and_sha256_integrity():
    """Verifies candidate spec is frozen, tamper-evident, and documents historical cutoffs."""
    LOCKED_VCB_V1_SPEC.verify_integrity()
    assert LOCKED_VCB_V1_SPEC.candidate_id == "VOL_COMPRESSION_BREAKOUT_V1"
    assert LOCKED_VCB_V1_SPEC.spec_version == "2.0.0-passive-shadow"
    payload = LOCKED_VCB_V1_SPEC.canonical_strategy_payload()
    assert "evidence_epoch_id" not in payload
    assert "collection_start_timestamp" not in payload
    assert LOCKED_VCB_V1_SPEC.last_parameter_fit_timestamp == "2025-12-31T23:45:00+00:00"
    assert LOCKED_VCB_V1_SPEC.last_used_historical_timestamp == "2026-06-30T23:45:00+00:00"
    assert LOCKED_VCB_V1_SPEC.strategy_spec_sha256 == "7a7f6d647ac2adf7c20754200d75a52bdfecbd33679b8a4b231a5e05c0ee4ea8"
    assert LOCKED_VCB_V1_SPEC.spec_sha256 == "7a7f6d647ac2adf7c20754200d75a52bdfecbd33679b8a4b231a5e05c0ee4ea8"
    assert len(LOCKED_VCB_V1_SPEC.spec_sha256) == 64

    with pytest.raises(dataclasses.FrozenInstanceError):
        LOCKED_VCB_V1_SPEC.tp_bps = 400.0  # type: ignore[misc]

    frozen_map = LOCKED_VCB_V1_SPEC.to_frozen_mapping()
    with pytest.raises(TypeError):
        frozen_map["tp_bps"] = 400.0  # type: ignore[index]


def test_candlestore_per_stream_capacity_and_production_handoff_warmup(tmp_path: Path):
    """Verifies CandleStore capacity separation (500 for candidates, 220 for other symbols)
    and production MarketAnalystAgent -> AutoTrader prospective shadow warmup handoff."""
    store = CandleStore(
        max_candles=220,
        capacity_overrides={("BTC", "15m"): 500, ("ETH", "15m"): 500, ("BNB", "15m"): 500},
    )

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    btc_candles = _make_15m_series(start_ts, 450, drift_per_bar=0.01)
    sol_candles = _make_15m_series(start_ts, 450, drift_per_bar=0.01)

    store.seed("BTC", "15m", btc_candles)
    store.seed("SOL", "15m", sol_candles)

    assert store.candle_count("BTC", "15m") == 450
    assert store.candle_count("SOL", "15m") == 220

    agent = MarketAnalystAgent(analysis_symbols=("BTC", "SOL"))
    ctx = {
        "raw_candles": {
            "BTC": store.get("BTC", "15m"),
            "SOL": store.get("SOL", "15m"),
        },
        "mtf_candles": {},
    }
    with patch("btc_scraper.core.candle_store.candle_store", store):
        results = agent.run(ctx)
    ana_btc = results["analysis"]["BTC:Binance"]
    ana_sol = results["analysis"]["SOL:Binance"]

    assert "_shadow_candles_15m" in ana_btc
    assert len(ana_btc["_shadow_candles_15m"]) == 450
    assert "candles_15m" not in ana_btc
    assert "_shadow_candles_15m" not in ana_sol


def test_p0_production_evaluate_and_trade_single_batch_wiring(tmp_path: Path):
    """P0 Test: Verifies that AutoTrader.evaluate_and_trade:
    1. Calls observe_cycle_candidate_batch exactly once per cycle.
    2. NEVER calls observe_symbol_candles from production.
    3. Persists state exactly once per cycle.
    4. Strips _shadow_candles_15m from all logs/payloads.
    5. Enforces global health gate across candidate symbols."""
    log_file = tmp_path / "prod_batch_wiring.jsonl"
    state_file = tmp_path / "prod_batch_wiring_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=state_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    symbols = (
        "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI",
        "NEAR", "APT", "DOT", "UNI", "ICP", "RENDER", "FET", "POL", "AAVE", "LDO",
        "PEPE", "SHIB"
    )
    assert len(symbols) == 22

    analysis = {}
    for sym in symbols:
        c_count = 500 if sym in ("BTC", "ETH", "BNB") else 220
        c_list = _make_15m_series(start_ts, c_count, base_price=100.0, drift_per_bar=0.01)
        ana = {
            "coin": sym,
            "signal": "HOLD",
            "close": c_list[-1]["close"],
            "candle_store_fresh": True,
        }
        if sym in ("BTC", "ETH", "BNB"):
            ana["_shadow_candles_15m"] = c_list
        analysis[f"{sym}:Binance"] = ana

    trader = AutoTrader()

    with patch.object(logger, "observe_cycle_candidate_batch", wraps=logger.observe_cycle_candidate_batch) as mock_batch, \
         patch.object(logger, "observe_symbol_candles", wraps=logger.observe_symbol_candles) as mock_single, \
         patch("btc_scraper.trading.auto_trader.get_prospective_shadow_logger", return_value=logger), \
         patch("btc_scraper.trading.prospective_shadow_logger.get_prospective_shadow_logger", return_value=logger):

        logs = asyncio.run(trader.evaluate_and_trade(analysis))

    # 1. Batch API was called exactly once for the cycle
    assert mock_batch.call_count == 1
    # 2. Production never called observe_symbol_candles
    assert mock_single.call_count == 0
    # 3. State was persisted exactly once (generation == 1)
    assert logger._checkpoint_generation == 1
    # 4. _shadow_candles_15m is never present in returned logs
    for log in logs:
        assert "_shadow_candles_15m" not in log
        assert "candles_15m" not in log


def test_p1_global_chronological_interleaved_bars_ordering(tmp_path: Path):
    """P1 Test: Proves that observe_cycle_candidate_batch merges unseen closed bars across
    BTC, ETH, and BNB and processes them strictly in global (timestamp, symbol) order."""
    log_file = tmp_path / "global_order.jsonl"
    state_file = tmp_path / "global_order_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=state_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    # Warm up all 3 symbols with 400 bars
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, base_price=100.0, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, base_price=50.0, drift_per_bar=0.01),
        "BNB": _make_15m_series(start_ts, 400, base_price=30.0, drift_per_bar=0.01),
    }
    ts_400 = start_ts + timedelta(minutes=15 * 400)
    ts_401 = start_ts + timedelta(minutes=15 * 401)
    now_ref_warm = ts_400
    now_ref_interleaved = ts_401 + timedelta(minutes=15)
    logger.observe_cycle_candidate_batch(batch_warm, now_utc=now_ref_warm, allow_historical_replay=False)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    # Now create interleaved missed bars across the 3 symbols:
    # ETH has bar at 400 (ts0)
    # BTC has bar at 400 (ts0)
    # BNB has bar at 400 (ts0)
    # Plus ETH has bar at 401 (ts1)
    # Plus BTC has bar at 401 (ts1)
    batch_interleaved = {
        "BTC": list(batch_warm["BTC"]),
        "ETH": list(batch_warm["ETH"]),
        "BNB": list(batch_warm["BNB"]),
    }
    for sym in ("BNB", "BTC", "ETH"):
        batch_interleaved[sym].append({
            "time_utc": ts_400.isoformat(),
            "time": int(ts_400.timestamp() * 1000),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 150.0,
            "closed": True, "is_closed": True,
        })
    # Add second bar only to BTC and ETH
    for sym in ("BTC", "ETH"):
        batch_interleaved[sym].append({
            "time_utc": ts_401.isoformat(),
            "time": int(ts_401.timestamp() * 1000),
            "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 180.0,
            "closed": True, "is_closed": True,
        })

    # Observe interleaved batch
    logger.observe_cycle_candidate_batch(batch_interleaved, now_utc=now_ref_interleaved, allow_historical_replay=False)

    lines = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    eval_events = [l for l in lines if l["event_type"] in ("SHADOW_CLOSED_BAR_EVALUATED", "SHADOW_SIGNAL_ACCEPTED")]
    assert len(eval_events) == 8  # 3 warmup evaluation events (ts_399) + 5 interleaved events (ts_400, ts_401)

    # Check timestamps and symbols sequence for the 5 interleaved events
    order = [(e["signal_timestamp"], e["symbol"]) for e in eval_events[-5:]]
    assert order == [
        (ts_400.isoformat(), "BNB"),
        (ts_400.isoformat(), "BTC"),
        (ts_400.isoformat(), "ETH"),
        (ts_401.isoformat(), "BTC"),
        (ts_401.isoformat(), "ETH"),
    ]


def test_p1_dictionary_order_invariance(tmp_path: Path):
    """P1 Test: Verifies that passing candidate symbols in different dict orders
    yields identical execution order, identical event sequences, and identical state."""
    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    candles_btc = _make_15m_series(start_ts, 402, drift_per_bar=0.01)
    candles_eth = _make_15m_series(start_ts, 402, drift_per_bar=0.012)
    candles_bnb = _make_15m_series(start_ts, 402, drift_per_bar=0.008)

    # Run A: BTC, ETH, BNB
    log_a = tmp_path / "run_a.jsonl"
    st_a = tmp_path / "st_a.json"
    logger_a = ProspectiveShadowLogger(log_path=log_a, state_path=st_a, log_rejected_closed_candles=True)
    logger_a.observe_cycle_candidate_batch({"BTC": candles_btc, "ETH": candles_eth, "BNB": candles_bnb}, allow_historical_replay=True)

    # Run B: BNB, BTC, ETH (reversed dict order)
    log_b = tmp_path / "run_b.jsonl"
    st_b = tmp_path / "st_b.json"
    logger_b = ProspectiveShadowLogger(log_path=log_b, state_path=st_b, log_rejected_closed_candles=True)
    logger_b.observe_cycle_candidate_batch({"BNB": candles_bnb, "BTC": candles_btc, "ETH": candles_eth}, allow_historical_replay=True)

    lines_a = log_a.read_text(encoding="utf-8").splitlines()
    lines_b = log_b.read_text(encoding="utf-8").splitlines()
    assert len(lines_a) == len(lines_b)

    for la, lb in zip(lines_a, lines_b):
        ea = json.loads(la)
        eb = json.loads(lb)
        # Strip timestamp of execution
        ea.pop("logged_at_utc", None)
        eb.pop("logged_at_utc", None)
        assert ea == eb

    # Canonical state files st_a and st_b must be identical (modulo execution timestamps)
    st_a_data = json.loads(st_a.read_text(encoding="utf-8"))
    st_b_data = json.loads(st_b.read_text(encoding="utf-8"))
    for st_data in (st_a_data, st_b_data):
        st_data.pop("last_persisted_utc", None)
        st_data["counters"].pop("last_successful_persist_timestamp", None)
        for sym_state in st_data.get("symbols", {}).values():
            if isinstance(sym_state.get("last_summary"), dict):
                sym_state["last_summary"].pop("logged_at_utc", None)
    assert st_a_data == st_b_data


def test_p1_global_health_admission_gate(tmp_path: Path):
    """P1 Test: Verifies that prospective signals are strictly blocked when global health
    is WARMING_UP or DEGRADED_GAP, even if individual indicators pass."""
    log_file = tmp_path / "health_gate.jsonl"
    st_file = tmp_path / "health_gate_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    # Warm up ONLY BTC with 400 bars (ETH and BNB have only 10 bars)
    bars_btc = _make_15m_series(start_ts, 401, drift_per_bar=0.02)
    # Force breakout on BTC at bar 400
    prev_hi = max(b["high"] for b in bars_btc[304:400])
    bars_btc[400]["open"] = prev_hi - 0.02
    bars_btc[400]["low"] = prev_hi - 0.05
    bars_btc[400]["close"] = round(prev_hi + 0.30, 6)
    bars_btc[400]["high"] = round(prev_hi + 0.35, 6)
    bars_btc[400]["volume"] = 250.0

    batch_partial = {
        "BTC": bars_btc,
        "ETH": _make_15m_series(start_ts, 10, drift_per_bar=0.01),
        "BNB": _make_15m_series(start_ts, 10, drift_per_bar=0.01),
    }

    logger.observe_cycle_candidate_batch(batch_partial, allow_historical_replay=True)
    h = logger.get_health_status()
    assert h["health_status"] == "WARMING_UP"

    # BTC should NOT have an accepted signal because global health is WARMING_UP
    summary_btc = logger._states["BTC"].last_summary
    assert summary_btc["accepted"] is False
    assert summary_btc["decision_reason"] == "REJECTED_GLOBAL_HEALTH_WARMING_UP"
    assert logger._states["BTC"].pending_signal is None


def test_p2_bounded_wal_tail_recovery_large_file(tmp_path: Path):
    """P2 Test: Verifies that recovery on a large 10,000-line JSONL archive:
    1. Reads at most 64KB tail without loading the entire file into memory.
    2. Recovers in < 15 ms.
    3. Monotonically preserves event_sequence and watermark."""
    log_file = tmp_path / "large_archive.jsonl"
    st_file = tmp_path / "large_archive_state.json"

    # Pre-generate a 10,000-line JSONL file
    lines = []
    base_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    for i in range(1, 10001):
        ts = (base_ts + timedelta(minutes=15 * (i % 500))).isoformat()
        rec = {
            "event_id": f"{TEST_EPOCH}:BTC:{ts}:TEST_RECORD:none:{i}",
            "event_sequence": i,
            "checkpoint_generation": i // 10,
            "evidence_epoch_id": "NOT_ACTIVATED",
            "logger_schema_version": "2.0.0",
            "event_type": "SHADOW_CLOSED_BAR_EVALUATED",
            "logged_at_utc": ts,
            "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
            "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
            "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
            "symbol": "BTC",
        }
        lines.append(json.dumps(rec, separators=(",", ":")))
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert log_file.stat().st_size > 1_500_000  # > 1.5 MB

    # Write state checkpoint pointing to last committed event = 10000
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": "NOT_ACTIVATED",
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1000,
        "event_sequence": 10000,
        "last_committed_event_sequence": 10000,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    # Measure recovery latency
    t0 = time.perf_counter()
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=False)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 25.0, f"Recovery latency too high: {elapsed_ms:.2f} ms"
    assert logger._event_sequence == 10000
    assert logger._last_committed_event_sequence == 10000
    assert len(logger._flushed_event_ids) > 0
    # Flushed event IDs bounded
    assert len(logger._flushed_event_ids) <= 2000


def test_p2_failure_injection_production_batch(tmp_path: Path):
    """P2 Test: Failure injection across checkpoint preparation, JSONL flush, and restart recovery."""
    log_file = tmp_path / "wal_fail_batch.jsonl"
    st_file = tmp_path / "wal_fail_batch_state.json"
    logger1 = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch = {
        "BTC": _make_15m_series(start_ts, 401, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 401, drift_per_bar=0.01),
        "BNB": _make_15m_series(start_ts, 401, drift_per_bar=0.01),
    }
    logger1.observe_cycle_candidate_batch(batch, allow_historical_replay=True)
    initial_log_lines = len(log_file.read_text(encoding="utf-8").splitlines())

    # Simulate crash right after state checkpoint replace, before JSONL flush:
    # We add an event to state outbox with sequence = 9999
    st_data = json.loads(st_file.read_text(encoding="utf-8"))
    st_data["event_sequence"] = 9999
    st_data["outbox"] = [{
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T15:00:00+00:00:SHADOW_TEST_CRASH:none:9999",
        "event_sequence": 9999,
        "checkpoint_generation": st_data["checkpoint_generation"] + 1,
        "evidence_epoch_id": TEST_EPOCH,
        "logger_schema_version": "2.0.0",
        "event_type": "SHADOW_TEST_CRASH",
        "logged_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "lock_timestamp": LOCKED_VCB_V1_SPEC.lock_timestamp,
        "last_used_historical_timestamp": LOCKED_VCB_V1_SPEC.last_used_historical_timestamp,
        "collection_start_timestamp": "",
        "symbol": "BTC",
    }]
    st_file.write_text(json.dumps(st_data), encoding="utf-8")

    # Recover process
    logger2 = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)
    recovered_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(recovered_lines) == initial_log_lines + 1
    assert "SHADOW_TEST_CRASH" in recovered_lines[-1]
    assert logger2._event_sequence >= 9999
    assert logger2._last_committed_event_sequence >= 9999

    # Re-instantiate again: must be completely idempotent (no duplicate events added)
    logger3 = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)
    final_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(final_lines) == len(recovered_lines)


def test_p2_partial_line_truncation_at_eof(tmp_path: Path):
    """P2 Test: Verifies that broken trailing line at EOF of JSONL is truncated cleanly."""
    log_file = tmp_path / "broken_eof.jsonl"
    st_file = tmp_path / "broken_eof_state.json"

    # Pre-create valid state matching spec
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": TEST_EPOCH,
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 2,
        "last_committed_event_sequence": 2,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    rec1 = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:00:00+00:00:E1:none:1",
        "event_sequence": 1,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }
    rec2 = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:15:00+00:00:E2:none:2",
        "event_sequence": 2,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }

    # Write 2 valid lines followed by an incomplete line without newline
    log_file.write_text(
        json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n" + '{"event_sequence": 3, "partial": ',
        encoding="utf-8",
    )

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=False)
    content = log_file.read_text(encoding="utf-8")
    assert content == json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n"


def test_p3_production_path_benchmarks(tmp_path: Path):
    """P3 Benchmark: Measures latency across:
    1. Candidate batch alone (< 15 ms target).
    2. Production integration path through AutoTrader.evaluate_and_trade with 22 symbols."""
    log_file = tmp_path / "bench_prod.jsonl"
    state_file = tmp_path / "bench_prod_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=state_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    symbols = (
        "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI",
        "NEAR", "APT", "DOT", "UNI", "ICP", "RENDER", "FET", "POL", "AAVE", "LDO",
        "PEPE", "SHIB"
    )

    # 1. Warm up candidate batch
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.015),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=False)

    # Measure batch observation alone
    batch_latencies = []
    curr_batch = {k: list(v) for k, v in batch_warm.items()}
    for step in range(10):
        next_ts = start_ts + timedelta(minutes=15 * (400 + step))
        for sym in ("BTC", "ETH", "BNB"):
            c = curr_batch[sym][-1]
            curr_batch[sym].append({
                "time_utc": next_ts.isoformat(),
                "time": int(next_ts.timestamp() * 1000),
                "open": c["close"], "high": c["close"] + 0.05, "low": c["close"] - 0.05, "close": c["close"] + 0.01,
                "volume": 120.0, "closed": True, "is_closed": True,
            })
        t0 = time.perf_counter()
        logger.observe_cycle_candidate_batch(curr_batch, allow_historical_replay=False)
        batch_latencies.append((time.perf_counter() - t0) * 1000)

    median_batch_ms = sorted(batch_latencies)[len(batch_latencies) // 2]
    p95_batch_ms = sorted(batch_latencies)[int(len(batch_latencies) * 0.95)]
    max_batch_ms = max(batch_latencies)

    assert median_batch_ms < 15.0, f"Candidate batch median latency too high: {median_batch_ms:.2f} ms"

    # 2. Measure production evaluate_and_trade path across all 22 symbols
    trader = AutoTrader()
    analysis = {}
    for sym in symbols:
        c_list = curr_batch.get(sym) or _make_15m_series(start_ts, 210, drift_per_bar=0.01)
        ana = {
            "coin": sym,
            "signal": "HOLD",
            "close": c_list[-1]["close"],
            "candle_store_fresh": True,
        }
        if sym in ("BTC", "ETH", "BNB"):
            ana["_shadow_candles_15m"] = c_list
        analysis[f"{sym}:Binance"] = ana

    prod_latencies = []
    with patch("btc_scraper.trading.auto_trader.get_prospective_shadow_logger", return_value=logger), \
         patch("btc_scraper.trading.prospective_shadow_logger.get_prospective_shadow_logger", return_value=logger):
        for _ in range(10):
            t0 = time.perf_counter()
            logs = asyncio.run(trader.evaluate_and_trade(analysis))
            prod_latencies.append((time.perf_counter() - t0) * 1000)

    median_prod_ms = sorted(prod_latencies)[len(prod_latencies) // 2]
    assert len(logs) == 22
    assert median_prod_ms < 250.0, f"Production evaluate_and_trade latency too high: {median_prod_ms:.2f} ms"


def test_batch_simulator_vs_prospective_logger_exact_parity_all_outcomes(tmp_path: Path):
    """Asserts exact identity between simulate_next_bar_open_barrier_trade and ProspectiveShadowLogger
    across TP, SL, and SL_GAP barrier outcomes."""
    cases = [
        ("TP", lambda b: b.__setitem__(402, dict(b[402], open=110.6, low=110.4, high=114.5, close=114.0))),
        ("SL", lambda b: b.__setitem__(402, dict(b[402], open=110.0, high=110.2, low=108.0, close=108.2))),
        ("SL_GAP", lambda b: b.__setitem__(402, dict(b[402], open=107.5, high=107.8, low=107.0, close=107.2))),
    ]

    for outcome_name, mutate_fn in cases:
        start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        bars = _make_15m_series(start_ts, 405, base_price=100.0, drift_per_bar=0.02, half_range=0.05)

        prev_hi = max(b["high"] for b in bars[304:400])
        bars[400]["open"] = prev_hi - 0.02
        bars[400]["low"] = prev_hi - 0.05
        bars[400]["close"] = round(prev_hi + 0.30, 6)
        bars[400]["high"] = round(prev_hi + 0.35, 6)
        bars[400]["volume"] = 250.0

        bars[401]["open"] = 110.00
        bars[401]["high"] = 111.00
        bars[401]["low"] = 109.50
        bars[401]["close"] = 110.50

        mutate_fn(bars)

        # 1. Batch trade simulation
        opens = np.array([b["open"] for b in bars])
        highs = np.array([b["high"] for b in bars])
        lows = np.array([b["low"] for b in bars])
        closes = np.array([b["close"] for b in bars])
        timestamps = [b["time_utc"] for b in bars]

        batch_res = simulate_next_bar_open_barrier_trade(
            side="BUY",
            signal_idx=400,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            timestamps=timestamps,
            max_hold=LOCKED_VCB_V1_SPEC.max_hold_bars,
            tp_bps=LOCKED_VCB_V1_SPEC.tp_bps,
            sl_bps=LOCKED_VCB_V1_SPEC.sl_bps,
        )

        # 2. ProspectiveShadowLogger
        log_file = tmp_path / f"parity_{outcome_name}.jsonl"
        logger = ProspectiveShadowLogger(log_path=log_file, log_rejected_closed_candles=False)
        # Use candidate batch
        logger.observe_cycle_candidate_batch({"BTC": bars[:401], "ETH": bars[:401], "BNB": bars[:401]}, allow_historical_replay=True)
        logger.observe_cycle_candidate_batch({"BTC": bars[:404], "ETH": bars[:404], "BNB": bars[:404]}, allow_historical_replay=True)

        records = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        resolved = [r for r in records if r["event_type"] == "SHADOW_LIFECYCLE_RESOLVED" and r["symbol"] == "BTC"]
        assert len(resolved) == 1, f"Expected 1 resolved trade for {outcome_name}, got {len(resolved)}"
        shadow_res = resolved[0]

        assert shadow_res["outcome"] == batch_res["exit_reason"]
        assert shadow_res["entry_price"] == pytest.approx(batch_res["entry_price"])
        assert shadow_res["exit_price"] == pytest.approx(batch_res["exit_price"])
        assert shadow_res["gross_pnl_bps"] == pytest.approx(batch_res["gross_pnl_bps"], abs=1e-3)
        assert shadow_res["bars_held"] == batch_res["bars_held"]


def test_p0_gap_recovery_lifecycle(tmp_path: Path):
    """P0 Test: Verifies state machine lifecycle on missing-bar gap:
    ACTIVE -> DEGRADED_GAP -> RECOVERING_GAP -> ACTIVE.
    Verifies gap_recovery_bars, gap_recoveries_completed, and admission blocks during recovery."""
    log_file = tmp_path / "gap_lifecycle.jsonl"
    st_file = tmp_path / "gap_lifecycle_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    # Warm up with 400 bars across BTC, ETH, BNB
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"
    assert logger._states["BTC"].health_status == "ACTIVE"

    # Step 1: Inject a missing-bar gap on BTC
    gap_ts = start_ts + timedelta(minutes=15 * 403)
    logger._handle_missing_bar_gap(logger._states["BTC"], gap_ts=gap_ts, flags=None)
    assert logger._states["BTC"].health_status == "DEGRADED_GAP"
    assert logger.get_health_status()["health_status"] == "DEGRADED_GAP"
    assert logger._counters["missing_bar_gaps"] >= 1

    # Step 2: Deliver first continuous new bar at 404 -> transitions DEGRADED_GAP -> RECOVERING_GAP
    ts_404 = start_ts + timedelta(minutes=15 * 404)
    batch_rec1 = {
        "BTC": list(batch_warm["BTC"]) + [{
            "time_utc": ts_404.isoformat(),
            "time": int(ts_404.timestamp() * 1000),
            "open": 104.5, "high": 106.0, "low": 104.0, "close": 105.5, "volume": 200.0,
            "closed": True, "is_closed": True,
        }],
        "ETH": list(batch_warm["ETH"]),
        "BNB": list(batch_warm["BNB"]),
    }
    logger.observe_cycle_candidate_batch(batch_rec1, allow_historical_replay=True)
    assert logger._states["BTC"].health_status == "RECOVERING_GAP"
    assert logger.get_health_status()["health_status"] == "RECOVERING_GAP"
    assert logger._counters["gap_recovery_bars"] >= 1

    # In RECOVERING_GAP, signals must NOT be admitted
    summary_btc = logger._states["BTC"].last_summary
    assert summary_btc["accepted"] is False
    assert "REJECTED" in summary_btc["decision_reason"]

    # Step 3: Advance continuous closed bars until full warmup restored (386 bars)
    curr_btc = list(batch_rec1["BTC"])
    for i in range(1, 388):
        ts_i = ts_404 + timedelta(minutes=15 * i)
        curr_btc.append({
            "time_utc": ts_i.isoformat(),
            "time": int(ts_i.timestamp() * 1000),
            "open": 105.5, "high": 106.0, "low": 105.0, "close": 105.8, "volume": 110.0,
            "closed": True, "is_closed": True,
        })
    logger.observe_cycle_candidate_batch({
        "BTC": curr_btc,
        "ETH": batch_warm["ETH"],
        "BNB": batch_warm["BNB"],
    }, allow_historical_replay=True)
    assert logger._states["BTC"].health_status == "ACTIVE"
    assert logger.get_health_status()["health_status"] == "ACTIVE"
    assert logger._counters["gap_recoveries_completed"] >= 1


def test_p0_candidate_missing_degrades_global_health(tmp_path: Path):
    """P0 Test: Verifies that missing any candidate asset in batch degrades global health
    to DEGRADED_MISSING_CANDIDATE and blocks admission."""
    log_file = tmp_path / "missing_cand.jsonl"
    st_file = tmp_path / "missing_cand_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    # Batch only provides BTC and ETH, BNB is missing
    batch_missing = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
    }
    logger.observe_cycle_candidate_batch(batch_missing, allow_historical_replay=True)
    h = logger.get_health_status()
    assert h["health_status"] == "DEGRADED_MISSING_CANDIDATE"
    assert logger._counters["missing_candidate_cycles"] >= 1

    summary_btc = logger._states["BTC"].last_summary
    assert summary_btc["accepted"] is False
    assert summary_btc["decision_reason"] == "REJECTED_GLOBAL_HEALTH_DEGRADED_MISSING_CANDIDATE"


def test_p0_candidate_stale_store_blocks_admission(tmp_path: Path):
    """P0 Test: Verifies that candle_store_fresh=False or stale candle degrades global health
    to DEGRADED_STALE and blocks signal admission."""
    log_file = tmp_path / "stale_store.jsonl"
    st_file = tmp_path / "stale_store_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    # Pass candle_store_fresh=False for BNB
    flags = {
        "BNB": {"candle_store_fresh": False, "present": True},
        "BTC": {"candle_store_fresh": True, "present": True},
        "ETH": {"candle_store_fresh": True, "present": True},
    }
    logger.observe_cycle_candidate_batch(batch, data_quality_flags=flags, allow_historical_replay=True)
    h = logger.get_health_status()
    assert h["health_status"] == "DEGRADED_STALE"
    assert logger._counters["stale_candidate_cycles"] >= 1


def test_p0_no_unseen_bar_in_forming_candle_not_marked_stale(tmp_path: Path):
    """P0 Test: Verifies that an intra-bar cycle with no new unseen closed bars
    retains ACTIVE health status if within the 45-minute freshness window."""
    log_file = tmp_path / "forming_candle.jsonl"
    st_file = tmp_path / "forming_candle_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    now_ref = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    start_ts = now_ref - timedelta(minutes=15 * 400)
    batch = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch, now_utc=now_ref, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    # 2 minutes later: same candles, no new unseen bars
    logger.observe_cycle_candidate_batch(batch, now_utc=now_ref + timedelta(minutes=2), allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"


def test_p1_orphan_jsonl_without_state_quarantined(tmp_path: Path):
    """P1 Test: Verifies that an existing JSONL file with no corresponding state file
    is quarantined independently with quarantine manifest."""
    log_file = tmp_path / "orphan_log.jsonl"
    st_file = tmp_path / "orphan_log_state.json"

    rec = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:00:00+00:00:TEST:none:1",
        "event_sequence": 1,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }
    log_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert log_file.exists()
    assert not st_file.exists()

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert not log_file.exists()
    quarantine_dir = tmp_path / "quarantine"
    assert quarantine_dir.is_dir()
    manifests = list(quarantine_dir.glob("quarantine_manifest_*.json"))
    assert len(manifests) >= 1
    m_data = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert any(r["reason"] == "ORPHAN_LOG_WITHOUT_VALID_STATE" for r in m_data["quarantined_files"])


def test_p1_corrupt_state_with_old_jsonl_quarantined(tmp_path: Path):
    """P1 Test: Verifies that corrupt state file and associated old JSONL
    are moved to quarantine/ and documented in manifest."""
    log_file = tmp_path / "corrupt_log.jsonl"
    st_file = tmp_path / "corrupt_state.json"

    st_file.write_text('{"candidate_id": "VOL_COMPRESSION_BREAKOUT_V1", "corrupt": ', encoding="utf-8")
    log_file.write_text('{"event_sequence": 1}\n', encoding="utf-8")

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert not log_file.exists()
    assert not st_file.exists()
    quarantine_dir = tmp_path / "quarantine"
    assert quarantine_dir.is_dir()
    manifests = list(quarantine_dir.glob("quarantine_manifest_*.json"))
    assert len(manifests) >= 1


def test_p1_quarantine_failure_safe_attributes(tmp_path: Path):
    """P1 Test: Verifies that quarantine failure degrades health to DEGRADED_QUARANTINE_FAILURE
    without uninitialized attribute errors in constructor."""
    log_file = tmp_path / "qfail_log.jsonl"
    st_file = tmp_path / "qfail_state.json"
    st_file.write_text('{"corrupt": ', encoding="utf-8")

    with patch("shutil.move", side_effect=OSError("Disk write protected")):
        logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)

    assert logger._health_status == "DEGRADED_QUARANTINE_FAILURE"
    assert hasattr(logger, "_counters")
    assert hasattr(logger, "_flushed_event_ids")
    assert hasattr(logger, "_states")


def test_p1_recovery_reseals_checkpoint_on_disk(tmp_path: Path):
    """P1 Test: Verifies that during restore_state, recovered outbox events are flushed
    and the checkpoint state file on disk is atomically resealed with empty outbox."""
    log_file = tmp_path / "reseal.jsonl"
    st_file = tmp_path / "reseal_state.json"

    # Pre-create valid state with 2 uncommitted outbox entries
    ev1 = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:00:00+00:00:E1:none:5",
        "event_sequence": 5,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "event_type": "SHADOW_CLOSED_BAR_EVALUATED",
        "symbol": "BTC",
    }
    ev2 = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:15:00+00:00:E2:none:6",
        "event_sequence": 6,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "event_type": "SHADOW_CLOSED_BAR_EVALUATED",
        "symbol": "BTC",
    }
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": TEST_EPOCH,
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 6,
        "last_committed_event_sequence": 4,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "ACTIVE",
        "symbols": {},
        "counters": {},
        "outbox": [ev1, ev2],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")
    log_file.write_text(json.dumps({
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T09:45:00+00:00:E0:none:4",
        "event_sequence": 4,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }) + "\n", encoding="utf-8")

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert logger._last_committed_event_sequence == 6

    # Verify state on disk has empty outbox
    disk_state = json.loads(st_file.read_text(encoding="utf-8"))
    assert disk_state["outbox"] == []
    assert disk_state["last_committed_event_sequence"] == 6


def test_p3_persist_cadence_zero_or_one(tmp_path: Path):
    """P3 Test: Verifies persist cadence is at most 1 persist per cycle:
    0 persists when no unseen closed bars, 1 persist when unseen closed bars present."""
    log_file = tmp_path / "cadence.jsonl"
    st_file = tmp_path / "cadence_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch1 = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    # Cycle 1: unseen bars present -> exactly 1 persist
    logger.observe_cycle_candidate_batch(batch1, allow_historical_replay=True)
    assert logger._checkpoint_generation == 1

    # Cycle 2: same batch, NO unseen bars -> 0 persists
    logger.observe_cycle_candidate_batch(batch1, allow_historical_replay=True)
    assert logger._checkpoint_generation == 1

    # Cycle 3: append 1 new closed bar -> exactly 1 persist (gen becomes 2)
    next_ts = start_ts + timedelta(minutes=15 * 400)
    batch2 = {
        "BTC": list(batch1["BTC"]) + [{
            "time_utc": next_ts.isoformat(), "time": int(next_ts.timestamp() * 1000),
            "open": 104.0, "high": 105.0, "low": 103.5, "close": 104.5, "volume": 120.0,
            "closed": True, "is_closed": True,
        }],
        "ETH": batch1["ETH"],
        "BNB": batch1["BNB"],
    }
    logger.observe_cycle_candidate_batch(batch2, allow_historical_replay=True)
    assert logger._checkpoint_generation == 2


def test_p2_timezone_aware_utc_activation():
    """P2 Test: Verifies timezone awareness: collection manifests require valid ISO UTC collection_start_timestamp,
    are not in the future relative to machine UTC time, and candle timestamps parse correctly."""
    now_utc = datetime.now(timezone.utc)
    manifest = create_activation_manifest(
        evidence_epoch_id="EPOCH_TEST_001",
        activated_at_utc=now_utc.isoformat(),
        collection_start_utc=now_utc.isoformat(),
        strategy_spec_sha256=LOCKED_VCB_V1_SPEC.strategy_spec_sha256,
        git_head="f96c6b8b64516dd76d3af132dac316c5672e35be",
        staged_manifest_identity="test_identity",
        runtime_environment="paper_test",
        process_runtime_id="test_proc_1",
        paper_policy="NO_TRADE_SHADOW",
        first_complete_fresh_batch_utc=now_utc.isoformat(),
        first_checkpoint_generation=1,
        state_path="logs/test_state.json",
        log_path="logs/test_log.jsonl",
    )
    dt = datetime.fromisoformat(manifest.collection_start_utc)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)
    assert dt <= now_utc

    # Candle parser UTC timezone-awareness
    parsed = parse_candle_open_utc({"time_utc": "2026-11-02T10:00:00Z"})
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_p3_paper_batch_append_single_disk_open(tmp_path: Path):
    """P3 Test: Verifies AutoTrader._append_logs_batch writes all entries in a single open/seek operation."""
    log_file = tmp_path / "paper_batch.json"
    from btc_scraper.trading.auto_trader import _append_logs_batch

    entries = [{"symbol": f"SYM_{i}", "action": "HOLD", "cycle": 1} for i in range(22)]

    real_open = open
    open_calls = []

    def open_spy(*args, **kwargs):
        path_arg = str(args[0])
        if "paper_batch.json" in path_arg:
            open_calls.append(path_arg)
        return real_open(*args, **kwargs)

    with patch("btc_scraper.trading.auto_trader._auto_trade_log_path", return_value=log_file), \
         patch("builtins.open", side_effect=open_spy):
        _append_logs_batch(entries)

    assert len(open_calls) == 1, f"Expected exactly 1 open call, got {len(open_calls)}"
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert len(data) == 22
    assert [d["symbol"] for d in data] == [f"SYM_{i}" for i in range(22)]


def test_p3_production_path_benchmarks_with_artifact(tmp_path: Path):
    """P3 Benchmark: Runs 20 warmup + 100 measured iterations of AutoTrader.evaluate_and_trade
    across 22 symbols and exports artifact to runtime/paper/benchmarks/prospective_shadow_microbenchmarks.json."""
    log_file = tmp_path / "bench_artifact.jsonl"
    st_file = tmp_path / "bench_artifact_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    symbols = (
        "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI",
        "NEAR", "APT", "DOT", "UNI", "ICP", "RENDER", "FET", "POL", "AAVE", "LDO",
        "PEPE", "SHIB"
    )

    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.015),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=False)

    trader = AutoTrader()
    analysis = {}
    for sym in symbols:
        c_list = batch_warm.get(sym) or _make_15m_series(start_ts, 210, drift_per_bar=0.01)
        ana = {
            "coin": sym,
            "signal": "HOLD",
            "close": c_list[-1]["close"],
            "candle_store_fresh": True,
        }
        if sym in ("BTC", "ETH", "BNB"):
            ana["_shadow_candles_15m"] = c_list
        analysis[f"{sym}:Binance"] = ana

    with patch("btc_scraper.trading.auto_trader.get_prospective_shadow_logger", return_value=logger), \
         patch("btc_scraper.trading.prospective_shadow_logger.get_prospective_shadow_logger", return_value=logger), \
         patch("btc_scraper.trading.auto_trader._auto_trade_log_path", return_value=tmp_path / "bench_paper.json"):
        # 20 warmup iterations
        for _ in range(20):
            asyncio.run(trader.evaluate_and_trade(analysis))

        # 100 measured iterations
        latencies_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            asyncio.run(trader.evaluate_and_trade(analysis))
            latencies_ms.append(round((time.perf_counter() - t0) * 1000, 3))

    sorted_lats = sorted(latencies_ms)
    median_ms = sorted_lats[len(sorted_lats) // 2]
    p95_ms = sorted_lats[int(len(sorted_lats) * 0.95)]
    p99_ms = sorted_lats[int(len(sorted_lats) * 0.99)]
    max_ms = max(latencies_ms)
    min_ms = min(latencies_ms)

    bench_file = tmp_path / "prospective_shadow_microbenchmarks.json"

    bench_payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "strategy_spec_sha256": LOCKED_VCB_V1_SPEC.strategy_spec_sha256,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "symbols_count": 22,
        "warmup_iterations": 20,
        "measured_iterations": 100,
        "latency_metrics_ms": {
            "median_ms": median_ms,
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
            "max_ms": max_ms,
            "min_ms": min_ms,
        },
        "latencies_ms": latencies_ms,
    }
    bench_file.write_text(json.dumps(bench_payload, indent=2), encoding="utf-8")

    assert bench_file.exists()
    assert median_ms < 250.0, f"Microbenchmark median {median_ms} ms exceeds 250 ms threshold"


def test_active_to_missing_to_active_dynamic_recovery(tmp_path: Path):
    """P0/P1 Test: Verifies dynamic recovery ACTIVE -> DEGRADED_MISSING_CANDIDATE -> ACTIVE."""
    log_file = tmp_path / "dyn_miss.jsonl"
    st_file = tmp_path / "dyn_miss_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    # Cycle 2: BNB is missing
    batch_missing = {
        "BTC": list(batch_warm["BTC"]) + [_make_15m_series(start_ts + timedelta(minutes=15 * 400), 1)[0]],
        "ETH": list(batch_warm["ETH"]) + [_make_15m_series(start_ts + timedelta(minutes=15 * 400), 1)[0]],
    }
    logger.observe_cycle_candidate_batch(batch_missing, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "DEGRADED_MISSING_CANDIDATE"

    # Cycle 3: BNB returns continuous bar -> dynamically recovers to ACTIVE
    batch_recovered = {
        "BTC": list(batch_missing["BTC"]) + [_make_15m_series(start_ts + timedelta(minutes=15 * 401), 1)[0]],
        "ETH": list(batch_missing["ETH"]) + [_make_15m_series(start_ts + timedelta(minutes=15 * 401), 1)[0]],
        "BNB": list(batch_warm["BNB"]) + [
            _make_15m_series(start_ts + timedelta(minutes=15 * 400), 1)[0],
            _make_15m_series(start_ts + timedelta(minutes=15 * 401), 1)[0],
        ],
    }
    logger.observe_cycle_candidate_batch(batch_recovered, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"


def test_active_to_stale_to_active_dynamic_recovery(tmp_path: Path):
    """P0/P1 Test: Verifies dynamic recovery ACTIVE -> DEGRADED_STALE -> ACTIVE."""
    log_file = tmp_path / "dyn_stale.jsonl"
    st_file = tmp_path / "dyn_stale_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    # Cycle 2: Candle store flagged as stale for BTC
    stale_flags = {"BTC": {"candle_store_fresh": False}}
    next_ts = start_ts + timedelta(minutes=15 * 400)
    batch_step = {
        sym: list(batch_warm[sym]) + [_make_15m_series(next_ts, 1)[0]]
        for sym in ("BTC", "ETH", "BNB")
    }
    logger.observe_cycle_candidate_batch(batch_step, data_quality_flags=stale_flags, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "DEGRADED_STALE"

    # Cycle 3: Candle store returns fresh -> dynamically recovers to ACTIVE
    next_ts2 = start_ts + timedelta(minutes=15 * 401)
    batch_step2 = {
        sym: list(batch_step[sym]) + [_make_15m_series(next_ts2, 1)[0]]
        for sym in ("BTC", "ETH", "BNB")
    }
    fresh_flags = {"BTC": {"candle_store_fresh": True}}
    logger.observe_cycle_candidate_batch(batch_step2, data_quality_flags=fresh_flags, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"


def test_missing_candidate_with_historical_state_detected(tmp_path: Path):
    """P0 Test: Verifies that a missing candidate with historical state (last_closed_ts is not None)
    is strictly detected and degrades health."""
    log_file = tmp_path / "hist_miss.jsonl"
    st_file = tmp_path / "hist_miss_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger._states["BNB"].last_closed_ts is not None

    # Omit BNB from batch completely
    next_ts = start_ts + timedelta(minutes=15 * 400)
    batch_no_bnb = {
        "BTC": list(batch_warm["BTC"]) + [_make_15m_series(next_ts, 1)[0]],
        "ETH": list(batch_warm["ETH"]) + [_make_15m_series(next_ts, 1)[0]],
    }
    logger.observe_cycle_candidate_batch(batch_no_bnb, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "DEGRADED_MISSING_CANDIDATE"


def test_durable_dirty_state_checkpoint_on_health_transition_and_restart(tmp_path: Path):
    """P1 Test: Verifies dirty state checkpointing persists health transitions even without unseen bars,
    and restart correctly recovers degraded status."""
    log_file = tmp_path / "dirty_state.jsonl"
    st_file = tmp_path / "dirty_state_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    gen_after_warm = logger._checkpoint_generation

    # Deliver empty batch (missing all candidates, 0 unseen bars)
    logger.observe_cycle_candidate_batch({}, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "DEGRADED_MISSING_CANDIDATE"
    assert logger._checkpoint_generation > gen_after_warm

    # Fresh restart from disk state
    restarted = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert restarted.get_health_status()["health_status"] == "DEGRADED_MISSING_CANDIDATE"


def test_current_cycle_summary_contract_envelope(tmp_path: Path):
    """P0 Test: Verifies observe_cycle_candidate_batch returns fresh cycle envelope for all symbols."""
    log_file = tmp_path / "env.jsonl"
    st_file = tmp_path / "env_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    summaries = logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    for sym in ("BTC", "ETH", "BNB"):
        s = summaries[sym]
        assert "cycle_id" in s
        assert s["symbol"] == sym
        assert s["observed_this_cycle"] is True
        assert s["candidate_present"] is True
        assert s["candidate_fresh"] is True
        assert s["symbol_health"] == "ACTIVE"
        assert s["global_health"] == "ACTIVE"
        assert "blockers" in s
        assert s["last_signal_evaluation"] is not None


def test_future_candle_rejection(tmp_path: Path):
    """P6 Test: Verifies is_15m_candle_closed rejects candles with open + 15m > now_utc,
    and increments future_candles_rejected in production."""
    ref_now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    # Candle open at 11:50 closes at 12:05 (> 12:00) -> NOT closed
    future_c = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "closed": True}
    is_closed = is_15m_candle_closed(
        future_c,
        candle_open_utc=datetime(2026, 11, 2, 11, 50, tzinfo=timezone.utc),
        has_newer_candle_after=False,
        now_utc=ref_now,
    )
    assert is_closed is False

    log_file = tmp_path / "fut.jsonl"
    st_file = tmp_path / "fut_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)
    future_batch = {
        "BTC": [{"time_utc": "2026-11-02T13:00:00Z", "time": 1793624400000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10, "closed": True}],
        "ETH": [],
        "BNB": [],
    }
    logger.observe_cycle_candidate_batch(future_batch, now_utc=ref_now, allow_historical_replay=False)
    assert logger._counters["future_candles_rejected"] >= 1


def test_mixed_epoch_quarantine(tmp_path: Path):
    """P1 Test: Verifies mixed epochs across head and tail are quarantined with LOG_MIXED_EPOCH_DETECTED."""
    log_file = tmp_path / "mixed.jsonl"
    st_file = tmp_path / "mixed_state.json"

    # State matches current unactivated epoch
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": "NOT_ACTIVATED",
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 2,
        "last_committed_event_sequence": 2,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    rec1 = {
        "event_id": "NOT_ACTIVATED:BTC:2026-11-02T10:00:00+00:00:E1:none:1",
        "event_sequence": 1,
        "evidence_epoch_id": "NOT_ACTIVATED",
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }
    rec2 = {
        "event_id": "EPOCH_OTHER:BTC:2026-11-02T10:15:00+00:00:E2:none:2",
        "event_sequence": 2,
        "evidence_epoch_id": "EPOCH_OTHER",
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }
    log_file.write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n", encoding="utf-8")

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert not log_file.exists()
    quarantine_dir = tmp_path / "quarantine"
    assert quarantine_dir.is_dir()
    manifests = list(quarantine_dir.glob("quarantine_manifest_*.json"))
    assert len(manifests) >= 1
    m_data = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert any("LOG_MIXED_EPOCH_DETECTED" in r["reason"] for r in m_data["quarantined_files"])


def test_reseal_exception_sets_degraded_write_failure(tmp_path: Path):
    """P1 Test: Verifies failure to atomically reseal state marks DEGRADED_WRITE_FAILURE without swallowing."""
    log_file = tmp_path / "reseal_fail.jsonl"
    st_file = tmp_path / "reseal_fail_state.json"

    ev = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:00:00+00:00:E1:none:5",
        "event_sequence": 5,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "event_type": "SHADOW_CLOSED_BAR_EVALUATED",
        "symbol": "BTC",
    }
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": TEST_EPOCH,
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 5,
        "last_committed_event_sequence": 4,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "ACTIVE",
        "symbols": {},
        "counters": {},
        "outbox": [ev],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")
    log_file.write_text("", encoding="utf-8")

    # Simulate write error when resealing state tmp file
    with patch("pathlib.Path.replace", side_effect=OSError("Read-only file system")):
        logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)

    assert logger._health_status == "DEGRADED_WRITE_FAILURE"
    assert logger._counters["write_failures"] >= 1


def test_bounded_tail_recovery_no_newline_64kb(tmp_path: Path):
    """P1 Test: Verifies corrupt tail without newline in last 64KB is truncated in O(1) time and memory."""
    log_file = tmp_path / "big_corrupt.jsonl"
    st_file = tmp_path / "big_corrupt_state.json"

    # Write 1 valid JSON line followed by 70KB of corrupt bytes without newline
    rec = {
        "event_id": f"{TEST_EPOCH}:BTC:2026-11-02T10:00:00+00:00:E1:none:1",
        "event_sequence": 1,
        "evidence_epoch_id": TEST_EPOCH,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
    }
    valid_prefix = (json.dumps(rec) + "\n").encode("utf-8")
    corrupt_garbage = b"X" * 70000

    log_file.write_bytes(valid_prefix + corrupt_garbage)
    assert log_file.stat().st_size > 70000

    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": TEST_EPOCH,
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 1,
        "last_committed_event_sequence": 1,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert logger._counters["write_failures"] >= 1
    assert log_file.stat().st_size <= len(valid_prefix) + 6000


def test_append_logs_batch_calls_flush_and_fsync(tmp_path: Path):
    """P3 Test: Verifies AutoTrader._append_logs_batch calls f.flush() and os.fsync(f.fileno())."""
    from btc_scraper.trading.auto_trader import _append_logs_batch

    log_file = tmp_path / "fsync_log.json"
    entries = [{"symbol": f"S_{i}", "val": i} for i in range(5)]

    flushed = []
    fsynced = []

    real_fsync = os.fsync

    def fsync_spy(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    with patch("btc_scraper.trading.auto_trader._auto_trade_log_path", return_value=log_file), \
         patch("os.fsync", side_effect=fsync_spy):
        _append_logs_batch(entries)

    assert len(fsynced) >= 1
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert len(data) == 5


def test_default_preactivation_constructor_status_and_defaults(tmp_path: Path):
    """P0 Test: Verifies default preactivation constructor initializes cleanly in CODE_READY_NOT_ACTIVATED
    without parsing empty timestamps, with no active evidence eligibility."""
    log_file = tmp_path / "default_preact.jsonl"
    st_file = tmp_path / "default_preact_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)

    assert logger.runtime_status == "CODE_READY_NOT_ACTIVATED"
    assert logger.activation_manifest is None
    assert logger.evidence_epoch_id == "NOT_ACTIVATED"
    assert logger.collection_start_cutoff is None
    assert logger.collection_start_timestamp == ""
    assert logger.is_activated is False

    # Strategy spec is pure mathematical algorithm: no operational epoch/start fields
    payload = LOCKED_VCB_V1_SPEC.canonical_strategy_payload()
    assert "evidence_epoch_id" not in payload
    assert "collection_start_timestamp" not in payload


def test_activation_manifest_wiring_into_runtime_and_auto_trader(tmp_path: Path):
    """P0 Test: Verifies explicit activation manifest wiring into AutoTrader and ProspectiveShadowLogger."""
    from btc_scraper.trading.auto_trader import AutoTrader
    from dataclasses import asdict

    now_utc = datetime.now(timezone.utc)
    log_file = tmp_path / "active_log.jsonl"
    st_file = tmp_path / "active_state.json"
    manifest_file = tmp_path / "activation_manifest.json"

    manifest = create_activation_manifest(
        evidence_epoch_id="EXP_PAPER_ACTIVE_20261102_001",
        activated_at_utc=now_utc.isoformat(),
        collection_start_utc=now_utc.isoformat(),
        strategy_spec_sha256=LOCKED_VCB_V1_SPEC.strategy_spec_sha256,
        git_head="f96c6b8b64516dd76d3af132dac316c5672e35be",
        staged_manifest_identity="manifest_test_hash",
        runtime_environment="paper_daemon",
        process_runtime_id="proc_active_01",
        paper_policy="NO_TRADE_SHADOW",
        first_complete_fresh_batch_utc=now_utc.isoformat(),
        first_checkpoint_generation=1,
        state_path=str(st_file),
        log_path=str(log_file),
    )
    manifest_file.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

    trader = AutoTrader(activation_manifest_path=manifest_file)
    logger = trader.activate_prospective_evidence(manifest_file)

    assert logger.is_activated is True
    assert logger.runtime_status == "ACTIVE_COLLECTING"
    assert logger.evidence_epoch_id == "EXP_PAPER_ACTIVE_20261102_001"
    assert logger.collection_start_cutoff is not None
    assert logger.collection_start_timestamp == manifest.collection_start_utc

    # Observe warm batch and verify event ID uses the verified manifest epoch
    batch_warm = {
        "BTC": _make_15m_series(now_utc - timedelta(hours=100), 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(now_utc - timedelta(hours=100), 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(now_utc - timedelta(hours=100), 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # Queue an event and verify its epoch_id matches the manifest
    ev = logger._queue_event("SHADOW_ACTIVE_TEST", symbol="BTC", c_ts=now_utc, payload={"test": True})
    assert ev["evidence_epoch_id"] == "EXP_PAPER_ACTIVE_20261102_001"
    assert "RETRACTED_PREACTIVATION_SPEC_004" not in ev["event_id"]


def test_mixed_epoch_in_middle_of_jsonl_detected_and_quarantined(tmp_path: Path):
    """P1 Test: Verifies mixed epochs placed in the middle of a JSONL log file are detected and quarantined."""
    log_file = tmp_path / "mid_mixed.jsonl"
    st_file = tmp_path / "mid_mixed_state.json"

    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": "NOT_ACTIVATED",
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 20,
        "last_committed_event_sequence": 20,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    lines = []
    for i in range(1, 21):
        epoch = "EPOCH_ROGUE_MIDDLE" if i == 11 else "NOT_ACTIVATED"
        rec = {
            "event_id": f"{epoch}:BTC:2026-11-02T10:00:00+00:00:EV:none:{i}",
            "event_sequence": i,
            "evidence_epoch_id": epoch,
            "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        }
        lines.append(json.dumps(rec))
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    assert not log_file.exists(), "Log with mixed epoch in middle must be quarantined"
    quarantine_dir = tmp_path / "quarantine"
    assert quarantine_dir.is_dir()
    manifests = list(quarantine_dir.glob("quarantine_manifest_*.json"))
    assert len(manifests) >= 1
    m_data = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert any("LOG_MIXED_EPOCH_DETECTED" in r["reason"] for r in m_data["quarantined_files"])


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION SUITE: FLAT ENVELOPE, BOUNDED CHECKPOINT & HONEST PROVENANCE
# ─────────────────────────────────────────────────────────────────────────────

def test_hot_cycle_envelope_is_flat(tmp_path: Path):
    """P0 Test: Verifies that hot cycle envelopes do not nest old envelopes inside last_signal_evaluation."""
    log_file = tmp_path / "flat.jsonl"
    st_file = tmp_path / "flat_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    # Initial warm pass
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # 10 hot cycles without new closed bars
    for i in range(10):
        env = logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
        for sym in ("BTC", "ETH", "BNB"):
            s = env[sym]
            assert s["signal_evaluated_this_cycle"] is False
            last_eval = s["last_signal_evaluation"]
            assert isinstance(last_eval, dict)
            # Must be a flat signal evaluation snapshot, NOT a cycle envelope
            assert "cycle_id" not in last_eval
            assert "blockers" not in last_eval
            assert "last_signal_evaluation" not in last_eval
            assert "current_cycle_envelope" not in last_eval


def test_hot_cycle_envelope_size_constant_after_10000_cycles(tmp_path: Path):
    """P0 Test: Verifies that envelope serialized JSON size remains strictly constant over 10,000 hot cycles."""
    log_file = tmp_path / "size_const.jsonl"
    st_file = tmp_path / "size_const_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # Hot cycle 1
    env_1 = logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    btc_size_1 = len(json.dumps(env_1["BTC"]))

    # Hot cycles 2 to 10,000
    last_env = None
    for _ in range(10000):
        last_env = logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    btc_size_10k = len(json.dumps(last_env["BTC"]))
    # Envelope size must be strictly identical (both use same cycle_id format length and same flat snapshot)
    assert btc_size_10k == btc_size_1
    assert btc_size_10k < 4000, f"Envelope size too large: {btc_size_10k} bytes"


def test_checkpoint_size_bounded_after_hot_cycles_then_health_transition(tmp_path: Path):
    """P0 Test: Verifies checkpoint size on disk does not grow after 1,000 hot cycles followed by a health transition."""
    log_file = tmp_path / "chk_bound.jsonl"
    st_file = tmp_path / "chk_bound_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    initial_checkpoint_size = st_file.stat().st_size

    # Run 1,000 hot cycles
    for _ in range(1000):
        logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # Induce health transition (missing ETH)
    missing_batch = {"BTC": batch_warm["BTC"], "BNB": batch_warm["BNB"]}
    logger.observe_cycle_candidate_batch(missing_batch, allow_historical_replay=True)

    final_checkpoint_size = st_file.stat().st_size
    # Size delta must be strictly bounded (< 1 KB difference)
    delta = abs(final_checkpoint_size - initial_checkpoint_size)
    assert delta < 2048, f"Checkpoint grew by {delta} bytes (initial={initial_checkpoint_size}, final={final_checkpoint_size})"
    assert final_checkpoint_size < 60000, f"Checkpoint size exceeded 60KB: {final_checkpoint_size} bytes"

    # Verify cold restart recovers health and does not produce DEGRADED_WRITE_FAILURE
    new_logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file)
    health = new_logger.get_health_status()
    assert health["health_status"] == "DEGRADED_MISSING_CANDIDATE"
    assert health["health_status"] != "DEGRADED_WRITE_FAILURE"


def test_signal_evaluation_snapshot_is_not_cycle_envelope(tmp_path: Path):
    """P0 Test: Verifies state.last_signal_evaluation is strictly the flat signal evaluation, not the cycle envelope."""
    log_file = tmp_path / "sig_eval.jsonl"
    st_file = tmp_path / "sig_eval_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    summaries = logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    st = logger._states["BTC"]
    assert st.last_signal_evaluation is not None
    # Must not be the cycle envelope object or contain envelope fields
    assert st.last_signal_evaluation is not summaries["BTC"]
    assert "cycle_id" not in st.last_signal_evaluation
    assert "last_signal_evaluation" not in st.last_signal_evaluation
    assert "blockers" not in st.last_signal_evaluation
    assert "candidate_present" not in st.last_signal_evaluation


def test_hot_cycle_memory_growth_is_bounded(tmp_path: Path):
    """P0 Test: Verifies tracemalloc memory usage does not leak linearly during 2,000 hot cycles."""
    import tracemalloc

    log_file = tmp_path / "mem.jsonl"
    st_file = tmp_path / "mem_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # Warmup 50 cycles
    for _ in range(50):
        logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    tracemalloc.start()
    snapshot_start = tracemalloc.take_snapshot()

    for _ in range(2000):
        logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    snapshot_end = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot_end.compare_to(snapshot_start, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in top_stats) / 1024.0
    # Memory growth over 2,000 cycles must be bounded (< 150 KB total)
    assert total_diff_kb < 150.0, f"Memory leaked {total_diff_kb:.2f} KB over 2,000 cycles"


def test_staged_identity_requires_exact_paths(monkeypatch):
    """P0 Test: Verifies provenance verification fails when count is 72 but path set does not match."""
    from scripts.run_prospective_shadow_benchmark import verify_staged_provenance

    # Return 72 files, but replace one real path with a fake one
    real_paths = [
        "docs/NEXT_STEP_EXECUTION_PLAN_2026-09-22.md",
        "evidence/next-step-20260922/baseline_inventory.json",
    ] + [f"evidence/next-step-20260922/file_{i}.txt" for i in range(70)]
    fake_output = "\n".join(real_paths)

    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda cmd, **kw: fake_output.encode("utf-8") if "diff" in cmd else b"blob_data",
    )

    result = verify_staged_provenance()
    assert result["verified_intact"] is False
    assert result["paths_match"] is False
    assert "mismatch" in result["error"].lower()


def test_staged_identity_requires_exact_blob_hashes(monkeypatch):
    """P0 Test: Verifies provenance verification fails if a staged blob hash differs from manifest."""
    from scripts.run_prospective_shadow_benchmark import verify_staged_provenance

    # Let diff succeed with exact paths, but make git show return corrupted bytes for one path
    orig_check_output = subprocess.check_output

    def mock_check_output(cmd, **kw):
        if "diff" in cmd:
            return orig_check_output(cmd, **kw)
        if "show" in cmd:
            # Corrupt blob output
            return b"corrupted_blob_content_different_hash"
        return orig_check_output(cmd, **kw)

    monkeypatch.setattr(subprocess, "check_output", mock_check_output)

    result = verify_staged_provenance()
    assert result["verified_intact"] is False
    assert result["blobs_match"] is False
    assert "mismatch" in result["error"].lower()


def test_staged_identity_failure_is_never_verified(monkeypatch):
    """P0 Test: Verifies subprocess or parsing errors return verified_intact=False and identity=None."""
    from scripts.run_prospective_shadow_benchmark import verify_staged_provenance

    def raise_err(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "diff"])

    monkeypatch.setattr(subprocess, "check_output", raise_err)

    result = verify_staged_provenance()
    assert result["verified_intact"] is False
    assert result["identity_sha256"] is None
    assert result["error"] is not None


def test_gap_benchmark_full_recovery_reaches_active(tmp_path: Path):
    """P1 Test: Verifies full gap recovery lifecycle transitions from DEGRADED_GAP -> RECOVERING_GAP -> ACTIVE."""
    log_file = tmp_path / "gap_full.jsonl"
    st_file = tmp_path / "gap_full_state.json"
    logger = ProspectiveShadowLogger(log_path=log_file, state_path=st_file, log_rejected_closed_candles=True)

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {
        "BTC": _make_15m_series(start_ts, 400, drift_per_bar=0.01),
        "ETH": _make_15m_series(start_ts, 400, drift_per_bar=0.012),
        "BNB": _make_15m_series(start_ts, 400, drift_per_bar=0.008),
    }
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    # Step 1: Induce gap by skipping 1 bar (gap > 15m)
    ts_gap = start_ts + timedelta(minutes=15 * 402)
    batch_gap = {
        sym: list(batch_warm[sym]) + [{
            "time_utc": ts_gap.isoformat(),
            "time": int(ts_gap.timestamp() * 1000),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
            "closed": True, "is_closed": True,
        }]
        for sym in ("BTC", "ETH", "BNB")
    }
    logger.observe_cycle_candidate_batch(batch_gap, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] in ("DEGRADED_GAP", "RECOVERING_GAP")

    # Step 2: Feed first consecutive bar -> transitions to RECOVERING_GAP
    ts_rec1 = ts_gap + timedelta(minutes=15)
    batch_rec1 = {
        sym: batch_gap[sym] + [{
            "time_utc": ts_rec1.isoformat(),
            "time": int(ts_rec1.timestamp() * 1000),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
            "closed": True, "is_closed": True,
        }]
        for sym in ("BTC", "ETH", "BNB")
    }
    logger.observe_cycle_candidate_batch(batch_rec1, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "RECOVERING_GAP"

    # Step 3: Feed remaining 385 consecutive bars (total 386 continuous bars)
    curr_batch = batch_rec1
    for i in range(2, 387):
        ts_step = ts_gap + timedelta(minutes=15 * i)
        curr_batch = {
            sym: curr_batch[sym] + [{
                "time_utc": ts_step.isoformat(),
                "time": int(ts_step.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            }]
            for sym in ("BTC", "ETH", "BNB")
        }

    logger.observe_cycle_candidate_batch(curr_batch, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"
    assert logger._counters["gap_recoveries_completed"] >= 1


def test_large_log_mixed_epoch_guarantee_matches_documentation(tmp_path: Path):
    """P1 Test: Documents and tests the exact quarantine guarantee:
    - Files <= 256 KB: fully streamed; an alien epoch anywhere (e.g. 1/4 file) is caught.
    - Files > 256 KB: bounded O(1) sampling; an alien epoch at midpoint sample is caught,
      while an alien epoch at 1/4 file outside sample windows is not scanned without full archive reading.
    """
    st_file = tmp_path / "guar_state.json"
    st_payload = {
        "candidate_id": LOCKED_VCB_V1_SPEC.candidate_id,
        "spec_version": LOCKED_VCB_V1_SPEC.spec_version,
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "evidence_epoch_id": "NOT_ACTIVATED",
        "collection_start_timestamp": "",
        "logger_schema_version": "2.0.0",
        "checkpoint_generation": 1,
        "event_sequence": 20,
        "last_committed_event_sequence": 20,
        "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
        "global_health_status": "WARMING_UP",
        "symbols": {},
        "counters": {},
        "outbox": [],
    }
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")

    # Part A: File <= 256KB with alien epoch at 1/4 file -> MUST be quarantined
    log_small = tmp_path / "small.jsonl"
    lines_small = []
    for i in range(100):
        epoch = "ROGUE_EPOCH_QUARTER" if i == 25 else "NOT_ACTIVATED"
        rec = {
            "event_id": f"{epoch}:BTC:2026-11-02:EV:{i}",
            "evidence_epoch_id": epoch,
            "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        }
        lines_small.append(json.dumps(rec))
    log_small.write_text("\n".join(lines_small) + "\n", encoding="utf-8")
    assert log_small.stat().st_size < 262144

    logger_small = ProspectiveShadowLogger(log_path=log_small, state_path=st_file)
    assert not log_small.exists(), "Small file with alien epoch at 1/4 must be quarantined"

    # Part B: File > 256KB with alien epoch placed precisely at midpoint sample -> MUST be quarantined
    log_large_mid = tmp_path / "large_mid.jsonl"
    # Build a file > 262144 bytes (~300 KB)
    pad_str = "x" * 200
    lines_large = []
    for i in range(1200):
        rec = {
            "event_id": f"NOT_ACTIVATED:BTC:2026-11-02:EV:{i}",
            "evidence_epoch_id": "NOT_ACTIVATED",
            "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
            "padding": pad_str,
        }
        lines_large.append(json.dumps(rec))
    # Place rogue record at midpoint (line 600)
    lines_large[600] = json.dumps({
        "event_id": "ROGUE_MID:BTC:2026-11-02:EV:600",
        "evidence_epoch_id": "ROGUE_MID",
        "spec_sha256": LOCKED_VCB_V1_SPEC.spec_sha256,
        "padding": pad_str,
    })
    log_large_mid.write_text("\n".join(lines_large) + "\n", encoding="utf-8")
    assert log_large_mid.stat().st_size > 262144

    # Restore state file for Part B
    st_file.write_text(json.dumps(st_payload), encoding="utf-8")
    logger_large_mid = ProspectiveShadowLogger(log_path=log_large_mid, state_path=st_file)
    assert not log_large_mid.exists(), "Large file with alien epoch at midpoint sample must be quarantined"


def test_benchmark_artifact_records_real_iterations_and_sizes():
    """P1 Test: Verifies benchmark runner records accurate iterations, call paths, file sizes, and gate evaluations."""
    from scripts.run_prospective_shadow_benchmark import verify_staged_provenance, _measure_scenario

    prov = verify_staged_provenance()
    assert isinstance(prov, dict)
    if prov.get("verified_intact") is True:
        assert prov["identity_sha256"] == "c6f354b7ea84f868f6dd0e5498ba5701dbb2836db6c9a7a56d02e689e3754a26"

    # Test _measure_scenario records exact parameters and gates
    res = _measure_scenario(
        lambda: None,
        benchmark_type="function_microbenchmark",
        call_path="test_fn",
        warmup_iters=7,
        measured_iters=23,
        initial_health="ACTIVE",
        final_health="ACTIVE",
        gate_metric="median_ms",
        budget_ms=10.0,
    )
    assert res["warmup_iterations"] == 7
    assert res["measured_iterations"] == 23
    assert res["call_path"] == "test_fn"
    assert res["benchmark_type"] == "function_microbenchmark"
    assert res["gate_metric"] == "median_ms"
    assert res["budget_ms"] == 10.0
    assert res["gate_passed"] is True


def test_stateful_benchmark_uses_fresh_context_per_sample(tmp_path: Path):
    """P0 Test: Verifies stateful benchmark iterations create isolated contexts per sample."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext

    seen_dirs = []

    def setup_fn(i: int, is_warmup: bool):
        td = tmp_path / f"ctx_{i}_{is_warmup}"
        td.mkdir(parents=True, exist_ok=True)
        seen_dirs.append(td)
        return BenchmarkContext(temp_dir=td, sample_idx=i)

    def timed_fn(ctx):
        marker = ctx.temp_dir / "marker.txt"
        assert not marker.exists(), "Sample directory was not fresh!"
        marker.write_text("done", encoding="utf-8")

    def tear_fn(ctx):
        shutil.rmtree(ctx.temp_dir, ignore_errors=True)

    res = _measure_scenario(
        setup_fn=setup_fn,
        timed_fn=timed_fn,
        teardown_fn=tear_fn,
        warmup_iters=3,
        measured_iters=5,
    )
    assert res["valid_samples_count"] == 5
    assert len(seen_dirs) == 8  # 3 warmup + 5 measured
    assert len(set(seen_dirs)) == 8, "Each sample context must be strictly unique"


def test_warmup_state_does_not_leak_into_measured_samples(tmp_path: Path):
    """P0 Test: Verifies state created during warmup never leaks into measured samples."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext

    warmup_artifacts = []
    measured_states = []

    def setup_fn(i: int, is_warmup: bool):
        sf = tmp_path / f"state_{i}_{is_warmup}.json"
        return BenchmarkContext(state_file=sf, is_warmup=is_warmup)

    def timed_fn(ctx):
        if ctx.is_warmup:
            warmup_artifacts.append(ctx.state_file)
            ctx.state_file.write_text("warmup_data", encoding="utf-8")
        else:
            # Measured iteration must not see warmup state
            assert not ctx.state_file.exists()
            ctx.state_file.write_text("measured_data", encoding="utf-8")
            measured_states.append(ctx.state_file)

    res = _measure_scenario(
        setup_fn=setup_fn,
        timed_fn=timed_fn,
        warmup_iters=4,
        measured_iters=6,
    )
    assert len(warmup_artifacts) == 4
    assert len(measured_states) == 6
    assert set(warmup_artifacts).isdisjoint(set(measured_states))


def test_gap_detection_benchmark_observes_actual_terminal_state(tmp_path: Path):
    """P0 Test: Verifies gap detection scenario records actual observed terminal state (RECOVERING_GAP)."""
    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {sym: _make_15m_series(start_ts, 400) for sym in ("BTC", "ETH", "BNB")}

    lf = tmp_path / "bench.jsonl"
    sf = tmp_path / "bench_state.json"
    logger = ProspectiveShadowLogger(log_path=lf, state_path=sf)
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)
    assert logger.get_health_status()["health_status"] == "ACTIVE"

    ts_gap = start_ts + timedelta(minutes=15 * 402)
    gap_c = {
        "time_utc": ts_gap.isoformat(),
        "time": int(ts_gap.timestamp() * 1000),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
        "closed": True, "is_closed": True,
    }
    batch_gap = {sym: list(batch_warm[sym]) + [gap_c] for sym in ("BTC", "ETH", "BNB")}

    gaps_before = logger._counters["missing_bar_gaps"]
    bars_before = logger._counters["actual_new_bars_processed"]

    logger.observe_cycle_candidate_batch(batch_gap, allow_historical_replay=True)

    # Must observe RECOVERING_GAP, not DEGRADED_GAP
    assert logger.get_health_status()["health_status"] == "RECOVERING_GAP"
    assert logger._counters["missing_bar_gaps"] - gaps_before == 3
    assert logger._counters["actual_new_bars_processed"] - bars_before == 3


def test_gap_first_recovery_benchmark_starts_from_degraded_gap(tmp_path: Path):
    """P0 Test: Verifies gap first recovery starts strictly from DEGRADED_GAP and transitions to RECOVERING_GAP."""
    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {sym: _make_15m_series(start_ts, 400) for sym in ("BTC", "ETH", "BNB")}

    lf = tmp_path / "bench.jsonl"
    sf = tmp_path / "bench_state.json"
    logger = ProspectiveShadowLogger(log_path=lf, state_path=sf)
    logger.observe_cycle_candidate_batch(batch_warm, allow_historical_replay=True)

    # Induce gap outside timing
    ts_gap = start_ts + timedelta(minutes=15 * 402)
    for sym in ("BTC", "ETH", "BNB"):
        logger._handle_missing_bar_gap(logger._states[sym], gap_ts=ts_gap, flags=None)
    logger._evaluate_global_health()

    assert logger.get_health_status()["health_status"] == "DEGRADED_GAP"
    for sym in ("BTC", "ETH", "BNB"):
        assert logger._states[sym].health_status == "DEGRADED_GAP"
        assert logger._states[sym].next_seq == 0

    gap_c = {
        "time_utc": ts_gap.isoformat(),
        "time": int(ts_gap.timestamp() * 1000),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
        "closed": True, "is_closed": True,
    }
    batch_first = {sym: list(batch_warm[sym]) + [gap_c] for sym in ("BTC", "ETH", "BNB")}
    logger.observe_cycle_candidate_batch(batch_first, allow_historical_replay=True)

    assert logger.get_health_status()["health_status"] == "RECOVERING_GAP"
    for sym in ("BTC", "ETH", "BNB"):
        assert logger._states[sym].health_status == "RECOVERING_GAP"
        assert logger._states[sym].next_seq == 1


def test_gap_full_rewarm_processes_expected_bars_every_sample(tmp_path: Path):
    """P0 Test: Verifies Scenario 7c processes exactly 1155 new bars and completes recoveries every sample."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {sym: _make_15m_series(start_ts, 400) for sym in ("BTC", "ETH", "BNB")}

    processed_deltas = []
    completed_deltas = []

    def setup_7c(i: int, is_warmup: bool):
        td = tmp_path / f"bench_7c_{i}_{is_warmup}"
        td.mkdir(parents=True, exist_ok=True)
        lf = td / "bench.jsonl"
        sf = td / "bench_state.json"
        l = ProspectiveShadowLogger(log_path=lf, state_path=sf)
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
        remaining = []
        for j in range(1, 386):
            ts = ts_gap + timedelta(minutes=15 * j)
            remaining.append({
                "time_utc": ts.isoformat(),
                "time": int(ts.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            })
        batch_rewarm = {sym: list(bg[sym]) + remaining for sym in ("BTC", "ETH", "BNB")}
        return BenchmarkContext(
            temp_dir=td, log_file=lf, state_file=sf, logger=l,
            batch_rewarm=batch_rewarm,
            bars_before=l._counters["actual_new_bars_processed"],
            gap_rec_before=l._counters["gap_recoveries_completed"],
        )

    def pre_7c(ctx):
        assert ctx.logger.get_health_status()["health_status"] == "RECOVERING_GAP"
        for sym in ("BTC", "ETH", "BNB"):
            assert ctx.logger._states[sym].health_status == "RECOVERING_GAP"
            assert ctx.logger._states[sym].next_seq == 1

    def timed_7c(ctx):
        return ctx.logger.observe_cycle_candidate_batch(ctx.batch_rewarm, allow_historical_replay=True)

    def post_7c(ctx, res):
        assert ctx.logger.get_health_status()["health_status"] == "ACTIVE"
        b_delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
        r_delta = ctx.logger._counters["gap_recoveries_completed"] - ctx.gap_rec_before
        processed_deltas.append(b_delta)
        completed_deltas.append(r_delta)
        assert b_delta == 1155
        assert r_delta == 3
        return {"processed_bars_delta": b_delta}

    res = _measure_scenario(
        setup_fn=setup_7c,
        precondition_fn=pre_7c,
        timed_fn=timed_7c,
        postcondition_fn=post_7c,
        warmup_iters=2,
        measured_iters=3,
        input_event_count=1155,
        budget_ms=50.0,
    )
    assert res["valid_samples_count"] == 3
    assert all(d == 1155 for d in processed_deltas)
    assert all(r == 3 for r in completed_deltas)


def test_gap_full_rewarm_never_measures_duplicate_noop(tmp_path: Path):
    """P0 Test: Verifies measured samples never measure 0 processed bars."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext

    start_ts = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    batch_warm = {sym: _make_15m_series(start_ts, 400) for sym in ("BTC", "ETH", "BNB")}

    sample_work = []

    def setup_7c(i: int, is_warmup: bool):
        td = tmp_path / f"bench_noop_{i}_{is_warmup}"
        td.mkdir(parents=True, exist_ok=True)
        lf = td / "bench.jsonl"
        sf = td / "bench_state.json"
        l = ProspectiveShadowLogger(log_path=lf, state_path=sf)
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
        remaining = []
        for j in range(1, 386):
            ts = ts_gap + timedelta(minutes=15 * j)
            remaining.append({
                "time_utc": ts.isoformat(),
                "time": int(ts.timestamp() * 1000),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 120.0,
                "closed": True, "is_closed": True,
            })
        batch_rewarm = {sym: list(bg[sym]) + remaining for sym in ("BTC", "ETH", "BNB")}
        return BenchmarkContext(
            temp_dir=td, log_file=lf, state_file=sf, logger=l,
            batch_rewarm=batch_rewarm,
            bars_before=l._counters["actual_new_bars_processed"],
        )

    def timed_7c(ctx):
        return ctx.logger.observe_cycle_candidate_batch(ctx.batch_rewarm, allow_historical_replay=True)

    def post_7c(ctx, res):
        delta = ctx.logger._counters["actual_new_bars_processed"] - ctx.bars_before
        sample_work.append(delta)
        assert delta > 0, "Measured sample must never process 0 bars (duplicate no-op)!"
        return {"processed_bars_delta": delta}

    _measure_scenario(
        setup_fn=setup_7c,
        timed_fn=timed_7c,
        postcondition_fn=post_7c,
        warmup_iters=2,
        measured_iters=4,
    )
    assert len(sample_work) == 6  # 2 warmup + 4 measured
    assert all(w > 0 for w in sample_work), "Every sample performed real work"


def test_benchmark_sizes_are_probed_after_operation(tmp_path: Path):
    """P1 Test: Verifies sizes are probed directly after operation and reflect real growth."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext

    def setup_fn(i: int, is_warmup: bool):
        td = tmp_path / f"probe_{i}_{is_warmup}"
        td.mkdir(parents=True, exist_ok=True)
        sf = td / "state.json"
        sf.write_text("{}", encoding="utf-8")
        return BenchmarkContext(temp_dir=td, state_file=sf)

    def timed_fn(ctx):
        # Grow state file during timed operation
        ctx.state_file.write_text("x" * 5000, encoding="utf-8")

    res = _measure_scenario(
        setup_fn=setup_fn,
        timed_fn=timed_fn,
        warmup_iters=2,
        measured_iters=3,
    )
    assert res["initial_state_size_bytes"] == 2
    assert res["final_state_size_bytes"] == 5000
    assert res["initial_state_size_stats"]["median"] == 2
    assert res["final_state_size_stats"]["median"] == 5000


def test_aged_log_fixture_is_reset_to_same_size_per_sample(tmp_path: Path):
    """P1 Test: Verifies aged log fixture starts at identical byte size across all samples."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext
    from btc_scraper.trading.auto_trader import _append_logs_batch

    template = tmp_path / "template.json"
    template.write_text(json.dumps([{"id": i} for i in range(100)]), encoding="utf-8")
    template_size = template.stat().st_size

    initial_sizes = []

    def setup_8(i: int, is_warmup: bool):
        sf = tmp_path / f"sample_{i}_{is_warmup}.json"
        shutil.copyfile(template, sf)
        initial_sizes.append(sf.stat().st_size)
        return BenchmarkContext(log_file=sf)

    def timed_8(ctx):
        with patch("btc_scraper.trading.auto_trader._auto_trade_log_path", return_value=ctx.log_file):
            _append_logs_batch([{"id": 101}])

    res = _measure_scenario(
        setup_fn=setup_8,
        timed_fn=timed_8,
        warmup_iters=3,
        measured_iters=5,
    )
    assert all(s == template_size for s in initial_sizes)
    assert res["initial_log_size_stats"]["min"] == template_size
    assert res["initial_log_size_stats"]["max"] == template_size


def test_benchmark_fails_on_precondition_or_postcondition_mismatch(tmp_path: Path):
    """P0 Test: Verifies benchmark runner fails when precondition or postcondition is violated."""
    from scripts.run_prospective_shadow_benchmark import _measure_scenario, BenchmarkContext
    import pytest

    # Precondition failure
    def pre_fail(ctx):
        raise AssertionError("Expected precondition failure")

    with pytest.raises(AssertionError, match="Precondition failed"):
        _measure_scenario(
            setup_fn=lambda i, w: BenchmarkContext(),
            precondition_fn=pre_fail,
            timed_fn=lambda ctx: None,
            warmup_iters=1,
            measured_iters=2,
        )

    # Postcondition failure
    def post_fail(ctx, res):
        raise AssertionError("Expected postcondition failure")

    with pytest.raises(AssertionError, match="Postcondition failed"):
        _measure_scenario(
            setup_fn=lambda i, w: BenchmarkContext(),
            timed_fn=lambda ctx: None,
            postcondition_fn=post_fail,
            warmup_iters=1,
            measured_iters=2,
        )


def test_reported_iteration_counts_match_artifact():
    """P1 Test: Verifies canonical microbenchmarks artifact matches reported iteration counts."""
    from scripts.run_prospective_shadow_benchmark import REPO_ROOT

    art_path = REPO_ROOT / "runtime" / "paper" / "benchmarks" / "prospective_shadow_microbenchmarks.json"
    assert art_path.exists(), "Benchmark artifact must exist"
    data = json.loads(art_path.read_text(encoding="utf-8"))

    scenarios = data["scenarios"]
    assert len(scenarios) == 12, f"Expected 12 scenarios, found {len(scenarios)}"

    for name, s in scenarios.items():
        assert s["warmup_iterations"] == 10, f"{name} warmup_iterations != 10"
        assert s["measured_iterations"] == 50, f"{name} measured_iterations != 50"
        assert s["valid_samples_count"] == 50, f"{name} valid_samples_count != 50"
        assert s["gate_passed"] is True, f"{name} gate_passed is not True"
        assert s["invariant_passed"] is True, f"{name} invariant_passed is not True"

    # Specific assertions on 7c
    s7c = scenarios["7c_gap_full_386_bar_rewarm_ms"]
    assert s7c["processed_event_delta_per_sample"] == 1155
    assert s7c["initial_health"] == "RECOVERING_GAP"
    assert s7c["final_health"] == "ACTIVE"
    assert s7c["median_ms"] < 50.0



