import pytest

import json
from datetime import datetime, timedelta, timezone

from btc_scraper.ml_engine.lifecycle_observability import producer_coverage_report
from btc_scraper.ml_engine.gate_a_runtime_evidence import evaluate_gate_a_runtime_evidence
from btc_scraper.ml_engine.recalibration_governance import (
    RecalibrationCandidate,
    block_direct_candidate_to_production,
    evaluate_shadow_candidate,
)
from btc_scraper.ml_engine.runtime_calibration import evidence_state, runtime_calibration_report
from btc_scraper.ml_engine.runtime_health import evaluate_runtime_health
from btc_scraper.ml_engine.runtime_outcome_linker import (
    CalibrationSampleJsonlStore,
    OrphanCategory,
    link_runtime_outcomes,
)
from btc_scraper.ml_engine.shadow_evidence_window import (
    GateSnapshot,
    RESET_DUPLICATE_OUTCOME,
    RESET_GATE_SNAPSHOT_STALE,
    RESET_LIFECYCLE_E2E_NOT_PASSED,
    RESET_LINKER_SCHEMA_CHANGED,
    RESET_PRODUCER_COVERAGE_BELOW_GATE,
    ShadowEvidenceWindow,
    ShadowEvidenceWindowStore,
    evaluate_shadow_evidence_window,
)
from btc_scraper.ml_engine.trade_lifecycle import TradeLifecycleContext


def _prediction(**overrides):
    row = {
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "position_id": "pos-1",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "symbol": "BTC",
        "decision_context": "entry",
        "model_name": "meta_model",
        "model_version": "v3",
        "artifact_sha256": "abc",
        "feature_schema_version": "meta-v3",
        "calibrated_prediction": 0.72,
    }
    row.update(overrides)
    return row


def _outcome(**overrides):
    row = {
        "position_id": "pos-1",
        "signal_id": "sig-1",
        "outcome_id": "out-1",
        "outcome_revision": 1,
        "net_pnl_pct": 2.4,
        "closed_at": "2026-07-16T01:00:00+00:00",
        "source": "real_paper",
        "side": "LONG",
    }
    row.update(overrides)
    return row


def _gate_snapshot(**overrides):
    payload = {
        "producer_coverage": {
            "prediction": 0.99,
            "entry_decision": 0.99,
            "reservation": 0.99,
            "submitted_order": 0.99,
            "fill": 0.99,
            "open_position": 0.99,
            "closed_outcome": 0.99,
        },
        "closed_outcome_coverage": 0.98,
        "duplicate_outcomes": 0,
        "mixed_artifact_schema_samples": 0,
        "unresolved_critical_orphans": 0,
        "lifecycle_e2e_passed": True,
        "recovery_tests_passed": True,
        "evaluated_at": datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
        "closed_trade_prediction_to_outcome_rate": 0.90,
    }
    payload.update(overrides)
    return GateSnapshot(**payload)


def _paper_runtime_bundle(count=20):
    events = {
        "prediction": [],
        "entry_decision": [],
        "reservation": [],
        "submitted_order": [],
        "fill": [],
        "open_position": [],
        "closed_outcome": [],
    }
    predictions = []
    outcomes = []
    for index in range(count):
        prediction_id = f"pred-paper-{index}"
        signal_id = f"sig-paper-{index}"
        entry_decision_id = f"ed-paper-{index}"
        reservation_id = f"res-paper-{index}"
        client_order_id = f"client-paper-{index}"
        fill_id = f"fill-paper-{index}"
        position_id = f"pos-paper-{index}"
        outcome_id = f"out-paper-{index}"
        prediction = _prediction(
            prediction_id=prediction_id,
            signal_id=signal_id,
            position_id=position_id,
            execution_mode="paper",
            artifact_sha256="artifact-paper",
            feature_schema_version="schema-paper",
        )
        outcome = _outcome(
            position_id=position_id,
            signal_id=signal_id,
            outcome_id=outcome_id,
            source="real_paper",
            artifact_sha256="artifact-paper",
            feature_schema_version="schema-paper",
        )
        predictions.append(prediction)
        outcomes.append(outcome)
        events["prediction"].append(prediction)
        events["entry_decision"].append({
            "prediction_id": prediction_id,
            "signal_id": signal_id,
            "entry_decision_id": entry_decision_id,
            "execution_mode": "paper",
        })
        events["reservation"].append({
            "entry_decision_id": entry_decision_id,
            "reservation_id": reservation_id,
            "idempotency_key": f"idem-paper-{index}",
            "execution_mode": "paper",
        })
        events["submitted_order"].append({
            "entry_decision_id": entry_decision_id,
            "reservation_id": reservation_id,
            "client_order_id": client_order_id,
            "execution_mode": "paper",
        })
        events["fill"].append({
            "client_order_id": client_order_id,
            "fill_id": fill_id,
            "position_id": position_id,
            "execution_mode": "paper",
        })
        events["open_position"].append({
            "prediction_id": prediction_id,
            "signal_id": signal_id,
            "position_id": position_id,
            "execution_mode": "paper",
        })
        events["closed_outcome"].append({
            "position_id": position_id,
            "outcome_id": outcome_id,
            "outcome_revision": 1,
            "execution_mode": "paper",
        })
    return events, predictions, outcomes


