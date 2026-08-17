"""Tests for HMR-V5-C3 Confirmatory Model & Selection Policy Audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_c3_confirmatory_audit.json"
AUDIT_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_c3_confirmatory_audit_report.md"


def test_audit_files_exist():
    """Verify that both JSON and Markdown C3 report files exist."""
    assert AUDIT_JSON.exists(), f"C3 audit JSON not found: {AUDIT_JSON}"
    assert AUDIT_REPORT.exists(), f"C3 audit report MD not found: {AUDIT_REPORT}"


def test_program_metadata():
    """Verify HMR-V5-C3 program metadata."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-C3"
    assert data["split_taxonomy"] == "CONFIRMATORY_WITHIN_RESEARCH_WINDOW"
    assert data["frozen_policy"] in ["S1", "S2", "S3"]
    assert "audit_timestamp" in data


def test_verdict_and_gates():
    """Verify that the gates G0-G9 exist and all passed successfully."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    assert data["verdict"] in ["PROMOTE_FILTER_MODEL", "NO_INCREMENTAL_MODEL_VALUE"]
    assert "verdict_note" in data
    
    gates = data["gates"]
    for g in ["C3-G0", "C3-G1", "C3-G2", "C3-G3", "C3-G4", "C3-G5", "C3-G6", "C3-G7", "C3-G8", "C3-G9"]:
        assert g in gates
        assert gates[g] == "PASS"


def test_confirmatory_oos_improvements():
    """Verify that the frozen canonical selection policy produces out-of-sample utility."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    combined = data["confirmatory"]["COMBINED"]
    control = combined["control"]
    treatment = combined["treatment"]
    
    # Net EV Maker must improve under ML treatment
    assert treatment["net_ev_maker_bps"] > control["net_ev_maker_bps"]
    
    # Retention rates check
    assert treatment["good_trade_retention_pct"] >= 60.0
    assert treatment["bad_trade_rejection_pct"] > 30.0
    
    # Check BTC specifically
    btc = data["confirmatory"]["BTC"]
    assert btc["treatment"]["net_ev_maker_bps"] > btc["control"]["net_ev_maker_bps"]
    assert btc["treatment"]["sharpe"] > btc["control"]["sharpe"]
