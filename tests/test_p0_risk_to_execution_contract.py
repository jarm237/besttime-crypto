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
import time
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
from btc_scraper.execution.reservation_store import ReservationStatus
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
    assert rec.execution_recheck_result == "FAILED"
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
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_to_close_123", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )

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


# ─── Phase H1: Fail-Closed KillSwitch & Dynamic Risk Recheck Tests ──────────────

def test_gate3_killswitch_exception_fails_closed(monkeypatch):
    """Phase H1: KillSwitch exception fails closed rather than swallowing error."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    trader = AutoTrader()
    engine = trader._get_execution_engine()
    candle = _make_sample_candle(200.0)

    # Simulate KillSwitch raising an unexpected disk or parsing error
    def _exploding_ks():
        raise RuntimeError("Disk corruption in kill_switch_state.json")

    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", _exploding_ks)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "prediction_id": "pred_immutable_ks_err",
        "entry_decision_id": "dec_immutable_ks_err",
        "final_decision_id": "fd_immutable_ks_err",
    }
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=30.0)
    assert rec.status == OrderStatus.REJECTED
    assert "KILL_SWITCH_ERROR" in rec.reason
    assert rec.execution_recheck_result == "FAILED"
    assert rec.filled_qty == 0.0


def test_gate3_dynamic_risk_recheck_drawdown_limit_breached(monkeypatch):
    """Phase H1: Dynamic risk recheck halts entry when account drawdown limit is breached."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    trader = AutoTrader()
    engine = trader._get_execution_engine()
    candle = _make_sample_candle(200.0)

    # KillSwitch allows entry, but dynamic risk metrics report drawdown limit breach
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda: {"blocked": True, "failure_reason": "DRAWDOWN_LIMIT_BREACHED", "status": "BLOCKED"},
    )
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "prediction_id": "pred_dyn_risk",
        "entry_decision_id": "dec_dyn_risk",
        "final_decision_id": "fd_dyn_risk",
    }
    rec = engine.submit_paper(signal_payload, candle, notional_usdt=40.0)
    assert rec.status == OrderStatus.REJECTED
    assert "DYNAMIC_RISK_BLOCKED: DRAWDOWN_LIMIT_BREACHED" in rec.reason
    assert rec.execution_recheck_result == "FAILED"
    assert rec.filled_qty == 0.0


# ─── Phase H2: Authoritative Account Equity & Cap Validation Tests ──────────────

def test_phase_h2_authoritative_equity_missing_or_invalid(monkeypatch):
    """Phase H2: Missing or non-finite equity prevents allocation without arbitrary constant fallback."""
    portfolio_agent = PortfolioManagerAgent()

    # Case A: context has NO account_balance or account_equity
    context_no_balance = {
        "signals_info": [
            {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.25, "close": 200.0},
        ],
        "analysis": {
            "BTC:Binance": _make_sample_analysis("BTC", "BUY", close=200.0),
        },
    }
    ctx_res = portfolio_agent.run(context_no_balance)
    assert ctx_res["signals_info"][0]["approved_notional"] == 0.0
    assert ctx_res["signals_info"][0]["portfolio_weight"] == 0.0
    assert ctx_res["signals_info"][0]["unallocated_portfolio"] is True
    assert ctx_res["analysis"]["BTC:Binance"]["approved_notional"] == 0.0
    assert ctx_res["analysis"]["BTC:Binance"]["entry_eligible"] is False

    # Case B: context has NaN or Inf account_balance
    context_nan = {
        "account_balance": float("nan"),
        "signals_info": [
            {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.25, "close": 200.0},
        ],
        "analysis": {
            "BTC:Binance": _make_sample_analysis("BTC", "BUY", close=200.0),
        },
    }
    ctx_nan_res = portfolio_agent.run(context_nan)
    assert ctx_nan_res["signals_info"][0]["approved_notional"] == 0.0
    assert ctx_nan_res["signals_info"][0]["unallocated_portfolio"] is True

    # Case C: negative account_balance
    context_neg = {
        "account_balance": -500.0,
        "signals_info": [
            {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.25, "close": 200.0},
        ],
        "analysis": {
            "BTC:Binance": _make_sample_analysis("BTC", "BUY", close=200.0),
        },
    }
    ctx_neg_res = portfolio_agent.run(context_neg)
    assert ctx_neg_res["signals_info"][0]["approved_notional"] == 0.0
    assert ctx_neg_res["signals_info"][0]["unallocated_portfolio"] is True


def test_phase_h2_sizing_rejects_non_finite_caps():
    """Phase H2: AutoTrader.compute_position_size rejects non-finite / NaN / Inf approved notional."""
    trader = AutoTrader()

    # NaN approved notional
    sd_nan = trader.compute_position_size(
        entry_price=200.0,
        sl_price=195.0,
        current_balance=500.0,
        approved_notional=float("nan"),
    )
    assert sd_nan.rejected is True
    assert sd_nan.rejection_reason == EntryRejectionReason.PORTFOLIO_CAP_EXCEEDED
    assert sd_nan.final_notional == 0.0

    # Inf approved notional
    sd_inf = trader.compute_position_size(
        entry_price=200.0,
        sl_price=195.0,
        current_balance=500.0,
        approved_notional=float("inf"),
    )
    assert sd_inf.rejected is True
    assert sd_inf.rejection_reason == EntryRejectionReason.PORTFOLIO_CAP_EXCEEDED
    assert sd_inf.final_notional == 0.0

    # Negative approved notional
    sd_neg = trader.compute_position_size(
        entry_price=200.0,
        sl_price=195.0,
        current_balance=500.0,
        approved_notional=-25.0,
    )
    assert sd_neg.rejected is True
    assert sd_neg.rejection_reason == EntryRejectionReason.PORTFOLIO_CAP_EXCEEDED
    assert sd_neg.final_notional == 0.0


# ─── Phase H3: Authoritative Reduce-Only Verification (All 9 Scenarios) ─────────

def test_phase_h3_1_valid_partial_reduction(monkeypatch):
    """Scenario 1: VALID_PARTIAL_REDUCTION -> Exiting 25% of open position succeeds."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_01", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # 1.0 BTC open @ 200 = $200. Exit $50 = 0.25 BTC (valid partial reduction)
    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_btc_01",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.FILLED
    assert rec.execution_recheck_result == "PASSED"
    assert rec.filled_qty == pytest.approx(0.25)


def test_phase_h3_2_valid_full_exit(monkeypatch):
    """Scenario 2: VALID_FULL_EXIT -> Exiting 100% of open position succeeds."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_02", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # Exit full 1.0 BTC ($200)
    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_btc_02",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=200.0)
    assert rec.status == OrderStatus.FILLED
    assert rec.execution_recheck_result == "PASSED"
    assert rec.filled_qty == pytest.approx(1.0)


def test_phase_h3_3_entry_risk_blocked_but_exit_allowed(monkeypatch):
    """Scenario 3: ENTRY_RISK_BLOCKED_BUT_EXIT_ALLOWED -> KillSwitch entry block does not stop exit."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = False
    mock_ks.allows_exit.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_03", "coin": "BTC", "direction": "BUY", "amount": 0.5, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_btc_03",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=100.0)
    assert rec.status == OrderStatus.FILLED
    assert rec.execution_recheck_result == "PASSED"


def test_phase_h3_4_unknown_position_id(monkeypatch):
    """Scenario 4: UNKNOWN_POSITION_ID -> Referencing non-existent position ID rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_real_01", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_ghost_99",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert "UNKNOWN_POSITION_ID" in rec.reason