def test_lifecycle_context_requires_ids_and_exports_metadata():
    context = TradeLifecycleContext.new(prediction_id="pred-1", signal_id="sig-1")
    context.require("prediction_id", "signal_id", "entry_decision_id")
    metadata = context.metadata()
    assert metadata["lifecycle_schema_version"] == "trade-lifecycle-v1"
    assert metadata["lifecycle_hash"]
    with pytest.raises(ValueError):
        context.require("reservation_id")


def test_runtime_linker_joins_by_stable_id_and_creates_sample_event():
    report = link_runtime_outcomes([_prediction()], [_outcome()])
    assert report.health() == "HEALTHY"
    assert report.prediction_to_outcome_link_rate == 1.0
    assert report.closed_trade_prediction_to_outcome_rate == 1.0
    assert report.actionable_prediction_to_trade_rate == 1.0
    sample = report.samples[0]
    assert sample.prediction_id == "pred-1"
    assert sample.label == 1
    event = sample.to_event()
    assert event["event_type"] == "calibration_sample_created"
    assert event["sample_id"] == sample.sample_id


def test_runtime_linker_excludes_synthetic_and_reports_orphans():
    report = link_runtime_outcomes(
        [_prediction(position_id="pos-2")],
        [_outcome(position_id="missing", signal_id="missing"), _outcome(position_id="synthetic", source="synthetic")],
    )
    assert len(report.samples) == 0
    assert report.excluded_synthetic_count == 1
    assert report.to_dict()["orphan_outcome_count"] == 1
    assert report.to_dict()["orphans_by_category"][OrphanCategory.OUTCOME_WITHOUT_PREDICTION.value] == 1
    assert report.orphans[0].status == "pending"
    assert report.orphans[0].owner == "prediction_audit"
    assert report.health() == "INSUFFICIENT_OUTCOMES"


def test_outcome_before_prediction_waits_then_resolves_when_prediction_arrives():
    pending = link_runtime_outcomes([], [_outcome(prediction_id="pred-late")])
    assert len(pending.samples) == 0
    assert pending.orphans[0].reason_code == "waiting_for_prediction"
    assert pending.orphans[0].status == "pending"

    resolved = link_runtime_outcomes([_prediction(prediction_id="pred-late")], [_outcome(prediction_id="pred-late")])
    assert len(resolved.samples) == 1
    assert resolved.samples[0].prediction_id == "pred-late"


def test_outcome_amendment_uses_latest_revision_only():
    rev1 = _outcome(outcome_revision=1, net_pnl_pct=-1.0, outcome_id="out-rev-1")
    rev2 = _outcome(outcome_revision=2, net_pnl_pct=2.5, outcome_id="out-rev-2")
    report = link_runtime_outcomes([_prediction()], [rev1, rev2])
    assert len(report.samples) == 1
    assert report.samples[0].outcome_revision == 2
    assert report.samples[0].outcome_id == "out-rev-2"
    assert report.samples[0].label == 1


def test_runtime_calibration_uses_latest_amendment_revision_only():
    rev1_report = link_runtime_outcomes([_prediction()], [_outcome(outcome_revision=1, net_pnl_pct=-1.0, outcome_id="out-rev-1")])
    rev2_report = link_runtime_outcomes([_prediction()], [_outcome(outcome_revision=2, net_pnl_pct=2.5, outcome_id="out-rev-2")])
    calibration = runtime_calibration_report([
        rev1_report.samples[0].to_event(),
        rev2_report.samples[0].to_event(),
    ])
    assert calibration["windows"]["7"]["sample_count"] == 1
    assert calibration["windows"]["7"]["breakdowns"]["side"]["LONG"]["net_pnl_pct"] == 2.5


