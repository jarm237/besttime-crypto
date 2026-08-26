"""P7 post-seal observation baseline contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "p7_postseal_observation_baseline.json"


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


def test_postseal_baseline_sidecar():
    sidecar = Path(str(REPORT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(REPORT_PATH) == sidecar.read_text().strip()


def test_postseal_baseline_properties(report):
    assert report["overall_verdict"] == "PASS"
    assert report["baseline_state"] == "FROZEN"
    assert report["gate"] == "N0_POST_SEAL_BASELINE"
    assert report["observation_mode"] == "EVENT_DRIVEN"
    assert report["runtime_change_policy"] == "FROZEN"
    assert report["synthetic_trades"] == "NOT_AUTHORIZED"
    assert report["p7"] == "OPEN"
    assert report["p7_final_seal"] == "PASS"
    assert report["blockers"] == []
    assert report["identity"]["release_id"] == "model-coverage-v1-r1"
    assert report["identity"]["deployment_id"] == "paper-canary-a5-20260825-01"
    assert report["identity"]["epoch_id"] == "canary-mc9-v1-a5-20260825-01"
    assert report["identity"]["runtime_source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"


def test_postseal_baseline_event_gates_waiting(report):
    assert report["natural_event_gates"] == {
        "O3": "WAITING_FOR_NATURAL_EVENT",
        "O4": "WAITING_FOR_NATURAL_EVENT",
        "O5": "WAITING_FOR_NATURAL_EVENT",
        "O6": "WAITING_FOR_NATURAL_EVENT",
    }
