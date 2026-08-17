"""Tests for HMR-V5-B0 Economic Cost Contract."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_b0_economic_cost_contract.json"
CONTRACT_MD = REPO_ROOT / "research/historical_market_replay_v5/v5_b0_economic_cost_contract.md"


def test_contract_files_exist():
    """Verify that both JSON and Markdown contract files exist."""
    assert CONTRACT_JSON.exists(), f"Contract JSON not found: {CONTRACT_JSON}"
    assert CONTRACT_MD.exists(), f"Contract MD not found: {CONTRACT_MD}"


def test_contract_metadata():
    """Verify program-level contract metadata."""
    data = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-B0"
    assert data["phase"] == "Economic Cost Contract Freeze"
    assert data["status"] == "FROZEN"


def test_contract_scenarios():
    """Verify that the required cost scenarios are defined with correct values."""
    data = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]

    for scenario_name in ["RESEARCH_IDEALIZED", "MAKER_REALISTIC", "TAKER_REALISTIC"]:
        assert scenario_name in scenarios
        s = scenarios[scenario_name]
        assert "fees_bps_per_leg" in s
        assert "spread_bps_per_leg" in s
        assert "slippage_bps_per_leg" in s
        assert "adverse_selection_bps_per_leg" in s
        assert "round_trip_convention" in s
        assert "total_cost_floor_bps" in s
        assert "rationale" in s

    # Specific cost floor values assertion
    assert scenarios["RESEARCH_IDEALIZED"]["total_cost_floor_bps"] == 2.5
    assert scenarios["MAKER_REALISTIC"]["total_cost_floor_bps"] == 7.0
    assert scenarios["TAKER_REALISTIC"]["total_cost_floor_bps"] == 15.0
