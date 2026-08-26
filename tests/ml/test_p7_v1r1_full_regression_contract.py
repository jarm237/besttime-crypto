"""P7 Post-Activation — Phase O8: Current Runtime Full Regression verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_v1r1_full_regression_report.json"


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


def test_full_regression_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_full_regression_properties(report):
    assert report["overall_verdict"] == "CONDITIONAL_PASS"

    ref = report["full_regression_reference"]
    assert ref["commit"] == "3816cb18dd7a868764dfcc02a5e500f7293fe520"
    assert ref["result"] == "518 passed, 6 skipped, 0 failed"
    assert ref["superseded_by_runtime_changes"] is True
    assert ref["superseded_by"] == "R6 embedded model composition remediation"

    curr = report["current_runtime_validation"]
    assert curr["release_id"] == "model-coverage-v1-r1"
    assert curr["source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert curr["passed"] == 1037
    assert curr["failed"] == 39
    assert curr["skipped"] == 6
    assert curr["full_regression_after_r6"] == "CONDITIONAL_PASS"

    fc = curr["failure_classification"]
    assert fc["new_regressions_vs_v1r1_source"] == 0
    assert fc["new_regression_ids"] == []
    assert fc["set_identity_invariant"] == "PASS"
    assert fc["pre_existing_at_v1r1_source"]["count"] == 24
    assert fc["superseded_state_assertions"]["count"] == 15
