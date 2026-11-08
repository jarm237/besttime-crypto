"""Integration tests proving honest NO_TRADE_SHADOW economic policy in paper runtime.

Verifies all 12 runtime paths and boundaries under PAPER_ECONOMIC_POLICY="NO_TRADE_SHADOW":
1. decide_with_provider with provider applying context
2. decide_with_provider with provider skipping context (should_apply=False)
3. decide_with_provider with provider raising exception
4. decide_with_context direct
5. Causal bridge from analysis to persisted final decision (enhance_signal_with_causal_context)
6. AutoTrader reading persisted decision and evaluating build_entry_decision
7. Verifying _process_signal does not call broker/execution adapter
8. End-to-end pipeline replay showing 0 executable orders, 0 fills, and shadow decisions preserved
9. Active paper policy allows execution when explicitly configured (ACTIVE_PAPER)
10. Unset environment defaults fail-closed to NO_TRADE_SHADOW
11. Single finalization and persistence boundary across all 6 decision branches (exact 1 finalizer call, 1 write)
12. Genuine shadow fast path bypassing DB, VaR, evaluator, execution engine, and synchronous Telegram alerts
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.causal_context_bridge import enhance_signal_with_causal_context
from btc_scraper.trading.auto_trader import AutoTrader
from btc_scraper.trading.decision_types import EntryRejectionReason


def _make_bullish_analysis_payload(coin: str = "BTC", symbol: str = "BTCUSDT") -> dict:
    """Helper to generate a valid, statistically positive entry candidate.
    
    Notice: enforce_economic_policy is NEVER passed here.
    The policy must be enforced canonically at runtime finalization.
    """
    prediction_id = f"pred-{uuid.uuid4().hex[:12]}"
    base = datetime.now(timezone.utc)
    start = base - timedelta(minutes=15 * 230)
    candles = []
    p = 40000.0
    for i in range(230):
        t = (start + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M")
        p += 20.0
        candles.append({"time": t, "open": p, "high": p + 30, "low": p - 30, "close": p + 10, "volume": 100.0})

    return {
        "coin": coin,
        "symbol": symbol,
        "timeframe": "15m",
        "signal": "BUY",
        "action": "BUY",
        "close": candles[-1]["close"],
        "history": candles,
        "signal_id": f"sig-{uuid.uuid4().hex[:12]}",
        "prediction_id": prediction_id,
        "caller_context": "EXECUTION_AUTHORIZING",
        "meta_probability": 0.90,
        "meta_confidence": 0.90,
        "model_probability_up": 0.90,
        "meta_expected_return": 0.0050,
        "model_version": "1.0.0",
        "artifact_sha256": "35bea38a767d673b6b87e40cc6f52f5b3a1aea453632a4b05ac8a49ab6b613db",
        "feature_schema_hash": "b866c5e78d7f6f02cb74fe52cbe1d8a5f69752d60acc2c5fe2e5ddf6e5fbc0dc",
        "tp_sl": {"entry": p, "sl": p - 400.0, "tp1": p + 800.0, "rr1": 2.0},
        "_meta_prediction": {
            "prediction_id": prediction_id,
            "probability": 0.90,
            "probability_semantics": "P(win_given_proposed_trade)",
            "expected_return": 0.0050,  # 50 bps positive EV
            "artifact_sha256": "35bea38a767d673b6b87e40cc6f52f5b3a1aea453632a4b05ac8a49ab6b613db",
            "feature_schema_hash": "b866c5e78d7f6f02cb74fe52cbe1d8a5f69752d60acc2c5fe2e5ddf6e5fbc0dc",
            "model_version": "1.0.0",
        },
    }


@pytest.fixture(autouse=True)
def set_paper_no_trade_env(monkeypatch):
    """Fixture ensuring the standard paper environment with NO_TRADE_SHADOW policy."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "NO_TRADE_SHADOW")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")


def test_path_1_decide_with_provider_applying_context():
    """Path 1: decide_with_provider where provider actively applies context."""
    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )
    payload = _make_bullish_analysis_payload()

    mock_provider = MagicMock()
    mock_provider.name = "MockBayesianProvider"
    mock_provider.should_apply_context.return_value = True

    mock_report = MagicMock()
    mock_report.to_dict.return_value = {
        "action": "BUY",
        "posterior": 0.88,
        "risk_action": "ALLOW",
        "risk_reasons": [],
        "context_snapshot_id": "snap-001",
    }
    mock_provider.generate_context_report.return_value = mock_report
    mock_state = MagicMock()

    decision = engine.decide_with_provider(payload, mock_provider, mock_state)

    assert decision["action"] == "HOLD"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["paper_economic_policy"] == "NO_TRADE_SHADOW"
    assert decision["shadow_action"] == "BUY"