def test_phase_h3_5_mismatched_symbol(monkeypatch):
    """Scenario 5: MISMATCHED_SYMBOL -> Signal coin does not match position coin rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_05", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(100.0)

    sig = {
        "coin": "ETH",  # Mismatched coin
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_btc_05",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert "MISMATCHED_SYMBOL" in rec.reason


def test_phase_h3_6_wrong_direction(monkeypatch):
    """Scenario 6: WRONG_DIRECTION -> Exiting a LONG with BUY rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_06", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    sig = {
        "coin": "BTC",
        "signal": "BUY",  # Wrong direction to exit a BUY/LONG position
        "canonical_action": "BUY",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_btc_06",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert "WRONG_DIRECTION" in rec.reason


def test_phase_h3_7_over_reduction(monkeypatch):
    """Scenario 7: OVER_REDUCTION -> Exiting more than open quantity rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_07", "coin": "BTC", "direction": "BUY", "amount": 0.5, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # 0.5 BTC open ($100). Requesting $300 (1.5 BTC) is an over-reduction
    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_btc_07",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=300.0)
    assert rec.status == OrderStatus.REJECTED
    assert "OVER_REDUCTION" in rec.reason


def test_phase_h3_8_duplicate_exit(monkeypatch):
    """Scenario 8: DUPLICATE_EXIT -> Re-submitting the same exit reservation rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [
            {"id": "pos_btc_08", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open", "execution_mode": "paper"}
        ],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_btc_08",
        "reservation_id": "res_duplicate_test_01",
        "idempotency_key": "idemp_dup_exit_01",
    }
    rec1 = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec1.status == OrderStatus.FILLED

    # Second submission with the same reservation_id / idempotency_key
    rec2 = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec2.status == OrderStatus.REJECTED
    assert "DUPLICATE_EXIT" in rec2.reason


