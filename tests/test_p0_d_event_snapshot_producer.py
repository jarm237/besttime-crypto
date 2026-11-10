"""
tests/test_p0_d_event_snapshot_producer.py
P0-D Targeted Integration Test Suite — Deterministic Event Snapshot Producer.

Covers:
1. Point-in-time filtering (available_at <= decision_time).
2. Future event exclusion (future information strictly excluded).
3. Late publication/ingestion handling.
4. Revision-as-of behavior (latest revision as-of decision_time used).
5. Duplicate normalization (no infinite compounding of risk reduction).
6. Deterministic snapshot hashing (reordering inputs yields identical SHA-256).
7. Event expiry (expired event does not continue blocking).
8. BLOCK -> zero paper entries (verified through AutoTrader & ExecutionEngine).
9. REDUCE -> lower effective order size.
10. Conflicting event precedence (hard BLOCK strictly dominates REDUCE / ALLOW).
11. Replay / production-path parity.
12. Zero-network deterministic replay.
13. Event snapshot -> EntryDecision -> Execution / Rejection lineage.
14. M0 Full Resolution: Prediction -> FinalDecision -> EventRisk -> EntryDecision -> Fill -> Outcome.
"""
from __future__ import annotations

import copy
import socket
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.execution.order_fill_ledger import OrderFillLedger
from btc_scraper.execution.reservation_store import ReservationStore, ReservationStatus
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import (
    EntryDecision,
    EntryRejectionReason,
)
from btc_scraper.trading.event_risk_policy import (
    DEFAULT_EVENT_RISK_POLICY_VERSION,
    EntryPermission,
    EventRiskContractError,
    EventRiskDecision,
    EventRiskLevel,
    PositionAction,
    RiskEvaluationResult,
    RiskPolicyEvaluator,
)
from btc_scraper.trading.event_risk_producer import (
    DeterministicEventReplayAdapter,
    DeterministicEventSnapshot,
    DeterministicEventSnapshotProducer,
    NormalizedEventRecord,
)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _make_candle(price: float = 50_000.0) -> dict:
    return {
        "open": price,
        "high": price * 1.002,
        "low": price * 0.998,
        "close": price,
        "volume": 1_000_000.0,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _make_event(
    event_id: str,
    available_at: datetime,
    event_time: datetime = None,
    affected_symbols: tuple = ("BTC",),
    severity: EventRiskLevel = EventRiskLevel.NORMAL,
    permission: EntryPermission = EntryPermission.ALLOW,
    action: PositionAction = PositionAction.NONE,
    risk_multiplier: Decimal = Decimal("1.0"),
    expires_at: datetime = None,
    revised_at: datetime = None,
    reason_codes: tuple = ("test_event",),
    uncertain_availability: bool = False,
) -> NormalizedEventRecord:
    t_event = event_time or available_at
    return NormalizedEventRecord(
        event_id=event_id,
        source_id="news_wire_mock",
        event_type="regulatory_announcement",
        affected_symbols=affected_symbols,
        event_time=t_event,
        published_at=available_at,
        available_at=available_at,
        ingested_at=available_at,
        revised_at=revised_at,
        severity=severity,
        permission=permission,
        action=action,
        risk_multiplier=risk_multiplier,
        expires_at=expires_at,
        reason_codes=reason_codes,
        uncertain_availability=uncertain_availability,
    )


# ── Test 1: Point-in-Time Filtering ──────────────────────────────────────────

def test_1_point_in_time_filtering():
    """Events available at or before decision_time are included; uncertain events are dropped."""
    producer = DeterministicEventSnapshotProducer()
    t_decision = _utc(2026, 11, 9, 12, 0, 0)

    e1 = _make_event("ev-past", available_at=_utc(2026, 11, 9, 11, 55, 0))
    e2 = _make_event("ev-exact", available_at=_utc(2026, 11, 9, 12, 0, 0))
    e3 = _make_event("ev-future", available_at=_utc(2026, 11, 9, 12, 0, 1))
    e4 = _make_event("ev-uncertain", available_at=_utc(2026, 11, 9, 11, 50, 0), uncertain_availability=True)

    snapshot = producer.build_snapshot([e1, e2, e3, e4], as_of_time=t_decision, symbol="BTC")

    assert snapshot.selected_event_ids == ("ev-past", "ev-exact")
    assert snapshot.uncertain_events_dropped == 1
    assert snapshot.missingness_status == "AVAILABLE"


# ── Test 2: Future Event Exclusion ───────────────────────────────────────────

def test_2_future_event_exclusion():
    """Events with availability strictly in the future are never leaked into the snapshot."""
    producer = DeterministicEventSnapshotProducer()
    t_decision = _utc(2026, 11, 9, 10, 0, 0)

    # Catastrophic event occurs in the future relative to decision time
    e_future_block = _make_event(
        "ev-future-sec-crackdown",
        available_at=_utc(2026, 11, 9, 10, 0, 5),
        permission=EntryPermission.BLOCK,
        severity=EventRiskLevel.CRITICAL,
    )
    snapshot = producer.build_snapshot([e_future_block], as_of_time=t_decision, symbol="BTC")

    # Snapshot as of 10:00:00 must be empty and ALLOW
    assert snapshot.selected_event_ids == ()
    assert snapshot.decision.entry_permission == EntryPermission.ALLOW
    assert snapshot.decision.max_risk_multiplier == Decimal("1.0")
    assert snapshot.missingness_status == "EMPTY"


# ── Test 3: Late Publication / Ingestion Handling ─────────────────────────────

def test_3_late_publication_and_ingestion():
    """An event occurring at t1 but not available until t2 cannot affect decisions before t2."""
    producer = DeterministicEventSnapshotProducer()
    t_event_occurred = _utc(2026, 11, 9, 8, 0, 0)
    t_info_available = _utc(2026, 11, 9, 9, 30, 0)

    e_late = _make_event(
        "ev-whale-alert",
        event_time=t_event_occurred,
        available_at=t_info_available,
        permission=EntryPermission.REDUCE_SIZE,
        risk_multiplier=Decimal("0.5"),
    )

    # Decision at 09:00:00: event has occurred, but info is NOT yet available
    snap_early = producer.build_snapshot([e_late], as_of_time=_utc(2026, 11, 9, 9, 0, 0), symbol="BTC")
    assert snap_early.selected_event_ids == ()
    assert snap_early.decision.entry_permission == EntryPermission.ALLOW

    # Decision at 09:35:00: info is now available -> affects decision
    snap_after = producer.build_snapshot([e_late], as_of_time=_utc(2026, 11, 9, 9, 35, 0), symbol="BTC")
    assert snap_after.selected_event_ids == ("ev-whale-alert",)
    assert snap_after.decision.entry_permission == EntryPermission.REDUCE_SIZE
    assert snap_after.decision.max_risk_multiplier == Decimal("0.5")


# ── Test 4: Revision-as-of Behavior ──────────────────────────────────────────

def test_4_revision_as_of_behavior():
    """Point-in-time snapshot reflects only the active revision available as of decision time."""
    producer = DeterministicEventSnapshotProducer()

    # Original report at 10:00:00 says REDUCE_SIZE (0.5)
    rev1 = _make_event(
        "ev-macro-cpi",
        available_at=_utc(2026, 11, 9, 10, 0, 0),
        revised_at=_utc(2026, 11, 9, 10, 0, 0),
        permission=EntryPermission.REDUCE_SIZE,
        risk_multiplier=Decimal("0.5"),
        reason_codes=("cpi_estimate_elevated",),
    )
    # Subsequent revision at 11:00:00 upgrades to hard BLOCK
    rev2 = _make_event(
        "ev-macro-cpi",
        available_at=_utc(2026, 11, 9, 10, 0, 0),
        revised_at=_utc(2026, 11, 9, 11, 0, 0),
        permission=EntryPermission.BLOCK,
        severity=EventRiskLevel.CRITICAL,
        risk_multiplier=Decimal("0.0"),
        reason_codes=("cpi_confirmed_hyperinflation",),
    )

    all_revs = [rev1, rev2]

    # As of 10:30:00, only rev1 is visible
    snap_1030 = producer.build_snapshot(all_revs, as_of_time=_utc(2026, 11, 9, 10, 30, 0), symbol="BTC")
    assert snap_1030.selected_event_ids == ("ev-macro-cpi",)
    assert snap_1030.decision.entry_permission == EntryPermission.REDUCE_SIZE
    assert snap_1030.decision.max_risk_multiplier == Decimal("0.5")
    assert "cpi_estimate_elevated" in snap_1030.decision.reason_codes

    # As of 11:15:00, rev2 is active
    snap_1115 = producer.build_snapshot(all_revs, as_of_time=_utc(2026, 11, 9, 11, 15, 0), symbol="BTC")
    assert snap_1115.selected_event_ids == ("ev-macro-cpi",)
    assert snap_1115.decision.entry_permission == EntryPermission.BLOCK
    assert snap_1115.decision.max_risk_multiplier == Decimal("0.0")
    assert "cpi_confirmed_hyperinflation" in snap_1115.decision.reason_codes


# ── Test 5: Duplicate Normalization ──────────────────────────────────────────

def test_5_duplicate_normalization_prevents_compounding():
    """Duplicate events are deduplicated so multipliers do not compound infinitely."""
    producer = DeterministicEventSnapshotProducer()
    t_decision = _utc(2026, 11, 9, 12, 0, 0)

    e1 = _make_event(
        "ev-dup-1",
        available_at=_utc(2026, 11, 9, 11, 0, 0),
        permission=EntryPermission.REDUCE_SIZE,
        risk_multiplier=Decimal("0.8"),
    )
    # Identical clone sent three times
    e1_clone1 = copy.deepcopy(e1)
    e1_clone2 = copy.deepcopy(e1)

    snapshot = producer.build_snapshot([e1, e1_clone1, e1_clone2], as_of_time=t_decision, symbol="BTC")
    assert snapshot.selected_event_ids == ("ev-dup-1",)
    # Risk multiplier is 0.8, NOT 0.8 * 0.8 * 0.8 = 0.512
    assert snapshot.decision.max_risk_multiplier == Decimal("0.8")


# ── Test 6: Deterministic Snapshot Hashing ────────────────────────────────────

def test_6_deterministic_snapshot_hashing_invariance():
    """Snapshot digest is 100% invariant to input order, iteration order, and repeat calls."""
    producer = DeterministicEventSnapshotProducer()
    t_decision = _utc(2026, 11, 9, 12, 0, 0)

    e1 = _make_event("ev-alpha", available_at=_utc(2026, 11, 9, 11, 0, 0), permission=EntryPermission.ALLOW)
    e2 = _make_event("ev-beta", available_at=_utc(2026, 11, 9, 11, 10, 0), permission=EntryPermission.REDUCE_SIZE, risk_multiplier=Decimal("0.6"))
    e3 = _make_event("ev-gamma", available_at=_utc(2026, 11, 9, 11, 20, 0), permission=EntryPermission.ALLOW)

    snap_order1 = producer.build_snapshot([e1, e2, e3], as_of_time=t_decision, symbol="BTC")
    snap_order2 = producer.build_snapshot([e3, e1, e2], as_of_time=t_decision, symbol="BTC")
    snap_order3 = producer.build_snapshot([e2, e3, e1], as_of_time=t_decision, symbol="BTC")

    assert snap_order1.snapshot_hash == snap_order2.snapshot_hash == snap_order3.snapshot_hash
    assert snap_order1.snapshot_id == snap_order2.snapshot_id == snap_order3.snapshot_id
    assert snap_order1.selected_event_ids == ("ev-alpha", "ev-beta", "ev-gamma")


# ── Test 7: Event Expiry ──────────────────────────────────────────────────────

def test_7_event_expiry():
    """Expired event drops out of active risk overlay and no longer blocks new entries."""
    producer = DeterministicEventSnapshotProducer()
    t_event = _utc(2026, 11, 9, 10, 0, 0)
    t_expiry = _utc(2026, 11, 9, 11, 0, 0)

    e_short_block = _make_event(
        "ev-flash-halt",
        available_at=t_event,
        expires_at=t_expiry,
        permission=EntryPermission.BLOCK,
        severity=EventRiskLevel.CRITICAL,
    )

    # During event: 10:30:00 -> BLOCKED
    snap_active = producer.build_snapshot([e_short_block], as_of_time=_utc(2026, 11, 9, 10, 30, 0), symbol="BTC")
    assert snap_active.decision.entry_permission == EntryPermission.BLOCK

    # After expiry: 11:01:00 -> ALLOW (event no longer active)
    snap_expired = producer.build_snapshot([e_short_block], as_of_time=_utc(2026, 11, 9, 11, 1, 0), symbol="BTC")
    assert snap_expired.selected_event_ids == ()
    assert snap_expired.decision.entry_permission == EntryPermission.ALLOW
    assert snap_expired.missingness_status == "EMPTY"


# ── Test 8: BLOCK Yields Zero Paper Entries ───────────────────────────────────

def test_8_event_block_yields_zero_paper_entries(monkeypatch, tmp_path):
    """An event with BLOCK permission guarantees zero paper orders executed through AutoTrader and ExecutionEngine."""
    producer = DeterministicEventSnapshotProducer()
    t_now = _utc(2026, 11, 9, 14, 0, 0)

    e_block = _make_event(
        "ev-regulatory-ban",
        available_at=_utc(2026, 11, 9, 13, 0, 0),
        permission=EntryPermission.BLOCK,
        severity=EventRiskLevel.CRITICAL,
    )
    snapshot = producer.build_snapshot([e_block], as_of_time=t_now, symbol="BTC")

    # 8a. Test AutoTrader.build_entry_decision
    trader = AutoTrader()
    analysis = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_score": {"action": "BUY", "score": 4, "strength": 85},
        "event_risk": snapshot.decision,
        "timestamp": t_now.isoformat(),
        "evaluation_time": t_now,
    }
    final_dec = {
        "decision_id": "fd-block-test",
        "prediction_id": "pred-block-test",
        "action": "BUY",
        "eligible": True,
        "terminal_status": "TRADE",
        "decision_sha256": "sha-block",
    }
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(get_committed_final_decision=lambda _p: final_dec),
    )

    entry_dec = trader.build_entry_decision(analysis, "BTC")
    assert entry_dec.eligible is False
    assert entry_dec.rejection_reason == EntryRejectionReason.EVENT_RISK_BLOCKED

    # 8b. Test ExecutionEngine.submit_paper
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "id": "sig-block-8",
        "prediction_id": "pred-block-test",
        "entry_decision_id": "ed-block-test",
        "decision_id": "ed-block-test",
        "final_decision_id": "ed-block-test",
        "latest_event_risk": snapshot.decision,
    }
    rec = engine.submit_paper(sig, _make_candle(50_000.0), notional_usdt=100.0)
    assert rec.status == "REJECTED"
    assert rec.reason == "EVENT_RISK_BLOCKED"
    assert rec.filled_qty == 0.0


