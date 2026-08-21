from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from btc_scraper.ml_engine.h14_observer import (
    H14ProspectiveObserver,
    _parse_timestamp,
)
from btc_scraper.ml_engine.multi_agent import SignalGeneratorAgent


def _write_schedules(root: Path) -> None:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "design_id": "MF2",
            "current_symbol_subset": ["ETHUSDT", "BNBUSDT"],
            "prospective_membership_schedule_hash": "mf2-schedule-hash",
        },
        {
            "design_id": "MF4",
            "current_symbol_subset": ["ETHUSDT", "BNBUSDT"],
            "prospective_membership_schedule_hash": "mf4-schedule-hash",
        },
    ]
    (data_dir / "h14_1_design_membership_schedules.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _analysis(**overrides) -> dict:
    row = {
        "symbol": "ETHUSDT",
        "coin": "ETH",
        "cycle_timestamp": "2026-08-13T08:55:07Z",
        "deployment_id": "observer-test-release",
        "model_version": "meta-test-v1",
        "artifact_sha256": "artifact-test",
        "feature_schema_version": "schema-test",
        "feature_hash": "feature-hash-test",
        "regime_snapshot": {"trend": "DOWN", "volatility": "NORMAL"},
        "signal": "SELL",
        "signal_score": {
            "action": "SELL",
            "score": 12,
            "meta_confidence": 0.77,
            "prediction_id": "prediction-test",
            "signal_id": "signal-test",
        },
        "causal_decision": {
            "action": "SELL",
            "posterior_probability": 0.22,
            "meta_probability": 0.78,
        },
    }
    row.update(overrides)
    return row


def test_h14_observer_first_row_and_idempotency(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)

    first = observer.observe(_analysis())
    second = observer.observe(_analysis())

    assert first.status == "APPENDED"
    assert second.status == "NO_OP"
    assert second.health == "PASS"
    assert second.analysis_rows == 1
    assert second.decision_rows == 2
    assert second.divergence_rows == 1
    assert second.duplicate_count == 0
    assert second.incomplete_accounting == 0

    analysis_rows = _rows(tmp_path / "data/h14_1_prospective_analysis_stream.jsonl")
    decision_rows = _rows(tmp_path / "data/h14_1_prospective_design_decisions.jsonl")
    divergence_rows = _rows(tmp_path / "data/h14_2_decision_divergence_accounting.jsonl")
    checkpoint = json.loads(
        (tmp_path / "reports/h14_2_stream_checkpoint.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(analysis_rows) == 1
    assert len(decision_rows) == 2
    assert len(divergence_rows) == 1
    assert {row["design_id"] for row in decision_rows} == {"MF2", "MF4"}
    assert divergence_rows[0]["bucket"] == "SHARED_ACTIONABLE"
    assert divergence_rows[0]["action_conflict"] is False
    assert checkpoint["pre_boundary_analysis"] == 0
    assert checkpoint["canonical_analysis_duplicates"] == 0
    assert checkpoint["governed_runtime_mutation"] == 0
    assert checkpoint["order_created"] == 0
    assert checkpoint["reservation_created"] == 0
    assert checkpoint["position_created"] == 0
    assert checkpoint["governed_evidence_write"] == 0
    assert analysis_rows[0]["epoch_id"] == "H14_PROSPECTIVE_OBSERVATION_EPOCH_V1_2026_08_13"
    assert analysis_rows[0]["semantic_analysis_key"]
    assert analysis_rows[0]["semantic_fingerprint"]


def test_h14_observer_test_process_requires_isolated_root(monkeypatch):
    monkeypatch.delenv("BTC_H14_OBSERVER_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="h14_test_requires_isolated_observer_root"):
        H14ProspectiveObserver()


def test_h14_observer_non_pytest_test_environment_requires_isolated_root(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("BTC_H14_OBSERVER_ROOT", raising=False)
    monkeypatch.setenv("BTC_ENVIRONMENT", "test")
    with pytest.raises(RuntimeError, match="h14_test_requires_isolated_observer_root"):
        H14ProspectiveObserver()


def test_h14_observer_rejects_semantic_collision(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)
    observer.observe(_analysis())

    with pytest.raises(RuntimeError, match="h14_canonical_semantic_collision"):
        observer.observe(_analysis(feature_hash="different-feature"))

    assert len(_rows(observer.analysis_path)) == 1


def test_h14_observer_skips_pre_boundary_analysis(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)

    result = observer.observe(_analysis(cycle_timestamp="2026-08-13T08:50:06Z"))

    assert result.status == "SKIPPED_PRE_BOUNDARY"
    assert _rows(tmp_path / "data/h14_1_prospective_analysis_stream.jsonl") == []
    assert _rows(tmp_path / "data/h14_1_prospective_design_decisions.jsonl") == []


def test_h14_timestamp_contract_normalizes_aware_inputs_to_utc():
    assert _parse_timestamp("2026-08-19T19:00:00+07:00").isoformat() == (
        "2026-08-19T12:00:00+00:00"
    )
    parsed_z = _parse_timestamp("2026-08-19T12:00:00Z")
    assert parsed_z.isoformat() == "2026-08-19T12:00:00+00:00"
    assert parsed_z.tzinfo is timezone.utc


def test_h14_timestamp_contract_rejects_unknown_naive_input():
    with pytest.raises(ValueError, match="h14_timestamp_timezone_required"):
        _parse_timestamp("2026-08-19T19:00:00")


def test_h14_legacy_timestamp_requires_explicit_producer_timezone():
    winter = _parse_timestamp(
        "2026-01-19T19:00:00",
        legacy_timezone="Asia/Ho_Chi_Minh",
    )
    summer = _parse_timestamp(
        "2026-08-19T19:00:00",
        legacy_timezone="Asia/Ho_Chi_Minh",
    )

    assert winter.isoformat() == "2026-01-19T12:00:00+00:00"
    assert summer.isoformat() == "2026-08-19T12:00:00+00:00"


def test_h14_observer_prefers_producer_utc_over_legacy_display_time(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)
    analysis = _analysis(
        cycle_timestamp=None,
        history=[
            {
                "time": "2026-08-13 17:45",
                "time_utc": "2026-08-13T10:45:00Z",
            }
        ],
    )

    result = observer.observe(analysis)

    assert result.status == "APPENDED"
    row = _rows(observer.analysis_path)[0]
    assert row["cycle_timestamp"] == "2026-08-13T10:45:00Z"


def test_h14_observer_rejects_future_timestamp_without_writing(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)

    with pytest.raises(ValueError, match="h14_timestamp_in_future"):
        observer.observe(_analysis(cycle_timestamp="2999-01-01T00:00:00Z"))

    assert not observer.analysis_path.exists()


def test_h14_observer_rejects_naive_timestamp_without_writing(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)

    with pytest.raises(ValueError, match="h14_timestamp_timezone_required"):
        observer.observe(_analysis(cycle_timestamp="2026-08-19T19:00:00"))

    assert not observer.analysis_path.exists()


def test_h14_observer_does_not_mutate_input_analysis(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)
    analysis = _analysis()
    original = copy.deepcopy(analysis)

    observer.observe(analysis)

    assert analysis == original


def test_h14_observer_recovers_incomplete_accounting(tmp_path):
    _write_schedules(tmp_path)
    observer = H14ProspectiveObserver(root=tmp_path)
    canonical = observer._canonical_record(  # noqa: SLF001 - deliberate restart smoke.
        _analysis(),
        _parse_timestamp("2026-08-13T08:55:07Z"),
    )
    observer._ensure_files()  # noqa: SLF001
    observer._append_unique(  # noqa: SLF001
        tmp_path / "data/h14_1_prospective_analysis_stream.jsonl",
        canonical,
        key="prospective_analysis_id",
    )

    result = observer.observe(_analysis())

    assert result.status == "NO_OP"
    assert result.health == "DEGRADED_RECOVERED"
    assert result.analysis_rows == 1
    assert result.decision_rows == 2
    assert result.divergence_rows == 1
    assert result.incomplete_accounting == 1


def test_h14_observer_concurrent_appends_are_serialized(tmp_path):
    _write_schedules(tmp_path)

    def observe(symbol: str) -> None:
        H14ProspectiveObserver(root=tmp_path).observe(
            _analysis(
                symbol=f"{symbol}USDT",
                coin=symbol,
                cycle_timestamp=f"2026-08-13T08:5{len(symbol)}:07Z",
                signal_score={
                    "action": "SELL",
                    "score": 12,
                    "meta_confidence": 0.77,
                    "prediction_id": f"prediction-{symbol}",
                    "signal_id": f"signal-{symbol}",
                },
            )
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(observe, ["BTC", "ETH", "BNB"]))

    analysis_rows = _rows(tmp_path / "data/h14_1_prospective_analysis_stream.jsonl")
    decision_rows = _rows(tmp_path / "data/h14_1_prospective_design_decisions.jsonl")
    divergence_rows = _rows(tmp_path / "data/h14_2_decision_divergence_accounting.jsonl")
    checkpoint = json.loads(
        (tmp_path / "reports/h14_2_stream_checkpoint.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(analysis_rows) == 3
    assert len({row["prospective_analysis_id"] for row in analysis_rows}) == 3
    assert len(decision_rows) == 6
    assert len({row["decision_hash"] for row in decision_rows}) == 6
    assert len(divergence_rows) == 3
    assert checkpoint["canonical_analysis_duplicates"] == 0
    assert checkpoint["decision_stream_rows"] == 2 * checkpoint["analysis_stream_rows"]
    assert checkpoint["checkpoint_sequence"] == 3


def test_signal_generator_continues_when_h14_observer_raises(monkeypatch):
    _patch_signal_generator_dependencies(monkeypatch)
    degradations = []
    monkeypatch.setattr(
        "btc_scraper.ml_engine.h14_observer.observe_h14_prospective_analysis",
        lambda _analysis: (_ for _ in ()).throw(OSError("disk denied")),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.operational_health.record_degradation",
        lambda component, metric, exc: degradations.append((component, metric, exc)),
    )

    result = SignalGeneratorAgent().run(_signal_generator_context())

    assert result["signals_info"][0]["action"] == "SELL"
    assert result["analysis"]["ETH:Binance"]["causal_decision"]["action"] == "SELL"
    assert [(component, metric) for component, metric, _ in degradations] == [
        ("h14_observer", "h14_observer_failure_total")
    ]


def test_signal_generator_continues_with_malformed_h14_jsonl(monkeypatch, tmp_path):
    _write_schedules(tmp_path)
    data_dir = tmp_path / "data"
    (data_dir / "h14_1_prospective_analysis_stream.jsonl").write_text(
        '{"truncated": true',
        encoding="utf-8",
    )
    monkeypatch.setenv("BTC_H14_OBSERVER_ROOT", str(tmp_path))
    _patch_signal_generator_dependencies(monkeypatch)
    degradations = []
    monkeypatch.setattr(
        "btc_scraper.ml_engine.operational_health.record_degradation",
        lambda component, metric, exc: degradations.append((component, metric, exc)),
    )

    result = SignalGeneratorAgent().run(_signal_generator_context())

    assert result["signals_info"][0]["action"] == "SELL"
    assert degradations
    assert degradations[0][0] == "h14_observer"


def test_signal_generator_invokes_h14_observer_after_analysis(monkeypatch, tmp_path):
    _write_schedules(tmp_path)
    monkeypatch.setenv("BTC_H14_OBSERVER_ROOT", str(tmp_path))
    _patch_signal_generator_dependencies(monkeypatch)

    result = SignalGeneratorAgent().run(_signal_generator_context())

    assert result["signals_info"][0]["action"] == "SELL"
    assert len(_rows(tmp_path / "data/h14_1_prospective_analysis_stream.jsonl")) == 1
    assert len(_rows(tmp_path / "data/h14_1_prospective_design_decisions.jsonl")) == 2
    checkpoint = json.loads(
        (tmp_path / "reports/h14_2_stream_checkpoint.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["governed_runtime_mutation"] == 0


def _patch_signal_generator_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: {
            "mode": "reference_only",
            "affects_signal": False,
            "decision_eligible": False,
            "status": "available",
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator",
        lambda: SimpleNamespace(
            predict_once=lambda *_args, **_kwargs: SimpleNamespace(
                to_dict=lambda: {
                    "probability": 0.8,
                    "prediction_id": "prediction-hook",
                    "signal_id": "signal-hook",
                    "model_version": "meta-test-v1",
                    "artifact_sha256": "artifact-test",
                    "feature_schema_version": "schema-test",
                    "feature_hash": "feature-hook",
                    "deployment_id": "observer-test-release",
                    "cycle_id": "cycle-hook",
                }
            )
        ),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
        lambda analysis, **kwargs: {
            "action": "SELL",
            "score": 12,
            "meta_confidence": 0.8,
            "prediction_id": "prediction-hook",
            "signal_id": "signal-hook",
            "model_version": "meta-test-v1",
            "artifact_sha256": "artifact-test",
            "feature_schema_version": "schema-test",
            "feature_hash": "feature-hook",
            "deployment_id": "observer-test-release",
            "cycle_id": "cycle-hook",
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_final_decision_for_prediction=lambda _prediction_id: {
                "action": "SELL",
                "posterior_probability": 0.2,
                "meta_probability": 0.8,
                "decision_id": "decision-hook",
                "prediction_id": "prediction-hook",
            }
        ),
    )


def _signal_generator_context() -> dict:
    return {
        "cycle_id": "cycle-hook",
        "analysis": {
            "ETH:Binance": {
                "symbol": "ETHUSDT",
                "coin": "ETH",
                "cycle_timestamp": "2026-08-13T08:55:07Z",
                "signal": "SELL",
                "close": 4200.0,
                "atr": 50.0,
            }
        },
    }