def test_phase_h3_9_no_position_available(monkeypatch):
    """Scenario 9: NO_POSITION_AVAILABLE -> Exit attempt when position ledger is empty rejects."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [])
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert "NO_POSITION_AVAILABLE" in rec.reason


# ─── Phase H4: Deterministic End-to-End Paper Path Integration Test ─────────────

def test_phase_h4_deterministic_end_to_end_paper_path(tmp_path, monkeypatch):
    """
    Phase H4: Full end-to-end paper execution path:
    Orchestrator context -> Risk -> Portfolio -> Execution -> AutoTrader
    -> ProductionEvaluator -> submit_paper -> ExecutionRecord persistence/readback.
    """
    import json
    from pathlib import Path
    # 1. Isolate disk execution and logs paths to tmp_path
    log_dir = tmp_path / "logs"
    fills_dir = tmp_path / "fills"

    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")

    # 2. Setup verified synthetic committed Final Decision in runtime evidence store mock
    dep_id = "dep_e2e_01"
    paper_id = "dep_e2e_01"
    monkeypatch.setattr("btc_scraper.core.paths.runtime_deployment_id", lambda: dep_id)
    monkeypatch.setattr("btc_scraper.core.paths.runtime_paper_run_id", lambda: paper_id)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_deployment_id", lambda: dep_id)
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_paper_run_id", lambda: paper_id)

    final_dec = {
        "decision_id": "fd_e2e_committed_01",
        "prediction_id": "pred_e2e_01",
        "cycle_id": "cycle_e2e_01",
        "deployment_id": dep_id,
        "paper_run_id": paper_id,
        "model_version": "vcb-greenfield-v1",
        "model_artifact_sha256": "sha256-mock-e2e-artifact",
        "feature_schema_version": "market-v1",
        "action": "BUY",
        "eligible": True,
        "terminal_status": "TRADE",
        "superseded": False,
        "decision_sha256": "sha256_mock_decision",
        "timestamp_utc": datetime.datetime.now(timezone.utc).isoformat(),
    }
    mock_ev_store = MagicMock()
    mock_ev_store.get_committed_final_decision.return_value = final_dec
    monkeypatch.setattr(
        "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
        lambda: mock_ev_store,
    )

    # 3. Build healthy multi-agent cycle context with authoritative equity
    risk_agent = RiskManagerAgent()
    portfolio_agent = PortfolioManagerAgent()

    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda: {"blocked": False, "risk_multiplier": 1.0, "status": "HEALTHY"},
    )
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)

    analysis_data = _make_sample_analysis("BTC", "BUY", close=200.0)
    analysis_data["prediction_id"] = "pred_e2e_01"
    analysis_data["causal_decision"] = final_dec

    context = {
        "account_balance": 1000.0,
        "signals_info": [
            {
                "coin": "BTC",
                "action": "BUY",
                "kelly_fraction": 0.20,
                "close": 200.0,
                "atr": 4.0,
                "prediction_id": "pred_e2e_01",
            }
        ],
        "analysis": {
            "BTC:Binance": analysis_data,
        },
        "raw_candles": {},
    }

    # Run Risk & Portfolio agents
    context = risk_agent.run(context)
    context = portfolio_agent.run(context)

    # Validate portfolio approved notional was assigned
    approved_notional = context["analysis"]["BTC:Binance"]["approved_notional"]
    assert approved_notional == 200.0
    assert context["analysis"]["BTC:Binance"].get("entry_eligible", True) is not False
    assert context["analysis"]["BTC:Binance"].get("unallocated_portfolio") is not True

    # 4. Instantiate AutoTrader and submit through paper path
    trader = AutoTrader()
    engine = trader._get_execution_engine()
    from btc_scraper.execution.fill_tracker import FillTracker
    engine._tracker = FillTracker(log_dir=str(log_dir), fills_dir=str(fills_dir))
    candle = _make_sample_candle(200.0)

    signal_payload = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "prediction_id": "pred_e2e_01",
        "decision_id": "fd_e2e_committed_01",
        "entry_decision_id": "fd_e2e_committed_01",
        "final_decision_id": "fd_e2e_committed_01",
        "final_decision_action": "BUY",
        "final_decision_prediction_id": "pred_e2e_01",
        "final_decision_cycle_id": "cycle_e2e_01",
        "final_decision_deployment_id": dep_id,
        "final_decision_paper_run_id": paper_id,
        "final_decision_eligible": True,
        "final_decision_terminal_status": "TRADE",
        "final_decision_superseded": False,
        "decision_sha256": "sha256_mock_decision",
        "cycle_id": "cycle_e2e_01",
        "paper_run_id": paper_id,
        "deployment_id": dep_id,
        "model_version": "vcb-greenfield-v1",
        "model_artifact_sha256": "sha256-mock-e2e-artifact",
        "feature_schema_version": "market-v1",
        "approved_notional": approved_notional,
    }

    rec = engine.submit_paper(signal_payload, candle, notional_usdt=approved_notional)

    # 5. Invariant assertions on memory record
    assert rec.status == OrderStatus.FILLED
    assert rec.intended_notional == 200.0
    assert rec.executed_notional == 200.0
    assert rec.approved_notional == 200.0
    assert rec.execution_recheck_result == "PASSED"
    assert rec.filled_qty == pytest.approx(1.0)
    assert len(rec.fills) == 1
    assert rec.fills[0].fill_id != ""
    assert rec.fills[0].price > 0.0

    # 6. Disk JSONL persistence and readback verification
    date_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records_file = log_dir / "paper" / f"execution_{date_str}.jsonl"
    assert records_file.exists()
    lines = records_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    persisted_record = json.loads(lines[-1])

    assert persisted_record["execution_id"] == rec.execution_id
    assert persisted_record["status"] == "FILLED"
    assert persisted_record["intended_notional"] == 200.0
    assert persisted_record["executed_notional"] == 200.0
    assert persisted_record["approved_notional"] == 200.0
    assert persisted_record["execution_recheck_result"] == "PASSED"
    assert persisted_record["prediction_id"] == "pred_e2e_01"
    assert persisted_record["final_decision_id"] == "fd_e2e_committed_01"
    assert persisted_record["cycle_id"] == "cycle_e2e_01"
    assert persisted_record["paper_run_id"] == paper_id


# ─── Blocker 1: Authoritative Equity Wiring Tests ─────────────────────────────

def test_blocker1_equity_wiring_and_snapshots(monkeypatch):
    """Blocker 1: Authoritative equity snapshot resolution, validation, and fail-closed behavior."""
    from btc_scraper.ml_engine.multi_agent import AgentOrchestrator

    async def _run():
        orchestrator = AgentOrchestrator(analysis_symbols=["BTC"])

        # Case A: Paper mode with valid AUTO_TRADE_ACCOUNT_USDT
        monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
        monkeypatch.setenv("AUTO_TRADE_ACCOUNT_USDT", "1250.0")
        snap_a = await orchestrator.resolve_authoritative_equity()
        assert snap_a["valid"] is True
        assert snap_a["equity"] == 1250.0
        assert snap_a["source_identity"] == "paper_config"
        assert snap_a["is_stale"] is False

        # Case B: Paper mode with missing equity
        monkeypatch.delenv("AUTO_TRADE_ACCOUNT_USDT", raising=False)
        monkeypatch.delenv("PAPER_ACCOUNT_EQUITY", raising=False)
        snap_b = await orchestrator.resolve_authoritative_equity()
        assert snap_b["valid"] is False
        assert snap_b["equity"] is None
        assert snap_b["reason"] == "MISSING_PAPER_ACCOUNT_EQUITY"

        # Case C: Context provides stale snapshot (> 300 seconds)
        stale_context = {
            "account_equity_snapshot": {
                "equity": 1000.0,
                "timestamp": datetime.datetime.now().timestamp() - 350.0,
                "source_identity": "paper_config",
                "is_stale": False,
                "valid": True,
            }
        }
        snap_c = await orchestrator.resolve_authoritative_equity(stale_context)
        assert snap_c["valid"] is False
        assert snap_c["is_stale"] is True
        assert snap_c["reason"] == "STALE_EQUITY_SNAPSHOT"

        # Case D: No 500.0 historical fallback in AutoTrader.account_usdt
        trader = AutoTrader()
        assert trader.account_usdt is None
        sizing_decision = trader.compute_position_size(100.0, 98.0, current_balance=None)
        assert sizing_decision.rejected is True
        assert sizing_decision.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT

    asyncio.run(_run())


# ─── Blocker 2: Atomic Cumulative Reduce-Only Tests ───────────────────────────

def test_blocker2_atomic_cumulative_reduce_only(monkeypatch):
    """Blocker 2: Cumulative reduce-only tracking enforces remaining qty without reversal or negative balance."""
    initial_pos = {
        "id": "pos_btc_atomic_01",
        "coin": "BTC",
        "amount": 1.0,
        "direction": "BUY",
        "execution_mode": "paper",
    }
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [initial_pos],
    )
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # 1. Exit A: 0.7 BTC reduction (notional 140 USDT) -> Approved & filled
    signal_a = {
        "coin": "BTC",
        "intent": "EXIT",
        "position_id": "pos_btc_atomic_01",
        "canonical_action": "SELL",
        "reservation_id": "res_exit_a",
    }
    rec_a = engine.submit_paper(signal_a, candle, notional_usdt=140.0)
    assert rec_a.status == OrderStatus.FILLED
    assert rec_a.filled_qty == pytest.approx(0.7)

    # 2. Exit B: 0.7 BTC reduction -> Exceeds remaining 0.3 BTC -> OVER_REDUCTION
    signal_b = {
        "coin": "BTC",
        "intent": "EXIT",
        "position_id": "pos_btc_atomic_01",
        "canonical_action": "SELL",
        "reservation_id": "res_exit_b",
    }
    rec_b = engine.submit_paper(signal_b, candle, notional_usdt=140.0)
    assert rec_b.status == OrderStatus.REJECTED
    assert rec_b.reason == "OVER_REDUCTION"
    assert rec_b.filled_qty == 0.0

    # 3. Exit C: Exact remaining 0.3 BTC (notional 60 USDT) -> Approved & filled
    signal_c = {
        "coin": "BTC",
        "intent": "EXIT",
        "position_id": "pos_btc_atomic_01",
        "canonical_action": "SELL",
        "reservation_id": "res_exit_c",
    }
    rec_c = engine.submit_paper(signal_c, candle, notional_usdt=60.0)
    assert rec_c.status == OrderStatus.FILLED
    assert rec_c.filled_qty == pytest.approx(0.3)

    # 4. Total filled is exactly 1.0 BTC. Any further attempt must reject NO_REMAINING_POSITION_EXPOSURE
    signal_d = {
        "coin": "BTC",
        "intent": "EXIT",
        "position_id": "pos_btc_atomic_01",
        "canonical_action": "SELL",
        "reservation_id": "res_exit_d",
    }
    rec_d = engine.submit_paper(signal_d, candle, notional_usdt=20.0)
    assert rec_d.status == OrderStatus.REJECTED
    assert rec_d.reason == "NO_REMAINING_POSITION_EXPOSURE"
    assert rec_d.filled_qty == 0.0


def test_blocker2_position_mode_isolation_and_ledger_failures(monkeypatch):
    """Blocker 2: Paper/live mode isolation, ledger failure handling, and invalid quantity validation."""
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # 1. Mode isolation: Live position attacked by paper exit
    live_pos = {
        "id": "pos_live_01",
        "coin": "BTC",
        "amount": 1.0,
        "direction": "BUY",
        "execution_mode": "live",
    }
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [live_pos],
    )
    rec_mismatch = engine.submit_paper(
        {"coin": "BTC", "intent": "EXIT", "position_id": "pos_live_01", "canonical_action": "SELL"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_mismatch.status == OrderStatus.REJECTED
    assert rec_mismatch.reason == "PAPER_LIVE_POSITION_MISMATCH"

    # 2. Position ledger unavailable
    rec_ledger = engine.submit_paper(
        {"coin": "BTC", "intent": "EXIT", "simulate_ledger_unavailable": True, "canonical_action": "SELL"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_ledger.status == OrderStatus.REJECTED
    assert rec_ledger.reason == "POSITION_LEDGER_UNAVAILABLE"

    # 3. Invalid position quantity (<= 0 or non-finite)
    invalid_pos = {
        "id": "pos_invalid_qty",
        "coin": "BTC",
        "amount": 0.0,
        "direction": "BUY",
        "execution_mode": "paper",
    }
    monkeypatch.setattr(
        "btc_scraper.trading.position_tracker.get_open_positions",
        lambda: [invalid_pos],
    )
    rec_inv = engine.submit_paper(
        {"coin": "BTC", "intent": "EXIT", "position_id": "pos_invalid_qty", "canonical_action": "SELL"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_inv.status == OrderStatus.REJECTED
    assert rec_inv.reason == "INVALID_POSITION_QUANTITY"


# ─── Blocker 3: Strict Intent and Dynamic Risk Contract Tests ─────────────────

def test_blocker3_strict_intent_and_risk_contract_rejections(monkeypatch):
    """Blocker 3: Enforces exact rejection reasons for all dynamic risk contract breaches."""
    engine = ExecutionEngine()
    candle = _make_sample_candle(200.0)

    # 1. UNKNOWN_INTENT
    rec_intent = engine.submit_paper(
        {"coin": "BTC", "intent": "UNSUPPORTED_ARBITRARY_INTENT"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_intent.status == OrderStatus.REJECTED
    assert rec_intent.reason == "UNKNOWN_INTENT"

    # 2. MISSING_ENTRY_RISK_STATUS
    rec_risk_stat = engine.submit_paper(
        {"coin": "BTC", "intent": "ENTRY", "missing_entry_risk_status": True},
        candle,
        notional_usdt=50.0,
    )
    assert rec_risk_stat.status == OrderStatus.REJECTED
    assert rec_risk_stat.reason == "MISSING_ENTRY_RISK_STATUS"

    # 3. INVALID_RISK_SCHEMA
    rec_schema = engine.submit_paper(
        {"coin": "BTC", "intent": "ENTRY", "simulate_invalid_risk_schema": True},
        candle,
        notional_usdt=50.0,
    )
    assert rec_schema.status == OrderStatus.REJECTED
    assert rec_schema.reason == "INVALID_RISK_SCHEMA"

    # 4. STALE_RISK_SNAPSHOT
    rec_stale = engine.submit_paper(
        {"coin": "BTC", "intent": "ENTRY", "is_risk_stale": True},
        candle,
        notional_usdt=50.0,
    )
    assert rec_stale.status == OrderStatus.REJECTED
    assert rec_stale.reason == "STALE_RISK_SNAPSHOT"

    # 5. RISK_DATABASE_UNAVAILABLE
    rec_db = engine.submit_paper(
        {"coin": "BTC", "intent": "ENTRY", "simulate_risk_database_unavailable": True},
        candle,
        notional_usdt=50.0,
    )
    assert rec_db.status == OrderStatus.REJECTED
    assert rec_db.reason == "RISK_DATABASE_UNAVAILABLE"

    # 6. KILL_SWITCH_EXCEPTION
    def _exploding_ks():
        raise RuntimeError("Corrupted KS state")

    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", _exploding_ks)
    rec_ks = engine.submit_paper(
        {"coin": "BTC", "intent": "ENTRY"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_ks.status == OrderStatus.REJECTED
    assert "KILL_SWITCH_EXCEPTION" in rec_ks.reason

    # 7. Preserve Emergency Exit Privileges: Even when KillSwitch blocks exit, EMERGENCY_EXIT succeeds
    mock_ks = MagicMock()
    mock_ks.allows_exit.return_value = False
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)
    pos = {
        "id": "pos_emer_01",
        "coin": "BTC",
        "amount": 1.0,
        "direction": "BUY",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])

    # Normal exit is blocked
    rec_exit_blocked = engine.submit_paper(
        {"coin": "BTC", "intent": "EXIT", "position_id": "pos_emer_01", "canonical_action": "SELL"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_exit_blocked.status == OrderStatus.REJECTED
    assert rec_exit_blocked.reason == "KILL_SWITCH_BLOCKS_EXIT"

    # Emergency exit succeeds
    rec_emer = engine.submit_paper(
        {"coin": "BTC", "intent": "EMERGENCY_EXIT", "position_id": "pos_emer_01", "canonical_action": "SELL"},
        candle,
        notional_usdt=50.0,
    )
    assert rec_emer.status == OrderStatus.FILLED
    assert rec_emer.filled_qty == pytest.approx(0.25)


# ─── Blocker 4: Real Full-Path Paper Integration Test ─────────────────────────

def test_blocker4_real_full_path_paper_integration(tmp_path, monkeypatch):
    """
    Blocker 4: Real Full-Path Paper Integration
    Exercises: AgentOrchestrator -> ExecutionAgent -> AutoTrader.evaluate_and_trade
    -> ProductionEvaluator -> submit_paper -> FillTracker -> JSONL persistence/readback.
    Validates both blocked and authorized outcomes, parity, and zero real exchange calls.
    """
    async def _run():
        import json
        from btc_scraper.ml_engine.multi_agent import AgentOrchestrator
        from btc_scraper.trading.auto_trader import auto_trader
        from btc_scraper.execution.fill_tracker import FillTracker

        log_dir = tmp_path / "logs"
        fills_dir = tmp_path / "fills"

        monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
        monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
        monkeypatch.setenv("AUTO_TRADE_ACCOUNT_USDT", "1000.0")

        # Isolate position tracking and circuit breaker from other tests
        monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [])
        monkeypatch.setattr("btc_scraper.trading.exposure_manager.exposure_manager.get_open_positions", lambda: [])
        monkeypatch.setattr("btc_scraper.trading.exposure_manager.ExposureManager.get_open_positions", lambda self: [])
        monkeypatch.setattr(auto_trader, "_check_circuit_breaker", lambda: (True, "OK"))
        monkeypatch.setattr(auto_trader, "get_last_exit_timestamps", lambda: {})

        dep_id = "dep_full_01"
        paper_id = "dep_full_01"
        monkeypatch.setattr("btc_scraper.core.paths.runtime_deployment_id", lambda: dep_id)
        monkeypatch.setattr("btc_scraper.core.paths.runtime_paper_run_id", lambda: paper_id)
        monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_deployment_id", lambda: dep_id)
        monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_paper_run_id", lambda: paper_id)

        # Configure FillTracker with temp directories on the AutoTrader's execution engine
        engine = auto_trader._get_execution_engine()
        engine._tracker = FillTracker(log_dir=str(log_dir), fills_dir=str(fills_dir))

        # Assert adapter is NOT called (zero real exchange calls)
        mock_adapter = MagicMock()
        engine.attach_adapter(mock_adapter)

        # Setup candles
        base_time = datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=15 * 220)
        history = []
        for i in range(220):
            t = base_time + datetime.timedelta(minutes=15 * i)
            history.append({
                "time": t.strftime("%Y-%m-%d %H:%M"),
                "time_utc": t.isoformat(),
                "open": 200.0 + (i * 0.05),
                "high": 201.0 + (i * 0.05),
                "low": 199.0 + (i * 0.05),
                "close": 200.5 + (i * 0.05),
                "volume": 1000.0,
            })
        raw_candles = {"BTC": history}
        mtf_candles = {"BTC": {"1h": history[-50:], "4h": history[-50:], "1d": history[-50:]}}

        orchestrator = AgentOrchestrator(analysis_symbols=["BTC"])

        # ── PART 1: Blocked Outcome (RiskManager drawdown limit breach) ────────────
        monkeypatch.setattr(
            "btc_scraper.trading.risk_manager.calculate_risk_metrics",
            lambda: {"blocked": True, "failure_reason": "consecutive_losses", "status": "BLOCKED"},
        )

        ctx_blocked = await orchestrator.run_cycle(raw_candles, mtf_candles)
        # Risk block must result in zero fills
        filled_blocked = [r for r in engine._tracker.get_history() if r.status == OrderStatus.FILLED]
        assert len(filled_blocked) == 0
        date_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records_file = log_dir / "paper" / f"execution_{date_str}.jsonl"
        if records_file.exists():
            lines = [json.loads(line) for line in records_file.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
            filled_records = [r for r in lines if r.get("status") == "FILLED"]
            assert len(filled_records) == 0

        # ── PART 2: Authorized Outcome (Full path execution to fill) ───────────────
        monkeypatch.setattr(
            "btc_scraper.trading.risk_manager.calculate_risk_metrics",
            lambda: {"blocked": False, "status": "HEALTHY", "risk_multiplier": 1.0},
        )
        mock_ks = MagicMock()
        mock_ks.allows_entry.return_value = True
        monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)

        final_dec = {
            "decision_id": "fd_full_path_01",
            "prediction_id": "pred_full_path_01",
            "cycle_id": "cycle_full_path_01",
            "deployment_id": dep_id,
            "paper_run_id": paper_id,
            "model_version": "vcb-greenfield-v1",
            "model_artifact_sha256": "sha256-mock-full-artifact",
            "feature_schema_version": "market-v1",
            "action": "BUY",
            "eligible": True,
            "terminal_status": "TRADE",
            "superseded": False,
            "decision_sha256": "sha256_full_decision",
            "timestamp_utc": datetime.datetime.now(timezone.utc).isoformat(),
        }
        mock_ev_store = MagicMock()
        mock_ev_store.get_committed_final_decision.return_value = final_dec
        mock_ev_store.get_final_decision_for_prediction.return_value = final_dec
        monkeypatch.setattr(
            "btc_scraper.ml_engine.runtime_evidence_store.get_runtime_evidence_store",
            lambda: mock_ev_store,
        )

        # Mock inference to produce our prediction_id
        mock_pred = MagicMock()
        mock_pred.to_dict.return_value = {
            "prediction_id": "pred_full_path_01",
            "action": "BUY",
            "score": 85,
            "strength": 85,
            "meta_confidence": 0.90,
            "meta_probability": 0.90,
            "kelly_fraction": 0.20,
            "model_version": "vcb-greenfield-v1",
            "artifact_sha256": "sha256-mock-full-artifact",
            "feature_schema_version": "market-v1",
            "deployment_id": dep_id,
            "paper_run_id": paper_id,
            "cycle_id": "cycle_full_path_01",
            "decision_sha256": "sha256_full_decision",
            "risk_status": "HEALTHY",
        }
        mock_coord = MagicMock()
        mock_coord.predict_once.return_value = mock_pred
        monkeypatch.setattr(
            "btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator",
            lambda: mock_coord,
        )

        monkeypatch.setenv("AUTO_TRADE_MIN_RR", "0.0")
        monkeypatch.setenv("AUTO_TRADE_MIN_EXPECTED_EDGE", "0.0")

        # Mock analyze_market to produce a clean BUY signal with 2.0 R:R
        from btc_scraper.analysis import analyze_market as real_analyze_market
        def _mock_analyze_market(candles, coin):
            res = real_analyze_market(candles, coin)
            res["signal"] = "BUY"
            res["action"] = "BUY"
            res["tp_sl"] = {"entry": 200.0, "tp1": 220.0, "sl": 190.0, "rr1": 2.0}
            return res

        monkeypatch.setattr("btc_scraper.ml_engine.multi_agent.analyze_market", _mock_analyze_market)
        scoring_result = {
            "score": 85,
            "strength": 85,
            "meta_probability": 0.90,
            "meta_confidence": 0.90,
            "action": "BUY",
            "kelly_fraction": 0.20,
            "prediction_id": "pred_full_path_01",
            "model_version": "vcb-greenfield-v1",
            "artifact_sha256": "sha256-mock-full-artifact",
            "feature_schema_version": "market-v1",
            "deployment_id": dep_id,
            "paper_run_id": paper_id,
            "cycle_id": "cycle_full_path_01",
            "decision_sha256": "sha256_full_decision",
            "risk_status": "HEALTHY",
            "risk_blocked": False,
        }
        monkeypatch.setattr(
            "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
            lambda ana, meta_prediction=None: dict(scoring_result),
        )
        monkeypatch.setattr(
            "btc_scraper.ml_engine.causal_context_bridge.enhance_signal_with_causal_context",
            lambda ana, analysis_info, alpha=0.0: dict(final_dec),
        )

        ctx_auth = await orchestrator.run_cycle(raw_candles, mtf_candles)
        ana_res = ctx_auth["analysis"]["BTC:Binance"]

        # Verify authoritative equity was wired into context
        assert ctx_auth["account_equity"] == 1000.0
        assert ctx_auth["account_equity_snapshot"]["valid"] is True

        # Exactly one fill must have occurred
        filled_auth = [r for r in engine._tracker.get_history() if r.status == OrderStatus.FILLED]
        assert len(filled_auth) == 1

        # Zero real exchange calls
        mock_adapter.create_order.assert_not_called()

        # JSONL file readback verification
        assert records_file.exists()
        lines = [json.loads(line) for line in records_file.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
        persisted = lines[-1]
        assert persisted["status"] == "FILLED"
        assert persisted["prediction_id"] == "pred_full_path_01"
        assert persisted["final_decision_id"] == "fd_full_path_01"
        assert persisted["execution_mode"] == "paper"
        assert persisted["approved_notional"] == pytest.approx(200.0)
        assert persisted["executed_notional"] == pytest.approx(100.0)
        assert persisted["executed_notional"] <= persisted["approved_notional"]

    asyncio.run(_run())


# ─── Phase 4: Durable Order Safety Verification ───────────────────────────────

def test_phase4_1_to_4_durable_exit_across_engine_instances(tmp_path, monkeypatch):
    """Phase 4 Tests 1-4:
    1) Exit 0.7 BTC through ExecutionEngine A.
    2) Recreate ExecutionEngine B using the same durable state (db_path).
    3) Attempt to exit another 0.7 BTC through Engine B.
    4) Verify rejection (OVER_REDUCTION) and safe clipping to the actual remaining 0.3 BTC.
    """
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    db_file = str(tmp_path / "test_reservations.db")
    pos = {
        "id": "pos_durable_btc_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])
    candle = _make_sample_candle(100.0)

    # 1) Engine A: Exit 0.7 BTC ($70 at $100/BTC)
    engine_a = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_a"),
        fills_dir=str(tmp_path / "fills_a"),
    )
    sig_1 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_durable_btc_01",
        "reservation_id": "res_exit_a_01",
        "idempotency_key": "idemp_exit_a_01",
    }
    rec_a = engine_a.submit_paper(sig_1, candle, notional_usdt=70.0)
    assert rec_a.status == OrderStatus.FILLED
    assert rec_a.filled_qty == pytest.approx(0.7)

    # 2) Recreate Engine B pointing to the exact same reservation database
    engine_b = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_b"),
        fills_dir=str(tmp_path / "fills_b"),
    )

    # 3) Engine B: Attempt another 0.7 BTC exit ($70) without clip_to_open_qty
    sig_2 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_durable_btc_01",
        "reservation_id": "res_exit_b_01",
        "idempotency_key": "idemp_exit_b_01",
    }
    rec_b_over = engine_b.submit_paper(sig_2, candle, notional_usdt=70.0)
    # 4a) Verify OVER_REDUCTION rejection
    assert rec_b_over.status == OrderStatus.REJECTED
    assert "OVER_REDUCTION" in rec_b_over.reason

    # 4b) Engine B: Attempt exit with clip_to_open_qty=True -> safely clips to remaining 0.3 BTC ($30)
    sig_3 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_durable_btc_01",
        "reservation_id": "res_exit_b_02",
        "idempotency_key": "idemp_exit_b_02",
        "clip_to_open_qty": True,
    }
    rec_b_clip = engine_b.submit_paper(sig_3, candle, notional_usdt=70.0)
    assert rec_b_clip.status == OrderStatus.FILLED
    assert rec_b_clip.intended_qty == pytest.approx(0.3)
    assert rec_b_clip.filled_qty == pytest.approx(0.3)
    assert rec_b_clip.executed_notional == pytest.approx(30.0)

    # 4c) Verify position is now fully exited -> further exits reject with NO_REMAINING_POSITION_EXPOSURE
    sig_4 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_durable_btc_01",
        "reservation_id": "res_exit_b_03",
        "idempotency_key": "idemp_exit_b_03",
    }
    rec_b_empty = engine_b.submit_paper(sig_4, candle, notional_usdt=10.0)
    assert rec_b_empty.status == OrderStatus.REJECTED
    assert "NO_REMAINING_POSITION_EXPOSURE" in rec_b_empty.reason


def test_phase4_5_restart_recovery_and_reconciliation(tmp_path, monkeypatch):
    """Phase 4 Test 5: Verify restart recovery and reconciliation (reconcile_crashed_reservations)
    when a crash occurs after fill but before reservation commit.
    """
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    db_file = str(tmp_path / "test_reconcile.db")
    pos = {
        "id": "pos_crash_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])
    candle = _make_sample_candle(100.0)

    engine_a = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_a"),
        fills_dir=str(tmp_path / "fills_a"),
    )
    sig_crash = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.REDUCE_POSITION,
        "position_id": "pos_crash_01",
        "reservation_id": "res_crash_01",
        "idempotency_key": "idemp_crash_01",
        "simulate_crash_after_fill_before_commit": True,
    }
    rec = engine_a.submit_paper(sig_crash, candle, notional_usdt=40.0)
    assert rec.status == OrderStatus.FILLED
    assert rec.filled_qty == pytest.approx(0.4)

    # In reservation store, reservation is still PENDING because of the simulated crash
    res_record = engine_a._reservation_store.get_reservation("res_crash_01")
    assert res_record is not None
    assert res_record.status == ReservationStatus.PENDING

    # Even while PENDING, cross-instance position allocation counts it (preventing over-reduction)
    engine_b = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_b"),
        fills_dir=str(tmp_path / "fills_b"),
    )
    exec_qty, pending_qty, total_alloc = engine_b._reservation_store.get_position_exit_allocations("pos_crash_01", "paper")
    assert pending_qty == pytest.approx(0.4)
    assert total_alloc == pytest.approx(0.4)

    # Reconcile crashed reservations against fill tracker records
    reconciled_count = engine_b._reservation_store.reconcile_crashed_reservations([rec])
    assert reconciled_count == 1

    # Check status transitioned to COMMITTED
    res_updated = engine_b._reservation_store.get_reservation("res_crash_01")
    assert res_updated.status == ReservationStatus.COMMITTED
    assert res_updated.filled_qty == pytest.approx(0.4)


def test_phase4_6_missing_execution_mode_rejects(monkeypatch):
    """Phase 4 Test 6: Verify an exit with missing or invalid execution mode is not automatically authorized (MISSING_EXECUTION_MODE)."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    pos_no_mode = {
        "id": "pos_no_mode_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos_no_mode])
    candle = _make_sample_candle(100.0)
    engine = ExecutionEngine()

    sig = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_no_mode_01",
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert rec.execution_recheck_result == "REJECTED"
    assert "MISSING_EXECUTION_MODE" in rec.reason


