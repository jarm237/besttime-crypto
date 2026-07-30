"""Versioned prediction envelope and JSONL audit logging."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .artifact_resolver import ROOT
from .data_contracts import validate_runtime_event
from .runtime_evidence_store import RuntimeEvidenceStore, get_runtime_evidence_store
from btc_scraper.core.paths import (
    build_prediction_audit_path,
    runtime_deployment_id,
    runtime_environment,
    runtime_evidence_eligible,
    runtime_id,
    runtime_owner_metadata,
    runtime_paper_run_id,
)


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def feature_hash(values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _infer_side(value: Any) -> str | None:
    text = str(value or "").upper()
    if any(token in text for token in ("BUY", "LONG", "BULLISH")):
        return "BUY"
    if any(token in text for token in ("SELL", "SHORT", "BEARISH")):
        return "SELL"
    return "NO_TRADE"


def append_prediction(*, model_name: str, model_version: str, artifact_sha256: str | None,
                      feature_schema_version: str, raw_prediction: Any, calibrated_prediction: Any,
                      features: Any, decision_context: str, symbol: str | None = None,
                      timeframe: str | None = None, side: str | None = None,
                      feature_snapshot_id: str | None = None, valid_until: str | None = None,
                      calibration_method: str | None = None, fallback_used: bool = False,
                      signal_id: str | None = None, caller_context: str = "runtime",
                      position_id: str | None = None,
                      order_id: str | None = None, fill_id: str | None = None,
                      extra: dict[str, Any] | None = None, log_dir: Path | None = None,
                      evidence_store: RuntimeEvidenceStore | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    now = datetime.now(timezone.utc)
    expires_at = valid_until or (now + timedelta(minutes=15)).isoformat()
    f_hash = feature_hash(features)
    snapshot_id = feature_snapshot_id or f"fs-{f_hash[:16]}"
    side_value = side or _infer_side((extra or {}).get("signal"))
    idempotency_key = (
        f"{signal_id}:{model_version}:{decision_context}"
        if signal_id else None
    )
    store = evidence_store or get_runtime_evidence_store()
    if idempotency_key:
        existing = store.get_prediction_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
    prediction_id = (
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"ml-prediction:{idempotency_key}"))
        if idempotency_key else str(uuid.uuid4())
    )
    entry: dict[str, Any] = {
        "event_type": "prediction_created", "schema_version": "prediction-created-v1",
        "event_id": str(uuid.uuid4()), "event_time": now.isoformat(), "ingest_time": now.isoformat(),
        "producer": "prediction_logger", "prediction_id": prediction_id,
        "timestamp": now.isoformat(), "predicted_at": now.isoformat(), "valid_until": expires_at,
        "symbol": symbol, "timeframe": timeframe,
        "decision_context": decision_context, "model_name": model_name, "model_version": model_version,
        "artifact_sha256": artifact_sha256, "model_artifact_sha256": artifact_sha256,
        "feature_schema_version": feature_schema_version,
        "feature_snapshot_id": snapshot_id, "feature_hash": f_hash, "side": side_value,
        "calibration_method": calibration_method,
        "raw_probability": raw_prediction, "calibrated_probability": calibrated_prediction,
        "raw_prediction": raw_prediction, "calibrated_prediction": calibrated_prediction,
        "environment": runtime_environment(), "deployment_id": runtime_deployment_id(),
        "runtime_id": runtime_id(), "evidence_eligible": runtime_evidence_eligible(),
        "paper_run_id": runtime_paper_run_id(),
        "fallback_used": bool(fallback_used), "git_commit": _git_commit(),
        "signal_id": signal_id, "caller_context": caller_context,
        "idempotency_key": idempotency_key,
        "position_id": position_id, "order_id": order_id, "fill_id": fill_id,
    }
    owner = runtime_owner_metadata()
    entry.setdefault("process_id", owner["process_id"])
    entry.setdefault("hostname", owner["hostname"])
    entry.setdefault("started_at", owner["started_at"])
    if extra:
        entry.update(extra)
    entry["latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
    validate_runtime_event(entry).raise_for_errors()
    snapshot = {"prediction_id": entry["prediction_id"], "feature_snapshot_id": snapshot_id,
                "timestamp": entry["timestamp"],
                "feature_schema_version": feature_schema_version, "features": features,
                "feature_hash": entry["feature_hash"],
                "environment": runtime_environment(), "deployment_id": runtime_deployment_id(),
                "runtime_id": runtime_id(), "evidence_eligible": runtime_evidence_eligible(),
                "paper_run_id": runtime_paper_run_id()}
    snapshot.setdefault("process_id", owner["process_id"])
    snapshot.setdefault("hostname", owner["hostname"])
    snapshot.setdefault("started_at", owner["started_at"])
    persisted = store.write_prediction_evidence(entry, snapshot)
    if persisted.get("event_id") != entry["event_id"]:
        return persisted

    # JSONL remains a compatibility mirror; SQLite above is the source of truth.
    destination = Path(log_dir) if log_dir is not None else build_prediction_audit_path()
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with (destination / f"predictions_{now.strftime('%Y-%m-%d')}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        # Values are kept separately for compatibility with legacy replay tools.
        with (destination / f"feature_snapshots_{now.strftime('%Y-%m-%d')}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        from .operational_health import record_degradation
        record_degradation("prediction_audit", "prediction_audit_write_failure_total", exc)
    return entry
