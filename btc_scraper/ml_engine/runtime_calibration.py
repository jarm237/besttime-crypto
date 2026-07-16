"""Runtime calibration reports from linked real outcomes."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CalibrationBucket:
    lower: float
    upper: float
    count: int
    confidence: float | None
    win_rate: float | None
    net_pnl_pct: float | None
    calibration_error: float | None
    evidence_state: str


def runtime_calibration_report(
    samples: Iterable[Mapping[str, Any]],
    *,
    generated_at: datetime | None = None,
    windows_days: tuple[int, ...] = (7, 14, 30, 90),
) -> dict[str, Any]:
    now = generated_at or datetime.now(timezone.utc)
    rows = latest_calibration_events(sample for sample in samples if _is_runtime_sample(sample))
    report = {
        "generated_at": now.isoformat(),
        "windows_days": list(windows_days),
        "status": "runtime_calibration",
        "windows": {},
        "global_health": "INSUFFICIENT_OUTCOMES",
    }
    health = "HEALTHY"
    for days in windows_days:
        window_rows = [row for row in rows if _in_window(row, now, days)]
        metrics = calibration_metrics(window_rows)
        report["windows"][str(days)] = metrics
        if metrics["sample_count"] == 0:
            health = "INSUFFICIENT_OUTCOMES"
        elif metrics["evidence_state"] == "insufficient" and health == "HEALTHY":
            health = "INSUFFICIENT_OUTCOMES"
    report["global_health"] = health
    return report


def latest_calibration_events(samples: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for sample in samples:
        row = dict(sample)
        prediction_id = _string_or_none(row.get("prediction_id"))
        position_id = _string_or_none(row.get("position_id"))
        if not prediction_id or not position_id:
            passthrough.append(row)
            continue
        key = (prediction_id, position_id)
        revision = int(row.get("outcome_revision") or row.get("revision") or 1)
        current = latest.get(key)
        current_revision = int(current.get("outcome_revision") or current.get("revision") or 1) if current else -1
        if current is None or revision >= current_revision:
            latest[key] = row
    return passthrough + list(latest.values())


def calibration_metrics(samples: Iterable[Mapping[str, Any]], *, bucket_count: int = 10) -> dict[str, Any]:
    pairs = [(_prob(row), int(row["label"]), float(row.get("net_pnl_pct") or 0.0), row) for row in samples]
    pairs = [(p, y, pnl, row) for p, y, pnl, row in pairs if math.isfinite(p) and 0.0 <= p <= 1.0]
    n = len(pairs)
    if n == 0:
        return {
            "sample_count": 0,
            "evidence_state": "insufficient",
            "brier": None,
            "roc_auc": None,
            "pr_auc": None,
            "ece": None,
            "maximum_calibration_error": None,
            "reliability_buckets": [],
            "breakdowns": {},
            "prediction_distribution": {},
        }

    brier = sum((p - y) ** 2 for p, y, _, _ in pairs) / n
    buckets = _buckets(pairs, bucket_count)
    ece = sum(bucket.count / n * (bucket.calibration_error or 0.0) for bucket in buckets)
    max_error = max((bucket.calibration_error or 0.0 for bucket in buckets), default=None)
    return {
        "sample_count": n,
        "evidence_state": evidence_state(n),
        "brier": brier,
        "roc_auc": _roc_auc([(p, y) for p, y, _, _ in pairs]),
        "pr_auc": _pr_auc([(p, y) for p, y, _, _ in pairs]),
        "ece": ece,
        "maximum_calibration_error": max_error,
        "reliability_buckets": [asdict(bucket) for bucket in buckets],
        "breakdowns": _breakdowns(pairs),
        "prediction_distribution": _prediction_distribution([p for p, _, _, _ in pairs]),
    }


def write_runtime_calibration_report(report: Mapping[str, Any], output_dir: str | Path = "logs/runtime_calibration") -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_dt(str(report.get("generated_at"))) or datetime.now(timezone.utc)
    path = target_dir / f"runtime_calibration_{generated_at.strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def evidence_state(count: int) -> str:
    if count < 30:
        return "insufficient"
    if count < 100:
        return "provisional"
    return "usable"


def _buckets(pairs: list[tuple[float, int, float, Mapping[str, Any]]], bucket_count: int) -> list[CalibrationBucket]:
    rows: list[CalibrationBucket] = []
    for index in range(bucket_count):
        lower = index / bucket_count
        upper = (index + 1) / bucket_count
        bucket = [(p, y, pnl) for p, y, pnl, _ in pairs if lower <= p < upper or (index == bucket_count - 1 and p == 1.0)]
        count = len(bucket)
        if not bucket:
            rows.append(CalibrationBucket(lower, upper, 0, None, None, None, None, evidence_state(0)))
            continue
        confidence = sum(p for p, _, _ in bucket) / count
        win_rate = sum(y for _, y, _ in bucket) / count
        net_pnl = sum(pnl for _, _, pnl in bucket) / count
        rows.append(CalibrationBucket(lower, upper, count, confidence, win_rate, net_pnl, abs(confidence - win_rate), evidence_state(count)))
    return rows


def _breakdowns(pairs: list[tuple[float, int, float, Mapping[str, Any]]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field in ("symbol", "regime", "side"):
        groups: dict[str, list[tuple[float, int, float, Mapping[str, Any]]]] = {}
        for pair in pairs:
            value = pair[3].get(field)
            if value is not None:
                groups.setdefault(str(value), []).append(pair)
        output[field] = {
            key: {
                "count": len(group),
                "evidence_state": evidence_state(len(group)),
                "win_rate": sum(y for _, y, _, _ in group) / len(group),
                "net_pnl_pct": sum(pnl for _, _, pnl, _ in group) / len(group),
            }
            for key, group in sorted(groups.items())
            if group
        }
    return output


def _prediction_distribution(probabilities: list[float]) -> dict[str, Any]:
    probs = sorted(probabilities)
    n = len(probs)
    return {
        "min": probs[0],
        "max": probs[-1],
        "mean": sum(probs) / n,
        "p10": _quantile(probs, 0.10),
        "p50": _quantile(probs, 0.50),
        "p90": _quantile(probs, 0.90),
    }


def _roc_auc(pairs: list[tuple[float, int]]) -> float | None:
    positives = sum(y for _, y in pairs)
    negatives = len(pairs) - positives
    if positives == 0 or negatives == 0:
        return None
    ranked = sorted(pairs, key=lambda row: row[0])
    rank_sum = sum(rank for rank, (_, y) in enumerate(ranked, start=1) if y == 1)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _pr_auc(pairs: list[tuple[float, int]]) -> float | None:
    positives = sum(y for _, y in pairs)
    if positives == 0:
        return None
    ordered = sorted(pairs, key=lambda row: row[0], reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    area = 0.0
    for _, label in ordered:
        if label == 1:
            tp += 1
        else:
            fp += 1
        recall = tp / positives
        precision = tp / (tp + fp)
        area += precision * max(0.0, recall - prev_recall)
        prev_recall = recall
    return area


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    index = (len(values) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[int(index)]
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _in_window(row: Mapping[str, Any], now: datetime, days: int) -> bool:
    timestamp = _parse_dt(str(row.get("closed_at") or row.get("event_time") or row.get("prediction_time") or ""))
    if timestamp is None:
        return True
    return timestamp >= now - timedelta(days=days)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _prob(row: Mapping[str, Any]) -> float:
    value = row.get("predicted_probability")
    if value is None:
        value = row.get("calibrated_prediction")
    if value is None:
        value = row.get("raw_prediction")
    return float(value)


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _is_runtime_sample(row: Mapping[str, Any]) -> bool:
    source = str(row.get("source") or "").lower()
    return "synthetic" not in source and "debug" not in source and "replay" not in source
