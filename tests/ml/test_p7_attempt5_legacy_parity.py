"""P7 Attempt #5 — Legacy BTC/ETH/BNB Parity test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_attempt5_legacy_parity_report.json"


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


def test_legacy_parity_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_legacy_parity_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["legacy_parity"]["btc_parity"] == "PASS"
    assert report["legacy_parity"]["eth_parity"] == "PASS"
    assert report["legacy_parity"]["bnb_parity"] == "PASS"
