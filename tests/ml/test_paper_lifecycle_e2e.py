import asyncio
import json
import math

import pytest

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.fill_tracker import OrderStatus
from btc_scraper.execution.order_fill_ledger import LedgerStateCorruptError, OrderFillLedger
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.lifecycle_observability import producer_coverage_report
from btc_scraper.ml_engine.prediction_logger import append_prediction
from btc_scraper.ml_engine.runtime_outcome_linker import write_calibration_samples
from btc_scraper.ml_engine.runtime_outcome_linker import link_runtime_outcomes
from btc_scraper.trading import position_tracker
from btc_scraper.trading.decision_types import ReservationStatus


class _MemoryCollection:
    def __init__(self):
        self.rows = []

    def insert_one(self, doc):
        self.rows.append(dict(doc))

    def find_one(self, query, projection=None):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return {key: value for key, value in row.items() if key != "_id"}
        return None

    def update_one(self, query, update):
        row = self.find_one(query)
        if row is None:
            return
        for existing in self.rows:
            if all(existing.get(key) == value for key, value in query.items()):
                existing.update(update.get("$set", {}))
                return

    def find(self, query=None, projection=None):
        query = query or {}
        return [
            {key: value for key, value in row.items() if key != "_id"}
            for row in self.rows
            if all(row.get(key) == value for key, value in query.items())
        ]