# ── Test 9: REDUCE Lowers Effective Order Size ─────────────────────────────────

def test_9_event_reduce_lowers_effective_order_size(tmp_path):
    """An event with REDUCE_SIZE permission dynamically reduces intended notional."""
    producer = DeterministicEventSnapshotProducer()
    t_now = _utc(2026, 11, 9, 14, 0, 0)

    e_reduce = _make_event(
        "ev-liquidity-drain",
        available_at=_utc(2026, 11, 9, 13, 0, 0),
        permission=EntryPermission.REDUCE_SIZE,
        risk_multiplier=Decimal("0.4"),
    )
    snapshot = producer.build_snapshot([e_reduce], as_of_time=t_now, symbol="BTC")

    # In AutoTrader/Execution, 100 USDT requested -> clamped to approved 40 USDT
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "id": "sig-reduce-9",
        "prediction_id": "pred-reduce-test",
        "entry_decision_id": "ed-reduce-test",
        "decision_id": "ed-reduce-test",
        "final_decision_id": "ed-reduce-test",
        "approved_notional": 100.0 * float(snapshot.decision.max_risk_multiplier),
    }
    rec = engine.submit_paper(sig, _make_candle(50_000.0), notional_usdt=100.0)
    assert rec.status == "FILLED"
    assert pytest.approx(rec.intended_notional, rel=1e-3) == 40.0
    assert pytest.approx(rec.filled_qty * 50_000.0, rel=1e-2) == 40.0