def test_phase4_7_missing_blocked_key_rejects(monkeypatch):
    """Phase 4 Test 7: Supply a risk result missing 'blocked', confirm entry rejection (INVALID_RISK_SCHEMA)."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    # Return risk result missing 'blocked' key completely
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda **kwargs: {"status": "HEALTHY", "current_equity": 1000.0},
    )
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)

    engine = ExecutionEngine()
    candle = _make_sample_candle(100.0)
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "intent": OrderIntent.ENTRY,
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert rec.execution_recheck_result == "FAILED"
    assert "INVALID_RISK_SCHEMA" in rec.reason

    # Also test when blocked is not a boolean (e.g. string "false")
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda **kwargs: {"status": "HEALTHY", "blocked": "false", "current_equity": 1000.0},
    )
    rec2 = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec2.status == OrderStatus.REJECTED
    assert rec2.execution_recheck_result == "FAILED"
    assert "INVALID_RISK_SCHEMA" in rec2.reason


def test_phase4_8_stale_risk_observation_rejects(monkeypatch):
    """Phase 4 Test 8: Supply a genuinely stale risk observation (> 300s) and confirm entry rejection (STALE_RISK_SNAPSHOT)."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)
    stale_timestamp = time.time() - 360.0  # 6 minutes old (> 300s)
    monkeypatch.setattr(
        "btc_scraper.trading.risk_manager.calculate_risk_metrics",
        lambda **kwargs: {"status": "HEALTHY", "blocked": False, "observation_timestamp": stale_timestamp},
    )
    mock_ks = MagicMock()
    mock_ks.allows_entry.return_value = True
    monkeypatch.setattr("btc_scraper.execution.kill_switch.KillSwitch", lambda: mock_ks)

    engine = ExecutionEngine()
    candle = _make_sample_candle(100.0)
    sig = {
        "coin": "BTC",
        "signal": "BUY",
        "canonical_action": "BUY",
        "intent": OrderIntent.ENTRY,
    }
    rec = engine.submit_paper(sig, candle, notional_usdt=50.0)
    assert rec.status == OrderStatus.REJECTED
    assert rec.execution_recheck_result == "FAILED"
    assert "STALE_RISK_SNAPSHOT" in rec.reason


