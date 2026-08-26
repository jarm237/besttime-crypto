"""P7 Post-Activation — Phase O3: Decision Lineage verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_first_actionable_decision_report.json"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


@pytest.fixture(scope="module")
def report():
    assert REPORT_PATH.exists()
    return json.loads(REPORT_PATH.read_bytes())


def test_decision_lineage_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_decision_lineage_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["status"] in ("WAITING_FOR_NATURAL_EVENT", "DECISION_LOGGED")
    assert report["partition_discovery"]["status"] == "PASS"
    assert report["partition_discovery"]["strategy"] == "CROSS_PARTITION"
    assert report["partition_discovery"]["partition_count"] >= 2
    assert "runtime_evidence_2026-08-26.sqlite" in report["partition_discovery"]["partitions_scanned"]
    assert report["decision_evidence"]["total_decisions"] >= report["decisions_analyzed"]
    if report["status"] == "WAITING_FOR_NATURAL_EVENT":
        assert report["actionable_decisions_count"] == 0
    else:
        assert report["actionable_decisions_count"] > 0
        fd = report["first_actionable_decision"]
        assert fd["prediction_id"] is not None
        assert fd["symbol"] is not None
