"""
tests/test_p0_b_event_risk_policy.py
Comprehensive verification suite for P0-B — Shared Event Risk Policy Contract.

13 Mandatory Tests:
    1. Absent overlay giữ nguyên P0-A baseline.
    2. Malformed dict bị reject, không tắt overlay.
    3. Naive datetime bị reject.
    4. expires_at trước evaluated_at bị reject.
    5. multiplier âm, >1, NaN và Infinity bị reject.
    6. Event overlay không bao giờ làm multiplier tăng (approved <= requested).
    7. Evaluator không gọi wall clock nội bộ (datetime.now forbidden, timestamp-driven).
    8. Fixed timestamp tạo deterministic result.
    9. Policy mismatch/stale/missing giữ nguyên stable reason trong EntryDecision evidence.
    10. RuntimeEvidenceStore readback trả đúng snapshot và evaluation result.
    11. Existing persisted final decision không thay đổi (unmutated, idempotency & conflict checks).
    12. Overlay off không tạo thêm evidence record.
    13. Zero network và không phụ thuộc collector.
"""
import copy
import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import (
    DEFAULT_EVENT_RISK_POLICY_VERSION,
    DecisionStage,
    EntryPermission,
    EntryRejectionReason,
    EventRiskContractError,
    EventRiskDecision,
    EventRiskLevel,
    EventRiskPolicyReason,
    FinalDecisionStatus,
    OrderIntent,
    PositionAction,
    RiskEvaluationResult,
    RiskPolicyEvaluator,
    StaleSnapshotPolicy,
    TradeAction,
)
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


@pytest.fixture(autouse=True)
def setup_hermetic_trader(monkeypatch):
    monkeypatch.setattr(AutoTrader, "allowed_coins", property(lambda self: ["BTC"]))
    monkeypatch.setattr(AutoTrader, "_has_open_position", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_open_positions",
        lambda: [],
    )
    monkeypatch.setattr(
        AutoTrader,
        "_check_circuit_breaker",
        lambda *args, **kwargs: (True, ""),
    )


def _make_trader() -> AutoTrader:
    return AutoTrader()


def _make_valid_analysis(coin: str = "BTC") -> dict:
    """Hermetic synthetic analysis payload for valid BUY trade."""
    return {
        "coin": coin,
        "signal": "BUY",
        "signal_score": {
            "score": 85,
            "action": "BUY",
            "meta_probability": 0.88,
            "strength": 85,
            "signal_id": "sig-test-1",
            "prediction_id": "pred-test-1",
            "model_version": "v1.0.0",
        },
        "tp_sl": {
            "entry": 50000.0,
            "sl": 45000.0,  # 10% stop distance -> raw_notional = 100 USDT
            "tp1": 55000.0,
            "rr1": 2.0,
        },
        "close": 50000.0,
    }


def _make_event_risk_snapshot(
    risk_level: EventRiskLevel = EventRiskLevel.NORMAL,
    entry_permission: EntryPermission = EntryPermission.ALLOW,
    position_action: PositionAction = PositionAction.NONE,
    max_risk_multiplier: Decimal = Decimal("1.0"),
    risk_policy_version: str = DEFAULT_EVENT_RISK_POLICY_VERSION,
    risk_state_version: str = "state-v1",
    evaluated_at: datetime | None = None,
    expires_at: datetime | None = None,
    reason_codes: tuple[str, ...] = ("TEST_EVENT",),
) -> EventRiskDecision:
    now = evaluated_at or datetime.now(timezone.utc)
    return EventRiskDecision(
        risk_level=risk_level,
        entry_permission=entry_permission,
        position_action=position_action,
        max_risk_multiplier=max_risk_multiplier,
        risk_state_version=risk_state_version,
        risk_policy_version=risk_policy_version,
        evaluated_at=now,
        expires_at=expires_at if expires_at is not None else (now + timedelta(hours=1)),
        reason_codes=reason_codes,
    )


# ── Test 1: Absent overlay giữ nguyên P0-A baseline ───────────────────────────

def test_1_absent_overlay_preserves_p0_a_baseline():
    trader = _make_trader()
    analysis = _make_valid_analysis("BTC")
    assert "event_risk" not in analysis

    decision = trader.build_entry_decision(analysis, "BTC", event_risk=None)

    assert decision.eligible is True
    assert decision.action == TradeAction.BUY
    assert decision.rejection_reason is None
    assert decision.event_risk is None
    assert decision.event_risk_result is None
    assert decision.breakdown.event_risk is None
    assert decision.breakdown.event_risk_result is None
    assert decision.breakdown.decision_stage == DecisionStage.SIZING
    assert decision.breakdown.risk_multiplier == 1.0


# ── Test 2: Malformed dict bị reject, không tắt overlay ───────────────────────

def test_2_malformed_dict_fails_closed_without_dropping_overlay():
    trader = _make_trader()

    # 2a. Malformed dict passed via argument
    analysis_clean = _make_valid_analysis("BTC")
    malformed_payload = {"invalid_key": "junk_data"}
    dec1 = trader.build_entry_decision(analysis_clean, "BTC", event_risk=malformed_payload)

    assert dec1.eligible is False
    assert dec1.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT
    assert dec1.final_status == FinalDecisionStatus.REJECTED
    assert dec1.final_position_size == 0.0
    assert dec1.gated is True

    # 2b. Malformed dict passed via analysis dictionary
    analysis_malformed = _make_valid_analysis("BTC")
    analysis_malformed["event_risk"] = {"risk_level": "UNKNOWN_LEVEL"}
    dec2 = trader.build_entry_decision(analysis_malformed, "BTC")

    assert dec2.eligible is False
    assert dec2.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT
    assert dec2.final_position_size == 0.0

    # 2c. Non-dict non-decision invalid type (e.g. integer)
    analysis_bad_type = _make_valid_analysis("BTC")
    analysis_bad_type["event_risk"] = 12345
    dec3 = trader.build_entry_decision(analysis_bad_type, "BTC")

    assert dec3.eligible is False
    assert dec3.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT


# ── Test 3: Naive datetime bị reject ──────────────────────────────────────────

def test_3_naive_datetime_rejected():
    naive_dt = datetime(2026, 11, 5, 12, 0, 0)  # No tzinfo
    aware_dt = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 3a. Naive evaluated_at in snapshot raises contract error
    with pytest.raises(EventRiskContractError, match="evaluated_at must be a timezone-aware datetime"):
        EventRiskDecision(
            risk_level=EventRiskLevel.NORMAL,
            entry_permission=EntryPermission.ALLOW,
            position_action=PositionAction.NONE,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="state-v1",
            risk_policy_version=DEFAULT_EVENT_RISK_POLICY_VERSION,
            evaluated_at=naive_dt,
        )

    # 3b. Naive expires_at in snapshot raises contract error
    with pytest.raises(EventRiskContractError, match="expires_at must be a timezone-aware datetime"):
        EventRiskDecision(
            risk_level=EventRiskLevel.NORMAL,
            entry_permission=EntryPermission.ALLOW,
            position_action=PositionAction.NONE,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="state-v1",
            risk_policy_version=DEFAULT_EVENT_RISK_POLICY_VERSION,
            evaluated_at=aware_dt,
            expires_at=naive_dt,
        )

    # 3c. Naive evaluation_timestamp in evaluator raises contract error
    valid_snapshot = _make_event_risk_snapshot(evaluated_at=aware_dt)
    evaluator = RiskPolicyEvaluator()
    with pytest.raises(EventRiskContractError, match="evaluation_timestamp must be a timezone-aware datetime"):
        evaluator.evaluate(
            snapshot=valid_snapshot,
            intent=OrderIntent.ENTRY,
            requested_multiplier=Decimal("1.0"),
            evaluation_timestamp=naive_dt,
        )


# ── Test 4: expires_at trước evaluated_at bị reject ───────────────────────────

def test_4_expires_at_before_evaluated_at_rejected():
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    earlier = now - timedelta(seconds=1)

    with pytest.raises(EventRiskContractError, match="cannot be earlier than evaluated_at"):
        EventRiskDecision(
            risk_level=EventRiskLevel.NORMAL,
            entry_permission=EntryPermission.ALLOW,
            position_action=PositionAction.NONE,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="state-v1",
            risk_policy_version=DEFAULT_EVENT_RISK_POLICY_VERSION,
            evaluated_at=now,
            expires_at=earlier,
        )