def test_phase4_9_equity_snapshot_provenance_validation():
    """Phase 4 Test 9: Validate equity snapshot provenance edge cases: missing/invalid timestamp, invalid source, non-finite equity."""
    from btc_scraper.ml_engine.multi_agent import AgentOrchestrator

    async def _run():
        orchestrator = AgentOrchestrator(analysis_symbols=["BTC"])

        # 1) Missing timestamp
        snap_no_ts = await orchestrator.resolve_authoritative_equity({
            "account_equity_snapshot": {"equity": 1000.0, "source_identity": "paper_config"}
        })
        assert snap_no_ts["valid"] is False
        assert snap_no_ts["reason"] == "MISSING_EQUITY_TIMESTAMP"

        # 2) Invalid timestamp (non-finite or negative)
        snap_inv_ts = await orchestrator.resolve_authoritative_equity({
            "account_equity_snapshot": {"equity": 1000.0, "timestamp": -50.0, "source_identity": "paper_config"}
        })
        assert snap_inv_ts["valid"] is False
        assert snap_inv_ts["reason"] == "INVALID_EQUITY_TIMESTAMP"

        # 3) Invalid source identity
        snap_inv_src = await orchestrator.resolve_authoritative_equity({
            "account_equity_snapshot": {"equity": 1000.0, "timestamp": time.time(), "source_identity": "untrusted_source"}
        })
        assert snap_inv_src["valid"] is False
        assert snap_inv_src["reason"] == "INVALID_EQUITY_SOURCE_IDENTITY"

        # 4) Non-finite or non-positive equity
        snap_zero_eq = await orchestrator.resolve_authoritative_equity({
            "account_equity_snapshot": {"equity": 0.0, "timestamp": time.time(), "source_identity": "paper_config"}
        })
        assert snap_zero_eq["valid"] is False
        assert snap_zero_eq["reason"] == "NON_FINITE_OR_NON_POSITIVE_EQUITY"

    asyncio.run(_run())


