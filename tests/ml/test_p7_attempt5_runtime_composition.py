"""P7 Attempt #5 — Complete Runtime Composition verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_attempt5_runtime_composition_report.json"


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


def test_composition_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_composition_properties(report):
    assert report["overall_verdict"] == "PASS"
    mapping = report["symbol_mapping"]
    
    # Check 6 MC5 qualified symbols
    for sym in ["DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]:
        assert mapping[sym]["observed_running_route"] == "MC5_QUALIFIED"
        
    # Check legacy symbols
    for sym in ["BTC", "ETH", "BNB"]:
        assert mapping[sym]["observed_running_route"] == "LEGACY"

    # Check negative invariants
    invariants = report["negative_invariants"]
    assert invariants["mc5_symbol_through_legacy_path"] == 0
    assert invariants["legacy_symbol_through_mc5_path"] == 0
    assert invariants["disabled_symbol_inference"] == 0