# ── Test 5: multiplier âm, >1, NaN và Infinity bị reject ───────────────────────

def test_5_invalid_multiplier_rejected():
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 5a. Snapshot construction with invalid max_risk_multiplier
    for invalid_mult in (Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(EventRiskContractError):
            EventRiskDecision(
                risk_level=EventRiskLevel.NORMAL,
                entry_permission=EntryPermission.ALLOW,
                position_action=PositionAction.NONE,
                max_risk_multiplier=invalid_mult,
                risk_state_version="state-v1",
                risk_policy_version=DEFAULT_EVENT_RISK_POLICY_VERSION,
                evaluated_at=now,
            )

    # 5b. Evaluator with invalid requested_multiplier fails-closed
    evaluator = RiskPolicyEvaluator()
    valid_snapshot = _make_event_risk_snapshot(evaluated_at=now)
    for bad_req in (Decimal("-0.1"), Decimal("1.5"), Decimal("NaN"), Decimal("Infinity")):
        res = evaluator.evaluate(
            snapshot=valid_snapshot,
            intent=OrderIntent.ENTRY,
            requested_multiplier=bad_req,
            evaluation_timestamp=now,
        )
        assert res.allowed is False
        assert res.approved_multiplier == Decimal("0.0")
        assert res.reason == EventRiskPolicyReason.INVALID_REQUESTED_MULTIPLIER


# ── Test 6: Event overlay không bao giờ làm multiplier tăng ───────────────────

def test_6_overlay_never_expands_multiplier():
    evaluator = RiskPolicyEvaluator()
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # Snapshot allows 1.0, but requested is 0.4 -> approved must be 0.4, NEVER 1.0
    allow_snapshot = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.NORMAL,
        entry_permission=EntryPermission.ALLOW,
        max_risk_multiplier=Decimal("1.0"),
        evaluated_at=now,
    )
    res1 = evaluator.evaluate(
        snapshot=allow_snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("0.4"),
        evaluation_timestamp=now,
    )
    assert res1.allowed is True
    assert res1.approved_multiplier == Decimal("0.4")
    assert res1.approved_multiplier <= Decimal("0.4")

    # Snapshot reduces to 0.5, requested is 0.8 -> approved is 0.5
    reduce_snapshot = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.HIGH,
        entry_permission=EntryPermission.REDUCE_SIZE,
        max_risk_multiplier=Decimal("0.5"),
        evaluated_at=now,
    )
    res2 = evaluator.evaluate(
        snapshot=reduce_snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("0.8"),
        evaluation_timestamp=now,
    )
    assert res2.allowed is True
    assert res2.approved_multiplier == Decimal("0.5")
    assert res2.approved_multiplier <= Decimal("0.8")


# ── Test 7: Evaluator không gọi wall clock nội bộ ─────────────────────────────

def test_7_evaluator_never_calls_wall_clock():
    # 7a. Static verification: inspect source code of evaluate method
    import btc_scraper.trading.event_risk_policy as erp
    src = inspect.getsource(erp.RiskPolicyEvaluator.evaluate)
    assert "datetime.now" not in src
    assert ".now(" not in src
    assert "time.time" not in src

    # 7b. Dynamic verification: evaluation depends strictly on evaluation_timestamp
    evaluator = erp.RiskPolicyEvaluator()
    eval_window = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    expired_window = datetime(2020, 1, 1, 15, 0, 0, tzinfo=timezone.utc)

    # Snapshot created with past timestamp (year 2020)
    past_snapshot = _make_event_risk_snapshot(
        evaluated_at=eval_window,
        expires_at=eval_window + timedelta(hours=2),  # expires at 14:00
    )

    # When evaluated at 13:00 (before expiry), it must be allowed regardless of current real wall clock
    res_valid = evaluator.evaluate(
        snapshot=past_snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=eval_window + timedelta(hours=1),
    )
    assert res_valid.allowed is True
    assert res_valid.reason == EventRiskPolicyReason.EVENT_RISK_ALLOWED

    # When evaluated at 15:00 (after expiry), it must be blocked regardless of current real wall clock
    res_expired = evaluator.evaluate(
        snapshot=past_snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=expired_window,
    )
    assert res_expired.allowed is False
    assert res_expired.reason == EventRiskPolicyReason.STALE_SNAPSHOT_BLOCK


# ── Test 8: Fixed timestamp tạo deterministic result ──────────────────────────

def test_8_fixed_timestamp_deterministic_result():
    evaluator = RiskPolicyEvaluator()
    now = datetime(2026, 11, 5, 14, 0, 0, tzinfo=timezone.utc)
    snapshot = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.ELEVATED,
        entry_permission=EntryPermission.REDUCE_SIZE,
        max_risk_multiplier=Decimal("0.75"),
        evaluated_at=now,
    )

    base = evaluator.evaluate(
        snapshot=snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=now,
    )

    for _ in range(100):
        res = evaluator.evaluate(
            snapshot=snapshot,
            intent=OrderIntent.ENTRY,
            requested_multiplier=Decimal("1.0"),
            evaluation_timestamp=now,
        )
        assert res.allowed == base.allowed
        assert res.approved_multiplier == base.approved_multiplier
        assert res.reason == base.reason
        assert res.snapshot_hash == base.snapshot_hash
        assert res.to_dict() == base.to_dict()


# ── Test 9: Policy mismatch/stale/missing giữ nguyên stable reason ────────────

def test_9_stable_rejection_reasons_preserved():
    evaluator = RiskPolicyEvaluator(current_policy_version="event-risk-v1")
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 9a. Policy mismatch
    mismatch_snap = _make_event_risk_snapshot(
        risk_policy_version="deprecated-v0",
        evaluated_at=now,
    )
    res_mismatch = evaluator.evaluate(
        snapshot=mismatch_snap,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=now,
    )
    assert res_mismatch.reason == EventRiskPolicyReason.POLICY_VERSION_MISMATCH

    # 9b. Stale snapshot block
    stale_snap = _make_event_risk_snapshot(
        evaluated_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=30),
    )
    res_stale = evaluator.evaluate(
        snapshot=stale_snap,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=now,
    )
    assert res_stale.reason == EventRiskPolicyReason.STALE_SNAPSHOT_BLOCK

    # 9c. Missing snapshot
    res_missing = evaluator.evaluate(
        snapshot=None,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=now,
    )
    assert res_missing.reason == EventRiskPolicyReason.MISSING_EVENT_RISK_SNAPSHOT


# ── Test 10: RuntimeEvidenceStore readback trả đúng snapshot & evaluation result

def test_10_runtime_evidence_store_readback(tmp_path):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # Insert hermetic prediction and causal final decision directly to satisfy foreign keys
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-readback-1", json.dumps({"prediction_id": "pred-readback-1"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-100", "pred-readback-1", json.dumps({"decision_id": "cfd-100", "prediction_id": "pred-readback-1"}), "cfd-sha", now.isoformat()),
        )

    snapshot = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.HIGH,
        entry_permission=EntryPermission.REDUCE_SIZE,
        max_risk_multiplier=Decimal("0.5"),
        evaluated_at=now,
    )
    evaluator = RiskPolicyEvaluator()
    ev_result = evaluator.evaluate(
        snapshot=snapshot,
        intent=OrderIntent.ENTRY,
        requested_multiplier=Decimal("1.0"),
        evaluation_timestamp=now,
    )

    evidence_record = {
        "entry_decision_id": "ed-readback-100",
        "prediction_id": "pred-readback-1",
        "causal_final_decision_id": "cfd-100",
        "eligible": True,
        "action": "BUY",
        "event_risk": snapshot.to_dict(),
        "event_risk_result": ev_result.to_dict(),
        "evaluation_timestamp": now.isoformat(),
        "risk_state_version": snapshot.risk_state_version,
        "risk_policy_version": snapshot.risk_policy_version,
        "snapshot_payload": snapshot.to_dict(),
        "snapshot_hash": ev_result.snapshot_hash,
    }

    store.append_entry_decision_evidence(evidence_record)

    # Readback by prediction_id
    readback = store.get_entry_decision_evidence("pred-readback-1")
    assert readback is not None
    assert readback["entry_decision_id"] == "ed-readback-100"
    assert readback["prediction_id"] == "pred-readback-1"
    assert readback["causal_final_decision_id"] == "cfd-100"
    assert readback["event_risk"]["risk_level"] == "HIGH"
    assert readback["event_risk"]["max_risk_multiplier"] == "0.5"
    assert readback["event_risk_result"]["approved_multiplier"] == "0.5"
    assert readback["event_risk_result"]["reason"] == "event_risk_size_reduced"
    assert readback["evidence_sha256"] is not None

    # Readback by entry_decision_id
    readback_by_id = store.get_entry_decision_evidence_by_id("ed-readback-100")
    assert readback_by_id is not None
    assert readback_by_id["entry_decision_id"] == "ed-readback-100"


