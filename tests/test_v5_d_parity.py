"""Tests for HMR-V5-D Parity Replay and B2-r1 Risk Accounting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PARITY_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_d2_parity_replay.json"
PARITY_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_d2_parity_report.md"
RISK_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_b2_r1_risk_accounting_audit.json"
RISK_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_b2_r1_risk_accounting_report.md"


def test_audit_files_exist():
    """Verify that all JSON and MD report files for V5-D2 and B2-r1 exist."""
    assert PARITY_JSON.exists(), f"D2 parity JSON not found: {PARITY_JSON}"
    assert PARITY_REPORT.exists(), f"D2 parity report MD not found: {PARITY_REPORT}"
    assert RISK_JSON.exists(), f"B2-r1 risk JSON not found: {RISK_JSON}"
    assert RISK_REPORT.exists(), f"B2-r1 risk report MD not found: {RISK_REPORT}"


def test_parity_matches():
    """Verify that runtime and research models achieve double precision parity matches."""
    data = json.loads(PARITY_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-D2"
    
    gates = data["gates"]
    for g in ["D2-G0", "D2-G1", "D2-G2", "D2-G3", "D2-G4", "D2-G5", "D2-G6", "D2-G7"]:
        assert gates[g] == "PASS"
        
    for sym in ["BTC", "ETH", "BNB"]:
        check = data["parity_check"][sym]
        assert check["max_probability_diff"] < 1e-12
        assert check["decision_mismatch_count"] == 0


def test_risk_accounting_audit():
    """Verify that the risk accounting audit executes correctly and logs the discrepancy."""
    data = json.loads(RISK_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-B2-r1"
    
    # Treatment group sequential capital has higher ending capital than control
    treatment = data["treatment"]
    control = data["control"]
    assert treatment["sequential_capital"]["final_capital"] > control["sequential_capital"]["final_capital"]
    
    # Max drawdown under sequential capital is low
    assert treatment["sequential_capital"]["max_drawdown_pct"] < 1.0


def test_real_runtime_parity():
    """Verify that real runtime feature builder and scoring pipeline achieves exact parity."""
    r1_json = REPO_ROOT / "research/historical_market_replay_v5/v5_d2_r1_real_runtime_parity.json"
    r1_report = REPO_ROOT / "research/historical_market_replay_v5/v5_d2_r1_real_runtime_parity_report.md"
    
    assert r1_json.exists(), f"D2-r1 JSON not found: {r1_json}"
    assert r1_report.exists(), f"D2-r1 report MD not found: {r1_report}"
    
    data = json.loads(r1_json.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-D2-r1"
    
    gates = data["gates"]
    for g in ["D2-G0", "D2-G1", "D2-G2", "D2-G3", "D2-G4", "D2-G5", "D2-G6", "D2-G7", "D2-G8"]:
        assert gates[g] == "PASS"
        
    for sym in ["BTC", "ETH", "BNB"]:
        check = data["parity_check"][sym]
        assert check["max_probability_diff"] < 1e-12
        assert check["decision_mismatch_count"] == 0