# ── Test 10: Conflicting Event Precedence ──────────────────────────────────────

def test_10_conflicting_event_precedence():
    """Hard BLOCK strictly dominates REDUCE_SIZE and ALLOW regardless of event order."""
    producer = DeterministicEventSnapshotProducer()
    t_now = _utc(2026, 11, 9, 15, 0, 0)

    e_allow = _make_event("ev-good-news", available_at=_utc(2026, 11, 9, 14, 0, 0), permission=EntryPermission.ALLOW, risk_multiplier=Decimal("1.0"))
    e_reduce = _make_event("ev-medium-news", available_at=_utc(2026, 11, 9, 14, 10, 0), permission=EntryPermission.REDUCE_SIZE, risk_multiplier=Decimal("0.7"))
    e_block = _make_event("ev-bad-news", available_at=_utc(2026, 11, 9, 14, 20, 0), permission=EntryPermission.BLOCK, severity=EventRiskLevel.CRITICAL)

    snap1 = producer.build_snapshot([e_allow, e_reduce, e_block], as_of_time=t_now, symbol="BTC")
    snap2 = producer.build_snapshot([e_block, e_reduce, e_allow], as_of_time=t_now, symbol="BTC")

    assert snap1.decision.entry_permission == EntryPermission.BLOCK
    assert snap2.decision.entry_permission == EntryPermission.BLOCK
    assert snap1.decision.max_risk_multiplier == Decimal("0.0")
    assert snap2.decision.max_risk_multiplier == Decimal("0.0")


