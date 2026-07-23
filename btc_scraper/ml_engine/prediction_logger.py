"""Versioned prediction envelope and JSONL audit logging."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_resolver import ROOT
from .data_contracts import validate_runtime_event
from .runtime_evidence_store import RuntimeEvidenceStore, get_runtime_evidence_store


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def feature_hash(values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_prediction(*, model_name: str, model_version: str, artifact_sha256: str | None,
                      feature_schema_version: str, raw_prediction: Any, calibrated_prediction: Any,
                      features: Any, decision_context: str, symbol: str | None = None,
                      calibration_method: str | None = None, fallback_used: bool = False,
                      signal_id: str | None = None, position_id: str | None = None,
                      order_id: str | None = None, fill_id: str | None = None,
                      extra: dict[str, Any] | None = None, log_dir: Path | None = None,
                      evidence_store: RuntimeEvidenceStore | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    now = datetime.now(timezone.utc)
    entry: dict[str, Any] = {
        "event_type": "prediction_created", "schema_version": "prediction-created-v1",
        "event_id": str(uuid.uuid4()), "event_time": now.isoformat(), "ingest_time": now.isoformat(),
        "producer": "prediction_logger", "prediction_id": str(uuid.uuid4()),
        "timestamp": now.isoformat(), "symbol": symbol,
        "decision_context": decision_context, "model_name": model_name, "model_version": model_version,
        "artifact_sha256": artifact_sha256, "feature_schema_version": feature_schema_version,
        "feature_hash": feature_hash(features), "calibration_method": calibration_method,
        "raw_prediction": raw_prediction, "calibrated_prediction": calibrated_prediction,
        "fallback_used": bool(fallback_used), "git_commit": _git_commit(),
        "deployment_id": __import__("os").getenv("DEPLOYMENT_ID"), "signal_id": signal_id,
        "position_id": position_id, "order_id": order_id, "fill_id": fill_id,
    }
    if extra:
        entry.update(extra)
    entry["latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
    validate_runtime_event(entry).raise_for_errors()
    snapshot = {"prediction_id": entry["prediction_id"], "timestamp": entry["timestamp"],
                "feature_schema_version": feature_schema_version, "features": features,
                "feature_hash": entry["feature_hash"]}
    (evidence_store or get_runtime_evidence_store()).write_prediction_evidence(entry, snapshot)

    # JSONL remains a compatibility mirror; SQLite above is the source of truth.
    destination = log_dir or ROOT / "logs" / "prediction_audit"
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
