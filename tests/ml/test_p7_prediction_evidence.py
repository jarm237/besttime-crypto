"""P7 Post-Activation — Phase O2: Prediction Evidence verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_prediction_evidence_report.json"


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


def test_prediction_evidence_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_prediction_evidence_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["prediction_count_delta"] == 28
    assert report["all_symbols_covered"] is True
    assert len(report["symbols_covered"]) == 9
    for sym in ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]:
        assert report["symbols_covered"][sym] >= 3
