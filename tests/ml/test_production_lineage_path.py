from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.ml_engine import meta_model
from btc_scraper.ml_engine import runtime_evidence_store as evidence_module
from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
from btc_scraper.ml_engine.multi_agent import AgentOrchestrator, SignalGeneratorAgent
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.trading import position_tracker
from btc_scraper.trading.auto_trader import AutoTrader


class _MemoryCollection:
    def __init__(self):
        self.rows: list[dict] = []

    def insert_one(self, document):
        self.rows.append(dict(document))

    def find_one(self, query, projection=None):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return {key: value for key, value in row.items() if key != "_id"}
        return None

    def update_one(self, query, update):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                row.update(update.get("$set", {}))
                return

    def find(self, query=None, projection=None):
        query = query or {}
        return [
            dict(row)
            for row in self.rows
            if all(row.get(key) == value for key, value in query.items())
        ]


class _FixedModel:
    def __init__(self):
        self.calls = 0

    def predict_proba(self, rows):
        self.calls += 1
        return np.asarray([[0.25, 0.75] for _ in rows])


class _AnalysisBoundary:
    def run(self, context):
        context["analysis"] = context["raw_candles"]
        return context


class _PassAgent:
    def run(self, context):
        return context


class _AsyncPassAgent:
    async def run(self, context):
        return context


def test_real_entry_components_propagate_prediction_to_outcome(monkeypatch, tmp_path):
    evidence_store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", evidence_store)
    model = _FixedModel()
    bundle = {"model": model, "features": ["rsi_score"]}
    monkeypatch.setattr(meta_model, "_MODEL_ARTIFACT_PROVENANCE", None)
    monkeypatch.setattr(meta_model, "_MODEL_ARTIFACT_OWNER_ID", None)
    meta_model.bind_model_artifact_provenance(
        bundle,
        artifact_version="lineage-test-v1",
        artifact_hash="a" * 64,
        feature_names=["rsi_score"],
        feature_schema_version="lineage-test-schema/v1",
        metadata={"features": ["rsi_score"], "n_features": 1},
    )
    monkeypatch.setattr(
        meta_model,
        "load_model",
        lambda: bundle,
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.artifact_resolver.ArtifactResolver.resolve",
        lambda self, name, require_metadata=False: SimpleNamespace(
            healthy=True,
            path=tmp_path / "meta.joblib",
            sha256="artifact-sha",
            metadata={"calibration_method": "isotonic"},
            reason=None,
        ),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score._load_adaptive_model",
        lambda: None,
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score._get_cached_risk_metrics",
        lambda: {"risk_multiplier": 1.0, "blocked": False, "drawdown_pct": 0.0},
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.causal_context_bridge.get_hybrid_provider",
        lambda alpha=None: None,
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.alternative_reference.load_alternative_reference",
        lambda: {},
    )
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "test")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "lineage-test")
    monkeypatch.setenv("BTC_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("BTC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BTC_PAPER_RUN_ID", "paper-lineage")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.60")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "60")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
    monkeypatch.setenv("AUTO_TRADE_MAX_DAILY", "99")

    positions = _MemoryCollection()
    monkeypatch.setattr(position_tracker, "positions_col", positions)
    monkeypatch.setattr(position_tracker, "closed_positions_col", _MemoryCollection())
    monkeypatch.setattr(position_tracker, "closed_trades_col", _MemoryCollection())
    monkeypatch.setattr(position_tracker, "save_lstm_cache", lambda: None)

    analysis = {
        "BTC:Binance": {
            "coin": "BTC",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "signal": "BUY",
            "close": 100.0,
            "open": 100.0,
            "high": 100.01,
            "low": 99.99,
            "volume": 1_000_000.0,
            "rsi": 30.0,
            "atr": 2.0,
            "tp_sl": {
                "entry": 100.0,
                "sl": 98.0,
                "tp1": 104.0,
                "tp2": 106.0,
                "rr1": 2.0,
                "rr2": 3.0,
            },
            "history": [{"time": "2026-07-30T03:00:00+00:00", "close": 100.0}],
        }
    }
    # Exercise the real orchestrator boundary while replacing only unrelated
    # market collection, portfolio, risk and RL dependencies.
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator.market_analyst = _AnalysisBoundary()
    orchestrator.signal_generator = SignalGeneratorAgent()
    orchestrator.risk_manager = _PassAgent()
    orchestrator.portfolio_manager = _PassAgent()
    orchestrator.rl_exit = _PassAgent()
    orchestrator.execution = _AsyncPassAgent()
    context = asyncio.run(orchestrator.run_cycle(analysis, {}))
    enriched = context["analysis"]["BTC:Binance"]
    prediction_id = enriched["prediction_id"]
    signal_id = enriched["signal_id"]

    assert prediction_id
    assert signal_id
    assert enriched["deployment_id"] == "lineage-test"
    assert evidence_store.count_rows("predictions") == 1
    assert evidence_store.count_rows("final_decisions") == 1
    prediction = evidence_store.get_prediction(prediction_id)
    final_decision = evidence_store.get_final_decision_for_prediction(prediction_id)
    assert prediction["symbol"] == "BTC"
    assert final_decision["prediction_id"] == prediction_id
    assert final_decision["signal_id"] == signal_id

    trader = AutoTrader()
    trader._execution_engine = ExecutionEngine(
        log_dir=str(tmp_path / "execution"),
        fills_dir=str(tmp_path / "fills"),
        reports_dir=str(tmp_path / "reports"),
        reservation_db_path=str(tmp_path / "reservations.sqlite"),
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_open_positions",
        lambda: [],
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit",
        lambda coin, open_positions, balance: 100.0,
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures",
        lambda balance: (0.0, {}, {}),
    )
    monkeypatch.setattr("btc_scraper.trading.auto_trader._append_log", lambda entry: None)
    monkeypatch.setattr(trader, "_notify_trade", lambda entry: None)

    execution = asyncio.run(trader._process_signal("BTC:Binance", enriched))
    assert execution and execution["status"] == "FILLED", (
        execution.get("reason_skip"),
        execution.get("guard_action"),
        execution.get("decision_breakdown"),
    )
    order = trader._execution_engine._tracker.get_history(limit=1)[0]
    reservation = trader._execution_engine._reservation_store.get_reservation(order.reservation_id)
    assert order.prediction_id == prediction_id
    assert reservation.prediction_id == prediction_id
    assert reservation.signal_id == signal_id
    assert len(positions.rows) == 1
    position = positions.rows[0]
    for row in (prediction, final_decision, order.to_dict(), reservation.to_dict(), position):
        assert row["signal_id"] == signal_id
        assert row["prediction_id"] == prediction_id
        assert row["model_version"] == prediction["model_version"]
        assert (
            row.get("model_artifact_sha256")
            or row.get("artifact_sha256")
            or row.get("artifact_hash")
        ) == prediction["artifact_sha256"]
        assert row["feature_schema_version"] == prediction["feature_schema_version"]
        assert row["deployment_id"] == "lineage-test"
        assert row["decision_context"] == "entry"
        assert row["caller_context"] == "agent_orchestrator"

    # Re-open the durable store before close to exercise the restart boundary.
    restarted_store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", restarted_store)
    outcome = position_tracker.close_position("BTC", position["entry_price"] * 1.02)
    assert outcome["prediction_id"] == prediction_id
    assert restarted_store.count_rows("outcome_links") == 1
    stored = restarted_store.latest_outcomes()[0]
    assert stored["prediction_id"] == prediction_id
    with pytest.raises(ValueError, match="Không tìm thấy"):
        position_tracker.close_position("BTC", position["entry_price"] * 1.02)
    assert restarted_store.count_rows("outcome_links") == 1