def test_path_2_decide_with_provider_skipping_context():
    """Path 2: decide_with_provider where provider skips context (should_apply=False)."""
    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )
    payload = _make_bullish_analysis_payload()

    mock_provider = MagicMock()
    mock_provider.name = "MockSkippingProvider"
    mock_provider.should_apply_context.return_value = False
    mock_state = MagicMock()

    decision = engine.decide_with_provider(payload, mock_provider, mock_state)

    assert decision["context_skipped"] is True
    assert decision["action"] == "HOLD"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["shadow_action"] == "BUY"


def test_path_3_decide_with_provider_raising_exception():
    """Path 3: decide_with_provider where provider raises an exception."""
    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )
    payload = _make_bullish_analysis_payload()

    mock_provider = MagicMock()
    mock_provider.name = "MockFailingProvider"
    mock_provider.should_apply_context.side_effect = RuntimeError("Provider unexpected fault")
    mock_state = MagicMock()

    decision = engine.decide_with_provider(payload, mock_provider, mock_state)

    assert decision["action"] == "HOLD"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["shadow_action"] == "BUY"


def test_path_4_decide_with_context():
    """Path 4: decide_with_context direct call with context report."""
    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )
    payload = _make_bullish_analysis_payload()
    context_report = {
        "action": "BUY",
        "posterior": 0.85,
        "risk_action": "ALLOW",
        "risk_reasons": [],
        "context_snapshot_id": "snap-ctx-001",
    }

    decision = engine.decide_with_context(payload, context_report)

    assert decision["action"] == "HOLD"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["shadow_action"] == "BUY"


def test_path_5_causal_bridge_enhance_signal_with_causal_context():
    """Path 5: Causal bridge from analysis to persisted final decision."""
    payload = _make_bullish_analysis_payload()
    ana = dict(payload)

    decision = enhance_signal_with_causal_context(ana, payload, alpha=0.0)

    assert bool(decision) is True
    assert decision["action"] == "HOLD"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["shadow_action"] == "BUY"


def test_path_6_auto_trader_build_entry_decision():
    """Path 6: AutoTrader reading persisted decision in build_entry_decision."""
    payload = _make_bullish_analysis_payload()
    ana = dict(payload)
    decision = enhance_signal_with_causal_context(ana, payload, alpha=0.0)
    payload["causal_decision"] = decision

    trader = AutoTrader()
    entry_decision = trader.build_entry_decision(payload, "BTC")

    assert entry_decision.eligible is False
    assert entry_decision.sizing is None


