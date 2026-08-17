"""Tests for HMR-V5-B1 Path-Aware Exit Capture Audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_b1_exit_audit.json"
AUDIT_REPORT = REPO_ROOT / "research/historical_market_replay_v5/v5_b1_exit_audit_report.md"


def test_audit_files_exist():
    """Verify that both JSON and Markdown exit audit report files exist."""
    assert AUDIT_JSON.exists(), f"Exit audit JSON not found: {AUDIT_JSON}"
    assert AUDIT_REPORT.exists(), f"Exit audit report MD not found: {AUDIT_REPORT}"


def test_program_metadata():
    """Verify HMR-V5-B1 program metadata."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert data["program"] == "HMR-V5-B1"
    assert data["governance_contract"] == "HMR-V5-B0"
    assert "audit_timestamp" in data


def test_verdict_taxonomy():
    """Verify that the generated verdict is a valid taxomony verdict."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    valid_verdicts = {
        "PROMOTE_EXIT_ARCHITECTURE",
        "REDESIGN_EXIT",
        "REDESIGN_ENTRY",
        "ECONOMICALLY_INSUFFICIENT",
        "HARD_STOP_STRATEGY_FAMILY",
        "RESULT_OBSERVED"
    }
    assert data["verdict"] in valid_verdicts
    assert "verdict_note" in data
    assert len(data["verdict_note"]) > 0


def test_symbols_and_families():
    """Verify exit metrics structure for required symbols and families."""
    data = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    symbols = data["symbols"]
    
    for sym in ["BTC", "ETH", "BNB"]:
        assert sym in symbols
        for side in ["BUY", "SELL"]:
            assert side in symbols[sym]
            for family in ["E0", "E1", "E2", "E3", "E4"]:
                assert family in symbols[sym][side]
                f_data = symbols[sym][side][family]
                
                # Check metrics structure
                assert "n_signals" in f_data
                assert "gross_ev_bps" in f_data
                assert "net_ev_idealized_bps" in f_data
                assert "net_ev_maker_bps" in f_data
                assert "net_ev_taker_bps" in f_data
                assert "mean_mfe_bps" in f_data
                assert "mean_mae_bps" in f_data
                assert "capture_ratio" in f_data
                assert "stop_hit_pct" in f_data
                assert "target_hit_pct" in f_data
                assert "timeout_pct" in f_data
                assert "time_to_mfe_bars" in f_data
                assert "time_to_mae_bars" in f_data
                assert "profit_factor" in f_data
                assert "cvar_95_pct" in f_data
                assert "max_drawdown_pct" in f_data
                assert "sharpe" in f_data
                assert "avg_bars_held" in f_data
                
                assert f_data["n_signals"] > 0
