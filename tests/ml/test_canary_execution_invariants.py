from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.multi_agent import SignalGeneratorAgent
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import EntryRejectionReason


DEPLOYMENT = "paper-canary-test-08"
CYCLE = "cycle-test-08"
PREDICTION = "prediction-test-08"
DECISION = "decision-test-08"


def _production_evidence(monkeypatch) -> None:
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "production")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", DEPLOYMENT)
    monkeypatch.setenv("BTC_PAPER_RUN_ID", DEPLOYMENT)
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "true")
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH,BNB")


def _final_decision(action: str = "SELL", **overrides) -> dict:
    row = {
        "decision_id": DECISION,
        "prediction_id": PREDICTION,
        "cycle_id": CYCLE,
        "deployment_id": DEPLOYMENT,
        "paper_run_id": DEPLOYMENT,
        "action": action,
        "terminal_status": "TRADE" if action in {"BUY", "SELL"} else "HOLD",
        "eligible": action in {"BUY", "SELL"},
        "superseded": False,
        "risk_status": "HEALTHY",
        "risk_blocked": False,
        "decision_sha256": "decision-sha-test-08",
    }
    row.update(overrides)
    return row


def _analysis(final_decision: dict | None) -> dict:
    row = {
        "signal": "STRONG SELL (Confirmed Reversal)",
        "close": 100.0,
        "prediction_id": PREDICTION,
        "cycle_id": CYCLE,
        "deployment_id": DEPLOYMENT,
        "paper_run_id": DEPLOYMENT,
        "model_version": "v3.1",
        "artifact_sha256": "artifact-test",
        "feature_schema_version": "schema-test",
        "signal_score": {
            "score": 5,
            "strength": 95,
            "action": "SELL",
            "meta_probability": 0.9,
            "kelly_fraction": 0.2,
            "prediction_id": PREDICTION,
            "cycle_id": CYCLE,
            "deployment_id": DEPLOYMENT,
            "paper_run_id": DEPLOYMENT,
            "model_version": "v3.1",
            "artifact_sha256": "artifact-test",
            "feature_schema_version": "schema-test",
        },
        "tp_sl": {"entry": 100.0, "sl": 102.0, "tp1": 96.0, "rr1": 2.0},
    }
    if final_decision is not None:
        row["causal_decision"] = final_decision
    return row


def _execution_signal(*, paper_run_id: str = DEPLOYMENT) -> dict:
    return {
        "coin": "BNB",
        "signal": "SELL",
        "signal_raw": "SELL",
        "id": "signal-test-08",
        "prediction_id": PREDICTION,
        "cycle_id": CYCLE,
        "deployment_id": DEPLOYMENT,
        "paper_run_id": paper_run_id,
        "entry_decision_id": DECISION,
        "decision_id": DECISION,
        "final_decision_id": DECISION,
        "final_decision_action": "SELL",
        "final_decision_prediction_id": PREDICTION,
        "final_decision_cycle_id": CYCLE,
        "final_decision_deployment_id": DEPLOYMENT,
        "final_decision_paper_run_id": paper_run_id,
        "final_decision_eligible": True,
        "final_decision_terminal_status": "TRADE",
        "final_decision_superseded": False,
        "canonical_action": "SELL",
        "decision_sha256": "decision-sha-test-08",
        "model_version": "v3.1",
        "model_artifact_sha256": "artifact-test",
        "feature_schema_version": "schema-test",
        "idempotency_key": "idempotency-test-08",
    }


def test_hold_final_decision_cannot_create_entry(monkeypatch):
    _production_evidence(monkeypatch)
    trader = AutoTrader()
    final_decision = _final_decision("HOLD")
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: final_decision
        ),
    )


def test_increase_is_not_an_entry_without_executable_buy_or_sell(monkeypatch):
    _production_evidence(monkeypatch)
    trader = AutoTrader()
    final_decision = _final_decision("INCREASE")
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: final_decision
        ),
    )

    decision = trader.build_entry_decision(_analysis(final_decision), "BNB")

    assert decision.eligible is False
    assert decision.rejection_reason == EntryRejectionReason.NON_EXECUTABLE_FINAL_DECISION

    decision = trader.build_entry_decision(_analysis(final_decision), "BNB")

    assert decision.eligible is False
    assert (
        decision.rejection_reason
        == EntryRejectionReason.NON_EXECUTABLE_FINAL_DECISION
    )