def test_paper_lifecycle_links_prediction_to_closed_outcome(monkeypatch, tmp_path):
    positions = _MemoryCollection()
    closed_positions = _MemoryCollection()
    closed_trades = _MemoryCollection()
    monkeypatch.setattr(position_tracker, "positions_col", positions)
    monkeypatch.setattr(position_tracker, "closed_positions_col", closed_positions)
    monkeypatch.setattr(position_tracker, "closed_trades_col", closed_trades)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    prediction = append_prediction(
        model_name="meta_model",
        model_version="v3-paper",
        artifact_sha256="artifact-sha",
        feature_schema_version="meta-v3",
        raw_prediction=0.74,
        calibrated_prediction=0.74,
        features=[1.0, 2.0, 3.0],
        decision_context="entry",
        symbol="BTC",
        timeframe="15m",
        side="BUY",
        signal_id="sig-paper-1",
        log_dir=tmp_path / "prediction_audit",
    )

    engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution_logs"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-paper-1",
        "prediction_id": prediction["prediction_id"],
        "entry_decision_id": "ed-paper-1",
        "decision_id": "ed-paper-1",
        "idempotency_key": "idem-paper-1",
        "client_order_id": "client-paper-1",
        "lifecycle_schema_version": "trade-lifecycle-v1",
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    fill_record = engine.submit_paper(signal, candle, notional_usdt=100.0)
    assert fill_record.status == "FILLED", fill_record.reason
    assert fill_record.fills
    assert fill_record.entry_decision_id == "ed-paper-1"
    assert fill_record.reservation_id
    assert fill_record.idempotency_key == "idem-paper-1"
    assert fill_record.client_order_id == "client-paper-1"

    position = position_tracker.add_position(
        coin="BTC",
        entry_price=fill_record.avg_fill_price,
        direction="LONG",
        invested_usdt=100.0,
        trade_origin="paper_mode",
        execution_mode="paper",
        fill_source=fill_record.fill_source,
        paper_run_id=fill_record.paper_run_id,
        created_by="paper_lifecycle_e2e",
        prediction_id=fill_record.prediction_id,
        signal_id=fill_record.signal_id,
        entry_decision_id=fill_record.entry_decision_id,
        reservation_id=fill_record.reservation_id,
        idempotency_key=fill_record.idempotency_key,
        client_order_id=fill_record.client_order_id,
        exchange_order_id=fill_record.exchange_order_id,
        fill_id=fill_record.fills[0].fill_id,
        lifecycle_schema_version=fill_record.lifecycle_schema_version,
        model_version=prediction["model_version"],
        artifact_sha256=prediction["artifact_sha256"],
        feature_schema_version=prediction["feature_schema_version"],
    )

    outcome = position_tracker.close_position("BTC", sell_price=fill_record.avg_fill_price * 1.02)
    assert outcome["prediction_id"] == prediction["prediction_id"]
    assert outcome["signal_id"] == "sig-paper-1"
    assert outcome["id"] == position["id"]
    assert outcome["outcome_revision"] == 1
    assert outcome["net_pnl_pct"] > 0
    assert outcome["reservation_id"] == fill_record.reservation_id
    assert outcome["client_order_id"] == fill_record.client_order_id

    report = link_runtime_outcomes([prediction], [{
        **outcome,
        "position_id": outcome["id"],
        "source": outcome["fill_source"],
        "closed_at": outcome["closed_at"],
    }])
    assert len(report.samples) == 1
    sample = report.samples[0]
    assert sample.prediction_id == prediction["prediction_id"]
    assert sample.signal_id == "sig-paper-1"
    assert sample.position_id == outcome["id"]
    assert sample.model_version == "v3-paper"
    assert sample.artifact_sha256 == "artifact-sha"
    assert sample.feature_schema_version == "meta-v3"
    assert write_calibration_samples(report.samples, tmp_path / "runtime_calibration.jsonl") == 1
    assert write_calibration_samples(report.samples, tmp_path / "runtime_calibration.jsonl") == 0

    duplicate_report = link_runtime_outcomes([prediction], [
        {**outcome, "position_id": outcome["id"], "source": outcome["fill_source"]},
        {**outcome, "position_id": outcome["id"], "source": outcome["fill_source"]},
    ])
    assert len(duplicate_report.samples) == 1
    assert duplicate_report.duplicate_outcome_count == 1

    coverage = producer_coverage_report({
        "prediction": [prediction],
        "entry_decision": [{
            "prediction_id": prediction["prediction_id"],
            "signal_id": "sig-paper-1",
            "entry_decision_id": "ed-paper-1",
        }],
        "reservation": [{
            "entry_decision_id": fill_record.entry_decision_id,
            "reservation_id": fill_record.reservation_id,
            "idempotency_key": fill_record.idempotency_key,
        }],
        "submitted_order": [{
            "entry_decision_id": fill_record.entry_decision_id,
            "reservation_id": fill_record.reservation_id,
            "client_order_id": fill_record.client_order_id,
        }],
        "fill": [{
            "client_order_id": fill_record.client_order_id,
            "fill_id": fill_record.fills[0].fill_id,
            "position_id": outcome["id"],
        }],
        "open_position": [{
            "prediction_id": position["prediction_id"],
            "signal_id": position["signal_id"],
            "position_id": position["id"],
        }],
        "closed_outcome": [{
            "position_id": outcome["id"],
            "outcome_id": outcome["outcome_id"],
            "outcome_revision": outcome["outcome_revision"],
        }],
    })
    assert coverage["all_required_coverage_rate"] == 1.0


def test_paper_timeout_then_restart_reuses_reservation_and_client_order_id(tmp_path):
    db_path = tmp_path / "reservations.db"
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-restart",
        "prediction_id": "pred-restart",
        "entry_decision_id": "ed-restart",
        "idempotency_key": "idem-restart",
        "client_order_id": "client-restart",
        "simulate_timeout_after_reserve": True,
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    first = ExecutionEngine(
        log_dir=str(tmp_path / "exec1"),
        fills_dir=str(tmp_path / "fills1"),
        reports_dir=str(tmp_path / "reports1"),
        reservation_db_path=str(db_path),
    ).submit_paper(signal, candle, notional_usdt=100.0)
    assert first.status == "TIMEOUT"
    reservation = ReservationStore(db_path).get_reservation(first.reservation_id)
    assert reservation.status == ReservationStatus.PENDING
    assert reservation.client_order_id is None

    retry_signal = {k: v for k, v in signal.items() if k != "simulate_timeout_after_reserve"}
    retry = ExecutionEngine(
        log_dir=str(tmp_path / "exec2"),
        fills_dir=str(tmp_path / "fills2"),
        reports_dir=str(tmp_path / "reports2"),
        reservation_db_path=str(db_path),
    ).submit_paper(retry_signal, candle, notional_usdt=100.0)
    assert retry.status == "FILLED"
    assert retry.reservation_id == first.reservation_id
    assert retry.client_order_id == "client-restart"
    committed = ReservationStore(db_path).get_reservation(retry.reservation_id)
    assert committed.status == ReservationStatus.COMMITTED
    assert committed.client_order_id == "client-restart"


