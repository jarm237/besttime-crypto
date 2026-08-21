from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

import pytest

from btc_scraper.trading.decision_types import (
    DecisionBreakdown,
    DecisionStage,
    EntryDecision,
    EntryRejectionReason,
    FinalDecisionStatus,
    SizingDecision,
    TradeAction,
)
from btc_scraper.trading.risk_sizing_contract import (
    RISK_SIZING_CONTRACT_VERSION,
    evaluate_risk_gate,
    finalize_position_size,
)


@pytest.mark.parametrize("action", ["NEUTRAL", "IGNORE", "BLOCKED", "BLOCK_ENTRY", "HOLD"])
@pytest.mark.parametrize("risk_approved", [True, False])
def test_non_actionable_matrix_is_always_zero(action, risk_approved):
    risk = evaluate_risk_gate(action=action, risk_approved=risk_approved)
    result = finalize_position_size(
        action=action,
        risk_result=risk,
        raw_position_size=1_000_000,
        kelly_fraction=1.0,
        minimum_size=10,
        maximum_size=100,
    )
    assert result.final_position_size == 0
    assert result.zeroed_by_gate is True


@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_risk_rejection_is_gated_and_zero(action):
    risk = evaluate_risk_gate(
        action=action,
        risk_approved=False,
        reason="DAILY_LOSS_LIMIT",
    )
    result = finalize_position_size(
        action=action,
        risk_result=risk,
        raw_position_size=50,
        minimum_size=10,
    )
    assert risk.gated is True
    assert result.gated is True
    assert result.final_position_size == 0
    assert result.gate_reason == "DAILY_LOSS_LIMIT"


@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_actionable_approved_size_preserves_lineage(action):
    risk = evaluate_risk_gate(action=action, risk_approved=True, risk_multiplier=0.5)
    result = finalize_position_size(
        action=action,
        risk_result=risk,
        raw_position_size=80,
        kelly_fraction=0.08,
        minimum_size=10,
        maximum_size=100,
        sizing_method="kelly",
    )
    assert result.raw_position_size == 80
    assert result.risk_adjusted_size == 40
    assert result.final_position_size == 40
    assert result.kelly_fraction == 0.08
    assert result.sizing_contract_version == RISK_SIZING_CONTRACT_VERSION


@pytest.mark.parametrize(
    ("raw", "expected", "minimum_applied"),
    [(0, 0, False), (1e-9, 10, True), (9.999, 10, True), (10, 10, False), (10.001, 10.001, False)],
)
def test_zero_and_positive_minimum_boundaries(raw, expected, minimum_applied):
    risk = evaluate_risk_gate(action="BUY", risk_approved=True)
    result = finalize_position_size(
        action="BUY", risk_result=risk, raw_position_size=raw, minimum_size=10
    )
    assert result.final_position_size == expected
    assert result.minimum_cap_applied is minimum_applied


@pytest.mark.parametrize(
    ("raw", "expected", "capped"),
    [(99.999, 99.999, False), (100, 100, False), (100.001, 100, True)],
)
def test_maximum_boundaries(raw, expected, capped):
    risk = evaluate_risk_gate(action="SELL", risk_approved=True)
    result = finalize_position_size(
        action="SELL", risk_result=risk, raw_position_size=raw, maximum_size=100
    )
    assert result.final_position_size == expected
    assert result.maximum_cap_applied is capped


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), -1, None, "bad"])
def test_invalid_exposure_fails_closed(raw):
    risk = evaluate_risk_gate(action="BUY", risk_approved=True)
    result = finalize_position_size(action="BUY", risk_result=risk, raw_position_size=raw)
    assert result.final_position_size == 0
    assert math.isfinite(result.final_position_size)


@pytest.mark.parametrize("kelly", [-0.01, 0.0, 1e-9, 0.2, 1.0, 1.1, float("nan"), float("inf")])
def test_kelly_is_explicit_metadata_not_authoritative_size(kelly):
    risk = evaluate_risk_gate(action="BUY", risk_approved=True)
    result = finalize_position_size(
        action="BUY", risk_result=risk, raw_position_size=25, kelly_fraction=kelly
    )
    assert result.final_position_size == 25
    assert result.kelly_fraction is None or math.isfinite(result.kelly_fraction)


