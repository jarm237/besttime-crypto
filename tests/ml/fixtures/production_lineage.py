from __future__ import annotations

from pathlib import Path
from typing import Any

import btc_scraper.ml_engine.runtime_evidence_store as evidence_module
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def configure_smoke_runtime(monkeypatch, tmp_path: Path) -> Path:
    """Point the runtime helpers at a fully isolated test-local namespace."""
    runtime_root = tmp_path / "runtime" / "test" / "paper-smoke"
    env_map = {
        "BTC_RUNTIME_ENVIRONMENT": "test",
        "BTC_ENVIRONMENT": "test",
        "BTC_DEPLOYMENT_ID": "paper-smoke-001",
        "BTC_RUNTIME_ID": "paper-smoke-001",
        "BTC_RUNTIME_ROOT": str(runtime_root),
        "BTC_EVIDENCE_ELIGIBLE": "false",
        "BTC_PAPER_RUN_ID": "paper-smoke-001",
        "BTC_ANALYSIS_UNIVERSE": "BTC,ETH,BNB",
        "AUTO_TRADE_COINS": "BTC,ETH,BNB",
        "BTC_DATA_DIR": str(runtime_root / "data"),
        "BTC_LOG_DIR": str(runtime_root / "logs"),
        "BTC_MODEL_DIR": str(runtime_root / "models"),
        "BTC_STATE_DIR": str(runtime_root / "state"),
        "BTC_EXECUTION_DATA_DIR": str(runtime_root / "data" / "execution"),
        "BTC_PREDICTION_AUDIT_DIR": str(runtime_root / "logs" / "prediction_audit"),
        "BTC_RUNTIME_EVIDENCE_PATH": str(runtime_root / "logs" / "runtime_evidence.sqlite"),
        "BTC_RESERVATION_DB_PATH": str(runtime_root / "data" / "execution" / "reservations.db"),
        "BTC_RUNTIME_LOCK_PATH": str(runtime_root / "state" / "runtime.lock"),
        "CATBOOST_INFO_DIR": str(runtime_root / "catboost_info"),
    }
    for key, value in env_map.items():
        monkeypatch.setenv(key, value)
    return runtime_root


def install_evidence_store(monkeypatch, tmp_path: Path) -> RuntimeEvidenceStore:
    """Install a per-test durable evidence store without touching the production namespace."""
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(evidence_module, "_STORE", store)
    return store


def build_smoke_analysis() -> dict[str, Any]:
    """Return a compact but realistic analysis payload for inference smoke validation."""
    return {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "signal": "BUY",
        "cycle_id": "smoke-cycle-001",
        "timeframe": "15m",
        "input_end_time": "2026-07-30T03:00:00+00:00",
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
        "history": [
            {"time": "2026-07-30T03:00:00+00:00", "close": 100.0},
            {"time": "2026-07-30T03:15:00+00:00", "close": 100.2},
        ],
    }
