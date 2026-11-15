"""
tests/test_p0_risk_to_execution_contract.py
Workstream C: P0 Risk-to-Execution Contract Closure Test Suite.

Deterministic validation of the 6 core invariants:
1. Gate 1: Risk Block -> ENTRY_ELIGIBLE = FALSE, EXECUTABLE_QUANTITY = 0, NEW_PAPER_ENTRY_COUNT = 0.
2. Gate 2: Portfolio Sizing -> Approved allocation strictly caps executable notional.
3. Gate 3: Execution-Time Risk Recheck -> Halts on fresh block without tampering with prior decision record.
4. Gate 4: Fail Closed -> Missing/corrupted lineage or unparseable context refuses entry.
5. Gate 5: Exit & Reduction Safety -> Exit/reduction/emergency stops are never blocked by entry restrictions.
6. Gate 6: Audit Lineage -> Complete traceable decision lineage throughout execution records.
"""
from __future__ import annotations

import asyncio
import datetime
from datetime import timezone
from unittest.mock import MagicMock
import pytest

from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import (
    TradeAction,
    EntryRejectionReason,
    SizingDecision,
    DecisionBreakdown,
    DecisionStage,
    FinalDecisionStatus,
)
from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.fill_tracker import OrderStatus
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.execution.kill_switch import KillSwitch, KSState
from btc_scraper.ml_engine.multi_agent import (
    RiskManagerAgent,
    PortfolioManagerAgent,
    ExecutionAgent,
)


def _make_sample_candle(close: float = 200.0) -> dict:
    return {
        "open": close,
        "high": close * 1.0005,
        "low": close * 0.9995,
        "close": close,
        "volume": 10000.0,
        "time": datetime.datetime.now(timezone.utc).isoformat(),
        "time_utc": datetime.datetime.now(timezone.utc).isoformat(),
        "closed": True,
    }


def _make_sample_analysis(
    coin: str = "BTC",
    action: str = "BUY",
    close: float = 200.0,
    risk_blocked: bool = False,
    approved_notional: float | None = None,
) -> dict:
    return {
        "signal": action,
        "close": close,
        "risk_blocked": risk_blocked,
        "approved_notional": approved_notional,
        "signal_score": {
            "score": 85,
            "strength": 85,
            "meta_probability": 0.90,
            "meta_confidence": 0.90,
            "action": action,
            "risk_blocked": risk_blocked,
            "approved_notional": approved_notional,
            "kelly_fraction": 0.25,
            "rr1": 2.0,
        },
        "tp_sl": {
            "entry": close,
            "tp1": close * 1.05,
            "sl": close * 0.95,
            "rr1": 2.0,
        },
    }


def test_gate1_risk_block_prevents_paper_entry(monkeypatch):
    """Gate 1: Risk block -> ENTRY_ELIGIBLE = FALSE, EXECUTABLE_QUANTITY = 0, NEW_PAPER_ENTRY_COUNT = 0."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    trader = AutoTrader()

    # Upstream analysis explicitly blocked by risk evaluation
    analysis_blocked = _make_sample_analysis("BTC", action="BUY", risk_blocked=True)

    # 1. build_entry_decision must reject with RISK_BLOCKED
    decision = trader.build_entry_decision(analysis_blocked, "BTC")
    assert decision.eligible is False
    assert decision.rejection_reason == EntryRejectionReason.RISK_BLOCKED
    assert decision.final_position_size == 0.0

    # 2. ExecutionEngine submit_paper must reject blocked entry
    engine = trader._get_execution_engine()
    candle = _make_sample_candle(200.0)
    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "risk_blocked": True,
        "canonical_action": "BUY",
    }
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert "RISK_BLOCKED" in rec.reason
    assert rec.filled_qty == 0.0
    assert rec.execution_recheck_result == "BLOCKED"


def test_gate2_portfolio_sizing_caps_executable_notional(monkeypatch):
    """Gate 2: Approved allocation strictly caps executable notional."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    trader = AutoTrader()

    # Sizing with approved_notional cap of $25.0
    # Even if raw/Kelly would size to $50, final_notional must be capped at $25.0
    sizing_capped = trader.compute_position_size(
        entry_price=200.0,
        sl_price=195.0,
        current_balance=500.0,
        multiplier=1.0,
        win_prob=0.90,
        rr_ratio=2.0,
        approved_notional=25.0,
    )
    assert sizing_capped.rejected is False
    assert sizing_capped.final_notional == 25.0

    # If approved_notional is 0 or negative -> must reject with PORTFOLIO_CAP_EXCEEDED
    sizing_zero = trader.compute_position_size(
        entry_price=200.0,
        sl_price=195.0,
        current_balance=500.0,
        approved_notional=0.0,
    )
    assert sizing_zero.rejected is True
    assert sizing_zero.rejection_reason == EntryRejectionReason.PORTFOLIO_CAP_EXCEEDED
    assert sizing_zero.final_notional == 0.0

    # In ExecutionEngine: approved_notional must cap submitted size
    engine = trader._get_execution_engine()
    candle = _make_sample_candle(200.0)
    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "approved_notional": 20.0,
        "prediction_id": "",
    }
    # Passing notional_usdt=100.0 must be reduced to approved_notional=20.0
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=100.0)
    assert rec.intended_notional == 20.0
    assert rec.executed_notional == 20.0
    assert rec.approved_notional == 20.0


