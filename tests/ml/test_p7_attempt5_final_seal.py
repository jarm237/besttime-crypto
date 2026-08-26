"""P7 Attempt #5 — Final Governance Seal test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_attempt5_final_activation_verdict.json"


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


def test_final_seal_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_final_seal_properties(report):
    assert report["P7_ATTEMPT_5"] == "PASS"
    assert report["ACTIVATION_STATE"] == "SUSTAINED"
    assert report["RELEASE"] == "model-coverage-v1-r1"
    assert report["RUNNING_SOURCE"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert report["AUTHORIZATION_5"] == "CONSUMED"
    assert report["SPAWN_COUNT"] == 1
    assert report["RESTART_COUNT"] == 0
    
    assert report["FRESH_EVIDENCE_EPOCH"] == "PASS"
    assert report["PROCESS_IDENTITY"] == "PASS"
    assert report["RUNNING_RELEASE_IDENTITY"] == "PASS"
    assert report["SUSTAINED_LIVENESS"] == "PASS"
    assert report["COMPLETE_RUNTIME_CYCLE"] == "PASS"
    assert report["LINEAGE"] == "PASS"
    
    assert report["LEGACY_PARITY"] == "PASS"
    assert report["MC5_SCHEMA_EQUIVALENCE"] == "PASS"
    assert report["RELEASE_IDENTITY_CLOSURE"] == "PASS"
    
    assert report["AUTHORIZED_SYMBOLS"] == 9
    assert report["OBSERVED_AUTHORIZED_SYMBOLS"] == 9
    
    assert report["UNSUPPORTED_ENABLED_SYMBOLS"] == 0
    assert report["DISABLED_SYMBOL_LEAKS"] == 0
    assert report["LEGACY_FALLBACKS"] == 0
    
    assert report["RUNTIME"] == "ACTIVE"
    assert report["EVIDENCE_ACCUMULATION"] == "ACTIVE"

    ref = report["full_regression_reference"]
    assert ref["commit"] == "3816cb18dd7a868764dfcc02a5e500f7293fe520"
    assert ref["result"] == "518 passed, 6 skipped, 0 failed"
    assert ref["superseded_by_runtime_changes"] is True
    assert ref["superseded_by"] == "R6 embedded model composition remediation"

    curr = report["current_runtime_validation"]
    assert curr["release_id"] == "model-coverage-v1-r1"
    assert curr["source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert curr["attempt5_closure_tests"]["passed"] == 16
    assert curr["full_regression_after_r6"] == "NOT_RUN"