# ── Test 11: Existing final decision không bị mutate & idempotency/conflict ───

def test_11_existing_final_decision_unmutated_and_idempotency(tmp_path):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # Insert hermetic prediction directly to satisfy foreign keys
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-immutable-1", json.dumps({"prediction_id": "pred-immutable-1"}), "pred-sha", now.isoformat()),
        )

    # Append causal final decision
    final_decision = {
        "decision_id": "cfd-original",
        "prediction_id": "pred-immutable-1",
        "action": "BUY",
        "eligible": True,
        "terminal_status": "TRADE",
        "cycle_id": "cycle-1",
    }
    store.append_final_decision(final_decision)
    original_final = store.get_committed_final_decision("pred-immutable-1")
    assert original_final is not None
    original_sha = original_final["decision_sha256"]

    # Append entry decision evidence
    evidence = {
        "entry_decision_id": "ed-entry-1",
        "prediction_id": "pred-immutable-1",
        "causal_final_decision_id": "cfd-original",
        "eligible": True,
        "action": "BUY",
        "event_risk": {"risk_level": "NORMAL"},
        "event_risk_result": {"allowed": True},
    }
    store.append_entry_decision_evidence(evidence)

    # Verify original final decision was NOT mutated
    after_final = store.get_committed_final_decision("pred-immutable-1")
    assert after_final == original_final
    assert after_final["decision_sha256"] == original_sha

    # Idempotent duplicate entry evidence with identical payload succeeds
    store.append_entry_decision_evidence(evidence)  # No exception

    # Conflicting duplicate entry evidence with differing payload is rejected
    conflicting_evidence = copy.deepcopy(evidence)
    conflicting_evidence["eligible"] = False
    with pytest.raises(ValueError, match="duplicate"):
        store.append_entry_decision_evidence(conflicting_evidence)


# ── Test 12: Overlay off không tạo thêm evidence record ───────────────────────

def test_12_overlay_off_creates_zero_evidence_record(tmp_path, monkeypatch):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: store,
    )

    trader = _make_trader()
    analysis = _make_valid_analysis("BTC")
    assert "event_risk" not in analysis

    # Spy on append_entry_decision_evidence to assert it is never called
    calls = []
    original_append = store.append_entry_decision_evidence
    def spy_append(ev):
        calls.append(ev)
        return original_append(ev)
    monkeypatch.setattr(store, "append_entry_decision_evidence", spy_append)

    # Evaluate with overlay off
    decision = trader.build_entry_decision(analysis, "BTC", event_risk=None)
    assert decision.eligible is True
    assert decision.event_risk is None
    assert decision.event_risk_result is None

    # Assert append was NEVER called and zero records exist in store
    assert len(calls) == 0
    readback = store.get_entry_decision_evidence("pred-test-1")
    assert readback is None


# ── Test 13: Zero network và không phụ thuộc collector ────────────────────────

def test_13_zero_network_hermetic_execution(monkeypatch):
    import socket

    def guarded_socket(*args, **kwargs):
        raise RuntimeError("Forbidden network socket call detected in hermetic test!")

    monkeypatch.setattr(socket, "socket", guarded_socket)

    trader = _make_trader()
    analysis = _make_valid_analysis("BTC")
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    snapshot = _make_event_risk_snapshot(evaluated_at=now)

    # Must complete cleanly without any network or external database
    decision = trader.build_entry_decision(
        analysis,
        "BTC",
        event_risk=snapshot,
        evaluation_time=now,
    )
    assert decision.eligible is True
    assert decision.event_risk is not None
    assert decision.event_risk_result is not None
    assert decision.event_risk_result.allowed is True


# ── Additional Integration Tests (P0-B Remediation & Guarantees) ─────────────

def _setup_evidence_environment(tmp_path, monkeypatch, pred_id="pred-prod-1", cfd_id="cfd-prod-1"):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: store,
    )
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "1")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "deploy-test-1")
    monkeypatch.setenv("BTC_PAPER_RUN_ID", "deploy-test-1")

    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    final_dec = {
        "decision_id": cfd_id,
        "prediction_id": pred_id,
        "action": "BUY",
        "terminal_status": "TRADE",
        "eligible": True,
        "superseded": False,
        "decision_sha256": "dsha-12345",
        "cycle_id": "cycle-test-1",
        "deployment_id": "deploy-test-1",
        "paper_run_id": "deploy-test-1",
        "meta_probability": 0.85,
        "execution_probability": 0.85,
    }
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            (pred_id, json.dumps({"prediction_id": pred_id}), "pred-sha", now.isoformat()),
        )
    store.append_final_decision(final_dec)

    analysis = _make_valid_analysis("BTC")
    analysis.update({
        "prediction_id": pred_id,
        "cycle_id": "cycle-test-1",
        "deployment_id": "deploy-test-1",
        "paper_run_id": "deploy-test-1",
        "decision_id": cfd_id,
        "causal_decision": final_dec,
        "evaluation_time": now.isoformat(),
    })
    return store, analysis, now


def test_14_runtime_evidence_on_valid_allow_overlay_single_record(tmp_path, monkeypatch):
    store, analysis, now = _setup_evidence_environment(tmp_path, monkeypatch)
    trader = _make_trader()
    snapshot = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.NORMAL,
        entry_permission=EntryPermission.ALLOW,
        max_risk_multiplier=Decimal("1.0"),
        evaluated_at=now,
    )

    decision = trader.build_entry_decision(
        analysis,
        "BTC",
        event_risk=snapshot,
        evaluation_time=now,
    )
    assert decision.eligible is True
    assert decision.rejection_reason is None

    readback = store.get_entry_decision_evidence("pred-prod-1")
    assert readback is not None
    assert readback["prediction_id"] == "pred-prod-1"
    assert readback["causal_final_decision_id"] == "cfd-prod-1"
    assert readback["eligible"] is True
    assert readback["rejection_reason"] is None
    assert readback["event_risk_result"]["allowed"] is True
    assert readback["event_risk_result"]["approved_multiplier"] == "1.0"