def test_mixed_artifact_or_schema_is_quarantined():
    report = link_runtime_outcomes(
        [_prediction(artifact_sha256="artifact-a", feature_schema_version="schema-a")],
        [_outcome(artifact_sha256="artifact-b", feature_schema_version="schema-a")],
    )
    payload = report.to_dict()
    assert len(report.samples) == 0
    assert payload["quarantined_sample_count"] == 1
    assert payload["mixed_artifact_schema_count"] == 1
    assert report.orphans[0].severity == "critical"


def test_model_version_mismatch_is_quarantined_with_reason():
    report = link_runtime_outcomes(
        [_prediction(model_version="v3-a")],
        [_outcome(model_version="v3-b")],
    )
    decision = evaluate_runtime_health(linkage=report.to_dict())
    assert len(report.samples) == 0
    assert report.orphans[0].reason_code == "model_version_mismatch"
    assert decision.state == "SCHEMA_MISMATCH"
    assert "freeze_promotion" in decision.actions
    assert "keep_sizing_clamp" in decision.actions
    assert "quarantine_samples" in decision.actions


def test_artifact_hash_mismatch_is_quarantined_with_reason():
    report = link_runtime_outcomes(
        [_prediction(artifact_sha256="artifact-a")],
        [_outcome(artifact_sha256="artifact-b")],
    )
    decision = evaluate_runtime_health(linkage=report.to_dict())
    assert len(report.samples) == 0
    assert report.orphans[0].reason_code == "artifact_hash_mismatch"
    assert decision.state == "SCHEMA_MISMATCH"
    assert "freeze_promotion" in decision.actions


def test_feature_schema_mismatch_is_quarantined_with_reason():
    report = link_runtime_outcomes(
        [_prediction(feature_schema_version="schema-a")],
        [_outcome(feature_schema_version="schema-b")],
    )
    decision = evaluate_runtime_health(linkage=report.to_dict())
    assert len(report.samples) == 0
    assert report.orphans[0].reason_code == "feature_schema_mismatch"
    assert decision.state == "SCHEMA_MISMATCH"
    assert "keep_sizing_clamp" in decision.actions


def test_runtime_calibration_report_has_windows_and_evidence_states():
    report = link_runtime_outcomes([_prediction()], [_outcome()])
    calibration = runtime_calibration_report([sample.to_event() for sample in report.samples])
    assert calibration["windows"]["7"]["sample_count"] == 1
    assert calibration["windows"]["7"]["evidence_state"] == "insufficient"
    assert evidence_state(30) == "provisional"
    assert evidence_state(100) == "usable"


def test_recalibration_candidate_is_candidate_only():
    candidate = RecalibrationCandidate("cand-1", "meta_model", "v3.1", "isotonic")
    assert candidate.to_dict()["auto_promote"] is False
    with pytest.raises(ValueError):
        block_direct_candidate_to_production("candidate", "production")


def test_shadow_candidate_requires_runtime_evidence():
    decision = evaluate_shadow_candidate([])
    assert decision.status == "insufficient_evidence"
    assert decision.action == "remain_shadow"


def test_sample_store_deduplicates_replayed_events_and_skips_corrupt_lines(tmp_path):
    report = link_runtime_outcomes([_prediction()], [_outcome()])
    store_path = tmp_path / "runtime_calibration.jsonl"
    store_path.write_text("{bad trailing line\n", encoding="utf-8")
    store = CalibrationSampleJsonlStore(store_path)
    assert store.append(report.samples) == 1
    assert store.corrupt_line_count == 1
    assert store.append(report.samples) == 0
    valid_rows = []
    for line in store_path.read_text(encoding="utf-8").splitlines():
        try:
            valid_rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    assert len(valid_rows) == 1


