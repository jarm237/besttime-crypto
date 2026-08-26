import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
import pytest

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.p8_economic_extractor import (
    extract_closed_trades,
    run_funnel_analysis,
)
from scripts.p8_economic_report import calculate_metrics, determine_verdict

def test_p8_economic_extraction_and_funnel_analysis(tmp_path):
    evidence_path = tmp_path / "runtime_evidence.sqlite"
    reservation_path = tmp_path / "reservations.db"
    
    # 1. Setup mock reservation DB
    conn = sqlite3.connect(reservation_path)
    conn.execute("""
        CREATE TABLE reservations (
            reservation_id TEXT PRIMARY KEY,
            idempotency_key TEXT,
            entry_decision_id TEXT,
            symbol TEXT,
            side TEXT,
            reserved_notional REAL,
            filled_notional REAL,
            reserved_position_slots INTEGER,
            status TEXT,
            exchange_order_id TEXT,
            client_order_id TEXT,
            created_at TEXT,
            expires_at TEXT,
            updated_at TEXT,
            signal_id TEXT,
            prediction_id TEXT,
            model_version TEXT,
            model_artifact_sha256 TEXT,
            feature_schema_version TEXT,
            deployment_id TEXT,
            decision_context TEXT,
            caller_context TEXT,
            paper_run_id TEXT,
            cycle_id TEXT
        )
    """)
    conn.execute(
        "INSERT INTO reservations(reservation_id, entry_decision_id, symbol, side, filled_notional, status, client_order_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("res-1", "ed-1", "BTC/USDT", "buy", 100.0, "committed", "client-1")
    )
    conn.execute(
        "INSERT INTO reservations(reservation_id, entry_decision_id, symbol, side, filled_notional, status, client_order_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("res-2", "ed-2", "ETH/USDT", "buy", 100.0, "committed", "client-2")
    )
    conn.commit()
    conn.close()

    # 2. Setup mock evidence store
    store = RuntimeEvidenceStore(evidence_path)
    
    # Add active epoch so assertions pass
    with store._global_transaction() as db:
        db.execute(
            "INSERT INTO evidence_epochs("
            "epoch_id,deployment_id,started_at,activated_at,code_commit_sha,model_version,"
            "artifact_sha256,feature_schema_version,analysis_universe,"
            "analysis_universe_hash,evidence_policy_version,risk_policy_version,"
            "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "epoch-p8-test", "local-production", "2026-08-26T00:00:00Z",
                "2026-08-26T00:00:00Z", "commit-sha-test", "v3.1",
                "artifact-sha-test", "schema-test", '["BTC","ETH","BNB"]',
                "universe-hash-test", "evidence-v4", "risk-fail-closed-v1",
                6, "ACTIVE", "local-production", "{}", "sha256-test", "{}", "2026-08-26T00:00:00Z"
            )
        )

    # Insert mock predictions
    pred_1 = {
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "position_id": "pos-1",
        "symbol": "BTC/USDT",
        "timestamp": "2026-08-26T01:00:00Z",
        "model_version": "v3.1",
        "artifact_sha256": "artifact-sha-test",
        "feature_schema_version": "schema-test",
        "calibrated_prediction": 0.85,
        "evidence_eligible": True,
        "epoch_id": "epoch-p8-test",
        "deployment_id": "local-production"
    }
    pred_2 = {
        "prediction_id": "pred-2",
        "signal_id": "sig-2",
        "position_id": "pos-2",
        "symbol": "ETH/USDT",
        "timestamp": "2026-08-26T01:05:00Z",
        "model_version": "v3.1",
        "artifact_sha256": "artifact-sha-test",
        "feature_schema_version": "schema-test",
        "calibrated_prediction": 0.65,
        "evidence_eligible": True,
        "epoch_id": "epoch-p8-test",
        "deployment_id": "local-production"
    }
    
    with store.transaction() as db:
        db.execute("INSERT INTO predictions VALUES (?, ?, ?, ?)", ("pred-1", json.dumps(pred_1), "sha", "2026-08-26T01:00:00Z"))
        db.execute("INSERT INTO predictions VALUES (?, ?, ?, ?)", ("pred-2", json.dumps(pred_2), "sha", "2026-08-26T01:05:00Z"))
        
        # Insert mock final decisions
        dec_1 = {
            "decision_id": "ed-1",
            "prediction_id": "pred-1",
            "action": "BUY",
            "written_at": "2026-08-26T01:00:05Z",
            "model_version": "v3.1",
            "artifact_sha256": "artifact-sha-test",
            "meta_probability": 0.85
        }
        dec_2 = {
            "decision_id": "ed-2",
            "prediction_id": "pred-2",
            "action": "BUY",
            "written_at": "2026-08-26T01:05:05Z",
            "model_version": "v3.1",
            "artifact_sha256": "artifact-sha-test",
            "meta_probability": 0.65
        }
        db.execute("INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)", ("ed-1", "pred-1", json.dumps(dec_1), "sha", "2026-08-26T01:00:05Z"))
        db.execute("INSERT INTO final_decisions VALUES (?, ?, ?, ?, ?)", ("ed-2", "pred-2", json.dumps(dec_2), "sha", "2026-08-26T01:05:05Z"))

        # Insert mock outcomes
        out_1 = {
            "outcome_id": "out-1",
            "prediction_id": "pred-1",
            "position_id": "pos-1",
            "outcome_revision": 1,
            "net_pnl_pct": 1.5,
            "closed_at": "2026-08-26T01:10:00Z",
            "entry_time": "2026-08-26T01:00:10Z",
            "symbol": "BTC/USDT",
            "side": "LONG",
            "entry_price": 60000.0,
            "sell_price": 60900.0,
            "fee_usd": 0.6,
            "invested_usdt": 100.0,
            "fill_id": "fill-entry-1",
            "client_order_id": "client-1",
            "model_version": "v3.1",
            "artifact_sha256": "artifact-sha-test",
            "feature_schema_version": "schema-test"
        }
        out_2 = {
            "outcome_id": "out-2",
            "prediction_id": "pred-2",
            "position_id": "pos-2",
            "outcome_revision": 1,
            "net_pnl_pct": -1.1,
            "closed_at": "2026-08-26T01:15:00Z",
            "entry_time": "2026-08-26T01:05:10Z",
            "symbol": "ETH/USDT",
            "side": "LONG",
            "entry_price": 3000.0,
            "sell_price": 2985.0,
            "fee_usd": 0.6,
            "invested_usdt": 100.0,
            "fill_id": "fill-entry-2",
            "client_order_id": "client-2",
            "model_version": "v3.1",
            "artifact_sha256": "artifact-sha-test",
            "feature_schema_version": "schema-test"
        }
        db.execute("INSERT INTO outcome_links VALUES (?, ?, ?, ?, ?)", ("out-1", "pred-1", json.dumps(out_1), "sha", "2026-08-26T01:10:00Z"))
        db.execute("INSERT INTO outcome_links VALUES (?, ?, ?, ?, ?)", ("out-2", "pred-2", json.dumps(out_2), "sha", "2026-08-26T01:15:00Z"))

    # 3. Test Extract trades
    trades = extract_closed_trades(store, reservation_path)
    assert len(trades) == 2
    
    btc_trade = [t for t in trades if t["symbol"] == "BTC/USDT"][0]
    assert btc_trade["route"] == "LEGACY"
    assert btc_trade["net_return_bps"] == 150.0
    assert btc_trade["observed_net"] == 150.0
    assert btc_trade["fee_bps"] == 60.0 # (0.6 / 100.0) * 10000.0
    assert btc_trade["gross_return_bps"] == 210.0 # max(150.0, 150.0 + 60.0)
    assert btc_trade["estimated_net"] == 150.0
    assert btc_trade["lineage_complete"] is True
    assert btc_trade["decision_id"] == "ed-1"
    assert btc_trade["execution_id"] == "client-1"
    
    # 4. Test Funnel Analysis
    funnel = run_funnel_analysis(store, reservation_path)
    assert funnel["counts"]["predictions"] == 2
    assert funnel["counts"]["final_decisions"] == 2
    assert funnel["counts"]["actionable_decisions"] == 2
    assert funnel["counts"]["execution_attempts"] == 2
    assert funnel["counts"]["fills"] == 2
    assert funnel["counts"]["closed_trades"] == 2
    assert funnel["rates"]["actionable_rate"] == 1.0
    assert funnel["rates"]["execution_rate"] == 1.0
    assert funnel["rates"]["fill_rate"] == 1.0
    assert funnel["rates"]["closure_rate"] == 1.0

    # 5. Test metrics calculation
    metrics = calculate_metrics(trades)
    assert metrics["trade_count"] == 2
    assert metrics["win_rate"] == 0.5
    assert abs(metrics["net_ev_bps"] - 20.0) < 1e-4
    assert abs(metrics["profit_factor"] - 150.0 / 110.0) < 1e-4

    # 6. Test verdict logic
    legacy_metrics = {"LEGACY": {"net_ev_bps": 150.0}}
    stage, verdict = determine_verdict(len(trades), metrics, legacy_metrics, funnel)
    assert stage == "PRELIMINARY"
    assert verdict == "CONTINUE_OBSERVATION"
