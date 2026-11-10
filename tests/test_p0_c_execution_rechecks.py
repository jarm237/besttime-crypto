"""Targeted verification suite for P0-C — Execution-Time Risk Rechecks.

Covers:
1. Risk block after decision yields zero entry.
2. Risk budget reduction dynamically clamps quantity or rejects if zero.
3. Decision TTL expiration rejects execution.
4. Entry decision evidence missing or quarantined rejects execution.
5. Critical risk state unavailable fails closed.
6. Concurrent execution / in-flight reservation prevents double execution.
7. Duplicate retry with same idempotency key is idempotent without refilling.
8. Protective reduce / exit not blocked by entry gates (risk block, missing final decision).
9. Protective reduce / exit prevents oversell and invalid side.
10. Valid entry executes with full lineage and accurate fills.
"""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.execution.reservation_store import ReservationStore, ReservationStatus
from btc_scraper.trading.event_risk_policy import (
    EventRiskDecision,
    EventRiskLevel,
    EntryPermission,
    PositionAction,
)


def _make_engine(tmp_path: Path) -> ExecutionEngine:
    return ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )


def _make_candle(price: float = 50_000.0) -> dict:
    return {
        "open": price,
        "high": price * 1.002,
        "low": price * 0.998,
        "close": price,
        "volume": 1_000_000.0,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _make_valid_signal(
    coin: str = "BTC",
    side: str = "BUY",
    notional: float = 100.0,
    **kwargs,
) -> dict:
    sig_id = f"sig-{uuid.uuid4().hex[:8]}"
    pred_id = f"pred-{uuid.uuid4().hex[:8]}"
    dec_id = f"ed-{uuid.uuid4().hex[:8]}"
    idem = f"idem-{uuid.uuid4().hex[:8]}"
    payload = {
        "coin": coin,
        "signal": side,
        "signal_raw": side,
        "canonical_action": side,
        "id": sig_id,
        "signal_id": sig_id,
        "prediction_id": pred_id,
        "entry_decision_id": dec_id,
        "decision_id": dec_id,
        "final_decision_id": dec_id,
        "idempotency_key": idem,
        "intent": OrderIntent.ENTRY,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "approved_notional": notional,
    }
    payload.update(kwargs)
    return payload


# ── Test 1: Risk Block After Decision Yields Zero Entry ──────────────────────────

def test_1_risk_block_after_decision_yields_zero_entry(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 1a. Latest risk restriction explicitly set to BLOCK
    sig_blocked = _make_valid_signal(latest_risk_restriction="BLOCK")
    rec_blocked = engine.submit_paper(sig_blocked, candle, notional_usdt=100.0)
    assert rec_blocked.status == "REJECTED"
    assert rec_blocked.reason == "LATEST_RISK_RESTRICTION_BLOCKED"
    assert rec_blocked.filled_qty == 0.0
    assert len(rec_blocked.fills) == 0

    # 1b. Latest event risk decision arrives with BLOCK permission
    event_risk_block = EventRiskDecision.from_dict({
        "risk_level": "HIGH",
        "entry_permission": "BLOCK",
        "position_action": "NONE",
        "max_risk_multiplier": "0.0",
        "risk_state_version": "risk-v1",
        "risk_policy_version": "event-risk-v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "reason_codes": ["breaking_regulatory_action"],
    })
    sig_event_block = _make_valid_signal(latest_event_risk=event_risk_block)
    rec_ev_block = engine.submit_paper(sig_event_block, candle, notional_usdt=100.0)
    assert rec_ev_block.status == "REJECTED"
    assert rec_ev_block.reason == "EVENT_RISK_BLOCKED"
    assert rec_ev_block.filled_qty == 0.0

    # 1c. Latest event risk arrives with CRITICAL level
    event_risk_crit = EventRiskDecision.from_dict({
        "risk_level": "CRITICAL",
        "entry_permission": "ALLOW",  # Even if allow, critical forces block
        "position_action": "REDUCE_ONLY",
        "max_risk_multiplier": "0.0",
        "risk_state_version": "risk-v1",
        "risk_policy_version": "event-risk-v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "reason_codes": ["market_wide_circuit_breaker"],
    })
    sig_crit = _make_valid_signal(latest_event_risk=event_risk_crit)
    rec_crit = engine.submit_paper(sig_crit, candle, notional_usdt=100.0)
    assert rec_crit.status == "REJECTED"
    assert rec_crit.reason == "EVENT_RISK_BLOCKED"
    assert rec_crit.filled_qty == 0.0


# ── Test 2: Risk Budget Reduction Adjusts or Rejects Quantity ───────────────────

def test_2_risk_budget_reduction_adjusts_or_rejects_quantity(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 2a. Remaining risk budget smaller than requested notional -> dynamically clamped
    sig_reduced = _make_valid_signal(remaining_risk_budget=40.0)
    rec_reduced = engine.submit_paper(sig_reduced, candle, notional_usdt=100.0)
    assert rec_reduced.status == "FILLED"
    assert rec_reduced.intended_notional == 40.0
    assert pytest.approx(rec_reduced.filled_qty * 50_000.0, rel=1e-2) == 40.0

    # 2b. Remaining risk budget zero or negative -> rejected
    sig_zero = _make_valid_signal(remaining_risk_budget=0.0)
    rec_zero = engine.submit_paper(sig_zero, candle, notional_usdt=100.0)
    assert rec_zero.status == "REJECTED"
    assert rec_zero.reason == "RISK_BUDGET_EXCEEDED"
    assert rec_zero.filled_qty == 0.0

    # 2c. Approved notional smaller than requested notional -> clamped to approved
    sig_appr = _make_valid_signal(approved_notional=65.0)
    rec_appr = engine.submit_paper(sig_appr, candle, notional_usdt=100.0)
    assert rec_appr.status == "FILLED"
    assert rec_appr.intended_notional == 65.0

    # 2d. Portfolio cap exceeded -> rejected
    sig_cap = _make_valid_signal(max_portfolio_notional=0.0)
    rec_cap = engine.submit_paper(sig_cap, candle, notional_usdt=100.0)
    assert rec_cap.status == "REJECTED"
    assert rec_cap.reason == "PORTFOLIO_CAP_EXCEEDED"


# ── Test 3: Decision TTL Expiration Rejects Execution ────────────────────────────

def test_3_decision_ttl_expiration_rejects(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 3a. Explicit decision_expired flag
    sig_exp1 = _make_valid_signal(decision_expired=True)
    rec_exp1 = engine.submit_paper(sig_exp1, candle, notional_usdt=100.0)
    assert rec_exp1.status == "REJECTED"
    assert rec_exp1.reason == "DECISION_TTL_EXPIRED"

    # 3b. valid_until in the past
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    sig_exp2 = _make_valid_signal(valid_until=past_iso)
    rec_exp2 = engine.submit_paper(sig_exp2, candle, notional_usdt=100.0)
    assert rec_exp2.status == "REJECTED"
    assert rec_exp2.reason == "DECISION_TTL_EXPIRED"

    # 3c. decision_ttl_seconds exceeded
    old_entry_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    sig_exp3 = _make_valid_signal(entry_time=old_entry_time, decision_ttl_seconds=60)
    rec_exp3 = engine.submit_paper(sig_exp3, candle, notional_usdt=100.0)
    assert rec_exp3.status == "REJECTED"
    assert rec_exp3.reason == "DECISION_TTL_EXPIRED"


# ── Test 4: Entry Evidence Missing or Quarantined Rejects Execution ──────────────

def test_4_entry_evidence_missing_or_quarantined_rejects(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 4a. Explicit quarantine flag
    sig_quar = _make_valid_signal(entry_decision_quarantined=True)
    rec_quar = engine.submit_paper(sig_quar, candle, notional_usdt=100.0)
    assert rec_quar.status == "REJECTED"
    assert rec_quar.reason == "ENTRY_DECISION_QUARANTINED"

    # 4b. Explicit missing flag
    sig_miss = _make_valid_signal(entry_decision_missing=True)
    rec_miss = engine.submit_paper(sig_miss, candle, notional_usdt=100.0)
    assert rec_miss.status == "REJECTED"
    assert rec_miss.reason == "ENTRY_DECISION_MISSING_OR_QUARANTINED"


# ── Test 5: Critical Risk State Unavailable Fails Closed ─────────────────────────

def test_5_critical_risk_state_unavailable_fails_closed(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 5a. Critical risk state unavailable
    sig_unavail = _make_valid_signal(critical_risk_state_unavailable=True)
    rec_unavail = engine.submit_paper(sig_unavail, candle, notional_usdt=100.0)
    assert rec_unavail.status == "REJECTED"
    assert rec_unavail.reason == "CRITICAL_RISK_STATE_UNAVAILABLE"
    assert rec_unavail.filled_qty == 0.0

    # 5b. Risk state missing
    sig_miss = _make_valid_signal(risk_state_missing=True)
    rec_miss = engine.submit_paper(sig_miss, candle, notional_usdt=100.0)
    assert rec_miss.status == "REJECTED"
    assert rec_miss.reason == "CRITICAL_RISK_STATE_UNAVAILABLE"

    # 5c. Risk policy version incompatible
    sig_ver = _make_valid_signal(risk_policy_version_incompatible=True)
    rec_ver = engine.submit_paper(sig_ver, candle, notional_usdt=100.0)
    assert rec_ver.status == "REJECTED"
    assert rec_ver.reason == "RISK_POLICY_VERSION_MISMATCH"


# ── Test 6: Concurrent Execution / In-Flight Reservation Prevents Double Submit ───

def test_6_concurrent_execution_in_flight_prevents_double_submit(tmp_path):
    db_path = tmp_path / "reservations.db"
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # Seed an in-flight reservation for ed-shared with idempotency_key 'idem-1'
    res_store = ReservationStore(db_path)
    rec1, created = res_store.reserve(
        reservation_id="res-inflight-1",
        idempotency_key="idem-1",
        entry_decision_id="ed-shared",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
    )
    assert created is True
    assert rec1.status == ReservationStatus.PENDING

    # A concurrent second caller attempts to execute ed-shared with different idempotency key 'idem-2'
    sig_concurrent = _make_valid_signal(
        entry_decision_id="ed-shared",
        idempotency_key="idem-2",
    )
    rec2 = engine.submit_paper(sig_concurrent, candle, notional_usdt=100.0)
    assert rec2.status == "REJECTED"
    assert rec2.reason == "RESERVATION_IN_FLIGHT"
    assert rec2.filled_qty == 0.0


# ── Test 7: Duplicate Retry Idempotent ───────────────────────────────────────────

def test_7_duplicate_retry_idempotent(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig = _make_valid_signal(idempotency_key="idem-idempotent-test")

    # First attempt fills and commits
    first = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert first.status == "FILLED"
    first_qty = first.filled_qty

    # Second attempt with identical idempotency_key returns already filled without refilling
    second = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert second.status == "FILLED"
    assert second.reason == "duplicate_idempotency_key_already_committed"
    assert pytest.approx(second.filled_qty, rel=1e-3) == first_qty


# ── Test 8: Protective Reduce / Exit Not Blocked By Entry Gates ─────────────────

def test_8_protective_reduce_and_exit_not_blocked_by_entry_gates(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # Case A: Exit position when risk restriction is BLOCK
    sig_exit = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "existing_position_qty": 0.002,
        "position_side": "LONG",
        "latest_risk_restriction": "BLOCK",  # Would block entry, but MUST NOT block exit!
        "event_risk_blocked": True,
        "entry_decision_missing": True,
    }
    rec_exit = engine.submit_paper(sig_exit, candle, notional_usdt=100.0)
    assert rec_exit.status == "FILLED"
    assert rec_exit.side == "SELL"
    assert rec_exit.filled_qty > 0.0

    # Case B: Emergency exit when critical risk state is unavailable
    sig_em_exit = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EMERGENCY_EXIT,
        "existing_position_qty": 0.002,
        "position_side": "LONG",
        "critical_risk_state_unavailable": True,  # Would fail-closed entry, but MUST NOT block emergency exit!
    }
    rec_em = engine.submit_paper(sig_em_exit, candle, notional_usdt=100.0)
    assert rec_em.status == "FILLED"
    assert rec_em.filled_qty > 0.0


# ── Test 9: Protective Reduce / Exit Prevents Oversell and Invalid Side ──────────

def test_9_protective_reduce_exit_prevents_oversell_and_invalid_side(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 9a. No position exists -> reject exit
    sig_no_pos = {
        "coin": "BTC",
        "signal": "SELL",
        "intent": OrderIntent.EXIT,
        "existing_position_qty": 0.0,
    }
    rec_no_pos = engine.submit_paper(sig_no_pos, candle, notional_usdt=100.0)
    assert rec_no_pos.status == "REJECTED"
    assert rec_no_pos.reason == "NO_POSITION_TO_CLOSE"

    # 9b. Position is LONG, but exit order is BUY -> invalid side
    sig_bad_side = {
        "coin": "BTC",
        "signal": "BUY",
        "intent": OrderIntent.EXIT,
        "existing_position_qty": 0.002,
        "position_side": "LONG",
    }
    rec_bad_side = engine.submit_paper(sig_bad_side, candle, notional_usdt=100.0)
    assert rec_bad_side.status == "REJECTED"
    assert rec_bad_side.reason == "INVALID_EXIT_SIDE"

    # 9c. Oversell prevented: intended_qty (100 USDT / 50k = 0.002 BTC) exceeds position (0.001 BTC)
    # Automatically clamped to 0.001 BTC so position doesn't flip into negative
    sig_oversell = {
        "coin": "BTC",
        "signal": "SELL",
        "intent": OrderIntent.EXIT,
        "existing_position_qty": 0.001,
        "position_side": "LONG",
    }
    rec_clamped = engine.submit_paper(sig_oversell, candle, notional_usdt=100.0)
    assert rec_clamped.status == "FILLED"
    assert pytest.approx(rec_clamped.intended_qty, rel=1e-4) == 0.001
    assert pytest.approx(rec_clamped.intended_notional, rel=1e-4) == 50.0

    # 9d. Explicit reduce_exceeds_position flag triggers rejection
    sig_exceed = {
        "coin": "BTC",
        "signal": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "existing_position_qty": 0.001,
        "position_side": "LONG",
        "reduce_exceeds_position": True,
    }
    rec_exceed = engine.submit_paper(sig_exceed, candle, notional_usdt=100.0)
    assert rec_exceed.status == "REJECTED"
    assert rec_exceed.reason == "OVERSELL_PREVENTED"


# ── Test 10: Valid Entry Full Linkage and Outcome ───────────────────────────────

def test_10_valid_entry_full_linkage_and_outcome(tmp_path):
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig = _make_valid_signal(
        coin="BTC",
        side="BUY",
        notional=100.0,
        model_version="v6-canary",
        deployment_id="dep-valid-1",
        cycle_id="cycle-42",
    )

    rec = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec.status == "FILLED"
    assert rec.coin == "BTC"
    assert rec.side == "BUY"
    assert rec.intended_notional == 100.0
    assert pytest.approx(rec.intended_qty, rel=1e-4) == 0.002
    assert rec.filled_qty > 0.0
    assert rec.avg_fill_price > 0.0
    assert rec.prediction_id == sig["prediction_id"]
    assert rec.entry_decision_id == sig["entry_decision_id"]
    assert rec.model_version == "v6-canary"
    assert rec.deployment_id == "dep-valid-1"
    assert rec.cycle_id == "cycle-42"
    assert rec.reservation_id != ""

    # Verify reservation committed in reservation store
    res_store = ReservationStore(tmp_path / "reservations.db")
    res = res_store.get_reservation(rec.reservation_id)
    assert res is not None
    assert res.status == ReservationStatus.COMMITTED
    assert res.entry_decision_id == rec.entry_decision_id
    assert res.prediction_id == rec.prediction_id


# ── Test 11: Missing Required Evidence Store Capability Fails Closed ───────────

def test_11_missing_required_evidence_store_capability_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "dep-cap")
    monkeypatch.setenv("BTC_PAPER_RUN_ID", "dep-cap")
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "true")
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # Incomplete store double lacking get_entry_decision_evidence
    incomplete_store = SimpleNamespace(
        get_committed_final_decision=lambda _pid: {
            "decision_id": "ed-missing-cap",
            "prediction_id": "pred-missing-cap",
            "action": "BUY",
            "eligible": True,
            "decision_sha256": "sha-test-cap",
            "terminal_status": "TRADE",
            "cycle_id": "cycle-cap",
            "deployment_id": "dep-cap",
            "paper_run_id": "dep-cap",
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: incomplete_store,
    )

    sig = _make_valid_signal(
        prediction_id="pred-missing-cap",
        entry_decision_id="ed-missing-cap",
        decision_id="ed-missing-cap",
        final_decision_id="ed-missing-cap",
        final_decision_action="BUY",
        final_decision_prediction_id="pred-missing-cap",
        final_decision_eligible=True,
        final_decision_terminal_status="TRADE",
        decision_sha256="sha-test-cap",
        cycle_id="cycle-cap",
        final_decision_cycle_id="cycle-cap",
        deployment_id="dep-cap",
        final_decision_deployment_id="dep-cap",
        paper_run_id="dep-cap",
        final_decision_paper_run_id="dep-cap",
    )
    rec = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec.status == "REJECTED"
    assert rec.reason == "REQUIRED_EVIDENCE_STORE_CAPABILITY_MISSING"


# ── Test 12: Atomic Shared Budget Concurrency Race ──────────────────────────────

def test_12_atomic_shared_budget_concurrency_race(tmp_path):
    """Case 3: Two concurrent orders of notional 80 race on shared budget of 100.

    Exactly one must succeed (80); the other must be rejected (RISK_BUDGET_EXHAUSTED).
    The total reserved notional must be exactly 80, never 160.
    """
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig1 = _make_valid_signal(coin="BTC", notional=80.0, max_shared_budget=100.0)
    sig2 = _make_valid_signal(coin="ETH", notional=80.0, max_shared_budget=100.0)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(engine.submit_paper, sig1, candle, 80.0)
        f2 = executor.submit(engine.submit_paper, sig2, candle, 80.0)
        rec1 = f1.result()
        rec2 = f2.result()

    statuses = [rec1.status, rec2.status]
    assert "FILLED" in statuses
    assert "REJECTED" in statuses
    rejected_rec = rec1 if rec1.status == "REJECTED" else rec2
    assert rejected_rec.reason == "RISK_BUDGET_EXHAUSTED"

    res_store = ReservationStore(tmp_path / "reservations.db")
    active_notional, active_slots = res_store.get_active_notional_and_slots()
    assert pytest.approx(active_notional, rel=1e-3) == 80.0


# ── Test 13: Independent Valid Intents Under Budget Both Succeed ───────────────

def test_13_independent_valid_intents_both_succeed_under_budget(tmp_path):
    """Case 4: Two independent orders of notional 40 on budget 100 both succeed."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig1 = _make_valid_signal(coin="BTC", notional=40.0, max_shared_budget=100.0)
    sig2 = _make_valid_signal(coin="ETH", notional=40.0, max_shared_budget=100.0)

    rec1 = engine.submit_paper(sig1, candle, 40.0)
    rec2 = engine.submit_paper(sig2, candle, 40.0)

    assert rec1.status == "FILLED"
    assert rec2.status == "FILLED"

    res_store = ReservationStore(tmp_path / "reservations.db")
    active_notional, _ = res_store.get_active_notional_and_slots()
    assert pytest.approx(active_notional, rel=1e-3) == 80.0


# ── Test 14: Same Decision Different Keys Rejected ─────────────────────────────

def test_14_same_decision_different_keys_rejected(tmp_path):
    """Case 2: Same canonical decision cannot be double executed under different idempotency keys."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig1 = _make_valid_signal(entry_decision_id="ed-exclusive-1", idempotency_key="key-A")
    sig2 = _make_valid_signal(entry_decision_id="ed-exclusive-1", idempotency_key="key-B")

    rec1 = engine.submit_paper(sig1, candle, 100.0)
    assert rec1.status == "FILLED"

    rec2 = engine.submit_paper(sig2, candle, 100.0)
    assert rec2.status == "REJECTED"
    assert rec2.reason == "RESERVATION_IN_FLIGHT"


# ── Test 15: Reservation Rollback On Execution Failure ──────────────────────────

def test_15_reservation_rollback_on_execution_failure(tmp_path):
    """Case 6: If execution fails/rejects after reservation, reservation is released and doesn't leak budget."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # Force rejection during pre-trade risk check (after reservation)
    engine._risk.evaluate = lambda **kwargs: SimpleNamespace(
        action="REJECT",
        reason="FORCED_POST_RESERVE_RISK_REJECT",
        adjusted_qty_usdt=None,
    )

    sig = _make_valid_signal(notional=100.0)
    rec = engine.submit_paper(sig, candle, 100.0)
    assert rec.status == "REJECTED"
    assert rec.reason == "FORCED_POST_RESERVE_RISK_REJECT"

    # Verify reservation was rolled back (RELEASED) and active notional is 0
    res_store = ReservationStore(tmp_path / "reservations.db")
    res = res_store.get_reservation(rec.reservation_id)
    assert res is not None
    assert res.status == ReservationStatus.RELEASED

    active_notional, _ = res_store.get_active_notional_and_slots()
    assert active_notional == 0.0


# ── Test 16: Forged Exit Without Position Cannot Bypass Entry Gates ────────────

def test_16_forged_exit_without_position_cannot_bypass_entry_gates(tmp_path):
    """Protective classification rejects forged exit flags when no actual position exists."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # Forged exit claim with no existing position
    sig_forged = {
        "coin": "BTC",
        "signal": "BUY",
        "intent": OrderIntent.EXIT,
        "is_exit": True,
        "existing_position_qty": 0.0,
        "critical_risk_state_unavailable": True,  # Would fail closed if entry
    }
    rec = engine.submit_paper(sig_forged, candle, notional_usdt=100.0)
    assert rec.status == "REJECTED"
    assert rec.reason == "NO_POSITION_TO_CLOSE"

    # Stale position state claim rejected
    sig_stale_pos = {
        "coin": "BTC",
        "signal": "SELL",
        "intent": OrderIntent.EXIT,
        "existing_position_qty": 0.002,
        "position_stale": True,
    }
    rec_stale = engine.submit_paper(sig_stale_pos, candle, notional_usdt=100.0)
    assert rec_stale.status == "REJECTED"
    assert rec_stale.reason == "STALE_POSITION_STATE"


# ── Test 17: Dynamic Sizing Respects Step Size and Min Notional ─────────────────

def test_17_dynamic_sizing_respects_step_size_and_min_notional(tmp_path):
    """Clamped sizing respects lot step size (flooring) and rejects if below min_notional."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    # 17a. Clamping to 42.5 USDT with step_size 0.0005 BTC (25 USDT per step)
    # 42.5 / 50,000 = 0.00085 BTC -> floored to 0.0005 BTC (25 USDT)
    sig_step = _make_valid_signal(
        remaining_risk_budget=42.5,
        step_size=0.0005,
        min_notional=10.0,
    )
    rec_step = engine.submit_paper(sig_step, candle, notional_usdt=100.0)
    assert rec_step.status == "FILLED"
    assert pytest.approx(rec_step.intended_qty, rel=1e-4) == 0.0005
    assert pytest.approx(rec_step.intended_notional, rel=1e-4) == 25.0

    # 17b. Remainder below min_notional (e.g. 4.0 USDT < min_notional 10.0) -> rejected
    sig_below_min = _make_valid_signal(
        remaining_risk_budget=4.0,
        min_notional=10.0,
    )
    rec_below_min = engine.submit_paper(sig_below_min, candle, notional_usdt=100.0)
    assert rec_below_min.status == "REJECTED"
    assert rec_below_min.reason == "REMAINDER_BELOW_MIN_NOTIONAL"


# ── Test 18: Rejection Does Not Quarantine Canonical Evidence ───────────────────

def test_18_rejection_does_not_quarantine_canonical_evidence(monkeypatch, tmp_path):
    """Execution rejection records 'execution_rejected' audit event without corrupting canonical evidence."""
    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    recorded_events = []
    fake_store = SimpleNamespace(
        get_committed_final_decision=lambda _pid: {"decision_id": "fd-valid"},
        get_entry_decision_evidence=lambda _pid: {
            "prediction_id": _pid,
            "causal_final_decision_id": "fd-valid",
            "eligible": True,
            "action": "BUY",
        },
        append_audit_event=lambda evt: recorded_events.append(evt),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: fake_store,
    )

    # Valid entry decision rejected purely for budget exhaustion
    sig = _make_valid_signal(
        prediction_id="pred-audit-1",
        entry_decision_id="ed-audit-1",
        final_decision_id="fd-valid",
        remaining_risk_budget=0.0,
    )
    rec = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec.status == "REJECTED"
    assert rec.reason in ("RISK_BUDGET_EXCEEDED", "RISK_BUDGET_EXHAUSTED")

    # Audit event should be execution_rejected, NOT execution_quarantined
    assert len(recorded_events) == 1
    evt = recorded_events[0]
    assert evt["event_type"] == "execution_rejected"
    assert evt["reason_code"] in ("RISK_BUDGET_EXCEEDED", "RISK_BUDGET_EXHAUSTED")
    assert evt["entry_decision_id"] == "ed-audit-1"


# ── Test 19: Positive End-to-End Paper Execution With Economic Lineage ───────────

def test_19_positive_end_to_end_paper_execution_with_economic_lineage(monkeypatch, tmp_path):
    """Complete positive flow: Prediction -> Decision -> P0-C -> Fill -> Ledger -> Outcome."""
    from btc_scraper.execution.order_fill_ledger import OrderFillLedger
    ledger_path = tmp_path / "ledger" / "order_fill_ledger.json"
    ledger = OrderFillLedger(ledger_path)

    recorded_audits = []
    fake_store = SimpleNamespace(
        get_committed_final_decision=lambda _pid: {"decision_id": "fd-e2e-1"},
        get_entry_decision_evidence=lambda _pid: {
            "prediction_id": _pid,
            "causal_final_decision_id": "fd-e2e-1",
            "eligible": True,
            "action": "BUY",
        },
        append_audit_event=lambda evt: recorded_audits.append(evt),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: fake_store,
    )

    engine = _make_engine(tmp_path)
    candle = _make_candle(50_000.0)

    sig = _make_valid_signal(
        coin="BTC",
        side="BUY",
        notional=100.0,
        prediction_id="pred-e2e-1",
        entry_decision_id="ed-e2e-1",
        final_decision_id="fd-e2e-1",
        cycle_id="cycle-e2e",
        deployment_id="dep-e2e",
        paper_run_id="dep-e2e",
        idempotency_key="key-e2e-1",
    )

    # 1. Execution through P0-C rechecks and atomic reservation
    rec = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec.status == "FILLED"
    assert rec.filled_qty > 0.0

    # 2. Record order and fill in ledger
    order_doc = {
        "order_id": rec.client_order_id,
        "symbol": f"{rec.coin}/USDT",
        "side": rec.side.lower(),
        "qty": rec.intended_qty,
        "entry_decision_id": rec.entry_decision_id,
        "prediction_id": rec.prediction_id,
        "cycle_id": rec.cycle_id,
    }
    ledger.record_order(order_doc)

    fill_doc = {
        "fill_id": rec.fills[0].fill_id if rec.fills else f"fill-{uuid.uuid4().hex[:6]}",
        "order_id": rec.client_order_id,
        "symbol": f"{rec.coin}/USDT",
        "side": rec.side.lower(),
        "price": rec.avg_fill_price,
        "qty": rec.filled_qty,
        "entry_decision_id": rec.entry_decision_id,
        "prediction_id": rec.prediction_id,
    }
    fill_status = ledger.record_fill(fill_doc)
    assert fill_status["status"] == "linked"

    # 3. Verify lineage in fill record
    assert rec.prediction_id == "pred-e2e-1"
    assert rec.entry_decision_id == "ed-e2e-1"
    assert rec.cycle_id == "cycle-e2e"
    assert rec.paper_run_id == "dep-e2e"

    # 4. Verify idempotent replay does not duplicate fill
    rec_replay = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec_replay.status == "FILLED"
    assert rec_replay.reason == "duplicate_idempotency_key_already_committed"
    assert pytest.approx(rec_replay.filled_qty, rel=1e-3) == rec.filled_qty

