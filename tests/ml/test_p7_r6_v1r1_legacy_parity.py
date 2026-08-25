"""Successor Release Legacy Parity verification test."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_legacy_parity_check():
    verdict_path = REPO_ROOT / "p7_r6_v1r1_validation_verdict.json"
    assert verdict_path.exists()
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["LEGACY_PARITY"] == "PASS"
