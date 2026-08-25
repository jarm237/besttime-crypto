"""Successor Release Route Class verification test."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_successor_route_classes():
    report_path = REPO_ROOT / "p7_r6_v1r1_route_class_report.json"
    assert report_path.exists()
    records = json.loads(report_path.read_text(encoding="utf-8"))
    
    for r in records:
        assert r["status"] == "PASS"
        if r["symbol"] in {"BTC", "ETH", "BNB"}:
            assert r["observed_route_class"] == "LEGACY"
        else:
            assert r["observed_route_class"] == "MC5_QUALIFIED"