def test_producer_coverage_report_identifies_missing_ids():
    report = producer_coverage_report({
        "prediction": [{"prediction_id": "pred-1"}],
        "entry_decision": [{"prediction_id": "pred-1", "signal_id": "", "entry_decision_id": "ed-1"}],
        "closed_outcome": [{"position_id": "pos-1", "outcome_id": "out-1", "outcome_revision": 1}],
    })
    assert report["producers"]["prediction"]["coverage_rate"] == 1.0
    assert report["producers"]["entry_decision"]["coverage_rate"] == 0.0
    assert report["producers"]["entry_decision"]["missing_counts"]["signal_id"] == 1
    assert report["producers"]["closed_outcome"]["coverage_rate"] == 1.0


def test_gate_a_runtime_evidence_creates_snapshot_from_fresh_paper_records():
    events, predictions, outcomes = _paper_runtime_bundle(20)
    result = evaluate_gate_a_runtime_evidence(
        events_by_producer=events,
        predictions=predictions,
        outcomes=outcomes,
        lifecycle_e2e_passed=True,
        recovery_tests_passed=True,
        evaluated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        min_closed_positions=20,
    )
    assert result.ready is True
    assert result.gate_snapshot is not None
    assert result.report["runtime_scope"] == "paper_only"
    assert result.report["closed_position_count"] == 20
    assert result.report["prediction_coverage"] == 1.0
    assert result.report["entry_decision_coverage"] == 1.0
    assert result.report["reservation_coverage"] == 1.0
    assert result.report["submitted_order_coverage"] == 1.0
    assert result.report["fill_coverage"] == 1.0
    assert result.report["open_position_coverage"] == 1.0
    assert result.report["closed_outcome_coverage"] == 1.0
    assert result.report["duplicate_outcomes"] == 0
    assert result.report["mixed_artifact_schema_samples"] == 0
    assert result.report["unresolved_critical_orphans"] == 0
    assert result.gate_snapshot.start_block_reason(now=datetime(2026, 7, 16, 12, 10, tzinfo=timezone.utc)) is None


def test_gate_a_runtime_evidence_blocks_thin_or_legacy_mixed_records():
    events, predictions, outcomes = _paper_runtime_bundle(2)
    events["fill"].append({
        "client_order_id": "legacy-client",
        "fill_id": "legacy-fill",
        "position_id": "legacy-pos",
        "execution_mode": "legacy",
    })
    result = evaluate_gate_a_runtime_evidence(
        events_by_producer=events,
        predictions=predictions + [_prediction(prediction_id="legacy-pred", execution_mode="legacy")],
        outcomes=outcomes,
        lifecycle_e2e_passed=True,
        recovery_tests_passed=True,
        evaluated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        min_closed_positions=20,
    )
    assert result.ready is False
    assert result.gate_snapshot is None
    assert "insufficient_closed_paper_positions" in result.blockers
    assert result.report["closed_position_count"] == 2
    assert result.report["fill_coverage"] == 1.0


def test_closed_trade_link_rate_excludes_rejected_non_traded_predictions():
    predictions = [
        _prediction(prediction_id="pred-linked", signal_id="sig-linked", position_id="pos-linked"),
        _prediction(prediction_id="pred-open", signal_id="sig-open", position_id="pos-open"),
        _prediction(prediction_id="pred-rejected", signal_id=None, position_id=None),
    ]
    outcomes = [_outcome(position_id="pos-linked", signal_id="sig-linked")]
    report = link_runtime_outcomes(predictions, outcomes)
    payload = report.to_dict()
    assert payload["total_prediction_count"] == 3
    assert payload["actionable_prediction_count"] == 2
    assert payload["traded_prediction_count"] == 2
    assert payload["actionable_prediction_to_trade_rate"] == 1.0
    assert payload["closed_trade_prediction_to_outcome_rate"] == 0.5
    assert payload["prediction_to_outcome_link_rate"] == payload["closed_trade_prediction_to_outcome_rate"]


