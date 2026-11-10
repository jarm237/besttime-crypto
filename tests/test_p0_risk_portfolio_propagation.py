"""
tests/test_p0_risk_portfolio_propagation.py

P0-A Acceptance & Remediation Tests:
Validates Risk & Portfolio Propagation for paper/demo trading:
1. RiskManager converts LONG/BUY to NEUTRAL or block: no entry, final position size = 0, no paper fill.
2. Stale raw analysis still has LONG but authoritative risk result blocked: stale analysis does not bypass risk result.
3. Portfolio weight drops 50%: final notional/quantity drops accordingly when not hitting other caps/floors;
   explicit portfolio_weight=0 creates PORTFOLIO_WEIGHT_ZERO; floor does not override risk caps.
4. Risk allows entry and portfolio weight unchanged: baseline behavior fully compatible; decision stage = SIZING.
5. Raw signal and raw action immutability: neither analysis nor signals_info raw action mutated;
   PortfolioManagerAgent evaluates approved_action; decision breakdown records complete lineage.
6. MTF risk propagation: AUTO_TRADE_MTF_ENABLED=true with risk block produces 0 primary and 0 MTF entries.
7. Real ExecutionEngine E2E (isolated): real reservation DB, real FillTracker, real submit_paper,
   proves blocked -> REJECTED (0 fills), healthy -> FILLED (with entry_decision_id), replay -> idempotent.
"""

import copy
import pytest
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import (
    TradeAction,
    EntryRejectionReason,
    DecisionStage,
    RiskPortfolioItem,
    build_risk_portfolio_map,
)
from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.execution_config import ExecutionConfig
from btc_scraper.execution.fill_tracker import OrderStatus
from btc_scraper.ml_engine.multi_agent import (
    RiskManagerAgent,
    PortfolioManagerAgent,
    ExecutionAgent,
)


def _sample_readiness_history(count: int = 73) -> list[dict]:
    base = datetime.now(timezone.utc) - timedelta(minutes=15 * (count + 2))
    return [
        {
            "time": (base + timedelta(minutes=15 * i)).isoformat(),
            "open": 100.0 + i * 0.01,
            "high": 100.1 + i * 0.01,
            "low": 99.9 + i * 0.01,
            "close": 100.0 + i * 0.01,
            "volume": 1_000_000.0,
        }
        for i in range(count)
    ]


def _make_sample_analysis(
    signal: str = "STRONG BUY",
    action: str = "BUY",
    score: int = 90,
    meta_prob: float = 0.85,
    entry: float = 100.0,
    sl: float = 95.0,
    tp1: float = 110.0,
    rr1: float = 2.0,
    timeframe: str = "15m",
) -> dict:
    return {
        "coin": "BTC",
        "signal": signal,
        "timeframe": timeframe,
        "close": entry,
        "history": _sample_readiness_history(),
        "signal_score": {
            "score": score,
            "action": action,
            "meta_probability": meta_prob,
            "position_size": 1.0,
        },
        "tp_sl": {
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "rr1": rr1,
        },
    }


def _make_loose_config() -> ExecutionConfig:
    cfg = ExecutionConfig()
    cfg.max_spread_bps = 5000.0
    cfg.max_slippage_bps = 10000.0
    cfg.min_liquidity_score = 0.0001
    cfg.max_latency_ms = 99999
    return cfg


# ─── Test 1: RiskManager converts LONG/BUY to NEUTRAL or block ─────────────────

