"""P7 Post-Activation — Phase O14: Final Seal Verdict verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_final_verdict.json"


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


def test_final_verdict_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_final_verdict_properties(report):
    assert report["P7"] == "OPEN"
    assert report["P7_ACTIVATION"] == "PASS"
    assert report["P7_RUNTIME"] == "SUSTAINED"
    assert report["P7_RELEASE"] == "model-coverage-v1-r1"
    assert report["RUNTIME_SOURCE"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert report["PREDICTION_LINEAGE"] == "PASS"
    assert report["DECISION_LINEAGE"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["EXECUTION_LINEAGE"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["OUTCOME_LINEAGE"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["LONG_RUN_STABILITY"] == "PASS"
    assert report["CURRENT_RUNTIME_FULL_REGRESSION"] == "CONDITIONAL_PASS"
    assert report["RELEASE_IMMUTABILITY"] == "PASS"
    assert report["EVIDENCE_INTEGRITY"] == "PASS"
    assert report["INCIDENT_STATUS"] == "CLEAN / CLOSED"
    assert report["P7_FINAL_SEAL_READINESS"] == "PASS"
    assert report["P7_FINAL_SEAL"] == "PASS"