# ─── Phase 5: Reservation Lifecycle Correctness & Edge Cases ───────────────────

def test_phase5_1_partial_fill_cancellation_remainder_lifecycle(tmp_path, monkeypatch):
    """
    Test Phase 5.1: Partial fill followed by cancellation of remainder.
    Initial: 1.0 BTC.
    Exit 1: Intended 0.7 BTC, filled 0.3 BTC, remainder cancelled.
    Asserts:
      - Confirmed filled = 0.3 BTC permanently protected.
      - Outstanding executable = 0.0 BTC.
      - Remaining position capacity = 0.7 BTC.
      - Unclipped exit of 0.8 BTC rejects with OVER_REDUCTION.
      - Clipped exit of 0.8 BTC safely clips to 0.7 BTC and fills.
      - Further exit attempts fail with NO_REMAINING_POSITION_EXPOSURE.
    """
    db_file = tmp_path / "reservations.db"
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    pos = {
        "id": "pos_part_cancel_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])
    candle = _make_sample_candle(100.0)
    engine = ExecutionEngine(reservation_db_path=db_file)

    # 1. Submit partial fill of 0.3 BTC (intended 0.7 BTC, notional = 70 USDT at price 100)
    sig1 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_cancel_01",
        "reservation_id": "res_part_01",
        "idempotency_key": "idemp_part_01",
        "paper_fill_fraction": 0.3 / 0.7,
        "paper_cancel_remaining": True,
    }
    rec1 = engine.submit_paper(sig1, candle, notional_usdt=70.0)
    assert rec1.status == OrderStatus.CANCELLED
    assert rec1.filled_qty == pytest.approx(0.3)
    assert rec1.unfilled_qty == pytest.approx(0.4)

    # Check reservation store record
    store = engine._reservation_store
    res1 = store.get_reservation("res_part_01")
    assert res1.status == ReservationStatus.CANCELLED_WITH_PARTIAL_FILL
    assert res1.filled_qty == pytest.approx(0.3)

    # Check position exit allocations
    exec_qty, pending_qty, total_alloc = store.get_position_exit_allocations("pos_part_cancel_01", "paper")
    assert exec_qty == pytest.approx(0.3)
    assert pending_qty == pytest.approx(0.0)
    assert total_alloc == pytest.approx(0.3)

    # 2. Attempt unclipped exit of 0.8 BTC (80 USDT at price 100) -> OVER_REDUCTION
    sig2 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_cancel_01",
        "reservation_id": "res_part_02",
        "idempotency_key": "idemp_part_02",
        "clip_to_open_qty": False,
    }
    rec2 = engine.submit_paper(sig2, candle, notional_usdt=80.0)
    assert rec2.status == OrderStatus.REJECTED
    assert "OVER_REDUCTION" in rec2.reason

    # 3. Attempt clipped exit of 0.8 BTC -> safely clipped to 0.7 BTC (70 USDT) and filled
    sig3 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_cancel_01",
        "reservation_id": "res_part_03",
        "idempotency_key": "idemp_part_03",
        "clip_to_open_qty": True,
    }
    rec3 = engine.submit_paper(sig3, candle, notional_usdt=80.0)
    assert rec3.status == OrderStatus.FILLED
    assert rec3.filled_qty == pytest.approx(0.7)

    # Now total executed should be 0.3 + 0.7 = 1.0 BTC
    exec_qty3, pending_qty3, total_alloc3 = store.get_position_exit_allocations("pos_part_cancel_01", "paper")
    assert exec_qty3 == pytest.approx(1.0)
    assert total_alloc3 == pytest.approx(1.0)

    # 4. Attempt any further exit -> NO_REMAINING_POSITION_EXPOSURE
    sig4 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_cancel_01",
        "reservation_id": "res_part_04",
        "idempotency_key": "idemp_part_04",
        "clip_to_open_qty": True,
    }
    rec4 = engine.submit_paper(sig4, candle, notional_usdt=10.0)
    assert rec4.status == OrderStatus.REJECTED
    assert "NO_REMAINING_POSITION_EXPOSURE" in rec4.reason


