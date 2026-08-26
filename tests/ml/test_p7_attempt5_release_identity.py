"""P7 Attempt #5 — Source Commit / Manifest Dual-Identity Closure test.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_attempt5_release_identity_closure.json"


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


def test_release_identity_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_release_identity_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["runtime_code_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert report["release_manifest_sha256"] == "6f79cd6b52bfb4083c1af2b258cbc7ef465ed07ebb383d4729e4d923500cd64b"
    assert report["release_identity_sha256"] == "d8dcafb2aef0010926acfa19114eb2c2b827517bae8f45be2a7e849b6643c14a"
    
    invariants = report["bootstrap_loop_invariants"]
    assert invariants["manifest_rebuilt"] is False
    assert invariants["release_identity_changed"] is False
    assert invariants["runtime_source_commit_changed"] is False
