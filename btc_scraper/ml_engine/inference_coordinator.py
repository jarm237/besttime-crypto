"""Single-owner entry inference and immutable prediction lineage."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Mapping

from btc_scraper.core.config import get_analysis_universe
from btc_scraper.core.paths import runtime_deployment_id


@dataclass(frozen=True)
class MetaPrediction:
    signal_id: str
    prediction_id: str
    symbol: str
    decision_context: str
    caller_context: str
    probability: float
    model_version: str
    artifact_sha256: str
    feature_schema_version: str
    deployment_id: str
    feature_hash: str
    expected_return: float | None = None
    expected_drawdown: float | None = None
    expected_hold_time: float | None = None
    prob_tp1: float | None = None
    prob_tp2: float | None = None
    prob_sl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_signal_id(
    analysis: Mapping[str, Any],
    *,
    symbol: str,
    timeframe: str,
    decision_context: str,
) -> str:
    """Build a replay-stable signal ID from the market observation boundary."""
    existing = analysis.get("signal_id") or analysis.get("id")
    if existing:
        return str(existing)
    history = analysis.get("history")
    observed_at = analysis.get("input_end_time") or analysis.get("observed_at") or analysis.get("time")
    if not observed_at and isinstance(history, list) and history:
        tail = history[-1]
        if isinstance(tail, Mapping):
            observed_at = tail.get("time") or tail.get("timestamp")
    if not observed_at:
        raise ValueError("entry inference requires an observed_at boundary")
    identity = ":".join((
        runtime_deployment_id(),
        str(symbol).upper(),
        str(timeframe),
        str(observed_at),
        str(analysis.get("signal") or ""),
        str(decision_context),
    ))
    return f"sig-{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"


class InferenceCoordinator:
    """The only production entry owner allowed to create a meta prediction."""

    def predict_once(
        self,
        analysis: dict[str, Any],
        *,
        symbol: str,
        timeframe: str = "15m",
        decision_context: str = "entry",
        caller_context: str = "agent_orchestrator",
    ) -> MetaPrediction:
        from .meta_model import MODEL_VERSION, predict_meta_confidence
        from .runtime_evidence_store import get_runtime_evidence_store

        normalized_symbol = str(symbol).upper().replace("/", "").removesuffix("USDT")
        if normalized_symbol not in get_analysis_universe():
            raise ValueError(
                f"inference symbol outside BTC_ANALYSIS_UNIVERSE: {normalized_symbol}"
            )
        signal_id = ensure_signal_id(
            analysis,
            symbol=symbol,
            timeframe=timeframe,
            decision_context=decision_context,
        )
        analysis.update({
            "coin": normalized_symbol,
            "symbol": str(symbol).upper(),
            "timeframe": timeframe,
            "signal_id": signal_id,
            "decision_context": decision_context,
            "caller_context": caller_context,
        })
        idempotency_key = f"{signal_id}:{MODEL_VERSION}:{decision_context}"
        with _INFERENCE_LOCK:
            existing = get_runtime_evidence_store().get_prediction_by_idempotency_key(
                idempotency_key
            )
            if existing is not None:
                result = {
                    "probability": existing.get("calibrated_probability"),
                    "prediction_id": existing.get("prediction_id"),
                    "model_version": existing.get("model_version"),
                    "artifact_sha256": existing.get("artifact_sha256"),
                    "feature_schema_version": existing.get("feature_schema_version"),
                    "deployment_id": existing.get("deployment_id"),
                    "feature_hash": existing.get("feature_hash"),
                    "expected_return": existing.get("expected_return"),
                    "expected_drawdown": existing.get("expected_drawdown"),
                    "expected_hold_time": existing.get("expected_hold_time"),
                    "prob_tp1": existing.get("prob_tp1"),
                    "prob_tp2": existing.get("prob_tp2"),
                    "prob_sl": existing.get("prob_sl"),
                }
            else:
                result = predict_meta_confidence(analysis)
        if result.get("probability") is None:
            raise RuntimeError(str(result.get("error") or "meta_prediction_unavailable"))
        required = (
            "prediction_id", "model_version", "artifact_sha256",
            "feature_schema_version", "deployment_id", "feature_hash",
        )
        missing = [field for field in required if not result.get(field)]
        if missing:
            raise RuntimeError(f"meta_prediction_missing_lineage:{','.join(missing)}")
        return MetaPrediction(
            signal_id=signal_id,
            prediction_id=str(result["prediction_id"]),
            symbol=str(symbol).upper(),
            decision_context=decision_context,
            caller_context=caller_context,
            probability=float(result["probability"]),
            model_version=str(result["model_version"]),
            artifact_sha256=str(result["artifact_sha256"]),
            feature_schema_version=str(result["feature_schema_version"]),
            deployment_id=str(result["deployment_id"]),
            feature_hash=str(result["feature_hash"]),
            expected_return=result.get("expected_return"),
            expected_drawdown=result.get("expected_drawdown"),
            expected_hold_time=result.get("expected_hold_time"),
            prob_tp1=result.get("prob_tp1"),
            prob_tp2=result.get("prob_tp2"),
            prob_sl=result.get("prob_sl"),
        )


_COORDINATOR: InferenceCoordinator | None = None
_INFERENCE_LOCK = Lock()


def get_inference_coordinator() -> InferenceCoordinator:
    global _COORDINATOR
    if _COORDINATOR is None:
        _COORDINATOR = InferenceCoordinator()
    return _COORDINATOR