def test_phase5_2_active_partial_fill_reserves_unfilled_remainder(tmp_path, monkeypatch):
    """
    Test Phase 5.2: Partially filled order remains active/open without cancellation.
    Initial: 1.0 BTC.
    Exit 1: Intended 0.7 BTC, filled 0.3 BTC, paper_cancel_remaining = False.
    Asserts:
      - Reservation store record status: PARTIALLY_COMMITTED.
      - executed_qty = 0.3, pending_reserved_qty = 0.4, total_allocated = 0.7.
      - Remaining position capacity = 0.3 BTC.
      - Unclipped exit of 0.4 BTC rejects with OVER_REDUCTION.
      - Exit of 0.3 BTC succeeds and fills.
    """
    db_file = tmp_path / "reservations.db"
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    pos = {
        "id": "pos_part_active_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])
    candle = _make_sample_candle(100.0)
    engine = ExecutionEngine(reservation_db_path=db_file)

    # 1. Submit partial fill with paper_cancel_remaining = False (order remains active)
    sig1 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_active_01",
        "reservation_id": "res_act_01",
        "idempotency_key": "idemp_act_01",
        "paper_fill_fraction": 0.3 / 0.7,
        "paper_cancel_remaining": False,
    }
    rec1 = engine.submit_paper(sig1, candle, notional_usdt=70.0)
    assert rec1.status == OrderStatus.PARTIAL_FILL
    assert rec1.filled_qty == pytest.approx(0.3)

    store = engine._reservation_store
    res1 = store.get_reservation("res_act_01")
    assert res1.status == ReservationStatus.PARTIALLY_COMMITTED
    assert res1.filled_qty == pytest.approx(0.3)

    # Check allocations: executed = 0.3, pending = 0.4, total = 0.7
    exec_qty, pending_qty, total_alloc = store.get_position_exit_allocations("pos_part_active_01", "paper")
    assert exec_qty == pytest.approx(0.3)
    assert pending_qty == pytest.approx(0.4)
    assert total_alloc == pytest.approx(0.7)

    # 2. Attempt unclipped exit of 0.4 BTC -> OVER_REDUCTION (available is only 1.0 - 0.7 = 0.3)
    sig2 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_active_01",
        "reservation_id": "res_act_02",
        "idempotency_key": "idemp_act_02",
        "clip_to_open_qty": False,
    }
    rec2 = engine.submit_paper(sig2, candle, notional_usdt=40.0)
    assert rec2.status == OrderStatus.REJECTED
    assert "OVER_REDUCTION" in rec2.reason

    # 3. Attempt exit of 0.3 BTC -> succeeds
    sig3 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_part_active_01",
        "reservation_id": "res_act_03",
        "idempotency_key": "idemp_act_03",
        "clip_to_open_qty": False,
    }
    rec3 = engine.submit_paper(sig3, candle, notional_usdt=30.0)
    assert rec3.status == OrderStatus.FILLED
    assert rec3.filled_qty == pytest.approx(0.3)

    # Now total allocated is 0.7 + 0.3 = 1.0 BTC
    exec_qty3, pending_qty3, total_alloc3 = store.get_position_exit_allocations("pos_part_active_01", "paper")
    assert total_alloc3 == pytest.approx(1.0)