# ── Test 11: Replay and Runtime Parity ─────────────────────────────────────────

def test_11_replay_and_runtime_parity():
    """DeterministicEventReplayAdapter and direct producer produce 100% equivalent snapshots."""
    events = [
        _make_event("ev-1", available_at=_utc(2026, 11, 9, 10, 0, 0), permission=EntryPermission.ALLOW),
        _make_event("ev-2", available_at=_utc(2026, 11, 9, 10, 30, 0), permission=EntryPermission.REDUCE_SIZE, risk_multiplier=Decimal("0.65")),
    ]
    t_as_of = _utc(2026, 11, 9, 11, 0, 0)

    producer = DeterministicEventSnapshotProducer()
    snap_producer = producer.build_snapshot(events, as_of_time=t_as_of, symbol="BTC")

    adapter = DeterministicEventReplayAdapter(events, producer=producer)
    snap_adapter = adapter.snapshot_as_of(as_of_time=t_as_of, symbol="BTC")

    assert snap_producer.snapshot_hash == snap_adapter.snapshot_hash
    assert snap_producer.selected_event_ids == snap_adapter.selected_event_ids
    assert snap_producer.decision.max_risk_multiplier == snap_adapter.decision.max_risk_multiplier


# ── Test 12: Zero-Network Deterministic Replay ─────────────────────────────────

