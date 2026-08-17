"""Tests for HMR-V5-C0 Learning Contract and V5-C1 Label Audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_c0_learning_contract.json"
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_c1_label_audit.json"
AUDIT_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_c1_label_audit_report.md"


def test_audit_files_exist():
    """Verify that learning contract and audit files exist."""
    assert CONTRACT_JSON.exists(), f"Contract JSON not found: {CONTRACT_JSON}"
    assert AUDIT_JSON.exists(), f"Audit JSON not found: {AUDIT_JSON}"
    assert AUDIT_REPORT.exists(), f"Audit report not found: {AUDIT_REPORT}"


def test_learning_contract_values():
    """Verify learning contract properties."""
    data = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    assert data["contract_name"] == "HMR-V5-C0"
    assert data["exit"]["family"] == "E4"
    assert data["exit"]["tp_bps"] == 50.0
    assert data["exit"]["sl_bps"] == 30.0
    assert data["execution"]["policy"] == "P4"


def test_label_audit_results():
    """Verify the metrics and properties evaluated by C1 audit."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-C1"
    
    # Class balance asserts
    btc = data["class_balance"]["BTC"]
    assert 70.0 <= btc["positive_rate_pct"] <= 80.0
    assert btc["total_signals"] > 0
    
    # Timeouts must be 0
    assert data["durations"]["timeouts"] == 0
    
    # Duplicates concentration
    assert data["state_concentration"]["BTC"]["duplicate_entry_signals"] == 0
    
    # Overlapping checks
    assert data["overlapping_dependence"]["BTC"]["overlap_pct"] > 80.0
