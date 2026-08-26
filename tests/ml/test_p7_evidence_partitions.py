"""P7 evidence partition helper tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.p7_evidence_partitions import (
    dedupe_decisions,
    discover_partitions,
    load_partition_payload_rows,
)


def _partition(root: Path, date: str, decisions: list[dict]) -> Path:
    path = root / f"runtime_evidence_{date}.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("create table final_decisions(decision_id text, prediction_id text, payload text, payload_sha256 text, written_at text)")
        for decision in decisions:
            db.execute(
                "insert into final_decisions values(?,?,?,?,?)",
                (
                    decision.get("decision_id"),
                    decision.get("prediction_id"),
                    json.dumps(decision, sort_keys=True),
                    "sha",
                    decision.get("created_at"),
                ),
            )
    return path


def test_discovers_partitions_in_date_order(tmp_path):
    _partition(tmp_path, "2026-08-26", [])
    _partition(tmp_path, "2026-08-25", [])
    assert [p.name for p in discover_partitions(tmp_path, observation_start_date="2026-08-25")] == [
        "runtime_evidence_2026-08-25.sqlite",
        "runtime_evidence_2026-08-26.sqlite",
    ]


def test_union_finds_newest_partition_decision(tmp_path):
    _partition(tmp_path, "2026-08-25", [{"decision_id": "d1", "prediction_id": "p1", "action": "IGNORE"}])
    _partition(tmp_path, "2026-08-26", [{"decision_id": "d2", "prediction_id": "p2", "action": "BUY"}])
    rows = dedupe_decisions(load_partition_payload_rows(discover_partitions(tmp_path, observation_start_date="2026-08-25"), "final_decisions"))
    assert len(rows) == 2
    assert rows[1][0].name == "runtime_evidence_2026-08-26.sqlite"
    assert rows[1][1]["action"] == "BUY"


def test_deduplicates_by_decision_id(tmp_path):
    decision = {"decision_id": "same", "prediction_id": "p1", "action": "IGNORE"}
    _partition(tmp_path, "2026-08-25", [decision])
    _partition(tmp_path, "2026-08-26", [decision])
    rows = dedupe_decisions(load_partition_payload_rows(discover_partitions(tmp_path, observation_start_date="2026-08-25"), "final_decisions"))
    assert len(rows) == 1


def test_malformed_partition_filename_fails_closed(tmp_path):
    (tmp_path / "runtime_evidence_latest.sqlite").write_text("")
    with pytest.raises(ValueError):
        discover_partitions(tmp_path, observation_start_date="2026-08-25")