def test_15_runtime_evidence_on_block_stale_mismatch_rejection_and_evidence(tmp_path, monkeypatch):
    trader = _make_trader()

    # 15a. BLOCK snapshot
    store1, analysis1, now1 = _setup_evidence_environment(tmp_path / "t1", monkeypatch, pred_id="pred-block-1", cfd_id="cfd-block-1")
    block_snap = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.CRITICAL,
        entry_permission=EntryPermission.BLOCK,
        max_risk_multiplier=Decimal("0.0"),
        evaluated_at=now1,
    )
    dec1 = trader.build_entry_decision(analysis1, "BTC", event_risk=block_snap, evaluation_time=now1)
    assert dec1.eligible is False
    assert dec1.rejection_reason == EntryRejectionReason.EVENT_RISK_BLOCKED
    readback1 = store1.get_entry_decision_evidence("pred-block-1")
    assert readback1 is not None
    assert readback1["rejection_reason"] == "event_risk_blocked"
    assert readback1["event_risk_result"]["reason"] == "event_risk_blocked"

    # 15b. Stale snapshot
    store2, analysis2, now2 = _setup_evidence_environment(tmp_path / "t2", monkeypatch, pred_id="pred-stale-1", cfd_id="cfd-stale-1")
    stale_snap = _make_event_risk_snapshot(
        evaluated_at=now2 - timedelta(hours=3),
        expires_at=now2 - timedelta(minutes=10),
    )
    dec2 = trader.build_entry_decision(analysis2, "BTC", event_risk=stale_snap, evaluation_time=now2)
    assert dec2.eligible is False
    assert dec2.rejection_reason == EntryRejectionReason.EVENT_RISK_BLOCKED
    readback2 = store2.get_entry_decision_evidence("pred-stale-1")
    assert readback2 is not None
    assert readback2["event_risk_result"]["reason"] == "stale_snapshot_block"

    # 15c. Version mismatch
    store3, analysis3, now3 = _setup_evidence_environment(tmp_path / "t3", monkeypatch, pred_id="pred-ver-1", cfd_id="cfd-ver-1")
    mismatch_snap = _make_event_risk_snapshot(
        risk_policy_version="deprecated-v0",
        evaluated_at=now3,
    )
    dec3 = trader.build_entry_decision(analysis3, "BTC", event_risk=mismatch_snap, evaluation_time=now3)
    assert dec3.eligible is False
    assert dec3.rejection_reason == EntryRejectionReason.EVENT_RISK_BLOCKED
    readback3 = store3.get_entry_decision_evidence("pred-ver-1")
    assert readback3 is not None
    assert readback3["event_risk_result"]["reason"] == "policy_version_mismatch"


def test_16_missing_or_wrong_causal_final_decision_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 16a. Store API rejected when prediction unknown
    with pytest.raises(ValueError, match="unknown prediction"):
        store.append_entry_decision_evidence({
            "entry_decision_id": "eed-unknown",
            "prediction_id": "pred-nonexistent",
            "causal_final_decision_id": "cfd-x",
        })

    # Seed valid prediction
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-c1", json.dumps({"prediction_id": "pred-c1"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-c2", json.dumps({"prediction_id": "pred-c2"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-c1", "pred-c1", json.dumps({"decision_id": "cfd-c1", "prediction_id": "pred-c1"}), "cfd-sha", now.isoformat()),
        )

    # 16b. Store API rejected when causal_final_decision_id unknown
    with pytest.raises(ValueError, match="causal final decision not found"):
        store.append_entry_decision_evidence({
            "entry_decision_id": "eed-c1",
            "prediction_id": "pred-c1",
            "causal_final_decision_id": "cfd-nonexistent",
        })

    # 16c. Store API rejected when causal_final_decision belongs to wrong prediction
    with pytest.raises(ValueError, match="does not belong to prediction"):
        store.append_entry_decision_evidence({
            "entry_decision_id": "eed-c2",
            "prediction_id": "pred-c2",
            "causal_final_decision_id": "cfd-c1",  # belongs to pred-c1
        })

    # 16d. Production path rejects when causal decision missing
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: store,
    )
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "1")
    trader = _make_trader()
    analysis = _make_valid_analysis("BTC")
    analysis.update({
        "prediction_id": "pred-c2",  # has no final decision in store
        "evaluation_time": now.isoformat(),
    })
    dec = trader.build_entry_decision(analysis, "BTC")
    assert dec.eligible is False
    assert dec.rejection_reason == EntryRejectionReason.MISSING_FINAL_DECISION


def test_17_persistence_exception_is_not_swallowed(tmp_path, monkeypatch):
    store, analysis, now = _setup_evidence_environment(tmp_path, monkeypatch)
    trader = _make_trader()
    snapshot = _make_event_risk_snapshot(evaluated_at=now)

    def failing_append(*args, **kwargs):
        raise IOError("Disk corruption simulated in evidence store")

    monkeypatch.setattr(store, "append_entry_decision_evidence", failing_append)

    with pytest.raises(IOError, match="Disk corruption simulated"):
        trader.build_entry_decision(analysis, "BTC", event_risk=snapshot, evaluation_time=now)


def test_18_three_distinct_identities(tmp_path, monkeypatch):
    store, analysis, now = _setup_evidence_environment(tmp_path, monkeypatch)
    trader = _make_trader()
    snapshot = _make_event_risk_snapshot(evaluated_at=now)

    decision = trader.build_entry_decision(analysis, "BTC", event_risk=snapshot, evaluation_time=now)
    assert decision.eligible is True

    readback = store.get_entry_decision_evidence("pred-prod-1")
    assert readback is not None

    entry_id = readback["entry_decision_id"]
    pred_id = readback["prediction_id"]
    cfd_id = readback["causal_final_decision_id"]

    assert bool(entry_id) and bool(pred_id) and bool(cfd_id)
    assert entry_id != cfd_id
    assert entry_id != pred_id
    assert cfd_id != pred_id


def test_19_malformed_overlay_creates_zero_canonical_evidence(tmp_path, monkeypatch):
    store, analysis, now = _setup_evidence_environment(tmp_path, monkeypatch)
    trader = _make_trader()

    analysis["event_risk"] = {"invalid": "malformed_schema"}
    decision = trader.build_entry_decision(analysis, "BTC", evaluation_time=now)

    assert decision.eligible is False
    assert decision.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT

    # Zero canonical entry evidence created
    readback = store.get_entry_decision_evidence("pred-prod-1")
    assert readback is None

    # Audit event recorded
    with store.transaction() as db:
        row = db.execute(
            "SELECT event_type FROM audit_events WHERE event_type='INVALID_EVENT_RISK_SNAPSHOT_REJECTED'"
        ).fetchone()
        assert row is not None


def test_20_cross_process_identical_retry_idempotent(tmp_path):
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-idem-1", json.dumps({"prediction_id": "pred-idem-1"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-idem-1", "pred-idem-1", json.dumps({"decision_id": "cfd-idem-1", "prediction_id": "pred-idem-1"}), "cfd-sha", now.isoformat()),
        )

    base_payload = {
        "entry_decision_id": "eed-idem-1",
        "prediction_id": "pred-idem-1",
        "causal_final_decision_id": "cfd-idem-1",
        "eligible": True,
        "action": "BUY",
        "event_risk": {"risk_level": "NORMAL"},
        "event_risk_result": {"allowed": True},
    }

    # Process A writes
    proc_a_payload = dict(base_payload)
    proc_a_payload["process_id"] = 1234
    proc_a_payload["hostname"] = "host-alpha"
    proc_a_payload["started_at"] = "2026-11-05T00:00:00Z"
    store.append_entry_decision_evidence(proc_a_payload)

    # Process B retries identical semantic payload from different host/pid
    proc_b_payload = dict(base_payload)
    proc_b_payload["process_id"] = 9999
    proc_b_payload["hostname"] = "host-beta"
    proc_b_payload["started_at"] = "2026-11-05T01:00:00Z"
    store.append_entry_decision_evidence(proc_b_payload)  # Succeeded idempotently

    # Conflicting semantic payload fails
    conflicting = dict(base_payload)
    conflicting["action"] = "SELL"
    with pytest.raises(ValueError, match="duplicate"):
        store.append_entry_decision_evidence(conflicting)


def test_21_direct_constructor_invalid_enums_rejected():
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 21a. Invalid risk_level
    with pytest.raises(EventRiskContractError, match="risk_level must be an EventRiskLevel enum"):
        EventRiskDecision(
            risk_level="NORMAL",  # str instead of enum
            entry_permission=EntryPermission.ALLOW,
            position_action=PositionAction.NONE,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="v1",
            risk_policy_version="v1",
            evaluated_at=now,
        )

    # 21b. Invalid entry_permission
    with pytest.raises(EventRiskContractError, match="entry_permission must be an EntryPermission enum"):
        EventRiskDecision(
            risk_level=EventRiskLevel.NORMAL,
            entry_permission="ALLOW",  # str instead of enum
            position_action=PositionAction.NONE,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="v1",
            risk_policy_version="v1",
            evaluated_at=now,
        )

    # 21c. Invalid position_action
    with pytest.raises(EventRiskContractError, match="position_action must be a PositionAction enum"):
        EventRiskDecision(
            risk_level=EventRiskLevel.NORMAL,
            entry_permission=EntryPermission.ALLOW,
            position_action=None,
            max_risk_multiplier=Decimal("1.0"),
            risk_state_version="v1",
            risk_policy_version="v1",
            evaluated_at=now,
        )