def test_1_risk_manager_converts_to_neutral_or_block(monkeypatch):
    """
    1. RiskManager converts LONG/BUY to NEUTRAL or block:
       - No entry, final position size = 0.0, no paper fill.
    """
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")

    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)

    blocked_risk_item = RiskPortfolioItem(
        coin="BTC",
        action="BUY",              # raw action preserved
        approved_action="NEUTRAL",  # demoted by risk manager
        risk_blocked=True,
        risk_status="UNAVAILABLE",
        risk_multiplier=0.0,
        portfolio_weight=0.0,
    )

    analysis = _make_sample_analysis()

    decision = trader.build_entry_decision(
        analysis,
        "BTC",
        risk_decision=blocked_risk_item,
    )

    assert not decision.eligible
    assert decision.action == TradeAction.NEUTRAL
    assert decision.rejection_reason == EntryRejectionReason.RISK_MANAGER_BLOCKED
    assert decision.final_position_size == 0.0
    assert decision.breakdown is not None
    assert decision.breakdown.risk_blocked is True
    assert decision.breakdown.risk_multiplier == 0.0
    assert decision.breakdown.approved_action == TradeAction.NEUTRAL
    assert decision.breakdown.signal_action == TradeAction.BUY

    # ── Direct defense-in-depth check at ExecutionEngine boundary ──────────────
    # Note: In the full-chain pipeline, risk-blocked decisions are halted before the
    # execution boundary (as proven in Test 7A). As defense-in-depth, if a non-tradeable
    # signal ever reached submit_paper directly, ExecutionEngine must reject it.
    engine = ExecutionEngine(config=_make_loose_config())
    signal_payload = {
        "coin": "BTC",
        "signal": "STRONG BUY",
        "canonical_action": decision.action.value,  # "NEUTRAL"
        "id": "test-risk-block-001",
        "entry_time": datetime.now(timezone.utc).isoformat(),
    }

    record = engine.submit_paper(signal=signal_payload, candle={"close": 100.0}, notional_usdt=0.0)
    assert record.status == OrderStatus.REJECTED
    assert record.reason in ("CANONICAL_ACTION_NOT_TRADEABLE", "ZERO_POSITION_SIZE")
    assert record.filled_qty == 0.0
    assert record.avg_fill_price in (None, 0.0)


# ─── Test 2: Stale raw analysis cannot bypass risk block ───────────────────────

def test_2_stale_raw_analysis_blocked_by_risk_result(monkeypatch):
    """
    2. Stale raw analysis still has LONG but authoritative risk result blocked:
       - Stale analysis does not bypass risk result.
       - Raw action is preserved in breakdown.signal_action, but decision.action is NEUTRAL.
    """
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")

    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)

    analysis = _make_sample_analysis(signal="STRONG BUY", action="BUY", score=95, meta_prob=0.92)

    risk_item = RiskPortfolioItem(
        coin="BTC",
        action="BUY",
        approved_action="NEUTRAL",
        risk_blocked=True,
        risk_status="BLOCKED_DRAWDOWN",
        risk_multiplier=0.0,
        portfolio_weight=0.0,
    )

    decision = trader.build_entry_decision(
        analysis,
        "BTC",
        risk_decision=risk_item,
    )

    assert not decision.eligible
    assert decision.action == TradeAction.NEUTRAL
    assert decision.rejection_reason == EntryRejectionReason.RISK_MANAGER_BLOCKED
    assert decision.final_position_size == 0.0
    assert decision.breakdown.signal_action == TradeAction.BUY
    assert decision.breakdown.approved_action == TradeAction.NEUTRAL
    assert decision.breakdown.risk_blocked is True


# ─── Test 3: Portfolio weight drops 50% & governing limits ────────────────────

