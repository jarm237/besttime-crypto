"""Tests for HMR-V5-B2 Executable Trade Stream Audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_b2_executable_audit.json"
AUDIT_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_b2_executable_audit_report.md"


def test_audit_files_exist():
    """Verify that both JSON and Markdown B2 report files exist."""
    assert AUDIT_JSON.exists(), f"B2 audit JSON not found: {AUDIT_JSON}"
    assert AUDIT_REPORT.exists(), f"B2 audit report MD not found: {AUDIT_REPORT}"


def test_program_metadata():
    """Verify HMR-V5-B2 program metadata."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-B2"
    assert data["exit_basis"] == "E4"
    assert "audit_timestamp" in data


def test_verdict_and_gates():
    """Verify that the gates G0-G8 exist and all passed successfully."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    assert data["verdict"] in ["PROMOTE_EXECUTABLE_BASELINE", "PROMOTE_MAKER_ONLY"]
    assert "verdict_note" in data
    
    gates = data["gates"]
    for g in ["B2-G0", "B2-G1", "B2-G2", "B2-G3", "B2-G4", "B2-G5", "B2-G6", "B2-G7", "B2-G8"]:
        assert g in gates
        assert "PASS" in gates[g]


def test_serialization_integrity():
    """Verify that serialization policies suppress overlapping signals correctly."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    btc = data["portfolio"]["BTC"]
    p0 = btc["P0"]
    p1 = btc["P1"]
    p4 = btc["P4"]
    
    # Executed trades must decrease as constraints tighten
    assert p0["executed_trades"] > p1["executed_trades"]
    assert p1["executed_trades"] > p4["executed_trades"]
    
    # Suppressed counts must match candidate reduction
    assert p0["executed_trades"] - p1["executed_trades"] == p1["suppressed_overlap"]
    
    # Confirm net EVs and edge retention are non-empty
    assert p4["net_ev_maker_bps"] > 0
    assert p4["edge_retention_pct"] > 0.0
    assert p4["peak_concurrency"] <= 2
    
    # Combined portfolio concurrency limit check
    combined_p4 = data["portfolio"]["COMBINED"]["P4"]
    assert combined_p4["peak_concurrency"] <= 3
