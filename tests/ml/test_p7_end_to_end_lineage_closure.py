"""P7 end-to-end lineage closure contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_end_to_end_lineage_closure.json"


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


def test_end_to_end_closure_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_end_to_end_closure_waits_for_natural_chain(report):
    assert report["overall_verdict"] == "READY"
    assert report["status"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["end_to_end_execution_lineage"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["waiting_for"] == ["O3", "O4", "O5", "O6"]
    assert report["same_causal_chain_required"] is True
    assert report["mixed_trade_evidence_rejected"] is True
    assert report["synthetic_trades"] == "NOT_AUTHORIZED"
    assert report["runtime_change_policy"] == "FROZEN"
    assert report["blockers"] == []


def test_end_to_end_closure_references_current_o3_o6_reports(report):
    assert report["report_statuses"] == {
        "O3": "WAITING_FOR_NATURAL_EVENT",
        "O4": "WAITING_FOR_NATURAL_EVENT",
        "O5": "WAITING_FOR_NATURAL_EVENT",
        "O6": "WAITING_FOR_NATURAL_EVENT",
    }
    assert set(report["report_sha256"]) == {"O3", "O4", "O5", "O6"}
