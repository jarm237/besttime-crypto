"""P7 Post-Activation — Phase O13: Final Seal Readiness verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_final_seal_readiness.json"


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


def test_final_readiness_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_final_readiness_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["activation"] == "PASS"
    assert report["sustained_liveness"] == "PASS"
    assert report["prediction_evidence"] == "PASS"
    assert report["decision_evidence"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["execution_evidence"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["outcome_evidence"] == "WAITING_FOR_NATURAL_EVENT"
    assert report["long_run_stability"] == "PASS"
    assert report["current_runtime_full_regression"] == "CONDITIONAL_PASS"
    assert report["evidence_integrity"] == "PASS"
    assert report["release_immutability"] == "PASS"
    assert report["incident_closure"] == "PASS"
    assert report["blockers"] == []