def test_missing_final_decision_cannot_create_entry(monkeypatch):
    _production_evidence(monkeypatch)
    trader = AutoTrader()
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: None
        ),
    )

    decision = trader.build_entry_decision(_analysis(None), "BNB")

    assert decision.eligible is False
    assert decision.rejection_reason == EntryRejectionReason.MISSING_FINAL_DECISION


def test_committed_sell_overrides_neutral_display_metadata(monkeypatch):
    _production_evidence(monkeypatch)
    trader = AutoTrader()
    final_decision = _final_decision(
        "SELL", meta_probability=0.2, execution_probability=0.8
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: final_decision
        ),
    )
    analysis = _analysis(final_decision)
    analysis["signal"] = "NEUTRAL (BEARISH)"
    analysis["signal_score"]["action"] = "NEUTRAL"

    decision = trader.build_entry_decision(analysis, "BNB")

    assert decision.eligible is True
    assert decision.action.value == "SELL"
    assert decision.decision_sha256 == "decision-sha-test-08"


def test_stale_presented_decision_is_rejected(monkeypatch):
    _production_evidence(monkeypatch)
    trader = AutoTrader()
    committed = _final_decision("SELL")
    presented = {**committed, "decision_id": "stale-decision"}
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: committed
        ),
    )

    decision = trader.build_entry_decision(_analysis(presented), "BNB")

    assert decision.eligible is False
    assert decision.rejection_reason == EntryRejectionReason.FINAL_DECISION_LINEAGE_MISMATCH


def test_wrong_paper_run_is_quarantined_before_reservation(monkeypatch, tmp_path):
    _production_evidence(monkeypatch)
    reservation_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(reservation_path),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: _final_decision()
        ),
    )
    signal = _execution_signal(paper_run_id="live-paper-legacy")

    record = engine.submit_paper(
        signal,
        {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1_000_000.0},
        notional_usdt=100.0,
    )

    assert record.status == "REJECTED"
    assert record.reason in {
        "PAPER_RUN_LINEAGE_MISMATCH", "FINAL_DECISION_LINEAGE_MISMATCH"
    }
    assert (
        ReservationStore(reservation_path).get_by_idempotency_key(
            signal["idempotency_key"]
        )
        is None
    )
    assert not list((tmp_path / "fills").rglob("fills_*.jsonl"))


def test_paper_fill_preserves_cycle_and_run_lineage(monkeypatch, tmp_path):
    _production_evidence(monkeypatch)
    reservation_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(reservation_path),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: _final_decision()
        ),
    )
    signal = _execution_signal()

    record = engine.submit_paper(
        signal,
        {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1_000_000.0},
        notional_usdt=100.0,
    )
    reservation = ReservationStore(reservation_path).get_by_idempotency_key(
        signal["idempotency_key"]
    )

    assert record.status == "FILLED", record.reason
    assert record.cycle_id == CYCLE
    assert record.paper_run_id == DEPLOYMENT
    assert reservation is not None
    assert reservation.cycle_id == CYCLE
    assert reservation.paper_run_id == DEPLOYMENT


def test_execution_reloads_and_rejects_wrong_decision_digest(monkeypatch, tmp_path):
    _production_evidence(monkeypatch)
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: _final_decision()
        ),
    )
    signal = {**_execution_signal(), "decision_sha256": "stale-sha"}

    record = engine.submit_paper(
        signal,
        {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1_000_000.0},
        notional_usdt=100.0,
    )

    assert record.status == "REJECTED"
    assert record.reason == "FINAL_DECISION_LINEAGE_MISMATCH"
    assert ReservationStore(tmp_path / "reservations.db").get_by_idempotency_key(
        signal["idempotency_key"]
    ) is None