def test_coordinator_replay_reuses_one_prediction(monkeypatch, tmp_path):
    evidence_store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", evidence_store)
    model = _FixedModel()
    bundle = {"model": model, "features": ["rsi_score"]}
    monkeypatch.setattr(meta_model, "_MODEL_ARTIFACT_PROVENANCE", None)
    monkeypatch.setattr(meta_model, "_MODEL_ARTIFACT_OWNER_ID", None)
    meta_model.bind_model_artifact_provenance(
        bundle,
        artifact_version="lineage-test-v1",
        artifact_hash="a" * 64,
        feature_names=["rsi_score"],
        feature_schema_version="lineage-test-schema/v1",
        metadata={"features": ["rsi_score"], "n_features": 1},
    )
    monkeypatch.setattr(
        meta_model,
        "load_model",
        lambda: bundle,
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.artifact_resolver.ArtifactResolver.resolve",
        lambda self, name, require_metadata=False: SimpleNamespace(
            healthy=True,
            path=tmp_path / "meta.joblib",
            sha256="artifact-sha",
            metadata={"calibration_method": "isotonic"},
            reason=None,
        ),
    )
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "test")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "lineage-test")
    analysis = {
        "coin": "BTC",
        "signal": "BUY",
        "cycle_id": "cycle-replay",
        "timeframe": "15m",
        "history": [{"time": "2026-07-30T03:00:00+00:00"}],
    }
    first = InferenceCoordinator().predict_once(dict(analysis), symbol="BTC")
    restarted_store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", restarted_store)
    second = InferenceCoordinator().predict_once(dict(analysis), symbol="BTC")
    assert first.prediction_id == second.prediction_id
    assert first.signal_id == second.signal_id
    assert model.calls == 1
    assert restarted_store.count_rows("predictions") == 1
    payload = restarted_store.get_prediction(first.prediction_id)
    assert payload["idempotency_key"] == f"{first.signal_id}:{first.model_version}:entry"
