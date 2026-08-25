"""Successor Release Preflight verification test."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_successor_release_preflight_verdict():
    verdict_path = REPO_ROOT / "p7_r6_v1r1_validation_verdict.json"
    assert verdict_path.exists()
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["SERIALIZED_RUNTIME_PREFLIGHT"] == "PASS"
    assert verdict["overall_verdict"] == "PASS"
    assert verdict["COMPLETED_RUNTIME_PATHS"] == 9
    assert verdict["UNSUPPORTED_ENABLED"] == 0