def test_controlled_sell_smoke_reaches_fill_and_replay_is_idempotent(
    monkeypatch, tmp_path,
):
    _production_evidence(monkeypatch)
    final_decision = _final_decision(
        "SELL", meta_probability=0.2, execution_probability=0.8
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: SimpleNamespace(
            get_committed_final_decision=lambda _prediction_id: final_decision
        ),
    )
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    trader = AutoTrader()
    monkeypatch.setattr(trader, "_get_execution_engine", lambda: engine)
    monkeypatch.setattr(trader, "_has_open_position", lambda *_args: False)
    monkeypatch.setattr(trader, "_check_circuit_breaker", lambda: (True, "ok"))
    monkeypatch.setattr(trader, "_notify_trade", lambda _row: None)
    monkeypatch.setattr(trader, "_record_trade_result", lambda _result: None)
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader._append_log", lambda _row: None
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_open_positions",
        lambda: [],
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit",
        lambda *_args: 1_000.0,
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures",
        lambda _balance: (0.0, {}, {}),
    )
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.add_position", lambda **_kwargs: None
    )
    analysis = _analysis(final_decision)
    analysis.update({
        "signal": "NEUTRAL (BEARISH)",
        "signal_id": "signal-smoke-sell",
        "idempotency_key": "smoke-sell-idempotency",
        "open": 100.0,
        "high": 100.1,
        "low": 99.9,
        "volume": 1_000_000.0,
    })
    analysis["signal_score"].update({
        "action": "NEUTRAL",
        "meta_probability": 0.2,
        "strength": 95,
    })

    first = asyncio.run(trader._process_signal("BNB:Binance", analysis))
    replay = asyncio.run(trader._process_signal("BNB:Binance", analysis))
    reservation = ReservationStore(tmp_path / "reservations.db").get_by_idempotency_key(
        "smoke-sell-idempotency"
    )

    assert first is not None and first["status"] == "FILLED", (
        first.get("status"), first.get("reason_skip"), first.get("error")
    )
    assert replay is not None and replay["status"] == "FILLED", (
        replay.get("status"), replay.get("reason_skip"), replay.get("error")
    )
    assert reservation is not None
    assert reservation.side == "sell"
    assert reservation.prediction_id == PREDICTION


def test_signal_generator_writes_one_terminal_error_decision(monkeypatch):
    class Prediction:
        def to_dict(self):
            return {
                "signal_id": "signal-terminal",
                "prediction_id": PREDICTION,
                "probability": 0.7,
                "model_version": "v3.1",
                "artifact_sha256": "artifact-test",
                "feature_schema_version": "schema-test",
                "deployment_id": DEPLOYMENT,
                "paper_run_id": DEPLOYMENT,
                "cycle_id": CYCLE,
                "feature_hash": "feature-test",
            }

    class Coordinator:
        def predict_once(self, *_args, **_kwargs):
            return Prediction()

    class EvidenceStore:
        def __init__(self):
            self.rows = []

        def get_final_decision_for_prediction(self, prediction_id):
            return self.rows[0] if self.rows and prediction_id == PREDICTION else None

        def append_final_decision(self, decision):
            self.rows.append(dict(decision))

    evidence = EvidenceStore()
    monkeypatch.setattr(
        "btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator",
        lambda: Coordinator(),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
        lambda _ana, meta_prediction: {
            **meta_prediction,
            "action": "SELL",
            "score": 5,
            "strength": 95,
            "risk_status": "HEALTHY",
        },
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: {},
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: evidence,
    )
    agent = SignalGeneratorAgent()
    context = {
        "cycle_id": CYCLE,
        "analysis": {"BNB:Binance": {"signal": "SELL", "close": 100.0}},
    }

    agent.run(context)
    agent.run(context)

    assert len(evidence.rows) == 1
    assert evidence.rows[0]["action"] == "ERROR"
    assert evidence.rows[0]["terminal_status"] == "ERROR"
    assert context["analysis"]["BNB:Binance"]["causal_decision"]["prediction_id"] == PREDICTION