def test_phase5_3_crash_recovery_ttl_expiry_and_authoritative_reconciliation(tmp_path, monkeypatch):
    """
    Test Phase 5.3: Crash after fill before SQLite commit, followed by >60s TTL expiry.
    Asserts:
      - Before reconciliation, unconfirmed expired reservation transitions to RECONCILIATION_REQUIRED.
      - Allocated quantity remains protected (new engine rejects over-reduction).
      - Authoritative reconciliation confirms fill and commits status.
      - Retry of reconciliation is strictly idempotent (0 changes).
      - Zero-fill rejected order releases reservation to RELEASED.
    """
    db_file = tmp_path / "reservations.db"
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.execution.execution_engine.runtime_evidence_eligible", lambda: False)

    pos = {
        "id": "pos_crash_ttl_01",
        "coin": "BTC",
        "direction": "BUY",
        "amount": 1.0,
        "status": "open",
        "execution_mode": "paper",
    }
    monkeypatch.setattr("btc_scraper.trading.position_tracker.get_open_positions", lambda: [pos])
    candle = _make_sample_candle(100.0)
    engine_a = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_a"),
        fills_dir=str(tmp_path / "fills_a"),
    )

    # 1. Exit of 0.7 BTC crashes after fill before SQLite commit
    sig1 = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_crash_ttl_01",
        "reservation_id": "res_crash_ttl_01",
        "idempotency_key": "idemp_crash_ttl_01",
        "simulate_crash_after_fill_before_commit": True,
    }
    rec1 = engine_a.submit_paper(sig1, candle, notional_usdt=70.0)
    assert rec1.status == OrderStatus.FILLED
    assert rec1.filled_qty == pytest.approx(0.7)

    # In SQLite, reservation is currently PENDING
    store_a = engine_a._reservation_store
    r1 = store_a.get_reservation("res_crash_ttl_01")
    assert r1.status == ReservationStatus.PENDING

    # 2. Simulate >60s elapsing: age the reservation past its TTL in SQLite
    past_ts = datetime.datetime.fromtimestamp(time.time() - 120.0, tz=timezone.utc).isoformat()
    with store_a._get_conn() as conn:
        conn.execute(
            "UPDATE reservations SET expires_at = ? WHERE reservation_id = ?",
            (past_ts, "res_crash_ttl_01"),
        )

    # 3. Engine B starts up sharing the same database
    engine_b = ExecutionEngine(
        reservation_db_path=db_file,
        log_dir=str(tmp_path / "log_b"),
        fills_dir=str(tmp_path / "fills_b"),
    )
    store_b = engine_b._reservation_store

    # Expiry check / allocation check transitions it to RECONCILIATION_REQUIRED, preserving protection
    exec_qty, pending_qty, total_alloc = store_b.get_position_exit_allocations("pos_crash_ttl_01", "paper")
    r1_expired = store_b.get_reservation("res_crash_ttl_01")
    assert r1_expired.status == ReservationStatus.RECONCILIATION_REQUIRED
    assert total_alloc == pytest.approx(0.7)

    # Attempting to exit 0.7 BTC from Engine B MUST reject with OVER_REDUCTION
    sig_b = {
        "coin": "BTC",
        "signal": "SELL",
        "canonical_action": "SELL",
        "intent": OrderIntent.EXIT,
        "position_id": "pos_crash_ttl_01",
        "reservation_id": "res_engine_b_01",
        "idempotency_key": "idemp_engine_b_01",
        "clip_to_open_qty": False,
    }
    rec_b = engine_b.submit_paper(sig_b, candle, notional_usdt=70.0)
    assert rec_b.status == OrderStatus.REJECTED
    assert "OVER_REDUCTION" in rec_b.reason

    # 4. Authoritative reconciliation with rec1
    reconciled = store_b.reconcile_crashed_reservations([rec1])
    assert reconciled == 1

    r1_committed = store_b.get_reservation("res_crash_ttl_01")
    assert r1_committed.status == ReservationStatus.COMMITTED
    assert r1_committed.filled_qty == pytest.approx(0.7)

    exec_qty2, pending_qty2, total_alloc2 = store_b.get_position_exit_allocations("pos_crash_ttl_01", "paper")
    assert exec_qty2 == pytest.approx(0.7)
    assert pending_qty2 == pytest.approx(0.0)
    assert total_alloc2 == pytest.approx(0.7)

    # 5. Retry reconciliation is idempotent
    reconciled_again = store_b.reconcile_crashed_reservations([rec1])
    assert reconciled_again == 0

    # 6. Test zero-fill rejection properly releases reservation
    # Reserve exit
    rec_rej_res, final_qty, created = store_b.reserve_position_exit(
        reservation_id="res_rej_01",
        idempotency_key="idemp_rej_01",
        position_id="pos_crash_ttl_01",
        execution_mode="paper",
        available_position_qty=1.0,
        intended_qty=0.2,
        notional_usdt=20.0,
        symbol="BTC/USDT",
        side="SELL",
    )
    assert created is True
    # Release it (zero fill)
    released_rec = store_b.release("res_rej_01")
    assert released_rec.status == ReservationStatus.RELEASED

    # Verify idempotent release
    released_again = store_b.release("res_rej_01")
    assert released_again.status == ReservationStatus.RELEASED

    # Verify idempotent commit
    committed_again = store_b.commit("res_crash_ttl_01", filled_notional=70.0, filled_qty=0.7)
    assert committed_again.status == ReservationStatus.COMMITTED