def test_paper_partial_fill_then_cancel_releases_remaining_reservation(tmp_path):
    db_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(db_path),
    )
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-partial",
        "prediction_id": "pred-partial",
        "entry_decision_id": "ed-partial",
        "idempotency_key": "idem-partial",
        "paper_fill_fraction": 0.4,
        "paper_cancel_remaining": True,
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    record = engine.submit_paper(signal, candle, notional_usdt=100.0)
    assert record.filled_qty > 0
    assert record.unfilled_qty > 0
    reservation = ReservationStore(db_path).get_reservation(record.reservation_id)
    assert reservation.status in (ReservationStatus.CANCELLED_WITH_PARTIAL_FILL, ReservationStatus.RELEASED)
    assert 39.0 <= reservation.filled_notional <= 41.0
    released_notional = reservation.reserved_notional - reservation.filled_notional
    assert 59.0 <= released_notional <= 61.0
    assert reservation.filled_notional <= reservation.reserved_notional
    assert released_notional >= 0.0


def test_paper_fill_before_reservation_commit_recovers_idempotently(tmp_path):
    shared_db_path = tmp_path / "reservations.db"
    shared_log_dir = tmp_path / "shared_exec"
    shared_fills_dir = tmp_path / "shared_fills"
    shared_reports_dir = tmp_path / "shared_reports"

    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-crash",
        "prediction_id": "pred-crash",
        "entry_decision_id": "ed-crash",
        "idempotency_key": "idem-crash",
        "simulate_crash_after_fill_before_commit": True,
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}

    # 1. Engine A simulates: reserve, fill, persist fill, crash before reservation commit
    engine_a = ExecutionEngine(
        log_dir=str(shared_log_dir),
        fills_dir=str(shared_fills_dir),
        reports_dir=str(shared_reports_dir),
        reservation_db_path=str(shared_db_path),
    )
    first = engine_a.submit_paper(signal, candle, notional_usdt=100.0)
    assert first.status == "FILLED"
    # Immediately after simulated crash before commit: reservation in DB is still PENDING
    pending = ReservationStore(shared_db_path).get_reservation(first.reservation_id)
    assert pending.status == ReservationStatus.PENDING

    # Verify persisted fill exists on disk
    fill_files = list(shared_fills_dir.rglob("fills_*.jsonl"))
    assert len(fill_files) > 0
    total_fills_after_first = sum(
        1 for p in fill_files for line in p.read_text(encoding="utf-8").strip().splitlines() if line.strip()
    )
    assert total_fills_after_first == 1

    # 3. Destroy Engine A
    del engine_a

    # 4. Initialize Engine B as a new process sharing reservation DB, log dir, fills dir
    engine_b = ExecutionEngine(
        log_dir=str(shared_log_dir),
        fills_dir=str(shared_fills_dir),
        reports_dir=str(shared_reports_dir),
        reservation_db_path=str(shared_db_path),
    )

    # Right after startup (BEFORE retry):
    # - persisted fill has been read
    # - reservation in SQLite is no longer PENDING; authoritatively transitioned to COMMITTED
    # - filled quantity matches
    startup_res = ReservationStore(shared_db_path).get_reservation(first.reservation_id)
    assert startup_res.status == ReservationStatus.COMMITTED
    assert math.isclose(startup_res.filled_qty, first.filled_qty, rel_tol=1e-7, abs_tol=1e-7)

    # 5. Retry with the same idempotency key:
    # - does not create new fill
    # - returns duplicate_idempotency_key_already_committed
    # - total persisted fill count remains EXACTLY 1
    retry_signal = {k: v for k, v in signal.items() if k != "simulate_crash_after_fill_before_commit"}
    retry = engine_b.submit_paper(retry_signal, candle, notional_usdt=100.0)
    assert retry.status == "FILLED"
    assert retry.reason == "duplicate_idempotency_key_already_committed"
    assert retry.reservation_id == first.reservation_id
    assert retry.fills == []

    # Total persisted fills on disk must STILL be strictly 1
    total_fills_after_retry = sum(
        1 for p in fill_files for line in p.read_text(encoding="utf-8").strip().splitlines() if line.strip()
    )
    assert total_fills_after_retry == 1

    # 6. Second reconciliation run:
    # - returns exactly 0 updates (strictly idempotent)
    second_reconciled = engine_b._reservation_store.reconcile_crashed_reservations(
        engine_b._tracker.load_persisted_records()
    )
    assert second_reconciled == 0