def test_runner_blocks_stale_prediction_without_terminal_decision(tmp_path):
    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "run_canary_until_seal_ready.py"
    spec = importlib.util.spec_from_file_location("canary_runner", runner_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    class Store:
        @staticmethod
        def health(**_kwargs):
            return {"status": "healthy", "severity": "HEALTHY"}

    epoch = SimpleNamespace(
        analysis_universe=("BTC", "ETH", "BNB"),
        activated_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        deployment_id=DEPLOYMENT,
    )
    prediction = {
        "prediction_id": PREDICTION,
        "symbol": "BNB",
        "evidence_eligible": True,
        "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    }

    with pytest.raises(runner.CanaryInvariantError, match="missing_final_decision"):
        runner._validate_static_invariants(
            store=Store(),
            rows={
                "predictions": [prediction],
                "final_decisions": [],
                "outcomes": [],
            },
            epoch=epoch,
            reservations=[],
            fills=[],
            mongo_positions=[],
            mongo_closed=[],
            risk={"status": "HEALTHY", "blocked": False},
            runtime_root=tmp_path,
            terminal_decision_grace=120.0,
        )


def test_closed_position_without_outcome_blocks_runner(tmp_path):
    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "run_canary_until_seal_ready.py"
    spec = importlib.util.spec_from_file_location("canary_runner_closed", runner_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    class Store:
        @staticmethod
        def health(**_kwargs):
            return {"status": "healthy", "severity": "HEALTHY"}

    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    prediction = {
        "prediction_id": PREDICTION,
        "symbol": "BNB",
        "cycle_id": CYCLE,
        "evidence_eligible": True,
        "timestamp": old,
    }
    decision = _final_decision("SELL")
    reservation = {
        "prediction_id": PREDICTION,
        "cycle_id": CYCLE,
        "paper_run_id": DEPLOYMENT,
    }
    closed = {
        "prediction_id": PREDICTION,
        "cycle_id": CYCLE,
        "paper_run_id": DEPLOYMENT,
        "closed_at": old,
    }
    epoch = SimpleNamespace(
        analysis_universe=("BTC", "ETH", "BNB"),
        activated_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        deployment_id=DEPLOYMENT,
    )

    with pytest.raises(runner.CanaryInvariantError, match="closed_position_outcome_gate"):
        runner._validate_static_invariants(
            store=Store(),
            rows={
                "predictions": [prediction],
                "final_decisions": [decision],
                "outcomes": [],
                "audit_events": [],
            },
            epoch=epoch,
            reservations=[reservation],
            fills=[],
            mongo_positions=[],
            mongo_closed=[closed],
            risk={"status": "HEALTHY", "blocked": False},
            runtime_root=tmp_path,
            terminal_decision_grace=120.0,
        )


def test_check_only_does_not_persist_failed_evaluation(monkeypatch, tmp_path):
    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "run_canary_until_seal_ready.py"
    spec = importlib.util.spec_from_file_location("canary_runner_read_only", runner_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    appended = []
    epoch = SimpleNamespace(
        epoch_id="epoch-read-only",
        deployment_id=DEPLOYMENT,
        analysis_universe=("BTC", "ETH", "BNB"),
        analysis_universe_hash="universe-hash",
        model_version="v3.1",
        artifact_sha256="artifact-test",
        feature_schema_version="schema-test",
        activated_at="2026-08-01T00:00:00+00:00",
    )

    class Store:
        def __init__(self, _path):
            pass

        def append_audit_event(self, event):
            appended.append(dict(event))

        def get_evidence_epoch(self, _epoch_id):
            return epoch

    class Mongo:
        def __getitem__(self, _name):
            return object()

        def close(self):
            pass

    monkeypatch.setattr(runner, "RuntimeEvidenceStore", Store)
    monkeypatch.setattr(runner, "_assert_epoch_and_code", lambda *_args: epoch)
    monkeypatch.setattr(runner, "_mongo_client", lambda _timeout: Mongo())
    monkeypatch.setattr(
        runner, "_evaluate",
        lambda **_kwargs: (_ for _ in ()).throw(runner.CanaryInvariantError("blocked")),
    )
    monkeypatch.setattr(sys, "argv", [
        str(runner_path),
        "--epoch-id", "epoch-read-only",
        "--deployment-id", DEPLOYMENT,
        "--evidence-path", str(tmp_path / "evidence.sqlite"),
        "--check-only",
    ])

    assert runner.main() == 2
    assert appended == []


def test_seal_blocked_audit_uses_epoch_lineage_and_missing_lineage_fails(tmp_path):
    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "run_canary_until_seal_ready.py"
    spec = importlib.util.spec_from_file_location("canary_runner_audit", runner_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    appended = []

    class Store:
        def append_audit_event(self, event):
            appended.append(dict(event))

    epoch = SimpleNamespace(
        deployment_id=DEPLOYMENT,
        model_version="v3.1",
        artifact_sha256="artifact-test",
        feature_schema_version="schema-test",
        analysis_universe=("BTC", "ETH", "BNB"),
        analysis_universe_hash="universe-hash",
        activated_at="2026-08-01T00:00:00+00:00",
    )
    runner._record_seal_blocked(
        Store(), epoch,
        epoch_id="epoch-audit",
        deployment_id=DEPLOYMENT,
        reason="blocked",
    )

    assert appended[0]["paper_run_id"] == DEPLOYMENT
    assert appended[0]["analysis_universe"] == ["BTC", "ETH", "BNB"]
    with pytest.raises(RuntimeError, match="lineage unavailable"):
        runner._record_seal_blocked(
            Store(), None,
            epoch_id="epoch-audit",
            deployment_id=DEPLOYMENT,
            reason="blocked",
        )
    assert len(appended) == 1