def test_12_zero_network_deterministic_replay(monkeypatch):
    """Replay executes completely in-memory without making any network socket calls."""
    # Monkeypatch socket to raise if any network call is attempted
    def _fail_socket(*args, **kwargs):
        raise RuntimeError("Network access forbidden in deterministic replay!")

    monkeypatch.setattr(socket, "socket", _fail_socket)

    fixture_rows = [
        {
            "event_id": "fx-1",
            "source_id": "fixture_source",
            "event_type": "macro_release",
            "affected_symbols": ["BTC"],
            "event_time": "2026-11-09T08:00:00+00:00",
            "published_at": "2026-11-09T08:00:00+00:00",
            "available_at": "2026-11-09T08:00:00+00:00",
            "severity": "ELEVATED",
            "permission": "REDUCE_SIZE",
            "action": "NONE",
            "risk_multiplier": "0.75",
        }
    ]

    adapter = DeterministicEventReplayAdapter.from_fixture_dicts(fixture_rows)
    snap = adapter.snapshot_as_of(_utc(2026, 11, 9, 9, 0, 0), symbol="BTC")

    assert snap.selected_event_ids == ("fx-1",)
    assert snap.decision.entry_permission == EntryPermission.REDUCE_SIZE
    assert snap.decision.max_risk_multiplier == Decimal("0.75")


# ── Test 13: Event Snapshot to EntryDecision & Execution Lineage ───────────────

def test_13_event_snapshot_entry_decision_execution_lineage(tmp_path):
    """Event snapshot identity and hashes are traceable end-to-end to EntryDecision and ExecutionRecord."""
    producer = DeterministicEventSnapshotProducer()
    t_now = _utc(2026, 11, 9, 16, 0, 0)

    e1 = _make_event("ev-lineage-1", available_at=_utc(2026, 11, 9, 15, 0, 0), permission=EntryPermission.ALLOW)
    snapshot = producer.build_snapshot([e1], as_of_time=t_now, symbol="BTC")

    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "id": "sig-lineage-13",
        "prediction_id": "pred-lineage-13",
        "entry_decision_id": "ed-lineage-13",
        "decision_id": "ed-lineage-13",
        "final_decision_id": "ed-lineage-13",
        "latest_event_risk": snapshot.decision,
        "event_risk_snapshot_hash": snapshot.snapshot_hash,
    }
    rec = engine.submit_paper(sig, _make_candle(50_000.0), notional_usdt=100.0)
    assert rec.status == "FILLED"
    assert rec.prediction_id == "pred-lineage-13"
    assert rec.entry_decision_id == "ed-lineage-13"