def test_loader_handles_truncated_and_corrupt_jsonl(tmp_path):
    from btc_scraper.execution.fill_tracker import FillTracker, _tail_read_jsonl
    fills_dir = tmp_path / "corrupt_fills"
    fills_dir.mkdir(parents=True)
    jsonl_file = fills_dir / "fills_2026-11-15.jsonl"

    valid_record_1 = json.dumps({"execution_id": "rec-001", "reservation_id": "res-001", "status": "FILLED", "filled_qty": 0.5})
    non_dict = json.dumps(["some", "array", "not", "dict"])
    corrupt_line = "{malformed json line:"
    valid_record_2 = json.dumps({"execution_id": "rec-002", "reservation_id": "res-002", "status": "FILLED", "filled_qty": 1.0})
    truncated_line = '{"execution_id": "rec-003", "status": "FIL'

    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(f"{valid_record_1}\n{non_dict}\n{corrupt_line}\n{valid_record_2}\n{truncated_line}")

    records = _tail_read_jsonl(jsonl_file, max_records=5000)
    record_ids = [r["execution_id"] for r in records if "execution_id" in r]
    assert "rec-002" in record_ids
    assert "rec-001" in record_ids
    assert len(record_ids) == 2

    tracker = FillTracker(log_dir=str(tmp_path / "logs"), fills_dir=str(fills_dir))
    loaded = tracker.load_persisted_records(limit=10)
    loaded_ids = [r.execution_id for r in loaded]
    assert "rec-002" in loaded_ids
    assert "rec-001" in loaded_ids


def test_paper_retry_unverified_reconciliation_required_fails_closed(tmp_path):
    db_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reservation_db_path=str(db_path),
    )
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-reconcile-fail-closed",
        "idempotency_key": "idem-fail-closed",
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    # Seed a reservation with RECONCILIATION_REQUIRED status (unverified fill state)
    res_rec, _ = engine._reservation_store.reserve(
        reservation_id="res-unverified",
        idempotency_key="idem-fail-closed",
        entry_decision_id="dec-1",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
    )
    with engine._reservation_store._get_conn() as conn:
        conn.execute(
            "UPDATE reservations SET status = ? WHERE reservation_id = ?",
            (ReservationStatus.RECONCILIATION_REQUIRED.value, res_rec.reservation_id),
        )

    # Attempting to submit retry with unverified reconciliation_required must reject, never fill
    record = engine.submit_paper(signal, candle, notional_usdt=100.0)
    assert record.status == OrderStatus.REJECTED
    assert "duplicate_idempotency_key_reconciliation_required" in record.reason
    fills = list((tmp_path / "fills").rglob("fills_*.jsonl"))
    assert len(fills) == 0


def test_paper_duplicate_idempotency_replay_does_not_refill(tmp_path):
    db_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(db_path),
    )
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-duplicate",
        "prediction_id": "pred-duplicate",
        "entry_decision_id": "ed-duplicate",
        "reservation_id": "res-duplicate",
        "idempotency_key": "idem-duplicate",
        "client_order_id": "client-duplicate",
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}

    first = engine.submit_paper(signal, candle, notional_usdt=100.0)
    replay = engine.submit_paper(signal, candle, notional_usdt=100.0)

    assert first.status == "FILLED"
    assert replay.status == "FILLED"
    assert replay.reason == "duplicate_idempotency_key_already_committed"
    assert replay.reservation_id == first.reservation_id
    assert replay.client_order_id == first.client_order_id
    assert replay.fills == []
    reservation = ReservationStore(db_path).get_reservation(first.reservation_id)
    assert reservation.status == ReservationStatus.COMMITTED
    assert 99.0 <= reservation.filled_notional <= 101.0


