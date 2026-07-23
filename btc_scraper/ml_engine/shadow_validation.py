"""Derived, fail-closed shadow validation gate backed by canonical SQLite evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable, Mapping

from .runtime_evidence_store import (
    RUNTIME_EVIDENCE_SCHEMA_VERSION,
    RuntimeEvidenceStore,
    get_runtime_evidence_store,
)
from .operational_health import health_snapshot

SHADOW_READINESS_RULE_VERSION = "shadow-readiness-v2"


@dataclass(frozen=True)
class ShadowThresholds:
    minimum_closed_paper_trades: int = 100
    minimum_elapsed_days: float = 30.0
    minimum_active_trading_days: int = 10
    minimum_symbols: int = 3
    minimum_regimes: int = 3


_cache_lock = Lock()
_cached_signature: tuple[Any, ...] | None = None
_cached_report: dict[str, Any] | None = None


def cached_shadow_validation() -> dict[str, Any]:
    """Avoid rescanning SQLite unless the database or WAL has changed."""
    global _cached_signature, _cached_report
    store = get_runtime_evidence_store()
    signature = _store_signature(store)
    with _cache_lock:
        if _cached_report is not None and signature == _cached_signature:
            return _cached_report
        report = evaluate_shadow_validation(store)
        _cached_signature = _store_signature(store)
        _cached_report = report
        return report


def evaluate_shadow_validation(
    store: RuntimeEvidenceStore | None = None,
    *,
    now: datetime | None = None,
    thresholds: ShadowThresholds | None = None,
) -> dict[str, Any]:
    store = store or get_runtime_evidence_store()
    limits = thresholds or ShadowThresholds()
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = store.shadow_evidence_rows()
    health = store.health()
    predictions = {str(row.get("prediction_id")): row for row in rows["predictions"]}
    decisions = {str(row.get("prediction_id")): row for row in rows["final_decisions"] if row.get("prediction_id")}
    outcomes = [row for row in rows["outcomes"] if _eligible_paper_outcome(row)]

    timestamps = [_timestamp(row) for row in outcomes]
    timestamps = [value for value in timestamps if value is not None and value <= current_time]
    elapsed_days = (
        max(0.0, (current_time - min(timestamps)).total_seconds() / 86400.0)
        if timestamps else 0.0
    )
    active_days = {value.date().isoformat() for value in timestamps}
    symbols = {_field(row, predictions, "symbol", "coin") for row in outcomes}
    regimes = {_regime(row, predictions) for row in outcomes}
    symbols.discard(None)
    regimes.discard(None)

    lineage_complete = 0
    decision_complete = 0
    for outcome in outcomes:
        prediction_id = str(outcome.get("prediction_id") or "")
        prediction = predictions.get(prediction_id, {})
        if all(_first(outcome, prediction, key) for key in (
            "artifact_sha256", "model_version", "feature_schema_version",
        )):
            lineage_complete += 1
        if prediction_id in decisions:
            decision_complete += 1

    audit_types = Counter(str(row.get("event_type") or "").lower() for row in rows["audit_events"])
    operational = health_snapshot()
    operational_metrics = operational["metrics"]
    hard_risk_violations = sum(
        count for name, count in audit_types.items() if "hard_risk_violation" in name or "hard-risk-violation" in name
    )
    governance_bypasses = sum(
        count for name, count in audit_types.items() if "governance_bypass" in name or "governance-bypass" in name
    )
    total = len(outcomes)
    lineage_coverage = lineage_complete / total if total else 0.0
    decision_coverage = decision_complete / total if total else 0.0

    checks = {
        "closed_paper_trades": total >= limits.minimum_closed_paper_trades,
        "elapsed_days": elapsed_days >= limits.minimum_elapsed_days,
        "active_trading_days": len(active_days) >= limits.minimum_active_trading_days,
        "symbols": len(symbols) >= limits.minimum_symbols,
        "regimes": len(regimes) >= limits.minimum_regimes,
        "hard_risk_violations": hard_risk_violations == 0,
        "governance_bypasses": governance_bypasses == 0,
        "evidence_integrity": health["status"] == "healthy",
        "artifact_lineage_coverage": lineage_coverage == 1.0,
        "decision_linkage_coverage": decision_coverage == 1.0,
    }
    return {
        "passed": all(checks.values()),
        "generated_at": current_time.isoformat(),
        "source": "runtime_evidence.sqlite",
        "evidence_schema_version": RUNTIME_EVIDENCE_SCHEMA_VERSION,
        "readiness_rule_version": SHADOW_READINESS_RULE_VERSION,
        "thresholds": asdict(limits),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "metrics": {
            "closed_paper_trades": total,
            "elapsed_days": elapsed_days,
            "active_trading_days": len(active_days),
            "symbols": sorted(symbols),
            "regimes": sorted(regimes),
            "hard_risk_violations": hard_risk_violations,
            "governance_bypasses": governance_bypasses,
            "artifact_lineage_coverage": lineage_coverage,
            "decision_linkage_coverage": decision_coverage,
            "evidence_health": health,
            "calibration_drift": _calibration_drift(outcomes, predictions),
            "decision_distribution": dict(Counter(
                str(decisions[str(row.get("prediction_id"))].get("action") or "UNKNOWN")
                for row in outcomes if str(row.get("prediction_id")) in decisions
            )),
            "decision_distribution_drift": {
                "status": "REFERENCE_REQUIRED",
                "reference_distribution": None,
            },
            "latency_ms": _latency_metrics(predictions.values()),
            "context_provider_failure_count": int(
                operational_metrics.get("context_provider_failure_total", 0)
                + audit_types["context_provider_failure"]
            ),
            "context_provider_failure_rate": (
                float(operational_metrics.get("context_provider_failure_total", 0)) / len(predictions)
                if predictions else 0.0
            ),
            "audit_write_failure_count": int(
                operational_metrics.get("prediction_audit_write_failure_total", 0)
                + audit_types["audit_write_failure"]
            ),
            "audit_write_failure_rate": (
                float(operational_metrics.get("prediction_audit_write_failure_total", 0)) / len(predictions)
                if predictions else 0.0
            ),
            "fallback_usage_count": sum(bool(row.get("fallback_used")) for row in predictions.values()),
            "fallback_usage_rate": (
                sum(bool(row.get("fallback_used")) for row in predictions.values()) / len(predictions)
                if predictions else 0.0
            ),
            "pnl_drawdown_by_regime": _pnl_by_regime(outcomes, predictions),
        },
    }


def _store_signature(store: RuntimeEvidenceStore) -> tuple[Any, ...]:
    signature: list[Any] = [
        RUNTIME_EVIDENCE_SCHEMA_VERSION,
        SHADOW_READINESS_RULE_VERSION,
        asdict(ShadowThresholds()),
    ]
    for path in (store.path, store.path.with_name(store.path.name + "-wal")):
        try:
            stat = path.stat()
            signature.append((stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            signature.append((0, 0))
    return tuple(signature)


def _eligible_paper_outcome(row: Mapping[str, Any]) -> bool:
    if any(bool(row.get(key)) for key in ("is_test_record", "is_manual", "is_user_order")):
        return False
    provenance = " ".join(str(row.get(key) or "").lower() for key in (
        "created_by", "source_test_name", "order_creator", "order_channel", "paper_run_id",
    ))
    if any(marker in provenance for marker in ("pytest", "test_", "_test", "e2e", "fixture")):
        return False
    if not str(row.get("paper_run_id") or "").strip():
        return False
    mode = " ".join(str(row.get(key) or "").lower() for key in (
        "execution_mode", "trade_origin", "fill_source", "order_channel",
    ))
    return row.get("is_paper") is True or "paper" in mode


def _timestamp(row: Mapping[str, Any]) -> datetime | None:
    for key in ("closed_at", "event_time", "exit_time", "timestamp"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _first(outcome: Mapping[str, Any], prediction: Mapping[str, Any], key: str) -> Any:
    return outcome.get(key) or prediction.get(key)


def _field(
    outcome: Mapping[str, Any],
    predictions: Mapping[str, Mapping[str, Any]],
    *keys: str,
) -> str | None:
    prediction = predictions.get(str(outcome.get("prediction_id") or ""), {})
    for key in keys:
        value = _first(outcome, prediction, key)
        if value:
            return str(value).upper()
    return None


def _regime(outcome: Mapping[str, Any], predictions: Mapping[str, Mapping[str, Any]]) -> str | None:
    explicit = _field(outcome, predictions, "regime", "market_regime")
    if explicit:
        return explicit
    prediction = predictions.get(str(outcome.get("prediction_id") or ""), {})
    for source in (outcome, prediction):
        for key, value in source.items():
            if key.startswith("regime_") and value == 1:
                return key.removeprefix("regime_").upper()
    return None


def _calibration_drift(
    outcomes: list[dict[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    probabilities: list[float] = []
    labels: list[int] = []
    for outcome in outcomes:
        prediction = predictions.get(str(outcome.get("prediction_id") or ""), {})
        raw_probability = prediction.get("calibrated_prediction", prediction.get("probability"))
        if raw_probability is None:
            continue
        pnl = outcome.get("net_pnl_pct", outcome.get("pnl_pct"))
        result = str(outcome.get("result") or "").upper()
        if result not in {"WIN", "LOSS"} and pnl is None:
            continue
        probabilities.append(float(raw_probability))
        labels.append(1 if result == "WIN" or (not result and float(pnl) > 0) else 0)
    if not probabilities:
        return {"sample_count": 0, "brier": None, "ece": None}
    brier = sum((probability - label) ** 2 for probability, label in zip(probabilities, labels)) / len(labels)
    return {
        "sample_count": len(labels),
        "brier": brier,
        "ece": _ece(probabilities, labels),
    }


def _ece(probabilities: list[float], labels: list[int]) -> float:
    ranges = ((0.0, 0.4), (0.4, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0))
    total = len(labels)
    error = 0.0
    for index, (lower, upper) in enumerate(ranges):
        bucket = [
            (probability, label)
            for probability, label in zip(probabilities, labels)
            if lower <= probability < upper or (index == len(ranges) - 1 and probability == 1.0)
        ]
        if bucket:
            predicted = sum(row[0] for row in bucket) / len(bucket)
            observed = sum(row[1] for row in bucket) / len(bucket)
            error += len(bucket) / total * abs(observed - predicted)
    return error


def _latency_metrics(predictions: Iterable[Mapping[str, Any]]) -> dict[str, float | None]:
    values = sorted(float(row["latency_ms"]) for row in predictions if row.get("latency_ms") is not None)
    return {name: _quantile(values, q) for name, q in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))}


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _pnl_by_regime(
    outcomes: list[dict[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for outcome in sorted(outcomes, key=lambda row: _timestamp(row) or datetime.min.replace(tzinfo=timezone.utc)):
        pnl = outcome.get("net_pnl_pct", outcome.get("pnl_pct"))
        regime = _regime(outcome, predictions)
        if pnl is not None and regime:
            grouped[regime].append(float(pnl))
    report: dict[str, dict[str, float | int]] = {}
    for regime, values in grouped.items():
        equity = peak = drawdown = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        report[regime] = {
            "sample_count": len(values),
            "net_pnl_pct": sum(values),
            "max_drawdown_pct": drawdown,
        }
    return report
