from __future__ import annotations

from btc_scraper.execution.order_fill_ledger import OrderFillLedger
from btc_scraper.execution.recovery import RecoveryCoordinator
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def make_coordinator(paths) -> RecoveryCoordinator:
    return RecoveryCoordinator(
        evidence_store=RuntimeEvidenceStore(paths["evidence"]),
        reservation_store=ReservationStore(paths["reservations"]),
        ledger=OrderFillLedger(paths["ledger"]),
    )


def seed_prediction(store: RuntimeEvidenceStore, prediction_id: str = "pred-recovery-1") -> dict:
    prediction = {
        "prediction_id": prediction_id,
        "signal_id": "sig-recovery-1",
        "symbol": "BTC",
        "timeframe": "15m",
        "side": "BUY",
        "model_name": "meta_model",
        "model_version": "v3-recovery",
        "artifact_sha256": "artifact-recovery",
        "feature_schema_version": "meta-v3",
        "calibrated_probability": 0.72,
    }
    snapshot = {
        "prediction_id": prediction_id,
        "feature_snapshot_id": "fs-recovery-1",
        "features": [1.0, 2.0, 3.0],
        "feature_hash": "feature-hash-recovery",
    }
    store.write_prediction_evidence(prediction, snapshot)
    return prediction