def test_no_stale_size_leakage_between_calls():
    approved = evaluate_risk_gate(action="BUY", risk_approved=True)
    first = finalize_position_size(action="BUY", risk_result=approved, raw_position_size=50)
    neutral = evaluate_risk_gate(action="NEUTRAL", risk_approved=True)
    second = finalize_position_size(action="NEUTRAL", risk_result=neutral, raw_position_size=first.final_position_size)
    rejected = evaluate_risk_gate(action="BUY", risk_approved=False)
    third = finalize_position_size(action="BUY", risk_result=rejected, raw_position_size=first.final_position_size)
    assert first.final_position_size == 50
    assert second.final_position_size == third.final_position_size == 0


def test_cross_symbol_size_isolation():
    fixtures = [
        ("BTC", "BUY", True, 100),
        ("ETH", "SELL", False, 80),
        ("BNB", "NEUTRAL", True, 60),
    ]

    def size(row):
        symbol, action, approved, raw = row
        risk = evaluate_risk_gate(action=action, risk_approved=approved)
        return symbol, finalize_position_size(action=action, risk_result=risk, raw_position_size=raw).final_position_size

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert dict(pool.map(size, fixtures)) == {"BTC": 100, "ETH": 0, "BNB": 0}


def test_sizing_decision_exposes_authoritative_compatibility_aliases():
    sizing = SizingDecision(
        entry_price=100,
        sl_price=95,
        stop_distance_pct=0.05,
        risk_pct=2,
        risk_notional=20,
        raw_notional=400,
        risk_adjusted_notional=100,
        final_notional=50,
    )
    payload = sizing.to_dict()
    assert payload["raw_position_size"] == 400
    assert payload["risk_adjusted_size"] == 100
    assert payload["final_position_size"] == 50
    assert payload["sizing_contract_version"] == "risk-sizing/v1"


def test_rejected_sizing_has_zero_authoritative_size():
    sizing = SizingDecision(
        entry_price=100,
        sl_price=95,
        stop_distance_pct=0.05,
        risk_pct=2,
        risk_notional=20,
        raw_notional=400,
        risk_adjusted_notional=5,
        final_notional=10,
        rejected=True,
        rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
    )
    assert sizing.final_position_size == 0
    assert sizing.to_dict()["final_position_size"] == 0


def test_non_actionable_entry_decision_serializes_zero():
    breakdown = DecisionBreakdown(
        decision_stage=DecisionStage.NORMALIZATION,
        technical_score=50,
        directional_score=0,
        signal_strength=0,
        signal_action=TradeAction.NEUTRAL,
    )
    decision = EntryDecision(
        eligible=False,
        action=TradeAction.NEUTRAL,
        rejection_reason=EntryRejectionReason.ACTION_DISAGREEMENT,
        final_status=FinalDecisionStatus.REJECTED,
        breakdown=breakdown,
        sizing=None,
    )
    payload = decision.to_dict()
    assert payload["final_position_size"] == payload["position_size"] == 0
    assert payload["gated"] is False


def test_risk_rejected_entry_decision_is_gated():
    decision = EntryDecision(
        eligible=False,
        action=TradeAction.BUY,
        rejection_reason=EntryRejectionReason.CIRCUIT_BREAKER,
        final_status=FinalDecisionStatus.REJECTED,
        breakdown=None,
        sizing=None,
    )
    assert decision.gated is True
    assert decision.final_position_size == 0


def test_signal_score_non_actionable_and_risk_rejected_are_zero(monkeypatch):
    import btc_scraper.ml_engine.signal_score as module

    monkeypatch.setattr(module, "_get_cached_risk_metrics", lambda: {
        "risk_multiplier": 1.0, "blocked": False, "status": "HEALTHY"
    })
    neutral = module.score_signal(
        "NEUTRAL", {"signal": "NEUTRAL"}, {"disable_ml": True},
        meta_prediction={"probability": 0.8},
    )
    assert neutral["position_size"] == neutral["final_position_size"] == 0

    monkeypatch.setattr(module, "_get_cached_risk_metrics", lambda: {
        "risk_multiplier": 0.0, "blocked": True, "status": "BLOCKED", "failure_reason": "daily_limit"
    })
    blocked = module.score_signal(
        "BUY", {"signal": "BUY"}, {"disable_ml": True},
        meta_prediction={"probability": 0.8},
    )
    assert blocked["action"] == "NEUTRAL"
    assert blocked["gated"] is True
    assert blocked["final_position_size"] == 0


def test_order_boundary_uses_authoritative_final_size():
    from pathlib import Path

    source = Path("btc_scraper/trading/auto_trader.py").read_text(encoding="utf-8")
    assert "usdt_amount = decision.final_position_size" in source
    assert "usdt_amount = sizing_decision.final_notional" not in source
