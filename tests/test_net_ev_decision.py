"""Tests for Cost-Aware Net EV Decision Gate & Abstain Policy."""
from __future__ import annotations

import pytest

from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.economic_contract import (
    COST_CONTRACT_VERSION,
    DEFAULT_ROUNDTRIP_COST_FRACTION,
    compute_net_expected_return,
)


def test_compute_net_expected_return_helper():
    res = compute_net_expected_return(0.0020, roundtrip_cost_fraction=0.0014)
    assert res["expected_gross_return"] == 0.0020
    assert res["expected_cost"] == 0.0014
    assert res["expected_net_return"] == pytest.approx(0.0006)
    assert res["expected_gross_return_bps"] == pytest.approx(20.0)
    assert res["expected_cost_bps"] == pytest.approx(14.0)
    assert res["expected_net_return_bps"] == pytest.approx(6.0)


def test_net_ev_gate_abstains_on_negative_net_ev():
    """Trade with 6 bps gross EV has negative net EV (-8 bps) after 14 bps friction and MUST be held."""
    engine = MetaDecisionEngine(
        roundtrip_cost_fraction=0.0014,  # 14 bps
        min_net_ev_pct=0.0,              # require net EV >= 0
        net_ev_gating_enabled=True,
    )

    decision = engine.decide({
        "coin": "BTC",
        "signal": "BUY",
        "action": "BUY",
        "_meta_prediction": {
            "probability": 0.85,
            "probability_semantics": "P(win_given_proposed_trade)",
            "expected_return": 0.0006,  # 6 bps gross EV (> 5 bps min_ev_pct, but < 14 bps cost!)
        },
    }, persist_final=False)

    assert decision["action"] == "HOLD"
    assert decision["rejection_reason"] == "NEGATIVE_NET_EXPECTED_VALUE"
    assert decision["expected_gross_return"] == pytest.approx(0.0006)
    assert decision["expected_cost"] == pytest.approx(0.0014)
    assert decision["expected_net_return"] == pytest.approx(-0.0008)
    assert decision["cost_contract_version"] == COST_CONTRACT_VERSION


def test_net_ev_gate_approves_positive_net_ev():
    """Trade with 25 bps gross EV has positive net EV (+11 bps) after 14 bps friction and is approved."""
    engine = MetaDecisionEngine(
        roundtrip_cost_fraction=0.0014,
        min_net_ev_pct=0.0,
        net_ev_gating_enabled=True,
    )

    decision = engine.decide({
        "coin": "BTC",
        "signal": "BUY",
        "action": "BUY",
        "_meta_prediction": {
            "probability": 0.85,
            "probability_semantics": "P(win_given_proposed_trade)",
            "expected_return": 0.0025,  # 25 bps gross EV
        },
    }, persist_final=False)

    assert decision["action"] == "BUY"
    assert decision["rejection_reason"] is None
    assert decision["expected_gross_return"] == pytest.approx(0.0025)
    assert decision["expected_cost"] == pytest.approx(0.0014)
    assert decision["expected_net_return"] == pytest.approx(0.0011)


def test_net_ev_telemetry_always_recorded_even_when_gating_disabled():
    """Telemetry fields must always be present for observability even if gate is in monitor-only mode."""
    engine = MetaDecisionEngine(net_ev_gating_enabled=False)

    decision = engine.decide({
        "coin": "BTC",
        "signal": "BUY",
        "action": "BUY",
        "_meta_prediction": {
            "probability": 0.85,
            "probability_semantics": "P(win_given_proposed_trade)",
            "expected_return": 0.0010,
        },
    }, persist_final=False)

    assert "expected_gross_return" in decision
    assert "expected_cost" in decision
    assert "expected_net_return" in decision
    assert decision["cost_contract_version"] == COST_CONTRACT_VERSION

