"""P7 Post-Activation — Phase O5: Fill Lineage verification test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_first_fill_report.json"


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


def test_fill_lineage_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_fill_lineage_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["status"] in ("WAITING_FOR_NATURAL_EVENT", "ORDER_FILLED")
    assert report["partition_discovery"]["status"] == "PASS"
    assert report["partition_discovery"]["strategy"] == "CROSS_PARTITION"
    assert report["partition_discovery"]["partition_count"] >= 2
    if report["status"] == "WAITING_FOR_NATURAL_EVENT":
        assert report["fills_analyzed"] == 0
    else:
        assert report["fills_analyzed"] > 0
        ff = report["first_fill"]
        assert ff["order_id"] is not None
        assert ff["symbol"] is not None