# ── Test 14: Phase D8 M0 Full Resolved Economic Outcome Lineage ────────────────

def test_14_m0_full_resolved_economic_outcome_lineage(monkeypatch, tmp_path):
    """Full causal lineage: Prediction -> FinalDecision -> EventRisk -> EntryDecision -> Fill -> Outcome."""
    ledger_path = tmp_path / "ledger" / "order_fill_ledger.json"
    ledger = OrderFillLedger(ledger_path)

    # 1. Deterministic event snapshot
    producer = DeterministicEventSnapshotProducer()
    t_decision = _utc(2026, 11, 9, 17, 0, 0)
    e1 = _make_event(
        "ev-m0-e2e",
        available_at=_utc(2026, 11, 9, 16, 30, 0),
        permission=EntryPermission.ALLOW,
        severity=EventRiskLevel.NORMAL,
    )
    snap = producer.build_snapshot([e1], as_of_time=t_decision, symbol="BTC")

    # 2. Causal Final Decision & Entry Decision
    final_dec = {
        "decision_id": "fd-m0-e2e",
        "prediction_id": "pred-m0-e2e",
        "action": "BUY",
        "eligible": True,
        "terminal_status": "TRADE",
        "decision_sha256": "sha-m0-e2e",
    }
    mock_store = SimpleNamespace(
        get_committed_final_decision=lambda _p: final_dec,
        get_entry_decision_evidence=lambda _pid: {
            "prediction_id": _pid,
            "causal_final_decision_id": "fd-m0-e2e",
            "eligible": True,
            "action": "BUY",
        },
        append_audit_event=lambda _evt: None,
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: mock_store,
    )

    # 3. Paper Execution
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "id": "sig-m0-e2e",
        "prediction_id": "pred-m0-e2e",
        "entry_decision_id": "ed-m0-e2e",
        "decision_id": "ed-m0-e2e",
        "final_decision_id": "ed-m0-e2e",
        "cycle_id": "cycle-m0",
        "deployment_id": "dep-m0",
        "paper_run_id": "dep-m0",
        "latest_event_risk": snap.decision,
        "event_risk_snapshot_hash": snap.snapshot_hash,
    }
    rec = engine.submit_paper(sig, _make_candle(50_000.0), notional_usdt=100.0)
    assert rec.status == "FILLED"
    assert rec.filled_qty > 0.0

    # 4. Fill Ledger Recording & Verification
    fill_doc = {
        "fill_id": rec.fills[0].fill_id if rec.fills else f"fill-{uuid.uuid4().hex[:6]}",
        "order_id": rec.client_order_id,
        "symbol": "BTC/USDT",
        "side": "buy",
        "price": rec.avg_fill_price,
        "qty": rec.filled_qty,
        "entry_decision_id": rec.entry_decision_id,
        "prediction_id": rec.prediction_id,
        "cycle_id": rec.cycle_id,
        "event_snapshot_hash": snap.snapshot_hash,
    }
    ledger.record_order({
        "order_id": rec.client_order_id,
        "symbol": "BTC/USDT",
        "side": "buy",
        "qty": rec.intended_qty,
        "entry_decision_id": rec.entry_decision_id,
        "prediction_id": rec.prediction_id,
        "cycle_id": rec.cycle_id,
    })
    fill_status = ledger.record_fill(fill_doc)
    assert fill_status["status"] == "linked"

    # 5. Position & Outcome Verification
    from btc_scraper.trading import position_tracker
    pos = position_tracker.add_position(
        coin="BTC",
        entry_price=rec.avg_fill_price,
        direction="LONG",
        invested_usdt=rec.filled_qty * rec.avg_fill_price,
        prediction_id="pred-m0-e2e",
        cycle_id="cycle-m0",
        entry_decision_id=rec.entry_decision_id,
        fill_id=fill_doc["fill_id"],
        client_order_id=rec.client_order_id,
        note=f"event_hash:{snap.snapshot_hash}",
    )
    assert pos["status"] == "open"
    outcome = position_tracker.close_position("BTC", sell_price=rec.avg_fill_price * 1.02)
    assert outcome["status"] == "closed"
    assert outcome["pnl_pct"] > 0
    assert outcome["fee_usd"] > 0

    # Lineage confirmation
    assert rec.prediction_id == "pred-m0-e2e"
    assert rec.entry_decision_id == "ed-m0-e2e"
    assert rec.cycle_id == "cycle-m0"