def test_22_from_dict_rejects_none_versions_and_non_string_reasons():
    valid_dict = {
        "risk_level": "NORMAL",
        "entry_permission": "ALLOW",
        "position_action": "NONE",
        "max_risk_multiplier": "1.0",
        "risk_state_version": "v1",
        "risk_policy_version": "v1",
        "evaluated_at": "2026-11-05T12:00:00+00:00",
        "reason_codes": ["TEST"],
    }

    # None risk_state_version
    d1 = dict(valid_dict, risk_state_version=None)
    with pytest.raises(EventRiskContractError, match="risk_state_version must be a non-empty string"):
        EventRiskDecision.from_dict(d1)

    # Numeric risk_policy_version
    d2 = dict(valid_dict, risk_policy_version=123)
    with pytest.raises(EventRiskContractError, match="risk_policy_version must be a non-empty string"):
        EventRiskDecision.from_dict(d2)

    # Numeric reason code inside list
    d3 = dict(valid_dict, reason_codes=[123])
    with pytest.raises(EventRiskContractError, match="reason_codes entries must be non-empty strings"):
        EventRiskDecision.from_dict(d3)

    # None reason code inside list
    d4 = dict(valid_dict, reason_codes=[None])
    with pytest.raises(EventRiskContractError, match="reason_codes entries must be non-empty strings"):
        EventRiskDecision.from_dict(d4)


def test_23_invalid_or_naive_evaluation_time_fails_closed_no_wall_clock(tmp_path, monkeypatch):
    store, analysis, now = _setup_evidence_environment(tmp_path, monkeypatch)
    trader = _make_trader()
    snapshot = _make_event_risk_snapshot(evaluated_at=now)

    # 23a. Missing evaluation_time with overlay present
    analysis_no_ts = dict(analysis)
    analysis_no_ts.pop("evaluation_time", None)
    analysis_no_ts.pop("timestamp", None)
    dec1 = trader.build_entry_decision(analysis_no_ts, "BTC", event_risk=snapshot, evaluation_time=None)
    assert dec1.eligible is False
    assert dec1.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT

    # 23b. Naive evaluation_time with overlay present
    naive_ts = datetime(2026, 11, 5, 12, 0, 0)
    dec2 = trader.build_entry_decision(analysis, "BTC", event_risk=snapshot, evaluation_time=naive_ts)
    assert dec2.eligible is False
    assert dec2.rejection_reason == EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT

    # 23c. Overlay absent keeps P0-A baseline working without requiring aware evaluation_time
    dec_baseline = trader.build_entry_decision(analysis_no_ts, "BTC", event_risk=None)
    assert dec_baseline.eligible is True


def test_24_protective_intents_guarantee():
    evaluator = RiskPolicyEvaluator()
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # CRITICAL + BLOCK snapshot
    critical_snap = _make_event_risk_snapshot(
        risk_level=EventRiskLevel.CRITICAL,
        entry_permission=EntryPermission.BLOCK,
        max_risk_multiplier=Decimal("0.0"),
        evaluated_at=now,
    )

    for protective_intent in (OrderIntent.REDUCE, OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT):
        # 24a. Normal requested multiplier
        res = evaluator.evaluate(
            snapshot=critical_snap,
            intent=protective_intent,
            requested_multiplier=Decimal("1.0"),
            evaluation_timestamp=now,
        )
        assert res.allowed is True
        assert res.approved_multiplier == Decimal("1.0")
        assert res.reason == EventRiskPolicyReason.EXIT_INTENT_UNBLOCKED

        # 24b. Invalid requested multiplier (-1.0 or NaN) still unblocked with safe 1.0 multiplier
        res_bad = evaluator.evaluate(
            snapshot=critical_snap,
            intent=protective_intent,
            requested_multiplier=Decimal("-1.0"),
            evaluation_timestamp=now,
        )
        assert res_bad.allowed is True
        assert res_bad.approved_multiplier == Decimal("1.0")
        assert res_bad.reason == EventRiskPolicyReason.EXIT_INTENT_UNBLOCKED


def test_25_atomic_concurrency_barrier(tmp_path):
    import threading
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # Seed prediction and final decision
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-conc-1", json.dumps({"prediction_id": "pred-conc-1"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-conc-1", "pred-conc-1", json.dumps({"decision_id": "cfd-conc-1", "prediction_id": "pred-conc-1"}), "cfd-sha", now.isoformat()),
        )

    # 25a. Concurrent writers with identical semantic payload
    barrier_a = threading.Barrier(2)
    results_a = []
    errors_a = []

    def worker_identical(worker_id):
        try:
            barrier_a.wait(timeout=5)
            store.append_entry_decision_evidence({
                "entry_decision_id": "eed-conc-1",
                "prediction_id": "pred-conc-1",
                "causal_final_decision_id": "cfd-conc-1",
                "eligible": True,
                "action": "BUY",
                "event_risk": {"risk_level": "NORMAL"},
                "event_risk_result": {"allowed": True},
                "process_id": 1000 + worker_id,
            })
            results_a.append(worker_id)
        except Exception as e:
            errors_a.append((worker_id, e))

    t1 = threading.Thread(target=worker_identical, args=(1,))
    t2 = threading.Thread(target=worker_identical, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(errors_a) == 0, f"Unexpected errors in identical workers: {errors_a}"
    assert len(results_a) == 2, "Both workers should succeed idempotently"

    # Exactly 1 row in entry_decision_evidence
    with store.transaction() as db:
        rows = db.execute("SELECT COUNT(*) FROM entry_decision_evidence WHERE prediction_id='pred-conc-1'").fetchone()[0]
        assert rows == 1

        # Exactly 1 audit event recorded (idempotent retry did not write second audit event)
        audit_count = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='ENTRY_DECISION_EVIDENCE_RECORDED' AND json_extract(payload, '$.prediction_id')='pred-conc-1'"
        ).fetchone()[0]
        assert audit_count == 1

    # 25b. Concurrent writers with conflicting payloads
    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-conc-2", json.dumps({"prediction_id": "pred-conc-2"}), "pred-sha", now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-conc-2", "pred-conc-2", json.dumps({"decision_id": "cfd-conc-2", "prediction_id": "pred-conc-2"}), "cfd-sha", now.isoformat()),
        )

    barrier_b = threading.Barrier(2)
    results_b = []
    errors_b = []

    def worker_conflicting(worker_id, action):
        try:
            barrier_b.wait(timeout=5)
            store.append_entry_decision_evidence({
                "entry_decision_id": f"eed-conc-2-{worker_id}",
                "prediction_id": "pred-conc-2",
                "causal_final_decision_id": "cfd-conc-2",
                "eligible": True,
                "action": action,
                "event_risk": {"risk_level": "NORMAL"},
                "event_risk_result": {"allowed": True},
                "process_id": 2000 + worker_id,
            })
            results_b.append(worker_id)
        except Exception as e:
            errors_b.append((worker_id, e))

    tb1 = threading.Thread(target=worker_conflicting, args=(1, "BUY"))
    tb2 = threading.Thread(target=worker_conflicting, args=(2, "SELL"))
    tb1.start()
    tb2.start()
    tb1.join(timeout=10)
    tb2.join(timeout=10)

    # Exactly 1 succeeds, exactly 1 gets conflict error
    assert len(results_b) == 1, f"Expected 1 success, got {len(results_b)}"
    assert len(errors_b) == 1, f"Expected 1 conflict error, got {len(errors_b)}"
    assert isinstance(errors_b[0][1], ValueError)
    assert "conflicting" in str(errors_b[0][1]) or "duplicate" in str(errors_b[0][1])


