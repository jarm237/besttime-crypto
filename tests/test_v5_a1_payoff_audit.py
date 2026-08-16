"""Tests for HMR-V5-A1 Entry-to-Payoff Surface Audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v5/v5_a1_payoff_audit.json"


@pytest.fixture(scope="module")
def data():
    assert AUDIT_JSON.exists(), f"Audit JSON not found: {AUDIT_JSON}"
    return json.loads(AUDIT_JSON.read_text())


def test_program_metadata(data):
    """Verify HMR-V5-A1 program metadata is correct."""
    assert data["program"] == "HMR-V5-A1"
    assert "maximum_valid_historical_window" in data
    assert "2023-01-01 to 2024-12-31" in data["maximum_valid_historical_window"]


def test_audit_verdict(data):
    """Verify that payoff surface audit verdict is properly determined."""
    assert data["verdict"] == "PROMOTE_PAYOFF_ARCHITECTURE"
    assert "verdict_note" in data
    assert "BLOCKED" in data["ml_training"]


def test_symbols_present(data):
    """Verify that the required assets are present and structured."""
    symbols = data["symbols"]
    for sym in ["BTC", "ETH", "BNB"]:
        assert sym in symbols
        for side in ["BUY", "SELL"]:
            assert side in symbols[sym]


def test_horizons_present(data):
    """Verify that all tested horizons are present under each side."""
    btc_buy = data["symbols"]["BTC"]["BUY"]
    required_horizons = ["30m", "1h", "2h", "4h", "8h", "12h", "24h", "48h", "72h"]
    for h in required_horizons:
        assert h in btc_buy
        h_data = btc_buy[h]
        assert "overall" in h_data
        assert "temporal" in h_data
        assert "regimes" in h_data


def test_metric_values(data):
    """Verify that computed metrics are formatted correctly and within bounds."""
    overall = data["symbols"]["BTC"]["BUY"]["24h"]["overall"]
    assert "n_signals" in overall
    assert overall["n_signals"] > 0
    assert "mean_return_bps" in overall
    assert "ci_lower_bps" in overall
    assert "ci_upper_bps" in overall
    assert "mfe_capture_ratio" in overall
    assert "cost_adjusted_ev_5_0_bps" in overall


def test_temporal_breakdown_structure(data):
    """Verify quarters and years breakdowns exist and have signal counts."""
    temporal = data["symbols"]["BTC"]["BUY"]["24h"]["temporal"]
    assert "by_year" in temporal
    assert "by_quarter" in temporal

    years = temporal["by_year"]
    for yr in ["2023", "2024"]:
        assert yr in years
        assert "n_signals" in years[yr]

    quarters = temporal["by_quarter"]
    # Check some quarters
    for qtr in ["2023Q1", "2023Q2", "2024Q4"]:
        assert qtr in quarters
        assert "n_signals" in quarters[qtr]


def test_regime_breakdown_structure(data):
    """Verify trend and volatility regimes breakdowns exist."""
    regimes = data["symbols"]["BTC"]["BUY"]["24h"]["regimes"]
    assert "trend" in regimes
    assert "volatility" in regimes

    trend = regimes["trend"]
    for t_reg in ["UPTREND", "DOWNTREND"]:
        assert t_reg in trend
        assert "n_signals" in trend[t_reg]

    vol = regimes["volatility"]
    for v_reg in ["HIGH_VOL", "LOW_VOL"]:
        assert v_reg in vol
        assert "n_signals" in vol[v_reg]