def test_live_path_rejects_paper_recovery_simulation_flags(tmp_path):
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.db"),
    )
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": "sig-live-guard",
        "simulate_timeout_after_reserve": True,
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}

    with pytest.raises(ValueError, match="Paper recovery simulation flags"):
        asyncio.run(engine.submit_live(signal, candle, notional_usdt=100.0))


def test_persistent_ledger_resolves_fill_before_order_after_restart(tmp_path):
    ledger_path = tmp_path / "order_fill_ledger.json"
    fill = {
        "exchange_trade_id": "trade-1",
        "exchange_order_id": "exchange-order-1",
        "client_order_id": "client-order-1",
        "fill_id": "fill-1",
        "qty": 0.4,
        "price": 100.0,
    }
    first = OrderFillLedger(ledger_path)
    fill_result = first.record_fill(fill)
    assert fill_result["status"] == "pending_order"
    assert first.snapshot()["pending_fill_count"] == 1

    restarted = OrderFillLedger(ledger_path)
    order_result = restarted.record_order({
        "exchange_order_id": "exchange-order-1",
        "client_order_id": "client-order-1",
        "reservation_id": "res-order-1",
    })
    assert order_result["status"] == "linked"
    assert order_result["resolved_fill_count"] == 1
    snapshot = restarted.snapshot()
    assert snapshot["order_count"] == 1
    assert snapshot["fill_count"] == 1
    assert snapshot["pending_fill_count"] == 0

    restarted.record_fill(fill)
    restarted.record_order({
        "exchange_order_id": "exchange-order-1",
        "client_order_id": "client-order-1",
        "reservation_id": "res-order-1",
    })
    replay_snapshot = restarted.snapshot()
    assert replay_snapshot["order_count"] == 1
    assert replay_snapshot["fill_count"] == 1
    assert replay_snapshot["pending_fill_count"] == 0
    order = next(iter(replay_snapshot["orders"].values()))
    assert order["fill_keys"] == ["exchange_trade_id:trade-1"]


def test_order_fill_ledger_quarantines_ambiguous_reconciliation(tmp_path):
    ledger = OrderFillLedger(tmp_path / "order_fill_ledger.json")
    ledger.record_order({"exchange_order_id": "exchange-order-a", "client_order_id": "client-a"})
    ledger.record_order({"exchange_order_id": "exchange-order-b", "client_order_id": "client-b"})

    result = ledger.record_fill({
        "exchange_trade_id": "trade-conflict",
        "exchange_order_id": "exchange-order-a",
        "client_order_id": "client-b",
        "qty": 0.1,
        "price": 100.0,
    })

    snapshot = ledger.snapshot()
    assert result["status"] == "quarantined_conflict"
    assert snapshot["conflict_count"] == 1
    assert snapshot["pending_fill_count"] == 0
    assert snapshot["single_writer_only"] is True


def test_order_fill_ledger_corrupt_state_fails_closed(tmp_path):
    ledger_path = tmp_path / "order_fill_ledger.json"
    ledger_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(LedgerStateCorruptError):
        OrderFillLedger(ledger_path)