def test_26_hash_integrity_and_tamper_detection(tmp_path):
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import _canonical
    db_path = tmp_path / "evidence_store.db"
    store = RuntimeEvidenceStore(db_path)
    now = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Seed predictions and final_decisions with canonical payload and real SHA-256
    pred_data = {"prediction_id": "pred-hash-1", "symbol": "BTC"}
    pred_canon = _canonical(pred_data)
    pred_sha = hashlib.sha256(pred_canon.encode("utf-8")).hexdigest()

    cfd_data = {"decision_id": "cfd-hash-1", "prediction_id": "pred-hash-1", "action": "BUY"}
    cfd_canon = _canonical(cfd_data)
    cfd_sha = hashlib.sha256(cfd_canon.encode("utf-8")).hexdigest()

    with store.transaction() as db:
        db.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?)",
            ("pred-hash-1", pred_canon, pred_sha, now.isoformat()),
        )
        db.execute(
            "INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)",
            ("cfd-hash-1", "pred-hash-1", cfd_canon, cfd_sha, now.isoformat()),
        )

    evidence = {
        "entry_decision_id": "eed-hash-1",
        "prediction_id": "pred-hash-1",
        "causal_final_decision_id": "cfd-hash-1",
        "eligible": True,
        "action": "BUY",
        "event_risk": {"risk_level": "NORMAL"},
        "event_risk_result": {"allowed": True},
    }
    store.append_entry_decision_evidence(evidence)

    # 2. Readback evidence_sha256 matches canonical hash of returned payload
    readback = store.get_entry_decision_evidence("pred-hash-1")
    assert readback is not None
    ev_sha = readback.pop("evidence_sha256")
    canonical_rb = json.dumps(readback, sort_keys=True, separators=(",", ":"))
    expected_hash = hashlib.sha256(canonical_rb.encode("utf-8")).hexdigest()
    assert ev_sha == expected_hash

    # 3. Before tamper: fresh store has count_corrupt_payloads == 0
    assert store.count_corrupt_payloads() == 0

    # 4. Tamper payload directly in SQLite database
    with store.transaction() as db:
        db.execute(
            "UPDATE entry_decision_evidence SET payload='{\"tampered\": true}' WHERE entry_decision_id='eed-hash-1'"
        )

    # 5. Tampered payload is detected
    assert store.count_corrupt_payloads() == 1

    # 6. verify_and_quarantine quarantines the corrupt record
    quarantined_count = store.verify_and_quarantine()
    assert quarantined_count == 1

    # Semantics: count_corrupt_payloads continues to count corrupt records even after quarantine,
    # because quarantine does not repair the corrupt payload in the underlying table
    assert store.count_corrupt_payloads() == 1

    # Quarantine entry exists
    with store.transaction() as db:
        q_row = db.execute(
            "SELECT reason FROM evidence_quarantine WHERE table_name='entry_decision_evidence' AND record_id='eed-hash-1'"
        ).fetchone()
        assert q_row is not None
        assert q_row[0] == "payload_sha256_mismatch"

    # Raw quarantined payload is preserved in evidence_quarantine_payloads
    q_payload = store.get_quarantined_payload("entry_decision_evidence", "eed-hash-1")
    assert q_payload is not None
    assert q_payload["original_payload"] == '{"tampered": true}'
    assert q_payload["quarantine_reason"] == "payload_sha256_mismatch"

    # Eligible/read APIs MUST exclude quarantined records
    assert store.get_entry_decision_evidence("pred-hash-1") is None
    assert store.get_entry_decision_evidence_by_id("eed-hash-1") is None