def test_path_7_process_signal_does_not_call_broker_or_execution_engine():
    """Path 7: Verifying _process_signal never routes or executes orders to adapter/broker."""
    payload = _make_bullish_analysis_payload()
    ana = dict(payload)
    decision = enhance_signal_with_causal_context(ana, payload, alpha=0.0)
    payload["causal_decision"] = decision

    trader = AutoTrader()

    with patch.object(trader, "_get_execution_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        result = asyncio.run(trader._process_signal("BTC:Binance", payload))

        # Execution engine was never called to submit paper or live orders
        mock_engine.submit_paper.assert_not_called()
        mock_engine.submit_live.assert_not_called()

        # The returned log entry indicates skip with NO_VIABLE_ECONOMIC_CANDIDATE
        assert result is not None
        assert result.get("order_id") is None
        assert result.get("paper_economic_policy") == "NO_TRADE_SHADOW"
        assert result.get("shadow_action") in {"BUY", "HOLD"}


def test_path_8_pipeline_replay_zero_executable_orders_retains_shadow():
    """Path 8: Subprocess / multi-candidate replay shows 0 fills, 0 orders, shadow preserved."""
    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )
    trader = AutoTrader()

    symbols = ["BTC", "ETH", "BNB"]
    orders_executed = 0
    shadow_intents = []

    for sym in symbols:
        payload = _make_bullish_analysis_payload(coin=sym, symbol=f"{sym}USDT")
        decision = engine.decide(payload, persist_final=True)
        payload["causal_decision"] = decision

        assert decision["action"] == "HOLD"
        assert decision["eligible"] is False
        shadow_intents.append(decision["shadow_action"])

        entry_dec = trader.build_entry_decision(payload, sym)
        assert entry_dec.eligible is False

        with patch.object(trader, "_get_execution_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine
            res = asyncio.run(trader._process_signal(f"{sym}:Binance", payload))
            if res and res.get("order_id") is not None:
                orders_executed += 1

    assert orders_executed == 0
    assert shadow_intents == ["BUY", "BUY", "BUY"]


def test_paper_policy_allows_active_trading_when_explicitly_configured(monkeypatch):
    """Verify that when active trading is explicitly requested, eligible candidate is authorized."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")

    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )

    payload = _make_bullish_analysis_payload()
    decision = engine.decide(payload, persist_final=True)

    assert decision["action"] == "BUY"
    assert decision["eligible"] is True
    assert decision["terminal_status"] == "TRADE"
    assert decision["rejection_reason"] is None


def test_paper_policy_defaults_to_no_trade_shadow_when_unset(monkeypatch):
    """Verify FAIL-CLOSED: when PAPER_ECONOMIC_POLICY is completely unset, runtime defaults to NO_TRADE_SHADOW."""
    monkeypatch.delenv("PAPER_ECONOMIC_POLICY", raising=False)
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")

    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )

    payload = _make_bullish_analysis_payload()
    decision = engine.decide(payload, persist_final=True)

    assert decision["paper_economic_policy"] == "NO_TRADE_SHADOW"
    assert decision["action"] == "HOLD"
    assert decision["shadow_action"] == "BUY"
    assert decision["eligible"] is False
    assert decision["terminal_status"] == "HOLD"
    assert decision["economic_rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert decision["rejection_reason"] == "NO_VIABLE_ECONOMIC_CANDIDATE"

    # Also verify AutoTrader._process_signal skips execution when unset
    payload["causal_decision"] = decision
    trader = AutoTrader()
    result = asyncio.run(trader._process_signal("BTC:Binance", payload))
    assert result is not None
    assert result.get("reason_skip") == "NO_VIABLE_ECONOMIC_CANDIDATE"
    assert result.get("paper_economic_policy") == "NO_TRADE_SHADOW"
    assert result.get("shadow_action") == "BUY"


def test_single_boundary_persisted_matches_returned_across_all_branches(monkeypatch):
    """Proves single finalize-and-persist boundary: finalizer called exactly once and persisted fields == returned fields across 6 branches."""
    from btc_scraper.ml_engine.decision_engine import apply_economic_policy_to_final_decision

    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "NO_TRADE_SHADOW")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")

    engine = MetaDecisionEngine(
        weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0},
        buy_threshold=0.50,
        min_ev_pct=0.0,
    )

    persisted_records = []

    def mock_append(decision):
        persisted_records.append(dict(decision))

    with patch("btc_scraper.ml_engine.decision_engine.apply_economic_policy_to_final_decision", wraps=apply_economic_policy_to_final_decision) as mock_finalizer, \
         patch("btc_scraper.ml_engine.runtime_evidence_store.RuntimeEvidenceStore.append_final_decision", side_effect=mock_append):

        # Branch 1: Direct decide(persist_final=True)
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload1 = _make_bullish_analysis_payload()
        ret1 = engine.decide(payload1, persist_final=True)
        assert mock_finalizer.call_count == 1, f"Branch 1 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted1 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason"]:
            assert ret1[key] == persisted1[key], f"Mismatch on {key} in direct decide"

        # Branch 2: decide_with_context
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload2 = _make_bullish_analysis_payload()
        ret2 = engine.decide_with_context(payload2, {"adjusted_score": 0.95, "adjustments": []})
        assert mock_finalizer.call_count == 1, f"Branch 2 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted2 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason"]:
            assert ret2[key] == persisted2[key], f"Mismatch on {key} in decide_with_context"

        # Branch 3: decide_with_provider - apply context (Verified: finalizer called EXACTLY ONCE)
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload3 = _make_bullish_analysis_payload()
        prov_apply = MagicMock()
        prov_apply.name = "MockApplyProvider"
        prov_apply.should_apply_context.return_value = True
        rep_mock = MagicMock()
        rep_mock.to_dict.return_value = {"adjusted_score": 0.88, "adjustments": []}
        prov_apply.generate_context_report.return_value = rep_mock
        ret3 = engine.decide_with_provider(payload3, prov_apply, MagicMock())
        assert mock_finalizer.call_count == 1, f"Branch 3 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted3 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason", "context_provider"]:
            assert ret3[key] == persisted3[key], f"Mismatch on {key} in decide_with_provider apply"

        # Branch 4: decide_with_provider - skip context
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload4 = _make_bullish_analysis_payload()
        prov_skip = MagicMock()
        prov_skip.name = "MockSkipProvider"
        prov_skip.should_apply_context.return_value = False
        ret4 = engine.decide_with_provider(payload4, prov_skip, MagicMock())
        assert mock_finalizer.call_count == 1, f"Branch 4 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted4 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason", "context_provider"]:
            assert ret4[key] == persisted4[key], f"Mismatch on {key} in decide_with_provider skip"

        # Branch 5: decide_with_provider - provider exception
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload5 = _make_bullish_analysis_payload()
        prov_exc = MagicMock()
        prov_exc.name = "MockExcProvider"
        prov_exc.should_apply_context.side_effect = RuntimeError("Provider exploded")
        ret5 = engine.decide_with_provider(payload5, prov_exc, MagicMock())
        assert mock_finalizer.call_count == 1, f"Branch 5 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted5 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason"]:
            assert ret5[key] == persisted5[key], f"Mismatch on {key} in decide_with_provider exception"

        # Branch 6: Causal context bridge
        persisted_records.clear()
        mock_finalizer.reset_mock()
        payload6 = _make_bullish_analysis_payload()
        ret6 = enhance_signal_with_causal_context(payload6, payload6)
        assert mock_finalizer.call_count == 1, f"Branch 6 called finalizer {mock_finalizer.call_count} times, expected 1"
        assert len(persisted_records) == 1
        persisted6 = persisted_records[0]
        for key in ["decision_id", "action", "eligible", "terminal_status", "paper_economic_policy", "shadow_action", "rejection_reason"]:
            assert ret6[key] == persisted6[key], f"Mismatch on {key} in causal bridge"


def test_shadow_fast_path_bypasses_all_expensive_queries_and_evaluators(monkeypatch):
    """Proves genuine shadow fast path: NO_TRADE_SHADOW bypasses DB, VaR, exposures, evaluator, execution engine, and Telegram."""
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "NO_TRADE_SHADOW")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")

    payload = _make_bullish_analysis_payload()
    causal_decision = {
        "decision_id": "dec-fastpath-123",
        "action": "HOLD",
        "shadow_action": "BUY",
        "eligible": False,
        "terminal_status": "HOLD",
        "rejection_reason": "NO_VIABLE_ECONOMIC_CANDIDATE",
        "economic_rejection_reason": "NO_VIABLE_ECONOMIC_CANDIDATE",
        "paper_economic_policy": "NO_TRADE_SHADOW",
        "meta_probability": 0.90,
    }
    payload["causal_decision"] = causal_decision

    trader = AutoTrader()

    with patch("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions") as mock_open_pos, \
         patch("btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit") as mock_var, \
         patch("btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures") as mock_exp, \
         patch("btc_scraper.ml_engine.production_evaluator.evaluate_live_market") as mock_eval, \
         patch.object(trader, "get_last_exit_timestamps") as mock_last_exit, \
         patch.object(trader, "_get_execution_engine") as mock_exec_engine, \
         patch.object(trader, "_notify_trade") as mock_notify, \
         patch("btc_scraper.telegram_bot.api.send_telegram_message") as mock_telegram:

        result = asyncio.run(trader._process_signal("BTC:Binance", payload))

        # Assert ALL expensive calls AND network alerts are completely bypassed
        mock_open_pos.assert_not_called()
        mock_var.assert_not_called()
        mock_exp.assert_not_called()
        mock_eval.assert_not_called()
        mock_last_exit.assert_not_called()
        mock_exec_engine.assert_not_called()
        mock_notify.assert_not_called()
        mock_telegram.assert_not_called()

        # Assert correct skip disposition returned
        assert result is not None
        assert result["status"] == "skipped"
        assert result["reason_skip"] == "NO_VIABLE_ECONOMIC_CANDIDATE"
        assert result["paper_economic_policy"] == "NO_TRADE_SHADOW"
        assert result["shadow_action"] == "BUY"
        assert result["decision_id"] == "dec-fastpath-123"


def test_notify_trade_suppressed_for_routine_shadow_skips():
    """Verify that AutoTrader._notify_trade suppresses Telegram alerts for routine paper shadow skips."""
    trader = AutoTrader()
    skip_entry = {
        "status": "skipped",
        "reason_skip": "NO_VIABLE_ECONOMIC_CANDIDATE",
        "paper_economic_policy": "NO_TRADE_SHADOW",
        "coin": "BTC",
        "direction": "BUY",
        "signal": "BUY",
    }
    with patch("btc_scraper.telegram_bot.api.send_telegram_message") as mock_tg:
        trader._notify_trade(skip_entry)
        mock_tg.assert_not_called()