def test_runtime_health_freezes_promotion_without_stopping_scoring():
    decision = evaluate_runtime_health(
        linkage={
            "closed_trade_prediction_to_outcome_rate": 0.50,
            "duplicate_outcome_count": 0,
            "critical_orphans": [{"category": "fill_without_position"}],
        },
        producer_coverage={"all_required_coverage_rate": 0.95},
        calibration={"generated_at": "2026-07-15T00:00:00+00:00"},
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    assert decision.state == "CALIBRATION_STALE"
    assert "freeze_promotion" in decision.actions
    assert "keep_sizing_clamp" in decision.actions
    assert "mark_calibration_degraded" in decision.actions
    assert "calibration_report_stale" in decision.reasons


def test_runtime_health_schema_mismatch_freezes_calibration():
    decision = evaluate_runtime_health(
        linkage={
            "closed_trade_prediction_to_outcome_rate": 1.0,
            "duplicate_outcome_count": 1,
            "mixed_artifact_schema_count": 1,
            "critical_orphans": [],
        },
    )
    assert decision.state == "SCHEMA_MISMATCH"
    assert "freeze_calibration" in decision.actions
    assert "quarantine_samples" in decision.actions


def test_runtime_health_healthy_has_no_freeze_actions():
    decision = evaluate_runtime_health(
        linkage={
            "closed_trade_prediction_to_outcome_rate": 0.99,
            "duplicate_outcome_count": 0,
            "mixed_artifact_schema_count": 0,
            "critical_orphans": [],
        },
        producer_coverage={"all_required_coverage_rate": 1.0},
        calibration={"generated_at": "2026-07-16T12:00:00+00:00"},
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    assert decision.state == "HEALTHY"
    assert decision.actions == ()


def test_shadow_evidence_window_starts_and_completes_after_required_days():
    now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
    window = evaluate_shadow_evidence_window(
        current_window=None,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        now=now,
    )
    assert window.shadow_window_valid is True
    assert window.shadow_window_started_at == now.isoformat()
    assert not window.complete(now=now + timedelta(days=6, hours=23))
    assert window.complete(now=now + timedelta(days=7))


def test_shadow_evidence_window_resets_on_gate_a_drop_or_duplicate_outcome():
    current = ShadowEvidenceWindow("2026-07-16T00:00:00+00:00", True)
    gate_reset = evaluate_shadow_evidence_window(
        current_window=current,
        gate_a={"required_lifecycle_id_coverage": 0.98, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
    )
    assert gate_reset.shadow_window_valid is False
    assert gate_reset.shadow_window_reset_reason == RESET_PRODUCER_COVERAGE_BELOW_GATE

    duplicate_reset = evaluate_shadow_evidence_window(
        current_window=current,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 1, "mixed_artifact_schema_count": 0, "critical_orphans": []},
    )
    assert duplicate_reset.shadow_window_valid is False
    assert duplicate_reset.shadow_window_reset_reason == RESET_DUPLICATE_OUTCOME
    assert duplicate_reset.hard_reset is True


def test_shadow_window_store_persists_state_across_restart(tmp_path):
    now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    window = evaluate_shadow_evidence_window(
        current_window=None,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        schema_versions={
            "linker_schema_version": "linker-v1",
            "calibration_schema_version": "calibration-v1",
            "producer_contract_version": "runtime-contracts-v1",
        },
        now=now,
    )
    store.save(window)
    loaded = store.load()
    assert loaded is not None
    assert loaded.shadow_window_started_at == now.isoformat()
    assert loaded.linker_schema_version == "linker-v1"

    continued = evaluate_shadow_evidence_window(
        current_window=loaded,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        now=now + timedelta(days=3),
    )
    assert continued.shadow_window_started_at == now.isoformat()
    assert continued.consecutive_valid_days == 3.0


def test_shadow_window_store_appends_reset_history(tmp_path):
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    previous = ShadowEvidenceWindow("2026-07-16T00:00:00+00:00", True)
    reset = evaluate_shadow_evidence_window(
        current_window=previous,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 1, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        schema_versions={"linker_schema_version": "linker-v1"},
        now=datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc),
    )
    store.save(
        reset,
        previous_window=previous,
        metrics_snapshot={"duplicate_outcome_count": 1},
        schema_versions={"linker_schema_version": "linker-v1"},
    )
    history = (tmp_path / "shadow_window.resets.jsonl").read_text(encoding="utf-8").splitlines()
    payload = json.loads(history[0])
    assert payload["reason"] == RESET_DUPLICATE_OUTCOME
    assert payload["reset_event_id"]
    assert payload["hard_reset"] is True
    assert payload["previous_started_at"] == "2026-07-16T00:00:00+00:00"
    assert payload["previous_valid_days"] == 1
    assert payload["metrics_snapshot"]["duplicate_outcome_count"] == 1
    assert payload["duplicate_outcomes"] == 1

    store.save(
        reset,
        previous_window=previous,
        metrics_snapshot={"duplicate_outcome_count": 1},
        schema_versions={"linker_schema_version": "linker-v1"},
    )
    assert len((tmp_path / "shadow_window.resets.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_shadow_window_rejects_backwards_time_and_negative_valid_days(tmp_path):
    window = ShadowEvidenceWindow(
        "2026-07-16T00:00:00+00:00",
        True,
        last_evaluated_at="2026-07-17T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="timestamp moved backwards"):
        evaluate_shadow_evidence_window(
            current_window=window,
            gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
            linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
            now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        )

    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    with pytest.raises(ValueError, match="non-negative"):
        store.save(ShadowEvidenceWindow("2026-07-16T00:00:00+00:00", True, consecutive_valid_days=-1))


def test_shadow_window_schema_version_change_hard_resets_before_continuing():
    current = ShadowEvidenceWindow(
        "2026-07-16T00:00:00+00:00",
        True,
        last_evaluated_at="2026-07-17T00:00:00+00:00",
        linker_schema_version="linker-v1",
        calibration_schema_version="calibration-v1",
        producer_contract_version="contracts-v1",
    )
    reset = evaluate_shadow_evidence_window(
        current_window=current,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        schema_versions={
            "linker_schema_version": "linker-v2",
            "calibration_schema_version": "calibration-v1",
            "producer_contract_version": "contracts-v1",
        },
        now=datetime(2026, 7, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert reset.shadow_window_valid is False
    assert reset.shadow_window_reset_reason == RESET_LINKER_SCHEMA_CHANGED
    assert reset.hard_reset is True


def test_shadow_window_valid_days_are_floor_of_elapsed_time():
    start = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
    current = ShadowEvidenceWindow(start.isoformat(), True, last_evaluated_at=start.isoformat())
    updated = evaluate_shadow_evidence_window(
        current_window=current,
        gate_a={"required_lifecycle_id_coverage": 0.99, "closed_position_outcome_coverage": 0.98},
        linkage={"duplicate_outcome_count": 0, "mixed_artifact_schema_count": 0, "critical_orphans": []},
        now=start + timedelta(days=2, hours=23, minutes=59),
    )
    assert updated.consecutive_valid_days == 2


def test_shadow_window_store_start_refuses_before_gate_a_or_e2e(tmp_path):
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    result = store.start(
        _gate_snapshot(producer_coverage={"prediction": 0.98}),
        now=datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
    )
    assert result.started is False
    assert result.reason == RESET_PRODUCER_COVERAGE_BELOW_GATE

    e2e_result = store.start(
        _gate_snapshot(lifecycle_e2e_passed=False, evaluated_at=datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)),
        now=datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc),
    )
    assert e2e_result.started is False
    assert e2e_result.reason == RESET_LIFECYCLE_E2E_NOT_PASSED


def test_shadow_window_store_start_persists_when_gate_clean(tmp_path):
    now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    result = store.start(
        _gate_snapshot(evaluated_at=now),
        schema_versions={"linker_schema_version": "linker-v1"},
        now=now,
    )
    assert result.started is True
    assert result.reason is None
    loaded = store.load()
    assert loaded.shadow_window_started_at == now.isoformat()
    assert loaded.start_gate_snapshot_hash
    assert loaded.start_gate_evaluated_at == now.isoformat()
    assert loaded.start_gate_metrics["closed_position_outcome_coverage"] == 0.98


def test_shadow_window_store_start_is_idempotent_for_same_valid_snapshot(tmp_path):
    now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    snapshot = _gate_snapshot(evaluated_at=now)
    first = store.start(snapshot, now=now)
    second = store.start(snapshot, now=now + timedelta(minutes=10))
    assert first.started is True
    assert second.started is True
    assert second.window.shadow_window_started_at == first.window.shadow_window_started_at
    assert second.window.start_gate_snapshot_hash == first.window.start_gate_snapshot_hash


def test_shadow_window_store_start_rejects_stale_gate_snapshot(tmp_path):
    now = datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)
    store = ShadowEvidenceWindowStore(tmp_path / "shadow_window.json")
    result = store.start(
        _gate_snapshot(evaluated_at=now - timedelta(minutes=16)),
        now=now,
    )
    assert result.started is False
    assert result.reason == RESET_GATE_SNAPSHOT_STALE
