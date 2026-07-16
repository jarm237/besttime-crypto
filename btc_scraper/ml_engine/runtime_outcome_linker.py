"""Runtime outcome linker for immutable calibration samples.

Production linkage uses stable IDs only. Timestamp-nearest joins are
intentionally absent so missing provenance fails closed.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .data_contracts import validate_runtime_event
from .trade_lifecycle import make_event_metadata


class LinkState(str, Enum):
    WAITING_FOR_PREDICTION = "WAITING_FOR_PREDICTION"
    WAITING_FOR_OUTCOME = "WAITING_FOR_OUTCOME"
    READY = "READY"
    LINKED = "LINKED"
    QUARANTINED = "QUARANTINED"


class OrphanState(str, Enum):
    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    QUARANTINED = "quarantined"


class OrphanCategory(str, Enum):
    PREDICTION_WITHOUT_SIGNAL = "prediction_without_signal"
    SIGNAL_WITHOUT_DECISION = "signal_without_decision"
    ELIGIBLE_DECISION_WITHOUT_RESERVATION = "eligible_decision_without_reservation"
    RESERVATION_WITHOUT_ORDER = "reservation_without_order"
    SUBMITTED_ORDER_WITHOUT_FILL = "submitted_order_without_fill"
    FILL_WITHOUT_POSITION = "fill_without_position"
    CLOSED_POSITION_WITHOUT_OUTCOME = "closed_position_without_outcome"
    OUTCOME_WITHOUT_PREDICTION = "outcome_without_prediction"
    PREDICTION_WITHOUT_OUTCOME = "prediction_without_outcome"


ORPHAN_OWNERS = {
    OrphanCategory.PREDICTION_WITHOUT_SIGNAL.value: "signal_producer",
    OrphanCategory.SIGNAL_WITHOUT_DECISION.value: "decision_engine",
    OrphanCategory.ELIGIBLE_DECISION_WITHOUT_RESERVATION.value: "reservation_store",
    OrphanCategory.RESERVATION_WITHOUT_ORDER.value: "execution_engine",
    OrphanCategory.SUBMITTED_ORDER_WITHOUT_FILL.value: "fill_tracker",
    OrphanCategory.FILL_WITHOUT_POSITION.value: "position_tracker",
    OrphanCategory.CLOSED_POSITION_WITHOUT_OUTCOME.value: "outcome_recorder",
    OrphanCategory.OUTCOME_WITHOUT_PREDICTION.value: "prediction_audit",
    OrphanCategory.PREDICTION_WITHOUT_OUTCOME.value: "outcome_recorder",
}


@dataclass(frozen=True)
class OrphanRecord:
    category: str
    state: OrphanState
    reason_code: str
    severity: str
    owner: str
    first_seen: str
    last_seen: str
    retry_count: int = 0
    key: str | None = None

    @property
    def status(self) -> str:
        return self.state.value

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["status"] = self.status
        return data


@dataclass(frozen=True)
class CalibrationSample:
    sample_id: str
    prediction_id: str
    signal_id: str | None
    position_id: str
    outcome_id: str | None
    outcome_revision: int
    model_name: str | None
    model_version: str
    artifact_sha256: str
    feature_schema_version: str
    predicted_probability: float
    label: int
    net_pnl_pct: float
    symbol: str | None
    side: str | None
    decision_context: str | None
    prediction_time: str | None
    closed_at: str | None
    source: str
    link_method: str
    link_state: LinkState = LinkState.LINKED

    def to_event(self) -> dict[str, Any]:
        event = {
            **make_event_metadata(
                event_type="calibration_sample_created",
                schema_version="calibration-sample-v1",
                producer="runtime_outcome_linker",
            ),
            **asdict(self),
        }
        event["link_state"] = self.link_state.value
        validate_runtime_event(event).raise_for_errors()
        return event


@dataclass(frozen=True)
class LinkageReport:
    samples: tuple[CalibrationSample, ...]
    orphans: tuple[OrphanRecord, ...]
    duplicate_outcome_count: int
    excluded_debug_count: int
    excluded_synthetic_count: int
    quarantined_sample_count: int = 0
    quarantine_reasons: tuple[str, ...] = ()
    total_prediction_count: int = 0
    actionable_prediction_count: int = 0
    traded_prediction_count: int = 0

    @property
    def closed_trade_prediction_to_outcome_rate(self) -> float:
        closed_traded = len(self.samples) + sum(1 for orphan in self.orphans if orphan.category == OrphanCategory.PREDICTION_WITHOUT_OUTCOME.value)
        return 0.0 if closed_traded == 0 else len(self.samples) / closed_traded

    @property
    def actionable_prediction_to_trade_rate(self) -> float:
        return 0.0 if self.actionable_prediction_count == 0 else self.traded_prediction_count / self.actionable_prediction_count

    @property
    def prediction_to_outcome_link_rate(self) -> float:
        return self.closed_trade_prediction_to_outcome_rate

    def health(self) -> str:
        if self.duplicate_outcome_count:
            return "SCHEMA_MISMATCH"
        if not self.samples:
            return "INSUFFICIENT_OUTCOMES"
        if self.closed_trade_prediction_to_outcome_rate < 0.90:
            return "DEGRADED_LINKAGE"
        return "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_sample_count": len(self.samples),
            "orphan_prediction_count": sum(1 for orphan in self.orphans if orphan.category == OrphanCategory.PREDICTION_WITHOUT_OUTCOME.value),
            "orphan_outcome_count": sum(1 for orphan in self.orphans if orphan.category == OrphanCategory.OUTCOME_WITHOUT_PREDICTION.value),
            "orphans_by_category": _orphan_counts(self.orphans),
            "critical_orphans": [orphan.to_dict() for orphan in self.orphans if orphan.severity == "critical"],
            "duplicate_outcome_count": self.duplicate_outcome_count,
            "excluded_debug_count": self.excluded_debug_count,
            "excluded_synthetic_count": self.excluded_synthetic_count,
            "quarantined_sample_count": self.quarantined_sample_count,
            "quarantine_reasons": list(self.quarantine_reasons),
            "mixed_artifact_schema_count": sum(1 for reason in self.quarantine_reasons if reason == "mixed_artifact_schema"),
            "total_prediction_count": self.total_prediction_count,
            "actionable_prediction_count": self.actionable_prediction_count,
            "traded_prediction_count": self.traded_prediction_count,
            "actionable_prediction_to_trade_rate": self.actionable_prediction_to_trade_rate,
            "closed_trade_prediction_to_outcome_rate": self.closed_trade_prediction_to_outcome_rate,
            "prediction_to_outcome_link_rate": self.prediction_to_outcome_link_rate,
            "health": self.health(),
        }


def link_runtime_outcomes(
    predictions: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
) -> LinkageReport:
    pred_rows = [dict(row) for row in predictions]
    raw_outcome_rows = [dict(row) for row in outcomes]
    by_prediction = _index_first(pred_rows, "prediction_id")
    by_signal = _index_first(pred_rows, "signal_id")
    by_position = _index_first(pred_rows, "position_id")

    linked_predictions: set[str] = set()
    samples: list[CalibrationSample] = []
    orphans: list[OrphanRecord] = []
    excluded_debug_count = 0
    excluded_synthetic_count = 0
    quarantined_sample_count = 0
    quarantine_reasons: list[str] = []
    eligible_outcome_rows: list[dict[str, Any]] = []

    for outcome in raw_outcome_rows:
        source = str(outcome.get("source") or outcome.get("fill_source") or outcome.get("execution_mode") or "runtime")
        if _is_debug(source, outcome):
            excluded_debug_count += 1
            continue
        if _is_synthetic(source, outcome):
            excluded_synthetic_count += 1
            continue
        eligible_outcome_rows.append(outcome)

    duplicate_outcome_count = _duplicate_outcome_count(eligible_outcome_rows)
    outcome_rows = _latest_outcome_revisions(eligible_outcome_rows)

    for outcome in outcome_rows:
        source = str(outcome.get("source") or outcome.get("fill_source") or outcome.get("execution_mode") or "runtime")
        position_id = _string_or_none(outcome.get("position_id"))
        prediction, link_method = _match_prediction(outcome, by_prediction, by_signal, by_position)
        if prediction is None:
            orphans.append(_orphan(OrphanCategory.OUTCOME_WITHOUT_PREDICTION, "waiting_for_prediction", "high", position_id))
            continue

        try:
            sample = _build_sample(prediction, outcome, link_method, source)
        except ValueError as exc:
            reason = str(exc)
            if reason in {"mixed_artifact_schema", "artifact_hash_mismatch", "feature_schema_mismatch", "model_version_mismatch"}:
                quarantined_sample_count += 1
                quarantine_reasons.append("mixed_artifact_schema")
                orphans.append(_orphan(OrphanCategory.OUTCOME_WITHOUT_PREDICTION, reason, "critical", position_id))
            else:
                orphans.append(_orphan(OrphanCategory.OUTCOME_WITHOUT_PREDICTION, reason, "high", position_id))
            continue
        samples.append(sample)
        linked_predictions.add(sample.prediction_id)

    for prediction in pred_rows:
        prediction_id = _string_or_none(prediction.get("prediction_id"))
        if prediction_id and not _string_or_none(prediction.get("signal_id")):
            orphans.append(_orphan(OrphanCategory.PREDICTION_WITHOUT_SIGNAL, "waiting_for_signal", "medium", prediction_id))
        if prediction_id and prediction_id not in linked_predictions and _has_trade_linkage(prediction):
            orphans.append(_orphan(OrphanCategory.PREDICTION_WITHOUT_OUTCOME, "waiting_for_outcome", "medium", prediction_id))

    return LinkageReport(
        samples=tuple(samples),
        orphans=tuple(orphans),
        duplicate_outcome_count=duplicate_outcome_count,
        excluded_debug_count=excluded_debug_count,
        excluded_synthetic_count=excluded_synthetic_count,
        quarantined_sample_count=quarantined_sample_count,
        quarantine_reasons=tuple(quarantine_reasons),
        total_prediction_count=len(pred_rows),
        actionable_prediction_count=sum(1 for prediction in pred_rows if _is_actionable_prediction(prediction)),
        traded_prediction_count=sum(1 for prediction in pred_rows if _has_trade_linkage(prediction)),
    )


def write_calibration_samples(samples: Iterable[CalibrationSample], path: str | Path) -> int:
    return CalibrationSampleJsonlStore(path).append(samples)


class CalibrationSampleJsonlStore:
    """Single-file shadow store with file lock, dedup index, and corrupt-line recovery."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.corrupt_line_count = 0

    def append(self, samples: Iterable[CalibrationSample]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
            _lock_file(lock_handle)
            try:
                existing = self._existing_keys()
                appended = 0
                with self.path.open("a", encoding="utf-8") as handle:
                    for sample in samples:
                        event = sample.to_event()
                        key = _sample_unique_key(event)
                        if key in existing:
                            continue
                        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                        handle.flush()
                        existing.add(key)
                        appended += 1
                    _fsync(handle)
                return appended
            finally:
                _unlock_file(lock_handle)

    def _existing_keys(self) -> set[tuple[str, str, int]]:
        keys: set[tuple[str, str, int]] = set()
        self.corrupt_line_count = 0
        if not self.path.exists():
            return keys
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    keys.add(_sample_unique_key(json.loads(line)))
                except Exception:
                    self.corrupt_line_count += 1
        return keys


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _match_prediction(
    outcome: Mapping[str, Any],
    by_prediction: Mapping[str, Mapping[str, Any]],
    by_signal: Mapping[str, Mapping[str, Any]],
    by_position: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, str]:
    for field, index in (("prediction_id", by_prediction), ("signal_id", by_signal), ("position_id", by_position)):
        value = _string_or_none(outcome.get(field))
        if value and value in index:
            return index[value], field
    return None, "none"


def _build_sample(
    prediction: Mapping[str, Any],
    outcome: Mapping[str, Any],
    link_method: str,
    source: str,
) -> CalibrationSample:
    prediction_id = _required(prediction, "prediction_id")
    position_id = _required(outcome, "position_id")
    model_version = _required(prediction, "model_version")
    artifact_sha256 = _required(prediction, "artifact_sha256")
    feature_schema_version = _required(prediction, "feature_schema_version")
    _assert_metadata_compatible(prediction, outcome)
    probability = _probability(prediction)
    net_pnl_pct = float(outcome.get("net_pnl_pct") if outcome.get("net_pnl_pct") is not None else outcome.get("pnl_pct"))
    revision = int(outcome.get("outcome_revision") or outcome.get("revision") or 1)
    sample_id = _sample_id(prediction_id, position_id, revision)
    return CalibrationSample(
        sample_id=sample_id,
        prediction_id=prediction_id,
        signal_id=_string_or_none(prediction.get("signal_id") or outcome.get("signal_id")),
        position_id=position_id,
        outcome_id=_string_or_none(outcome.get("outcome_id")),
        outcome_revision=revision,
        model_name=_string_or_none(prediction.get("model_name")),
        model_version=model_version,
        artifact_sha256=artifact_sha256,
        feature_schema_version=feature_schema_version,
        predicted_probability=probability,
        label=1 if net_pnl_pct > 0 else 0,
        net_pnl_pct=net_pnl_pct,
        symbol=_string_or_none(prediction.get("symbol") or outcome.get("symbol") or outcome.get("coin")),
        side=_string_or_none(outcome.get("side") or prediction.get("side")),
        decision_context=_string_or_none(prediction.get("decision_context")),
        prediction_time=_string_or_none(prediction.get("timestamp") or prediction.get("event_time")),
        closed_at=_string_or_none(outcome.get("closed_at") or outcome.get("event_time")),
        source=source,
        link_method=link_method,
    )


def _index_first(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = _string_or_none(row.get(field))
        if value and value not in index:
            index[value] = row
    return index


def _latest_outcome_revisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        position_id = _string_or_none(row.get("position_id"))
        if not position_id:
            passthrough.append(row)
            continue
        revision = int(row.get("outcome_revision") or row.get("revision") or 1)
        current = latest.get(position_id)
        current_revision = int(current.get("outcome_revision") or current.get("revision") or 1) if current else -1
        if current is None or revision >= current_revision:
            latest[position_id] = row
    return passthrough + list(latest.values())


def _duplicate_outcome_count(rows: Iterable[Mapping[str, Any]]) -> int:
    seen: set[tuple[str, int]] = set()
    duplicates = 0
    for row in rows:
        position_id = _string_or_none(row.get("position_id"))
        revision = int(row.get("outcome_revision") or row.get("revision") or 1)
        duplicate_key = (position_id or "", revision)
        if duplicate_key in seen:
            duplicates += 1
            continue
        seen.add(duplicate_key)
    return duplicates


def _orphan(category: OrphanCategory, reason: str, severity: str, key: str | None) -> OrphanRecord:
    now = datetime.now(timezone.utc).isoformat()
    return OrphanRecord(category.value, OrphanState.PENDING, reason, severity, ORPHAN_OWNERS[category.value], now, now, key=key)


def _required(row: Mapping[str, Any], field: str) -> str:
    value = _string_or_none(row.get(field))
    if not value:
        raise ValueError(f"missing_{field}")
    return value


def _probability(prediction: Mapping[str, Any]) -> float:
    value = prediction.get("calibrated_prediction")
    if value is None:
        value = prediction.get("raw_prediction")
    if value is None:
        value = prediction.get("meta_prob")
    if value is None:
        raise ValueError("missing_probability")
    prob = float(value)
    if prob < 0.0 or prob > 1.0:
        raise ValueError("probability_out_of_range")
    return prob


def _assert_metadata_compatible(prediction: Mapping[str, Any], outcome: Mapping[str, Any]) -> None:
    checks = (
        ("model_version", "model_version_mismatch"),
        ("artifact_sha256", "artifact_hash_mismatch"),
        ("feature_schema_version", "feature_schema_mismatch"),
    )
    for field, reason in checks:
        expected = _string_or_none(prediction.get(field))
        actual = _string_or_none(outcome.get(field))
        if expected and actual and expected != actual:
            raise ValueError(reason)


def _sample_id(prediction_id: str, position_id: str, revision: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prediction_id}:{position_id}:{revision}"))


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _has_trade_linkage(prediction: Mapping[str, Any]) -> bool:
    return any(_string_or_none(prediction.get(field)) for field in ("position_id", "order_id", "fill_id"))


def _is_actionable_prediction(prediction: Mapping[str, Any]) -> bool:
    if _string_or_none(prediction.get("signal_id")):
        return True
    status = str(prediction.get("final_status") or prediction.get("decision_status") or "").lower()
    return status in {"eligible", "authorized", "submitted", "filled", "partially_filled"}


def _is_debug(source: str, row: Mapping[str, Any]) -> bool:
    text = source.lower()
    return "debug" in text or str(row.get("debug") or "").lower() == "true" or str(row.get("execution_mode") or "").lower() == "test"


def _is_synthetic(source: str, row: Mapping[str, Any]) -> bool:
    text = source.lower()
    return "synthetic" in text or "replay" in text or str(row.get("synthetic") or "").lower() == "true"


def _orphan_counts(orphans: Iterable[OrphanRecord]) -> dict[str, int]:
    counts = {category.value: 0 for category in OrphanCategory}
    for orphan in orphans:
        counts[orphan.category] = counts.get(orphan.category, 0) + 1
    return counts


def _sample_unique_key(event: Mapping[str, Any]) -> tuple[str, str, int]:
    return (str(event["prediction_id"]), str(event["position_id"]), int(event["outcome_revision"]))


def _lock_file(handle: Any) -> None:
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except Exception:
        return


def _unlock_file(handle: Any) -> None:
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        return


def _fsync(handle: Any) -> None:
    try:
        import os
        os.fsync(handle.fileno())
    except Exception:
        return