def test_full_chain_replay_keeps_covered_paper_state_unchanged(monkeypatch, tmp_path):
    positions = _MemoryCollection()
    closed_positions = _MemoryCollection()
    closed_trades = _MemoryCollection()
    monkeypatch.setattr(position_tracker, "positions_col", positions)
    monkeypatch.setattr(position_tracker, "closed_positions_col", closed_positions)
    monkeypatch.setattr(position_tracker, "closed_trades_col", closed_trades)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    prediction = {
        "prediction_id": "pred-replay-chain",
        "signal_id": "sig-replay-chain",
        "position_id": "pos-replay-chain",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "symbol": "BTC",
        "decision_context": "entry",
        "model_name": "meta_model",
        "model_version": "v3-paper",
        "artifact_sha256": "artifact-replay",
        "feature_schema_version": "meta-v3",
        "calibrated_prediction": 0.74,
    }
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": prediction["signal_id"],
        "prediction_id": prediction["prediction_id"],
        "entry_decision_id": "ed-replay-chain",
        "reservation_id": "res-replay-chain",
        "idempotency_key": "idem-replay-chain",
        "client_order_id": "client-replay-chain",
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    db_path = tmp_path / "reservations.db"
    engine = ExecutionEngine(
        log_dir=str(tmp_path / "exec"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(db_path),
    )
    ledger = OrderFillLedger(tmp_path / "order_fill_ledger.json")
    sample_path = tmp_path / "runtime_calibration.jsonl"

    def run_once(close: bool):
        record = engine.submit_paper(signal, candle, notional_usdt=100.0)
        ledger.record_order({
            "client_order_id": record.client_order_id,
            "reservation_id": record.reservation_id,
        })
        if record.fills:
            ledger.record_fill({
                "exchange_trade_id": record.fills[0].fill_id,
                "client_order_id": record.client_order_id,
                "fill_id": record.fills[0].fill_id,
                "qty": record.fills[0].qty,
                "price": record.fills[0].price,
            })
        position_tracker.add_position(
            coin="BTC",
            entry_price=record.avg_fill_price or candle["close"],
            direction="LONG",
            invested_usdt=100.0,
            trade_origin="paper_mode",
            execution_mode="paper",
            fill_source="real_paper",
            prediction_id=prediction["prediction_id"],
            signal_id=prediction["signal_id"],
            entry_decision_id=signal["entry_decision_id"],
            reservation_id=record.reservation_id,
            idempotency_key=record.idempotency_key,
            client_order_id=record.client_order_id,
            fill_id=record.fills[0].fill_id if record.fills else "fill-replay-chain",
            position_id=prediction["position_id"],
            model_version=prediction["model_version"],
            artifact_sha256=prediction["artifact_sha256"],
            feature_schema_version=prediction["feature_schema_version"],
        )
        if close:
            outcome = position_tracker.close_position("BTC", sell_price=(record.avg_fill_price or candle["close"]) * 1.02)
            report = link_runtime_outcomes([prediction], [{**outcome, "position_id": outcome["id"], "source": outcome["fill_source"]}])
            write_calibration_samples(report.samples, sample_path)

    run_once(close=True)
    before = {
        "prediction_count": 1,
        "decision_count": 1,
        "reservation": ReservationStore(db_path).get_reservation("res-replay-chain").to_dict(),
        "ledger": ledger.snapshot(),
        "position_count": len(positions.rows),
        "outcome_count": len(closed_positions.rows),
        "sample_lines": sample_path.read_text(encoding="utf-8").count("\n"),
    }
    run_once(close=False)
    after = {
        "prediction_count": 1,
        "decision_count": 1,
        "reservation": ReservationStore(db_path).get_reservation("res-replay-chain").to_dict(),
        "ledger": ledger.snapshot(),
        "position_count": len(positions.rows),
        "outcome_count": len(closed_positions.rows),
        "sample_lines": sample_path.read_text(encoding="utf-8").count("\n"),
    }

    assert after == before


def test_operational_restart_closes_persisted_paper_position_once(monkeypatch, tmp_path):
    positions = _MemoryCollection()
    closed_positions = _MemoryCollection()
    closed_trades = _MemoryCollection()
    monkeypatch.setattr(position_tracker, "positions_col", positions)
    monkeypatch.setattr(position_tracker, "closed_positions_col", closed_positions)
    monkeypatch.setattr(position_tracker, "closed_trades_col", closed_trades)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    prediction = {
        "prediction_id": "pred-operational-restart",
        "signal_id": "sig-operational-restart",
        "position_id": "pos-operational-restart",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "symbol": "BTC",
        "decision_context": "entry",
        "model_name": "meta_model",
        "model_version": "v3-paper",
        "artifact_sha256": "artifact-restart",
        "feature_schema_version": "meta-v3",
        "calibrated_prediction": 0.76,
    }
    signal = {
        "coin": "BTC",
        "signal": "BUY",
        "signal_raw": "BUY",
        "id": prediction["signal_id"],
        "prediction_id": prediction["prediction_id"],
        "entry_decision_id": "ed-operational-restart",
        "reservation_id": "res-operational-restart",
        "idempotency_key": "idem-operational-restart",
        "client_order_id": "client-operational-restart",
    }
    candle = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 1_000_000.0}
    db_path = tmp_path / "reservations.db"
    ledger_path = tmp_path / "order_fill_ledger.json"
    sample_path = tmp_path / "runtime_calibration.jsonl"

    process_a = ExecutionEngine(
        log_dir=str(tmp_path / "exec_a"),
        fills_dir=str(tmp_path / "fills_a"),
        reports_dir=str(tmp_path / "reports_a"),
        reservation_db_path=str(db_path),
    )
    fill_record = process_a.submit_paper(signal, candle, notional_usdt=100.0)
    ledger_a = OrderFillLedger(ledger_path)
    ledger_a.record_order({"client_order_id": fill_record.client_order_id, "reservation_id": fill_record.reservation_id})
    ledger_a.record_fill({
        "exchange_trade_id": fill_record.fills[0].fill_id,
        "client_order_id": fill_record.client_order_id,
        "fill_id": fill_record.fills[0].fill_id,
        "qty": fill_record.fills[0].qty,
        "price": fill_record.fills[0].price,
    })
    position_tracker.add_position(
        coin="BTC",
        entry_price=fill_record.avg_fill_price,
        direction="LONG",
        invested_usdt=100.0,
        trade_origin="paper_mode",
        execution_mode="paper",
        fill_source="real_paper",
        prediction_id=prediction["prediction_id"],
        signal_id=prediction["signal_id"],
        entry_decision_id=signal["entry_decision_id"],
        reservation_id=fill_record.reservation_id,
        idempotency_key=fill_record.idempotency_key,
        client_order_id=fill_record.client_order_id,
        fill_id=fill_record.fills[0].fill_id,
        position_id=prediction["position_id"],
        model_version=prediction["model_version"],
        artifact_sha256=prediction["artifact_sha256"],
        feature_schema_version=prediction["feature_schema_version"],
    )

    process_b = ExecutionEngine(
        log_dir=str(tmp_path / "exec_b"),
        fills_dir=str(tmp_path / "fills_b"),
        reports_dir=str(tmp_path / "reports_b"),
        reservation_db_path=str(db_path),
    )
    replay = process_b.submit_paper(signal, candle, notional_usdt=100.0)
    ledger_b = OrderFillLedger(ledger_path)
    outcome = position_tracker.close_position("BTC", sell_price=fill_record.avg_fill_price * 1.02)
    report = link_runtime_outcomes([prediction], [{**outcome, "position_id": outcome["id"], "source": outcome["fill_source"]}])

    assert replay.reason == "duplicate_idempotency_key_already_committed"
    assert replay.fills == []
    assert ReservationStore(db_path).get_reservation(fill_record.reservation_id).status == ReservationStatus.COMMITTED
    assert ledger_b.snapshot()["fill_count"] == 1
    assert len(positions.rows) == 1
    assert len(closed_positions.rows) == 1
    assert outcome["prediction_id"] == prediction["prediction_id"]
    assert outcome["signal_id"] == prediction["signal_id"]
    assert outcome["entry_decision_id"] == signal["entry_decision_id"]
    assert outcome["reservation_id"] == fill_record.reservation_id
    assert outcome["id"] == prediction["position_id"]
    assert outcome["outcome_revision"] == 1
    assert len(report.samples) == 1
    assert write_calibration_samples(report.samples, sample_path) == 1
    assert write_calibration_samples(report.samples, sample_path) == 0
