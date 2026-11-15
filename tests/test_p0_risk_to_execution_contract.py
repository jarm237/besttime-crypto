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
            {"id": "pos_to_close_123", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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
            {"id": "pos_btc_01", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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
            {"id": "pos_btc_02", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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
            {"id": "pos_btc_03", "coin": "BTC", "direction": "BUY", "amount": 0.5, "status": "open"}
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
            {"id": "pos_btc_05", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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
            {"id": "pos_btc_06", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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
            {"id": "pos_btc_07", "coin": "BTC", "direction": "BUY", "amount": 0.5, "status": "open"}
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
            {"id": "pos_btc_08", "coin": "BTC", "direction": "BUY", "amount": 1.0, "status": "open"}
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