def test_3_portfolio_weight_drops_50_percent_and_governing_limits(monkeypatch):
    """
    3. Portfolio weight drops 50%:
       - Final notional/quantity drops accordingly when not hitting other caps/floors.
       - If hitting cap/floor, proves exact governing limit (sequential sizing invariant).
       - Explicit 0 portfolio weight rejects with PORTFOLIO_WEIGHT_ZERO.
       - Floor does not override portfolio allocation cap.
    """
    monkeypatch.setenv("AUTO_TRADE_RISK_PCT", "2.0")
    monkeypatch.setenv("AUTO_TRADE_USE_KELLY", "false")
    monkeypatch.setenv("AUTO_TRADE_MIN_TRADE_USDT", "10.0")
    monkeypatch.setenv("AUTO_TRADE_MAX_TRADE_USDT", "5000.0")

    trader = AutoTrader()
    balance = 10_000.0
    entry_price = 100.0
    sl_price = 95.0  # 5% stop distance -> raw_notional = 10,000 * 2% / 5% = 4,000 USDT

    # 3A: Portfolio weight is the binding constraint
    # weight = 0.08 -> portfolio_cap = 800 USDT -> notional = min(4000, 800) = 800.0 USDT
    res_full = trader.compute_position_size(
        entry_price=entry_price,
        sl_price=sl_price,
        current_balance=balance,
        portfolio_weight=0.08,
    )
    assert not res_full.rejected
    assert res_full.portfolio_capped == 800.0
    assert res_full.final_notional == 800.0
    assert res_full.governing_constraint == "portfolio_allocation_cap"

    # weight drops by 50% -> weight = 0.04 -> portfolio_cap = 400 USDT -> notional = 400.0 USDT
    res_half = trader.compute_position_size(
        entry_price=entry_price,
        sl_price=sl_price,
        current_balance=balance,
        portfolio_weight=0.04,
    )
    assert not res_half.rejected
    assert res_half.portfolio_capped == 400.0
    assert res_half.final_notional == 400.0
    assert res_half.governing_constraint == "portfolio_allocation_cap"

    # Exact 50% reduction ratio
    assert round(res_half.final_notional / res_full.final_notional, 4) == 0.5000

    # 3B: Floor boundary: portfolio weight drops below min_trade_cap -> rejected, floor does not override!
    # weight = 0.0005 -> 5.0 USDT < min_trade_cap (10.0 USDT)
    res_floor = trader.compute_position_size(
        entry_price=entry_price,
        sl_price=sl_price,
        current_balance=balance,
        portfolio_weight=0.0005,
        min_trade_cap=10.0,
    )
    assert res_floor.rejected
    assert res_floor.final_notional == 0.0
    assert res_floor.rejection_reason == EntryRejectionReason.CAPITAL_CAPACITY_EXCEEDED
    assert res_floor.governing_constraint == "min_trade_cap"

    # 3C: Cap boundary: max_trade_cap is more restrictive than portfolio weight
    res_cap = trader.compute_position_size(
        entry_price=entry_price,
        sl_price=sl_price,
        current_balance=balance,
        portfolio_weight=0.08,
        max_trade_cap=250.0,
    )
    assert not res_cap.rejected
    assert res_cap.portfolio_capped == 800.0
    assert res_cap.final_notional == 250.0
    assert res_cap.governing_constraint == "max_trade_cap"

    # 3D: Explicit zero portfolio weight -> rejects immediately with PORTFOLIO_WEIGHT_ZERO
    res_zero = trader.compute_position_size(
        entry_price=entry_price,
        sl_price=sl_price,
        current_balance=balance,
        portfolio_weight=0.0,
    )
    assert res_zero.rejected
    assert res_zero.final_notional == 0.0
    assert res_zero.rejection_reason == EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO

    # In build_entry_decision, explicit portfolio_weight=0.0 creates PORTFOLIO_WEIGHT_ZERO
    dec_zero = trader.build_entry_decision(
        _make_sample_analysis(),
        "BTC",
        portfolio_decision={"portfolio_weight": 0.0},
    )
    assert not dec_zero.eligible
    assert dec_zero.rejection_reason == EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO


# ─── Test 4: Risk allows entry and portfolio weight unchanged ─────────────────

