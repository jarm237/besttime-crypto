"""Tests for HMR-V5-B1-r1 Exit Simulation Semantic & Accounting Audit."""
from __future__ import annotations

import pandas as pd
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRADE_SAMPLES_CSV = REPO_ROOT / "research/historical_market_replay_v5/v5_b1_r1_trade_samples.csv"
AUDIT_REPORT_MD = REPO_ROOT / "research/historical_market_replay_v5/v5_b1_r1_exit_accounting_audit_report.md"


def test_audit_files_exist():
    """Verify that both CSV trade samples and validation report exist."""
    assert TRADE_SAMPLES_CSV.exists(), f"Trade samples CSV not found: {TRADE_SAMPLES_CSV}"
    assert AUDIT_REPORT_MD.exists(), f"Audit report MD not found: {AUDIT_REPORT_MD}"


def test_trade_samples_structure():
    """Verify that the trade samples CSV has correct columns and contents."""
    df = pd.read_csv(TRADE_SAMPLES_CSV)
    
    # Required columns from prompt
    required_cols = [
        "signal_id",
        "side",
        "entry_timestamp",
        "entry_price",
        "tp_price",
        "sl_price",
        "exit_timestamp",
        "exit_price",
        "exit_reason",
        "raw_return_bps",
        "realized_return_bps",
        "MFE_bps",
        "MAE_bps",
        "family"
    ]
    for col in required_cols:
        assert col in df.columns, f"Missing column: {col}"
        
    assert len(df) == 200, f"Expected 200 trade samples, got {len(df)}"
    
    # Assert specific exits
    reasons = set(df["exit_reason"].unique())
    assert "TP" in reasons
    assert "SL" in reasons
    assert "TIMEOUT" in reasons
    
    # Verify Invariant 1: TP is positive, SL is negative
    tp_trades = df[df["exit_reason"] == "TP"]
    assert (tp_trades["realized_return_bps"] > 0).all(), "Found TP trade with negative/zero return"
    
    sl_trades = df[df["exit_reason"] == "SL"]
    assert (sl_trades["realized_return_bps"] < 0).all(), "Found SL trade with positive/zero return"