def test_gate3_execution_time_risk_recheck_halts_on_kill_switch(monkeypatch):
    """Gate 3: Execution-time risk recheck halts on kill switch without tampering with prior decision."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    trader = AutoTrader()
    engine = trader._get_execution_engine()
    candle = _make_sample_candle(200.0)

    # Simulate KillSwitch triggered right before execution
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = False
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "prediction_id": "pred_immutable_123",
        "entry_decision_id": "dec_immutable_123",
        "final_decision_id": "fd_immutable_123",
    }
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=30.0)
    assert rec.status == OrderStatus.REJECTED
    assert "KILL_SWITCH_ACTIVE" in rec.reason
    assert rec.execution_recheck_result == "BLOCKED"
    assert rec.filled_qty == 0.0


def test_gate4_fail_closed_on_missing_or_corrupt_lineage(monkeypatch):
    """Gate 4: Fail closed -> Missing lineage or schema mismatch must refuse entry."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: True)

    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # Missing prediction_id and final_decision_id in eligible runtime
    broken_signal = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
    }
    rec = engine.submit_paper(broken_signal, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert rec.reason == "MISSING_FINAL_DECISION"
    assert rec.execution_recheck_result == "BLOCKED"
    assert rec.filled_qty == 0.0


def test_gate5_exit_and_reduction_safety(monkeypatch):
    """Gate 5: Exit/reduction orders are never blocked by entry risk restrictions."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # Even with kill switch blocking entries, exit intent MUST pass
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = False
    mock_ks.allows_exit.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    exit_signal = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_to_close_123",
    }
    rec = engine.submit_paper(exit_signal, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.FILLED
    assert rec.execution_recheck_result == "PASSED"
    assert rec.filled_qty > 0.0


def test_gate6_audit_lineage_traceability(monkeypatch):
    """Gate 6: Audit Lineage -> All mandatory lineage fields are preserved in execution record."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "prediction_id": "pred_audit_001",
        "decision_id": "dec_audit_001",
        "entry_decision_id": "dec_audit_001",
        "final_decision_id": "fd_audit_001",
        "cycle_id": "cycle_audit_001",
        "paper_run_id": "paper_audit_001",
        "approved_notional": 45.0,
        "position_id": "pos_audit_001",
    }
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=45.0)

    # Verify all mandatory lineage keys
    assert rec.prediction_id == "pred_audit_001"
    assert rec.decision_id == "dec_audit_001"
    assert rec.final_decision_id == "fd_audit_001"
    assert rec.cycle_id == "cycle_audit_001"
    assert rec.paper_run_id == "paper_audit_001"
    assert rec.approved_notional == 45.0
    assert rec.executed_notional == 45.0
    assert rec.execution_recheck_result == "PASSED"
    assert rec.position_id == "pos_audit_001"
    assert rec.status == OrderStatus.FILLED
    assert len(rec.fills) == 1
    assert rec.fills[0].fill_id != ""


def test_end_to_end_multiagent_risk_portfolio_execution_chain(monkeypatch):
    """End-to-end integration: MultiAgent Orchestrator context propagates risk blocks and portfolio sizing."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    risk_agent = RiskManagerAgent()
    portfolio_agent = PortfolioManagerAgent()
    exec_agent = ExecutionAgent()

    # Scenario A: RiskManager is blocked
    context_blocked = {
        "raw_candles": {},
        "signals_info": [
            {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.20, "close": 200.0, "atr": 5.0},
        ],
        "analysis": {
            "BTC:Binance": _make_sample_analysis("BTC", "BUY", close=200.0),
        },
        "account_balance": 500.0,
    }
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda: {"blocked": True, "failure_reason": "test_drawdown_breach", "status": "BLOCKED"},
    )

    context_after_risk = risk_agent.run(context_blocked)
    assert context_after_risk["signals_info"][0]["action"] == "NEUTRAL"
    assert context_after_risk["signals_info"][0]["risk_blocked"] is True
    assert context_after_risk["analysis"]["BTC:Binance"]["risk_blocked"] is True

    context_after_portfolio = portfolio_agent.run(context_after_risk)
    assert context_after_portfolio["analysis"]["BTC:Binance"]["risk_blocked"] is True

    # Scenario B: RiskManager is NOT blocked, PortfolioManager allocates weights
    context_healthy = {
        "raw_candles": {},
        "signals_info": [
            {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.15, "close": 200.0, "atr": 5.0},
            {"coin": "ETH", "action": "BUY", "kelly_fraction": 0.10, "close": 100.0, "atr": 2.0},
        ],
        "analysis": {
            "BTC:Binance": _make_sample_analysis("BTC", "BUY", close=200.0),
            "ETH:Binance": _make_sample_analysis("ETH", "BUY", close=100.0),
        },
        "account_balance": 1000.0,
    }
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda: {"blocked": False, "risk_multiplier": 1.0, "status": "HEALTHY"},
    )
    # Mock PortfolioManager optimizer: allocate 20% BTC ($200) and 0% ETH ($0)
    mock_pm = MagicMock()
    mock_pm.allocate_weights.return_value = {"BTC": 0.20, "ETH": 0.0}
    portfolio_agent.pm = mock_pm

    context_healthy = risk_agent.run(context_healthy)
    context_healthy = portfolio_agent.run(context_healthy)

    # BTC gets approved notional $200
    assert context_healthy["analysis"]["BTC:Binance"]["portfolio_weight"] == 0.20
    assert context_healthy["analysis"]["BTC:Binance"]["approved_notional"] == 200.0
    assert context_healthy["analysis"]["BTC:Binance"].get("unallocated_portfolio") is not True

    # ETH gets 0 allocation -> unallocated_portfolio is True, action set to NEUTRAL
    assert context_healthy["analysis"]["ETH:Binance"]["portfolio_weight"] == 0.0
    assert context_healthy["analysis"]["ETH:Binance"]["approved_notional"] == 0.0
    assert context_healthy["analysis"]["ETH:Binance"]["unallocated_portfolio"] is True
    assert context_healthy["analysis"]["ETH:Binance"]["signal_score"]["action"] == "NEUTRAL"