def test_4_risk_allows_entry_and_portfolio_weight_unchanged_baseline(monkeypatch):
    """
    4. Risk allows entry and portfolio weight unchanged:
       - Baseline behavior fully compatible.
       - Returns eligible = True, positive position size, sizing reflects portfolio weight.
       - Successful EntryDecision records DecisionStage.SIZING.
    """
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
    monkeypatch.setenv("AUTO_TRADE_USE_KELLY", "false")

    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)

    healthy_risk_item = RiskPortfolioItem(
        coin="BTC",
        action="BUY",
        approved_action="BUY",
        risk_blocked=False,
        risk_status="OK",
        risk_multiplier=1.0,
        portfolio_weight=0.20,
    )

    analysis = _make_sample_analysis()

    decision = trader.build_entry_decision(
        analysis,
        "BTC",
        risk_decision=healthy_risk_item,
        current_balance=10_000.0,
    )

    assert decision.eligible
    assert decision.action == TradeAction.BUY
    assert decision.rejection_reason is None
    assert decision.final_position_size > 0.0
    assert decision.breakdown.decision_stage == DecisionStage.SIZING
    assert decision.breakdown.risk_multiplier == 1.0
    assert decision.breakdown.risk_blocked is False
    assert decision.breakdown.portfolio_weight == 0.20
    assert decision.breakdown.approved_action == TradeAction.BUY
    assert decision.breakdown.signal_action == TradeAction.BUY
    assert decision.sizing is not None
    assert decision.sizing.portfolio_weight == 0.20
    assert decision.sizing.portfolio_capped == 2000.0
    assert decision.sizing.final_notional == decision.final_position_size


# ─── Test 5: Raw Action Immutability & Decision Lineage ───────────────────────

def test_5_raw_action_immutability_and_decision_evidence(monkeypatch):
    """
    5. Raw signal/action not mutated in either analysis or signals_info.
       - RiskManagerAgent only sets approved_action, does not overwrite s["action"].
       - PortfolioManagerAgent evaluates active signals from approved_action.
       - EntryDecision records raw result, approved result, sizing lineage.
    """
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")

    # 5A: RiskManagerAgent immutability check
    risk_agent = RiskManagerAgent()
    signals_info = [
        {
            "coin": "BTC",
            "action": "BUY",
            "meta_confidence": 0.85,
            "kelly_fraction": 0.15,
            "close": 100.0,
            "atr": 2.0,
            "signal": "STRONG BUY",
        }
    ]
    context = {"signals_info": signals_info, "analysis": {}}

    with patch("btc_scraper.trading.risk_manager.calculate_risk_metrics") as mock_crm:
        mock_crm.return_value = {
            "status": "UNAVAILABLE",
            "blocked": True,
            "drawdown_pct": 15.0,
            "failure_reason": "drawdown=15.0%",
            "risk_multiplier": 0.0,
        }
        res_ctx = risk_agent.run(context)

    # Invariant: signals_info[0]["action"] must STILL be "BUY" (not mutated to NEUTRAL!)
    assert res_ctx["signals_info"][0]["action"] == "BUY"
    assert res_ctx["signals_info"][0]["approved_action"] == "NEUTRAL"
    assert res_ctx["signals_info"][0]["risk_blocked"] is True
    assert res_ctx["signals_info"][0]["risk_multiplier"] == 0.0

    # 5B: PortfolioManager evaluates approved_action
    pm_agent = PortfolioManagerAgent()
    res_ctx = pm_agent.run(res_ctx)
    # Blocked item should receive 0.0 weight
    assert res_ctx["signals_info"][0]["portfolio_weight"] == 0.0

    # 5C: AutoTrader build_entry_decision lineage preservation
    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)

    raw_analysis = _make_sample_analysis(signal="STRONG BUY", action="BUY", score=92, meta_prob=0.88)
    snapshot_before = copy.deepcopy(raw_analysis)

    rp_map = build_risk_portfolio_map(res_ctx["signals_info"], res_ctx.get("risk_metrics"))
    rp_item = rp_map["BTC"]
    assert rp_item.action == "BUY"  # raw
    assert rp_item.approved_action == "NEUTRAL"  # approved

    decision = trader.build_entry_decision(
        raw_analysis,
        "BTC",
        risk_decision=rp_item,
    )

    # Invariant: raw_analysis must NOT be mutated
    assert raw_analysis == snapshot_before
    assert decision.breakdown.signal_action == TradeAction.BUY
    assert decision.breakdown.approved_action == TradeAction.NEUTRAL
    assert decision.breakdown.risk_multiplier == 0.0
    assert decision.breakdown.risk_blocked is True


