"""Read-only helpers for P7 evidence partition discovery."""
from __future__ import annotations

import datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

PARTITION_RE = re.compile(r"^runtime_evidence_(\d{4}-\d{2}-\d{2})\.sqlite$")


def discover_partitions(log_root: Path, *, observation_start_date: str) -> list[Path]:
    partitions: list[tuple[datetime.date, Path]] = []
    seen_dates: set[datetime.date] = set()
    malformed = [
        path.name
        for path in log_root.glob("runtime_evidence_*.sqlite")
        if not PARTITION_RE.match(path.name)
    ]
    if malformed:
        raise ValueError(f"malformed evidence partition filename(s): {', '.join(sorted(malformed))}")

    start_date = datetime.date.fromisoformat(observation_start_date)
    for path in log_root.glob("runtime_evidence_*.sqlite"):
        match = PARTITION_RE.match(path.name)
        if not match:
            continue
        partition_date = datetime.date.fromisoformat(match.group(1))
        if partition_date < start_date:
            continue
        if partition_date in seen_dates:
            raise ValueError(f"duplicate evidence partition date: {partition_date.isoformat()}")
        seen_dates.add(partition_date)
        partitions.append((partition_date, path))
    return [path for _, path in sorted(partitions, key=lambda item: item[0])]


def partition_discovery_report(partitions: list[Path]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "strategy": "CROSS_PARTITION",
        "partitions_scanned": [path.name for path in partitions],
        "partition_count": len(partitions),
    }


def load_payload_rows(partition: Path, table: str) -> list[dict[str, Any]]:
    with sqlite3.connect(partition) as db:
        try:
            rows = db.execute(f"SELECT payload FROM {table}").fetchall()
        except sqlite3.OperationalError:
            return []
        except sqlite3.DatabaseError:
            raise
    return [json.loads(row[0]) for row in rows]


def load_partition_payload_rows(partitions: list[Path], table: str) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for partition in partitions:
        for payload in load_payload_rows(partition, table):
            records.append((partition, payload))
    return records


def decision_key(decision: dict[str, Any]) -> tuple[Any, ...]:
    decision_id = decision.get("decision_id")
    if decision_id:
        return ("decision_id", decision_id)
    return (
        "fallback",
        decision.get("epoch_id"),
        decision.get("deployment_id"),
        decision.get("symbol"),
        decision.get("evaluation_timestamp") or decision.get("created_at") or decision.get("timestamp"),
        decision.get("prediction_id"),
    )


def dedupe_decisions(records: list[tuple[Path, dict[str, Any]]]) -> list[tuple[Path, dict[str, Any]]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[tuple[Path, dict[str, Any]]] = []
    for partition, decision in records:
        key = decision_key(decision)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((partition, decision))
    return deduped


def event_timestamp(payload: dict[str, Any]) -> str:
    return str(
        payload.get("created_at")
        or payload.get("evaluation_timestamp")
        or payload.get("timestamp")
        or payload.get("written_at")
        or ""
    )
