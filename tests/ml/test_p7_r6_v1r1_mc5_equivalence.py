"""Successor Release MC5 Equivalence verification test."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mc5_equivalence_check():
    verdict_path = REPO_ROOT / "p7_r6_v1r1_validation_verdict.json"
    assert verdict_path.exists()
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["MC5_RUNTIME_EQUIVALENCE"] == "PASS"