# ─── Test 6: MTF Risk Propagation & Bypass Closure ───────────────────────────

def test_6_mtf_risk_propagation_and_bypass_closure(monkeypatch):
    """
    6. MTF Risk Propagation & Bypass Closure:
       - With AUTO_TRADE_MTF_ENABLED=true:
       - When primary timeframe has a risk block, MTF receives the same RiskPortfolioItem
         and produces 0 primary entries and 0 MTF entries.
       - If risk result is missing for a coin in an authoritative cycle, MTF does NOT
         silently execute on raw signal.
    """
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setenv("AUTO_TRADE_MTF_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_MTF_TFS", "1h")

    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)
    monkeypatch.setattr("btc_scraper.trading.position_tracker.add_position", lambda *a, **kw: None)
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit",
        lambda *args, **kwargs: 5000.0,
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures",
        lambda balance: (0.0, {}, {}),
    )

    # Track any orders placed
    orders_placed = []
    class DummyEngine:
        def submit_paper(self, signal, candle=None, notional_usdt=None):
            orders_placed.append(signal)
            rec = MagicMock()
            rec.status = OrderStatus.FILLED
            return rec

    monkeypatch.setattr(trader, "_get_execution_engine", lambda: DummyEngine())

    # Mock MTF inference coordinator and signal scorer to yield a strong BUY on 1h
    class MockInferenceCoord:
        def predict_once(self, *args, **kwargs):
            pred = MagicMock()
            pred.to_dict.return_value = {"meta_probability": 0.95, "model_version": "v1"}
            return pred

    monkeypatch.setattr(
        "btc_scraper.ml_engine.inference_coordinator.get_inference_coordinator",
        lambda: MockInferenceCoord(),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score.evaluate_signal_score",
        lambda *args, **kwargs: {
            "score": 95,
            "action": "BUY",
            "meta_probability": 0.95,
            "model_version": "v1",
        },
    )

    # Spy directly on _process_signal to record evaluated keys (e.g. BTC:Binance, BTC:MTF:1h)
    processed_keys = []
    real_process_signal = trader._process_signal

    async def _spy_process_signal(key: str, ana: dict, *args, **kwargs):
        processed_keys.append(key)
        return await real_process_signal(key, ana, *args, **kwargs)

    monkeypatch.setattr(trader, "_process_signal", _spy_process_signal)

    primary_analysis = {
        "BTC:Binance": _make_sample_analysis(signal="STRONG BUY", action="BUY", score=90, meta_prob=0.85)
    }
    mtf_analysis = {
        "BTC": {
            "1h": _make_sample_analysis(signal="STRONG BUY", action="BUY", score=95, meta_prob=0.95, timeframe="1h")
        }
    }

    # Case 6A: Authoritative risk block is present for BTC
    signals_info_blocked = [
        {
            "coin": "BTC",
            "action": "BUY",
            "approved_action": "NEUTRAL",
            "risk_blocked": True,
            "risk_multiplier": 0.0,
            "risk_status": "UNAVAILABLE",
        }
    ]

    async def _run_blocked():
        return await trader.evaluate_and_trade(
            primary_analysis,
            mtf_analysis=mtf_analysis,
            signals_info=signals_info_blocked,
            risk_context={"status": "UNAVAILABLE", "blocked": True},
        )

    results_blocked = asyncio.run(_run_blocked())
    # Risk block creates 0 primary entries and 0 MTF entries in ExecutionEngine
    assert len(orders_placed) == 0
    # Both primary and MTF were evaluated and halted
    assert "BTC:Binance" in processed_keys
    assert "BTC:MTF:1h" in processed_keys
    # Any returned logs must be skipped/rejected
    for res in results_blocked:
        assert res.get("status") in ("skipped", "error")

    # Case 6B: Cycle has authoritative propagation active, but coin is missing from risk_portfolio_map
    orders_placed.clear()
    processed_keys.clear()
    signals_info_other_coin = [
        {
            "coin": "ETH",
            "action": "BUY",
            "approved_action": "BUY",
            "risk_blocked": False,
        }
    ]

    async def _run_missing_risk():
        return await trader.evaluate_and_trade(
            primary_analysis,
            mtf_analysis=mtf_analysis,
            signals_info=signals_info_other_coin,
            risk_context={"status": "OK", "blocked": False},
        )

    results_missing = asyncio.run(_run_missing_risk())
    # BTC had no risk entry in authoritative map -> MTF must NOT execute on raw signal!
    # Assert directly that BTC:MTF:1h was NOT called into _process_signal (fail-closed before execution)
    assert "BTC:MTF:1h" not in processed_keys
    # Assert DummyEngine received zero MTF submissions (checked by timeframe / key)
    mtf_orders = [o for o in orders_placed if o.get("timeframe") == "1h" or o.get("key", "").startswith("BTC:MTF:")]
    assert len(mtf_orders) == 0