def test_27_legacy_schema_migration_preserves_valid_and_quarantines_invalid(tmp_path):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import (
        _canonical,
        idempotency_payload_sha256,
    )
    db_path = tmp_path / "legacy_evidence.db"
    now_str = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    # Legacy v6 valid evidence with volatile fields
    legacy_valid_payload_dict = {
        "entry_decision_id": "eed-leg-valid",
        "prediction_id": "pred-leg-1",
        "causal_final_decision_id": "cfd-leg-1",
        "action": "BUY",
        "process_id": 99999,
        "hostname": "legacy-worker-01",
        "runtime_id": "run-leg-v6",
        "started_at": now_str,
    }
    legacy_canon_str = _canonical(legacy_valid_payload_dict)
    old_semantic_hash = idempotency_payload_sha256(legacy_valid_payload_dict)
    full_payload_hash = hashlib.sha256(legacy_canon_str.encode("utf-8")).hexdigest()

    # Prove old semantic digest differs from full payload hash due to volatile metadata
    assert old_semantic_hash != full_payload_hash

    pred_str = _canonical({"prediction_id": "pred-leg-1"})
    pred_sha = hashlib.sha256(pred_str.encode("utf-8")).hexdigest()
    cfd_str = _canonical({"decision_id": "cfd-leg-1", "prediction_id": "pred-leg-1"})
    cfd_sha = hashlib.sha256(cfd_str.encode("utf-8")).hexdigest()

    invalid_dict = {"invalid": True}
    invalid_canon_str = _canonical(invalid_dict)
    invalid_payload_sha = hashlib.sha256(invalid_canon_str.encode("utf-8")).hexdigest()

    # Create legacy database without causal_final_decision_id FK constraint (schema version 6)
    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA user_version = 6;
            CREATE TABLE predictions (
                prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE final_decisions (
                decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE entry_decision_evidence (
                entry_decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                causal_final_decision_id TEXT, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE evidence_quarantine (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
            );
            CREATE TABLE evidence_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                resolved_at TEXT
            );

            -- Seed prediction and final decision with canonical hashes
            INSERT INTO predictions VALUES ('pred-leg-1', '{pred_str}', '{pred_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-leg-1', 'pred-leg-1', '{cfd_str}', '{cfd_sha}', '{now_str}');

            -- Valid legacy entry decision evidence stored with v6 semantic hash
            INSERT INTO entry_decision_evidence VALUES ('eed-leg-valid', 'pred-leg-1', 'cfd-leg-1', '{legacy_canon_str}', '{old_semantic_hash}', '{now_str}');

            -- Invalid legacy entry decision evidence (referencing non-existent causal decision, but uncorrupted payload)
            INSERT INTO entry_decision_evidence VALUES ('eed-leg-invalid', 'pred-leg-1', 'cfd-ghost', '{invalid_canon_str}', '{invalid_payload_sha}', '{now_str}');
        """)

    # Initialize RuntimeEvidenceStore on the legacy DB
    store = RuntimeEvidenceStore(db_path)

    with store._connect(db_path) as db:
        # 1. user_version bumped to 7
        ver = db.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 7

        # 2. Foreign key to final_decisions exists
        fks = db.execute("PRAGMA foreign_key_list(entry_decision_evidence)").fetchall()
        has_causal_fk = any(row[2] == "final_decisions" and row[3] == "causal_final_decision_id" for row in fks)
        assert has_causal_fk is True

        # 3. Valid record preserved
        valid_row = db.execute(
            "SELECT entry_decision_id, payload_sha256 FROM entry_decision_evidence WHERE entry_decision_id='eed-leg-valid'"
        ).fetchone()
        assert valid_row is not None
        # Proves migration recalculated exact full payload hash from stored payload string
        assert valid_row[1] == full_payload_hash

        # 4. Valid record is NOT flagged as corrupt after migration
        assert store.count_corrupt_payloads() == 0

        # 5. Invalid record was quarantined, not silent-dropped
        invalid_in_table = db.execute(
            "SELECT entry_decision_id FROM entry_decision_evidence WHERE entry_decision_id='eed-leg-invalid'"
        ).fetchone()
        assert invalid_in_table is None

        quarantine_row = db.execute(
            "SELECT reason FROM evidence_quarantine WHERE record_id='eed-leg-invalid'"
        ).fetchone()
        assert quarantine_row is not None
        assert "invalid_causal" in quarantine_row[0]

        # 6. Raw invalid payload is preserved in evidence_quarantine_payloads
        q_payload = store.get_quarantined_payload("entry_decision_evidence", "eed-leg-invalid")
        assert q_payload is not None
        assert q_payload["original_payload"] == invalid_canon_str
        assert q_payload["original_payload_sha256"] == invalid_payload_sha

    # 7. Migration is idempotent on second initialization
    store2 = RuntimeEvidenceStore(db_path)
    with store2._connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT COUNT(*) FROM entry_decision_evidence").fetchone()[0] == 1


def test_28_legacy_migration_duplicate_handling_deterministic(tmp_path):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import _canonical
    db_path = tmp_path / "dup_migration.db"
    now_str = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    earlier_str = datetime(2026, 11, 5, 11, 0, 0, tzinfo=timezone.utc).isoformat()

    p1_payload = _canonical({"prediction_id": "pred-dup-1"})
    p1_sha = hashlib.sha256(p1_payload.encode("utf-8")).hexdigest()
    f1_payload = _canonical({"decision_id": "cfd-dup-1", "prediction_id": "pred-dup-1"})
    f1_sha = hashlib.sha256(f1_payload.encode("utf-8")).hexdigest()

    pm_payload = _canonical({"prediction_id": "pred-mix-1"})
    pm_sha = hashlib.sha256(pm_payload.encode("utf-8")).hexdigest()
    fm_payload = _canonical({"decision_id": "cfd-mix-1", "prediction_id": "pred-mix-1"})
    fm_sha = hashlib.sha256(fm_payload.encode("utf-8")).hexdigest()

    loser_payload = _canonical({"loser": True})
    loser_sha = hashlib.sha256(loser_payload.encode("utf-8")).hexdigest()
    winner_payload = _canonical({"winner": True})
    winner_sha = hashlib.sha256(winner_payload.encode("utf-8")).hexdigest()

    mix_valid_payload = _canonical({"mix_valid": True})
    mix_valid_sha = hashlib.sha256(mix_valid_payload.encode("utf-8")).hexdigest()
    mix_invalid_payload = _canonical({"mix_invalid": True})
    mix_invalid_sha = hashlib.sha256(mix_invalid_payload.encode("utf-8")).hexdigest()

    missing_p_payload = _canonical({"missing_p": True})
    missing_p_sha = hashlib.sha256(missing_p_payload.encode("utf-8")).hexdigest()

    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA user_version = 6;
            CREATE TABLE predictions (
                prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE final_decisions (
                decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE entry_decision_evidence (
                entry_decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                causal_final_decision_id TEXT, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE evidence_quarantine (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
            );
            CREATE TABLE evidence_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                resolved_at TEXT
            );

            -- Simulate an interrupted migration leaving a stale table
            CREATE TABLE entry_decision_evidence_new (stale_col TEXT);

            -- Predictions & final decisions with authentic hashes
            INSERT INTO predictions VALUES ('pred-dup-1', '{p1_payload}', '{p1_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-dup-1', 'pred-dup-1', '{f1_payload}', '{f1_sha}', '{now_str}');

            INSERT INTO predictions VALUES ('pred-mix-1', '{pm_payload}', '{pm_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-mix-1', 'pred-mix-1', '{fm_payload}', '{fm_sha}', '{now_str}');

            -- Case A: pred-dup-1 has two valid rows -> winner is latest written_at ('eed-dup-winner')
            INSERT INTO entry_decision_evidence VALUES ('eed-dup-loser', 'pred-dup-1', 'cfd-dup-1', '{loser_payload}', '{loser_sha}', '{earlier_str}');
            INSERT INTO entry_decision_evidence VALUES ('eed-dup-winner', 'pred-dup-1', 'cfd-dup-1', '{winner_payload}', '{winner_sha}', '{now_str}');

            -- Case B: pred-mix-1 has one valid + one invalid row (invalid causal decision)
            INSERT INTO entry_decision_evidence VALUES ('eed-mix-valid', 'pred-mix-1', 'cfd-mix-1', '{mix_valid_payload}', '{mix_valid_sha}', '{now_str}');
            INSERT INTO entry_decision_evidence VALUES ('eed-mix-invalid', 'pred-mix-1', 'cfd-ghost', '{mix_invalid_payload}', '{mix_invalid_sha}', '{now_str}');

            -- Case C: missing prediction
            INSERT INTO entry_decision_evidence VALUES ('eed-missing-pred', 'pred-ghost', 'cfd-dup-1', '{missing_p_payload}', '{missing_p_sha}', '{now_str}');
        """)

    store = RuntimeEvidenceStore(db_path)

    with store._connect(db_path) as db:
        # Check canonical table: exactly 2 winners preserved
        rows = db.execute("SELECT entry_decision_id FROM entry_decision_evidence ORDER BY entry_decision_id").fetchall()
        assert [r[0] for r in rows] == ["eed-dup-winner", "eed-mix-valid"]

        # Check quarantine: eed-dup-loser, eed-mix-invalid, eed-missing-pred quarantined
        q_loser = store.get_quarantined_payload("entry_decision_evidence", "eed-dup-loser")
        assert q_loser is not None
        assert q_loser["quarantine_reason"] == "duplicate_prediction_during_migration"
        assert q_loser["original_payload"] == loser_payload

        q_mix_inv = store.get_quarantined_payload("entry_decision_evidence", "eed-mix-invalid")
        assert q_mix_inv is not None
        assert "invalid_causal" in q_mix_inv["quarantine_reason"]

        q_miss_pred = store.get_quarantined_payload("entry_decision_evidence", "eed-missing-pred")
        assert q_miss_pred is not None
        assert "missing_prediction" in q_miss_pred["quarantine_reason"]


def test_29_active_epoch_v6_compatibility_and_upgrade(tmp_path):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
    from btc_scraper.core.paths import runtime_deployment_id
    from btc_scraper.core.config import get_runtime_universe, analysis_universe_hash

    db_path = tmp_path / "epoch_test.db"
    store = RuntimeEvidenceStore(db_path)
    now_iso = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    dep_id = runtime_deployment_id()
    universe = get_runtime_universe().analysis_symbols
    u_hash = analysis_universe_hash(universe)

    # 1. Create a legacy ACTIVE epoch with runtime_schema_version = 6 in global index
    with store._global_transaction() as db:
        manifest = {
            "manifest_schema_version": "evidence-manifest-v1",
            "release_sha": "git-leg-1",
            "artifact_sha256": "art-leg-1",
            "metadata_sha256": "meta-leg-1",
            "registry_sha256": "reg-leg-1",
            "deployment_id": dep_id,
            "paper_run_id": dep_id,
            "feature_schema_version": "feat-v1",
            "analysis_universe": ",".join(universe),
            "decision_contract": "side-probability-v2",
            "probability_semantics": "P(up)",
        }
        manifest_str = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        manifest_hash = hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()

        db.execute("""
            INSERT INTO evidence_epochs (
                epoch_id, deployment_id, started_at, activated_at, code_commit_sha,
                model_version, artifact_sha256, feature_schema_version,
                analysis_universe, analysis_universe_hash,
                evidence_policy_version, risk_policy_version,
                runtime_schema_version, status, paper_run_id,
                release_manifest, release_manifest_sha256, runtime_pause_policy,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "epoch-legacy-v6", dep_id, now_iso, now_iso, "git-leg-1",
            "mod-v1", "art-leg-1", "feat-v1",
            json.dumps(list(universe)), u_hash,
            "evidence-v4", "risk-fail-closed-v1",
            6, "ACTIVE", dep_id,
            manifest_str, manifest_hash, "{}",
            now_iso
        ))

    # 2. Opening store does NOT mutate the active epoch
    store_reopened = RuntimeEvidenceStore(db_path)
    active_epoch = store_reopened.get_active_evidence_epoch()
    assert active_epoch is not None
    assert active_epoch.epoch_id == "epoch-legacy-v6"
    assert active_epoch.runtime_schema_version == 6  # Remains immutable version 6

    # 3. Asserting runtime epoch ready fails with stable migration-required reason
    with pytest.raises(RuntimeError) as exc_info:
        store_reopened.assert_runtime_epoch_ready()
    assert "active epoch requires schema migration" in str(exc_info.value)
    assert "runtime_schema_version 6" in str(exc_info.value)

    # 4. Explicit procedure to upgrade active epoch schema
    upgraded = store_reopened.upgrade_active_epoch_schema(7)
    assert upgraded.runtime_schema_version == 7
    assert upgraded.status == "ACTIVE"

    # 5. After upgrade, assert_runtime_epoch_ready succeeds cleanly
    ready_epoch = store_reopened.assert_runtime_epoch_ready()
    assert ready_epoch is not None
    assert ready_epoch.runtime_schema_version == 7


def test_30_tampered_legacy_record_quarantined_not_migrated(tmp_path):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import _canonical
    db_path = tmp_path / "tampered_legacy.db"
    now_str = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    pred_payload = _canonical({"prediction_id": "pred-tamp-1"})
    pred_sha = hashlib.sha256(pred_payload.encode("utf-8")).hexdigest()
    cfd_payload = _canonical({"decision_id": "cfd-tamp-1", "prediction_id": "pred-tamp-1"})
    cfd_sha = hashlib.sha256(cfd_payload.encode("utf-8")).hexdigest()

    tampered_payload = _canonical({"entry_decision_id": "eed-tamp", "action": "BUY", "tampered_field": True})
    fake_sha = "0000000000000000000000000000000000000000000000000000000000000000"

    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA user_version = 6;
            CREATE TABLE predictions (
                prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE final_decisions (
                decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE entry_decision_evidence (
                entry_decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                causal_final_decision_id TEXT, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE evidence_quarantine (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
            );
            CREATE TABLE evidence_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                resolved_at TEXT
            );

            INSERT INTO predictions VALUES ('pred-tamp-1', '{pred_payload}', '{pred_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-tamp-1', 'pred-tamp-1', '{cfd_payload}', '{cfd_sha}', '{now_str}');
            INSERT INTO entry_decision_evidence VALUES ('eed-tamp', 'pred-tamp-1', 'cfd-tamp-1', '{tampered_payload}', '{fake_sha}', '{now_str}');
        """)

    store = RuntimeEvidenceStore(db_path)

    with store._connect(db_path) as db:
        # 1. Tampered row must NOT be promoted to migrated table
        rows = db.execute("SELECT entry_decision_id FROM entry_decision_evidence").fetchall()
        assert rows == []

        # 2. Tampered row must be in quarantine with corrupt_legacy_hash_during_migration
        q_row = db.execute(
            "SELECT reason FROM evidence_quarantine WHERE record_id='eed-tamp'"
        ).fetchone()
        assert q_row is not None
        assert q_row[0] == "corrupt_legacy_hash_during_migration"

        # 3. Raw tampered payload preserved
        q_payload = store.get_quarantined_payload("entry_decision_evidence", "eed-tamp")
        assert q_payload is not None
        assert q_payload["original_payload"] == tampered_payload
        assert q_payload["original_payload_sha256"] == fake_sha

        # 4. Incident logged
        incident = db.execute(
            "SELECT incident_type FROM evidence_incidents WHERE record_id='eed-tamp'"
        ).fetchone()
        assert incident is not None
        assert incident[0] == "legacy_migration_payload_corrupt"


def test_31_malformed_json_legacy_record_quarantined(tmp_path):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import _canonical
    db_path = tmp_path / "malformed_legacy.db"
    now_str = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    pred_payload = _canonical({"prediction_id": "pred-mal-1"})
    pred_sha = hashlib.sha256(pred_payload.encode("utf-8")).hexdigest()
    cfd_payload = _canonical({"decision_id": "cfd-mal-1", "prediction_id": "pred-mal-1"})
    cfd_sha = hashlib.sha256(cfd_payload.encode("utf-8")).hexdigest()

    malformed_payload = '{"unclosed_json: true'
    stored_hash = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA user_version = 6;
            CREATE TABLE predictions (
                prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE final_decisions (
                decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE entry_decision_evidence (
                entry_decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                causal_final_decision_id TEXT, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE evidence_quarantine (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
            );
            CREATE TABLE evidence_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                resolved_at TEXT
            );

            INSERT INTO predictions VALUES ('pred-mal-1', '{pred_payload}', '{pred_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-mal-1', 'pred-mal-1', '{cfd_payload}', '{cfd_sha}', '{now_str}');
            INSERT INTO entry_decision_evidence VALUES ('eed-mal', 'pred-mal-1', 'cfd-mal-1', '{malformed_payload}', '{stored_hash}', '{now_str}');
        """)

    store = RuntimeEvidenceStore(db_path)

    with store._connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM entry_decision_evidence").fetchone()[0] == 0
        q_payload = store.get_quarantined_payload("entry_decision_evidence", "eed-mal")
        assert q_payload is not None
        assert q_payload["quarantine_reason"] == "corrupt_legacy_hash_during_migration"
        assert q_payload["original_payload"] == malformed_payload


def test_32_migration_transaction_rollback_and_retry(tmp_path, monkeypatch):
    import sqlite3
    import hashlib
    from btc_scraper.ml_engine.runtime_evidence_store import _canonical
    db_path = tmp_path / "rollback_migration.db"
    now_str = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    pred_payload = _canonical({"prediction_id": "pred-rb-1"})
    pred_sha = hashlib.sha256(pred_payload.encode("utf-8")).hexdigest()
    cfd_payload = _canonical({"decision_id": "cfd-rb-1", "prediction_id": "pred-rb-1"})
    cfd_sha = hashlib.sha256(cfd_payload.encode("utf-8")).hexdigest()
    eed_payload = _canonical({"entry_decision_id": "eed-rb-1", "action": "BUY"})
    eed_sha = hashlib.sha256(eed_payload.encode("utf-8")).hexdigest()

    with sqlite3.connect(db_path) as db:
        db.executescript(f"""
            PRAGMA user_version = 6;
            CREATE TABLE predictions (
                prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE final_decisions (
                decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE entry_decision_evidence (
                entry_decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                causal_final_decision_id TEXT, payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
            );
            CREATE TABLE evidence_quarantine (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
            );
            CREATE TABLE evidence_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                resolved_at TEXT
            );

            INSERT INTO predictions VALUES ('pred-rb-1', '{pred_payload}', '{pred_sha}', '{now_str}');
            INSERT INTO final_decisions VALUES ('cfd-rb-1', 'pred-rb-1', '{cfd_payload}', '{cfd_sha}', '{now_str}');
            INSERT INTO entry_decision_evidence VALUES ('eed-rb-1', 'pred-rb-1', 'cfd-rb-1', '{eed_payload}', '{eed_sha}', '{now_str}');
        """)

    # Fault injection: simulate failure right at table rename inside transaction
    orig_connect_path = RuntimeEvidenceStore._connect_path
    fail_once = True

    def faulty_connect_path(self, path):
        conn = orig_connect_path(self, path)
        class FaultyConn:
            def __init__(self, inner):
                self._inner = inner
            def __getattr__(self, name):
                return getattr(self._inner, name)
            def execute(self, sql, *args, **kwargs):
                nonlocal fail_once
                if fail_once and "ALTER TABLE entry_decision_evidence_new RENAME TO entry_decision_evidence" in str(sql):
                    fail_once = False
                    raise sqlite3.OperationalError("simulated crash during table rename")
                return self._inner.execute(sql, *args, **kwargs)
            def __enter__(self):
                self._inner.__enter__()
                return self
            def __exit__(self, *args):
                return self._inner.__exit__(*args)
        return FaultyConn(conn)

    monkeypatch.setattr(RuntimeEvidenceStore, "_connect_path", faulty_connect_path)

    # 1. Opening store fails due to injected fault
    with pytest.raises(sqlite3.OperationalError, match="simulated crash during table rename"):
        RuntimeEvidenceStore(db_path)

    # 2. Check DB state: rollback preserved the original table and user_version remains 6
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert db.execute("SELECT COUNT(*) FROM entry_decision_evidence").fetchone()[0] == 1
        row = db.execute("SELECT entry_decision_id FROM entry_decision_evidence").fetchone()
        assert row[0] == "eed-rb-1"

    # 3. Retry must succeed idempotently (stale entry_decision_evidence_new dropped)
    monkeypatch.setattr(RuntimeEvidenceStore, "_connect_path", orig_connect_path)
    store_recovered = RuntimeEvidenceStore(db_path)
    with store_recovered._connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT COUNT(*) FROM entry_decision_evidence").fetchone()[0] == 1
        row = db.execute("SELECT entry_decision_id FROM entry_decision_evidence").fetchone()
        assert row[0] == "eed-rb-1"


