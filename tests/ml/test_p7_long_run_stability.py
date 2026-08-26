"""P7 Post-Activation — Phase O7: Long-Run Stability verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_long_run_stability_report.json"


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


def test_long_run_stability_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_long_run_stability_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["unexpected_restart"] is False
    assert report["release_identity_drift"] is False
    assert report["schema_drift"] == 0
    assert report["artifact_drift"] == 0
    assert report["unsupported_enabled_errors"] is False
    assert report["disabled_symbol_leaks"] is False
    assert report["lineage_mismatches"] == 0