# ─── Test 7: Real ExecutionEngine E2E (Isolated, Zero Network) ────────────────

def test_7_real_execution_engine_e2e_isolated(monkeypatch, tmp_path):
    """
    7. Real ExecutionEngine E2E Test:
       - Uses real ExecutionEngine with isolated temporary paths (temp reservation DB,
         temp fills/reports/logs dirs, real FillTracker, real submit_paper).
       - Zero network, zero writes to production collector data.
       - Proves:
         1. Blocked: RiskManagerAgent -> PortfolioManagerAgent -> ExecutionAgent -> AutoTrader
            -> EntryDecision (blocked before execution boundary; zero ExecutionRecord and zero fill).
         2. Healthy: same path -> real reservation -> real paper fill
            -> ExecutionRecord linked to entry_decision_id.
         3. Replay: same idempotency key does not create a second fill.
    """
    async def _run_real_e2e():
        # Setup isolated environment
        monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
        monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
        monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
        monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
        monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
        monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")

        # Isolated paths
        res_db = str(tmp_path / "reservations.db")
        exec_dir = tmp_path / "execution"
        fills_dir = tmp_path / "fills"
        reports_dir = tmp_path / "reports"
        for d in (exec_dir, fills_dir, reports_dir):
            d.mkdir(parents=True, exist_ok=True)

        engine = ExecutionEngine(
            config=_make_loose_config(),
            reservation_db_path=res_db,
            log_dir=str(exec_dir),
            fills_dir=str(fills_dir),
            reports_dir=str(reports_dir),
        )

        trader = AutoTrader()
        monkeypatch.setattr(trader, "_has_open_position", lambda *a, **kw: False)
        monkeypatch.setattr(trader, "get_last_exit_timestamps", lambda: {})
        monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])
        monkeypatch.setattr(
            "btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit",
            lambda *args, **kwargs: 5000.0,
        )
        monkeypatch.setattr(
            "btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures",
            lambda balance: (0.0, {}, {}),
        )
        monkeypatch.setattr(trader, "_get_execution_engine", lambda: engine)
        monkeypatch.setattr("btc_scraper.trading.auto_trader.auto_trader", trader)

        risk_agent = RiskManagerAgent()
        portfolio_agent = PortfolioManagerAgent()
        exec_agent = ExecutionAgent()

        analysis_dict = {
            "BTC:Binance": _make_sample_analysis(signal="STRONG BUY", action="BUY", score=90, meta_prob=0.85)
        }

        # ── 7A: Blocked before execution boundary; zero ExecutionRecord and zero fill ──
        signals_info_blocked = [
            {
                "coin": "BTC",
                "action": "BUY",
                "meta_confidence": 0.85,
                "kelly_fraction": 0.15,
                "close": 100.0,
                "atr": 2.0,
                "signal": "STRONG BUY",
            }
        ]
        context_blocked = {
            "analysis": analysis_dict,
            "signals_info": signals_info_blocked,
            "raw_candles": {},
        }

        with patch("btc_scraper.trading.risk_manager.calculate_risk_metrics") as mock_crm:
            mock_crm.return_value = {
                "status": "UNAVAILABLE",
                "blocked": True,
                "drawdown_pct": 14.0,
                "failure_reason": "drawdown=14.0%",
                "risk_multiplier": 0.0,
            }
            context_blocked = risk_agent.run(context_blocked)

        # Raw action preserved
        assert context_blocked["signals_info"][0]["action"] == "BUY"
        assert context_blocked["signals_info"][0]["approved_action"] == "NEUTRAL"
        assert context_blocked["signals_info"][0]["risk_blocked"] is True

        context_blocked = portfolio_agent.run(context_blocked)
        assert context_blocked["signals_info"][0]["portfolio_weight"] == 0.0

        await exec_agent.run(context_blocked)

        # In real ExecutionEngine: blocked before execution boundary, zero ExecutionRecord and zero fill
        history_blocked = engine._tracker.get_history()
        assert len(history_blocked) == 0

        # Reservation database has zero reservations
        with engine._reservation_store._get_conn() as conn:
            res_count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        assert res_count == 0
        active_notional, active_slots = engine._reservation_store.get_active_notional_and_slots()
        assert active_notional == 0.0
        assert active_slots == 0

        # Fills directory contains no fill files/records
        fill_files = list(fills_dir.glob("*.json*"))
        assert len(fill_files) == 0

        # ── 7B: Healthy run -> FILLED, reservation linked to entry_decision_id ──
        signals_info_healthy = [
            {
                "coin": "BTC",
                "action": "BUY",
                "meta_confidence": 0.85,
                "kelly_fraction": 0.15,
                "close": 100.0,
                "atr": 2.0,
                "signal": "STRONG BUY",
            }
        ]
        analysis_healthy = {
            "BTC:Binance": _make_sample_analysis(signal="STRONG BUY", action="BUY", score=90, meta_prob=0.85)
        }
        context_healthy = {
            "analysis": analysis_healthy,
            "signals_info": signals_info_healthy,
            "raw_candles": {},
        }

        with patch("btc_scraper.trading.risk_manager.calculate_risk_metrics") as mock_crm:
            mock_crm.return_value = {
                "status": "OK",
                "blocked": False,
                "drawdown_pct": 0.2,
                "failure_reason": None,
                "risk_multiplier": 1.0,
            }
            context_healthy = risk_agent.run(context_healthy)

        assert context_healthy["signals_info"][0]["action"] == "BUY"
        assert context_healthy["signals_info"][0]["approved_action"] == "BUY"
        assert context_healthy["signals_info"][0]["risk_blocked"] is False

        context_healthy = portfolio_agent.run(context_healthy)
        assert context_healthy["signals_info"][0]["portfolio_weight"] > 0.0

        with patch("btc_scraper.trading.position_tracker.add_position"):
            await exec_agent.run(context_healthy)

        history_healthy = engine._tracker.get_history()
        filled_healthy = [r for r in history_healthy if r.status == OrderStatus.FILLED]
        assert len(filled_healthy) == 1
        record = filled_healthy[0]
        assert record.coin == "BTC"
        assert record.side == "BUY"
        assert record.filled_qty > 0.0
        assert record.avg_fill_price is not None and record.avg_fill_price > 0.0
        assert abs(record.avg_fill_price - 100.0) < 25.0
        assert record.entry_decision_id is not None
        assert len(record.entry_decision_id) > 0

        # ── 7C: Replay idempotency test ───────────────────────────────────────
        # Submitting the exact same signal payload with same idempotency key must not create a 2nd new fill
        same_signal = {
            "coin": "BTC",
            "signal": "STRONG BUY",
            "id": record.signal_id,
            "entry_decision_id": record.entry_decision_id,
            "canonical_action": "BUY",
            "idempotency_key": record.idempotency_key,
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
        dup_record = engine.submit_paper(
            signal=same_signal,
            candle={"close": 100.0},
            notional_usdt=record.intended_notional,
        )
        assert dup_record.reason == "duplicate_idempotency_key_already_committed"

    asyncio.run(_run_real_e2e())
