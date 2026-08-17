"""Tests for HMR-V5-C2 Minimal Economic Selection Model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_c2_minimal_model.json"
AUDIT_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_c2_minimal_model_report.md"


def test_audit_files_exist():
    """Verify that both JSON and Markdown C2 report files exist."""
    assert AUDIT_JSON.exists(), f"C2 audit JSON not found: {AUDIT_JSON}"
    assert AUDIT_REPORT.exists(), f"C2 audit report MD not found: {AUDIT_REPORT}"


def test_program_metadata():
    """Verify HMR-V5-C2 program metadata."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-C2"
    assert data["embargo_bars"] == 96
    assert "audit_timestamp" in data


def test_verdict_and_gates():
    """Verify that the gates G0-G8 exist and all passed successfully."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    assert data["verdict"] in ["PROMOTE_FILTER_MODEL", "NO_INCREMENTAL_MODEL_VALUE"]
    assert "verdict_note" in data
    
    gates = data["gates"]
    for g in ["C2-G0", "C2-G1", "C2-G2", "C2-G3", "C2-G4", "C2-G5", "C2-G6", "C2-G7", "C2-G8"]:
        assert g in gates
        assert gates[g] == "PASS"


def test_statistical_discrimination():
    """Verify that the model outperforms the constant probability baseline OOS."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    btc_stats = data["folds"]["Fold 2"]["BTC"]["statistical"]
    
    # Model AUC should be significantly better than baseline 0.5
    assert btc_stats["model"]["auc"] > 0.65
    
    # Model LogLoss should be lower than baseline constant LogLoss
    assert btc_stats["model"]["logloss"] < btc_stats["baseline"]["logloss"]
    
    # Model Brier score should be lower than baseline Brier score
    assert btc_stats["model"]["brier"] < btc_stats["baseline"]["brier"]


def test_economic_replay_improvements():
    """Verify that ML selection filtering improves executable P4 utility."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    
    btc_eco = data["folds"]["Fold 2"]["BTC"]["economic"]
    
    s0 = btc_eco["S0"]
    s1 = btc_eco["S1"]
    s2 = btc_eco["S2"]
    s3 = btc_eco["S3"]
    
    # Executable Net Maker EV must improve as model filtering tightens
    assert s1["net_ev_maker_bps"] > s0["net_ev_maker_bps"]
    assert s2["net_ev_maker_bps"] > s1["net_ev_maker_bps"]
    
    # Good-trade retention must be within reasonable ranges
    assert s1["good_trade_retention_pct"] >= 80.0
    assert s2["good_trade_retention_pct"] >= 70.0
    
    # Bad-trade rejection must increase as filtering tightens
    assert s3["bad_trade_rejection_pct"] > s2["bad_trade_rejection_pct"]
    assert s2["bad_trade_rejection_pct"] > s1["bad_trade_rejection_pct"]
