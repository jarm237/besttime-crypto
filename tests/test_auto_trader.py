import pytest
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from btc_scraper.trading.auto_trader import AutoTrader, _load_circuit, _save_circuit, CIRCUIT_BREAKER_STATE
from btc_scraper.ml_engine.signal_score import score_signal, _primary_signal_action


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _readiness_history(count: int = 73) -> list[dict]:
    return [
        {
            "time": (NOW - timedelta(minutes=15 * (count - 1 - index))).isoformat(),
            "open": 100.0 + index * 0.01,
            "high": 100.1 + index * 0.01,
            "low": 99.9 + index * 0.01,
            "close": 100.0 + index * 0.01,
            "volume": 1_000.0,
        }
        for index in range(count)
    ]


def _healthy_risk_metrics():
    return {
        "status": "HEALTHY",
        "failure_reason": None,
        "risk_multiplier": 1.0,
        "blocked": False,
        "drawdown_pct": 0.0,
    }


def _unavailable_risk_metrics():
    return {
        "status": "UNAVAILABLE",
        "failure_reason": "risk_database_unavailable:ServerSelectionTimeoutError",
        "risk_multiplier": 0.0,
        "blocked": True,
        "drawdown_pct": None,
    }


def test_should_trade(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.85")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_COINS", "")
    monkeypatch.setattr(AutoTrader, "_has_open_position", lambda *args, **kwargs: False)
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])

    trader = AutoTrader()
    
    # Test wrong coin
    ok, reason = trader.should_trade("INVALID_COIN", "BUY", 0.9, 80)
    assert not ok
    assert reason == "coin_not_allowed"
    
    # Test weak signal
    ok, reason = trader.should_trade("BTC", "WEAK BUY", 0.9, 80)
    assert not ok
    assert reason == "weak_signal"

    # Test confidence threshold
    ok, reason = trader.should_trade("BTC", "BUY", 0.5, 80)
    assert not ok
    assert reason == "insufficient_statistical_edge"

    # Test strength threshold
    ok, reason = trader.should_trade("BTC", "BUY", 0.9, 60)
    assert not ok
    assert reason == "insufficient_statistical_edge"

    # Test OK BUY signal
    ok, reason = trader.should_trade("BTC", "BUY", 0.86, 76)
    assert ok
    assert reason == "OK"

    # Strong SELL has a low raw directional score but high side-agnostic strength.
    ok, reason = trader.should_trade(
        "BTC",
        "STRONG SELL (Confirmed Reversal)",
        0.86,
        10,
        sig_score_obj={"action": "SELL", "score": 10, "strength": 90},
    )
    assert ok
    assert reason == "OK"

    # Weak SELL normalizes to strength 55 and must fail the same threshold.
    ok, reason = trader.should_trade(
        "BTC",
        "WEAK SELL (Crossover)",
        0.86,
        45,
        sig_score_obj={"action": "SELL", "score": 45, "strength": 55},
    )
    assert not ok
    assert reason == "weak_signal"

    # Upstream gates can neutralize action even if the raw signal text still says BUY.
    ok, reason = trader.should_trade(
        "BTC",
        "STRONG BUY (Confirmed Reversal)",
        0.95,
        90,
        sig_score_obj={"action": "NEUTRAL", "score": 90, "strength": 0, "causal_overridden": True},
    )
    assert not ok
    assert reason == "action_disagreement"

def test_evaluate_and_trade_empty_analysis_does_not_require_client():
    import asyncio

    trader = AutoTrader()
    result = asyncio.run(trader.evaluate_and_trade({}))

    assert result == []
    assert not hasattr(trader, "_client")


def test_notify_trade_includes_kelly_fraction(monkeypatch):
    sent = []

    def fake_send(message, parse_mode=None):
        sent.append(message)
        return 123

    monkeypatch.setattr("btc_scraper.telegram_bot.send_telegram_message", fake_send)
    trader = AutoTrader()

    trader._notify_trade({
        "mode": "DRY_RUN",
        "coin": "BTC",
        "direction": "LONG",
        "signal": "BUY (Crossover)",
        "meta_confidence_pct": 68,
        "signal_score": 72,
        "kelly_fraction": 0.1234,
        "usdt_amount": 25.0,
        "entry_price": 100.0,
        "sl_price": 98.0,
        "tp1_price": 104.0,
        "order_id": "paper-1",
        "status": "FILLED",
    })

    assert sent
    assert "Kelly: 12.3%" in sent[0]


def test_process_signal_blocks_zero_signal_kelly(monkeypatch):
    import asyncio

    logged = []

    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.10")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "70")
    monkeypatch.setenv("AUTO_TRADE_COINS", "ZEC")
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    monkeypatch.setattr("btc_scraper.trading.auto_trader._append_log", lambda entry: logged.append(entry))

    trader = AutoTrader()
    result = asyncio.run(trader._process_signal("ZEC:Binance", {
        "signal": "STRONG SELL (Confirmed Reversal)",
        "close": 558.38,
        "tp_sl": {"entry": 558.38, "sl": 566.759, "tp1": 545.3445, "rr1": 1.55},
        "history": _readiness_history(),
        "signal_score": {
            "score": 21,
            "strength": 79,
            "action": "SELL",
            "meta_confidence": 0.47,
            "kelly_fraction": 0.0,
            "b_estimate": 1.55,
            "position_size": 1.0,
        },
    }))

    assert result["status"] == "skipped"
    assert result["reason_skip"] == "Kelly Fraction <= 0 (signal_score)"
    assert result["kelly_fraction"] == 0.0
    assert logged == [result]
    assert trader._execution_engine is None


def test_compute_position_size(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_KELLY_FRACTION", "0.5")
    trader = AutoTrader()
    
    # Default parameters: account_usdt = 500, risk_pct = 2.0% (10 USDT risk)
    # entry_price = 100.0, sl_price = 98.0 (2% distance)
    # position_usdt = 10 / 0.02 = 500 USDT, capped by max_trade_usdt (100 USDT)
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0)
    assert not size.rejected
    assert size.final_notional == 100.0
    
    # Entry = 100.0, sl_price = 90.0 (10% distance)
    # position_usdt = 10 / 0.10 = 100 USDT
    size = trader.compute_position_size(100.0, 90.0, current_balance=500.0)
    assert not size.rejected
    assert size.final_notional == 100.0

    # Entry = 100.0, sl_price = 50.0 (50% distance)
    # position_usdt = 10 / 0.50 = 20 USDT
    size = trader.compute_position_size(100.0, 50.0, current_balance=500.0)
    assert not size.rejected
    assert size.final_notional == 20.0

    # Test minimum order size cap
    # Entry = 100.0, sl_price = 1.0 (99% distance) -> size = 10 / 0.99 = 10.1 USDT
    size = trader.compute_position_size(100.0, 1.0, current_balance=500.0)
    assert not size.rejected
    assert size.final_notional >= 10.0

    # Test with multiplier (e.g. Kelly fraction 0.5)
    # entry_price = 100.0, sl_price = 98.0 (2% distance)
    # risk = 500 * (2% * 0.5) = 5 USDT
    # position_usdt = 5 / 0.02 = 250 USDT, capped by max_trade_usdt (100 USDT)
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, multiplier=0.5)
    assert not size.rejected
    assert size.final_notional == 100.0

    # Entry = 100.0, sl_price = 50.0 (50% distance)
    # multiplier = 0.5 -> risk = 5 USDT
    # size = 5 / 0.5 = 10 USDT (min cap)
    size = trader.compute_position_size(100.0, 50.0, current_balance=500.0, multiplier=0.5)
    assert not size.rejected
    assert size.final_notional == 10.0

    # Test Kelly logic
    # win_prob = 0.6, rr_ratio = 1.5 -> f* = 0.6 - 0.4/1.5 = 0.6 - 0.2667 = 0.3333
    # kelly_fraction = 0.5 -> kelly_risk_pct = 0.3333 * 0.5 * 100 = 16.66%
    # But max risk is adjusted_risk_pct (default 2% * multiplier 1.0 = 2.0%)
    # So risk_usdt = 500 * 2.0% = 10 USDT
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.6, rr_ratio=1.5)
    assert not size.rejected
    assert size.final_notional == 100.0  # (10 USDT / 0.02) = 500 capped to 100
    
    # Test Negative Kelly (win_prob = 0.4, rr_ratio = 1.0 -> f* = 0.4 - 0.6/1.0 = -0.2 <= 0)
    # size should be 0.0
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.4, rr_ratio=1.0)
    assert size.rejected
    assert size.final_notional == 0.0

    # Test Low Kelly bounded by risk_pct
    # win_prob = 0.51, rr_ratio = 1.0 -> f* = 0.51 - 0.49/1.0 = 0.02
    # kelly_fraction = 0.5 -> kelly_risk_pct = 0.01 * 100 = 1.0%
    # adjusted_risk_pct becomes 1.0%
    # risk_usdt = 500 * 1.0% = 5 USDT
    # position_usdt = 5 / 0.02 = 250 capped to 100 USDT
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.51, rr_ratio=1.0)
    assert not size.rejected
    assert size.final_notional == 100.0


def test_signal_score_parses_primary_action(monkeypatch):
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score._get_cached_risk_metrics",
        _healthy_risk_metrics,
    )
    raw_signal = "SELL (Break-SMA50) [BUY 52% LOW] | Meta: 60%"
    assert _primary_signal_action(raw_signal) == "SELL"
    res = score_signal(raw_signal, {"close": 1574.19}, {"disable_ml": True})
    assert res["action"] == "SELL"
    assert res["display_label"] == "SELL 70%"
    assert res["strength"] == res["display_score"]


def test_signal_score_fails_closed_when_risk_unavailable(monkeypatch):
    monkeypatch.setattr(
        "btc_scraper.ml_engine.signal_score._get_cached_risk_metrics",
        _unavailable_risk_metrics,
    )

    res = score_signal("BUY", {"close": 100.0}, {"disable_ml": True})

    assert res["risk_status"] == "UNAVAILABLE"
    assert res["risk_blocked"] is True
    assert res["risk_multiplier"] == 0.0
    assert res["action"] == "NEUTRAL"
    assert res["position_size"] == 0.0


def test_adaptive_model_blends_with_rule_score(monkeypatch):
    from btc_scraper.ml_engine import signal_score as score_mod

    monkeypatch.setattr(score_mod, "_load_adaptive_model", lambda: {"model": object(), "features": ["is_buy", "is_sell"]})
    monkeypatch.setattr(score_mod, "_use_kelly", lambda: False)
    monkeypatch.setattr(score_mod, "_append_meta_prob_entry", lambda entry: None)
    monkeypatch.setattr(
        score_mod,
        "_get_cached_risk_metrics",
        lambda: {"risk_multiplier": 1.0, "blocked": False},
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.meta_model.model_predict_proba",
        lambda model, rows, feature_names: [[0.48, 0.52]],
    )

    buy = score_mod.score_signal("BUY", {"close": 100.0}, {})
    sell = score_mod.score_signal("SELL", {"close": 100.0}, {})

    assert buy["score"] > 60
    assert buy["score"] != 52
    assert sell["score"] < 40
    assert sell["score"] != 48


def test_circuit_breaker(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_CIRCUIT_BREAKER_N", "5")
    trader = AutoTrader()
    
    # Backup original circuit state if any
    original_state = None
    if CIRCUIT_BREAKER_STATE.exists():
        with open(CIRCUIT_BREAKER_STATE, "r") as f:
            original_state = json.load(f)
            
    try:
        # Reset circuit state
        _save_circuit({"consecutive_losses": 0, "tripped_at": None, "total_trades_today": 0, "date": ""})
        
        # Test record trade result
        trader._record_trade_result("OPEN")
        state = _load_circuit()
        assert state["total_trades_today"] == 1
        assert state["consecutive_losses"] == 0
        
        trader._record_trade_result("LOSS")
        state = _load_circuit()
        assert state["total_trades_today"] == 1  # unchanged because result is not OPEN
        assert state["consecutive_losses"] == 1
        
        trader._record_trade_result("WIN")
        state = _load_circuit()
        assert state["total_trades_today"] == 1
        assert state["consecutive_losses"] == 0
        
        # Test trip consecutive losses
        for _ in range(5):
            trader._record_trade_result("LOSS")
        state = _load_circuit()
        assert state["consecutive_losses"] == 5
        assert state["tripped_at"] is not None
        
        # Check that circuit checker blocks
        ok, reason = trader._check_circuit_breaker()
        assert not ok
        assert "Circuit breaker" in reason
        
    finally:
        # Restore original state
        if original_state is not None:
            _save_circuit(original_state)
        elif CIRCUIT_BREAKER_STATE.exists():
            os.remove(CIRCUIT_BREAKER_STATE)


def test_dynamic_position_sizing():
    from btc_scraper.ml_engine.signal_score import _load_position_sizing_params, score_signal
    import btc_scraper.ml_engine.signal_score as score_mod
    from unittest.mock import patch

    with patch.object(score_mod, "_get_cached_risk_metrics", _healthy_risk_metrics):
    
        # 1. Test loading params
        params = _load_position_sizing_params()
        assert "method" in params
        assert "target_std_dev_pct" in params
        assert "target_atr_pct" in params
        assert "min_vol_mult" in params
        assert "max_vol_mult" in params

        # 2. Test score_signal with std_dev method and Bollinger Bands
        # bb_upper = 104, bb_lower = 96, close = 100 -> bb_width_pct = 8.0%, std_dev_pct = 2.0%
        # If target_std_dev_pct = 2.0%, vol_mult should be 1.0
        data = {
            "strategy": "DUMMY_STRATEGY",
            "close": 100.0,
            "bb_upper": 104.0,
            "bb_lower": 96.0,
            "atr": 2.0
        }
        context = {
            "regime": "RANGING"
        }
    
        # Force std_dev method using environment variable
        os.environ["AUTO_TRADE_POSITION_SIZING_METHOD"] = "std_dev"
        res = score_signal("BUY", data, context)
        assert res["position_sizing_method"] == "std_dev"
        assert res["std_dev_pct"] == 2.0
        assert abs(res["volatility_multiplier"] - 1.0) < 1e-4

        # Now make it highly volatile: bb_upper = 108, bb_lower = 92 -> bb_width_pct = 16%, std_dev_pct = 4.0%
        # With target_std_dev_pct = 2.0, vol_mult = 2.0 / 4.0 = 0.5
        data_high_vol = {
            "strategy": "DUMMY_STRATEGY",
            "close": 100.0,
            "bb_upper": 108.0,
            "bb_lower": 92.0,
            "atr": 4.0
        }
        res_high_vol = score_signal("BUY", data_high_vol, context)
        assert res_high_vol["std_dev_pct"] == 4.0
        assert abs(res_high_vol["volatility_multiplier"] - 0.5) < 1e-4
        # Size should be scaled down compared to normal vol
        assert res_high_vol["position_size"] < res["position_size"]

        # 3. Test fallback to ATR
        data_no_bb = {
            "strategy": "DUMMY_STRATEGY",
            "close": 100.0,
            "atr": 4.0 # atr_pct = 4.0%
        }
        # With target_atr_pct = 1.0, vol_mult = 1.0 / 4.0 = 0.25
        res_atr = score_signal("BUY", data_no_bb, context)
        assert res_atr["std_dev_pct"] == 4.0
        assert abs(res_atr["volatility_multiplier"] - 0.25) < 1e-4

    # Clean up env
    if "AUTO_TRADE_POSITION_SIZING_METHOD" in os.environ:
        del os.environ["AUTO_TRADE_POSITION_SIZING_METHOD"]


def test_dca_evaluation():
    from btc_scraper.trading.position_tracker import _evaluate_dca_opportunity
    
    # Setup test pos_list
    pos_list = [
        {
            "coin": "BTC",
            "direction": "LONG",
            "entry_price": 60000.0,
            "invested_usdt": 100.0,
            "status": "open"
        }
    ]
    
    # Test case 1: Price is too close (no DCA)
    # entry = 60000, current = 59500 (distance = 0.83% < 1.5%)
    ana = {"atr": 100.0, "support": 58000.0}
    res = _evaluate_dca_opportunity(pos_list, ana, 59500.0, 0.75)
    assert res is None

    # Test case 2: Low simulated win probability (no DCA)
    # distance = 3% >= 1.5%, but meta_prob = 0.5 < 0.65
    res = _evaluate_dca_opportunity(pos_list, ana, 58200.0, 0.5)
    assert res is None

    # Test case 3: Price is far from support level (no DCA)
    # price = 58200, support = 55000 (distance is > 1.01% from support boundary)
    ana_far_support = {"atr": 500.0, "support": 55000.0}
    res = _evaluate_dca_opportunity(pos_list, ana_far_support, 58000.0, 0.8)
    assert res is None

    # Test case 4: Valid DCA (Distance >= 1.5%, meta_prob >= 0.65, S/R zone matched within 1%)
    # entry = 60000, current = 58200 (diff = 3.0%), support = 58000 (diff = 0.3% which is < 1% zone)
    # sim_meta = 0.72
    res = _evaluate_dca_opportunity(pos_list, ana, 58200.0, 0.72)
    assert res is not None
    assert res["suggested_dca_size"] == 100.0
    # expected new avg entry: (100 * 60000 + 100 * 58200) / 200 = 59100.0
    assert res["new_avg_entry"] == 59100.0
    assert res["sim_meta_prob"] == 0.72

    # Test case 5: DCA Level cap exceeded (max 2 DCAs -> pos_list has 3 items)
    pos_list_3 = [
        {"coin": "BTC", "direction": "LONG", "entry_price": 60000.0, "invested_usdt": 100.0, "status": "open"},
        {"coin": "BTC", "direction": "LONG", "entry_price": 58000.0, "invested_usdt": 100.0, "status": "open"},
        {"coin": "BTC", "direction": "LONG", "entry_price": 57000.0, "invested_usdt": 100.0, "status": "open"},
    ]
    res = _evaluate_dca_opportunity(pos_list_3, ana, 55000.0, 0.8)
    assert res is None

    # Test case 6: RL action constraints (only action 5 is allowed, others are blocked)
    res_rl_trail = _evaluate_dca_opportunity(pos_list, ana, 58200.0, 0.72, rl_action=5)
    assert res_rl_trail is not None

    for act in [0, 1, 2, 3, 4]:
        res_rl_blocked = _evaluate_dca_opportunity(pos_list, ana, 58200.0, 0.72, rl_action=act)
        assert res_rl_blocked is None


def test_trailing_sl_activation_flow(monkeypatch):
    import btc_scraper.trading.position_tracker as pt

    monkeypatch.setenv("RL_EXIT_MODE", "active")
    monkeypatch.setenv("RL_EXIT_ALLOW_LIVE_ACTION", "true")
    
    # 1. Mock get_open_positions
    mock_positions = [
        {
            "coin": "BTC",
            "id": "test-pos-id-1",
            "direction": "LONG",
            "entry_price": 60000.0,
            "invested_usdt": 100.0,
            "entry_time": "2026-06-28 10:00",
            "status": "open",
            "trailing_sl": None,
            "trailing_sl_active": False,
        }
    ]
    monkeypatch.setattr(pt, "get_open_positions", lambda: mock_positions)
    
    # 2. Mock positions_col
    class DummyCol:
        def update_one(self, filter, update):
            for p in mock_positions:
                if p["id"] == filter.get("id"):
                    p.update(update["$set"])
        def update_many(self, filter, update):
            for p in mock_positions:
                if p["coin"] == filter.get("coin"):
                    p.update(update["$set"])
                    
    monkeypatch.setattr(pt, "positions_col", DummyCol())
    
    # 3. Mock RL exit model behavior
    context = {"rl_action": 0}  # Start with HOLD
    class DummyModel:
        def predict(self, obs, *args, **kwargs):
            return context["rl_action"], None
            
    monkeypatch.setattr(pt, "get_ppo_model", lambda: DummyModel())
    
    # 4. Dummy analysis results
    analysis_results = {
        "BTC:Binance": {
            "close": 61000.0,
            "atr": 1000.0,
            "support": 59000.0,
            "resistance": 62000.0,
            "bb_upper": 63000.0,
            "bb_middle": 61000.0,
            "bb_lower": 59000.0,
            "signal": "BUY"
        }
    }
    
    # Step A: Run with rl_action = 0 (HOLD).
    # Since trailing_sl_active is False and action is 0, trailing_sl should NOT activate.
    context["rl_action"] = 0
    pt.evaluate_positions(analysis_results)
    assert not mock_positions[0]["trailing_sl_active"]
    assert mock_positions[0]["trailing_sl"] is None
    
    # Step B: Run with rl_action = 5 (TRAILING_SL_ATR).
    # This should activate trailing_sl and set its value.
    context["rl_action"] = 5
    pt.evaluate_positions(analysis_results)
    assert mock_positions[0]["trailing_sl_active"]
    assert mock_positions[0]["trailing_sl"] is not None
    
    first_activated_sl = mock_positions[0]["trailing_sl"]
    
    # Step C: Run with rl_action = 0 (HOLD) but trailing_sl_active is now True.
    # It should continue to update trailing SL.
    context["rl_action"] = 0
    pt.evaluate_positions(analysis_results)
    assert mock_positions[0]["trailing_sl_active"]
    assert mock_positions[0]["trailing_sl"] >= first_activated_sl


def test_confidence_gate_and_shadow_mode(monkeypatch):
    import btc_scraper.trading.position_tracker as pt

    monkeypatch.setenv("RL_EXIT_MODE", "active")
    monkeypatch.setenv("RL_EXIT_ALLOW_LIVE_ACTION", "true")
    
    # 1. Setup mock database records
    mock_positions = [{
        "id": "test_pos_confidence",
        "coin": "BTC",
        "entry_price": 60000.0,
        "direction": "LONG",
        "invested_usdt": 100.0,
        "entry_time": "2026-01-01 00:00",
        "status": "open",
        "trailing_sl": None,
        "trailing_sl_active": False,
        "note": "[AUTO-TEST]"
    }]
    
    class DummyCol:
        def find(self, *args, **kwargs):
            return mock_positions
        def find_one(self, *args, **kwargs):
            return mock_positions[0]
        def update_one(self, filter_q, update_q):
            set_dict = update_q.get("$set", {})
            for k, v in set_dict.items():
                mock_positions[0][k] = v
        def update_many(self, filter_q, update_q):
            set_dict = update_q.get("$set", {})
            for k, v in set_dict.items():
                mock_positions[0][k] = v

    monkeypatch.setattr(pt, "positions_col", DummyCol())
    
    # 2. Mock PPO model predicting EXIT (4)
    class DummyExitModel:
        def predict(self, obs, *args, **kwargs):
            return 4, None  # RL action 4 = EXIT
            
    monkeypatch.setattr(pt, "get_ppo_model", lambda: DummyExitModel())

    # 3. Mock CorrelationEngine
    class DummyCorrEngine:
        def get_correlation(self, a, b):
            return 0.5
    monkeypatch.setattr("btc_scraper.analysis.correlation.correlation_engine", DummyCorrEngine())

    # 4. Dummy analysis results
    analysis_results = {
        "BTC:Binance": {
            "close": 60100.0,
            "atr": 1000.0,
            "support": 59000.0,
            "resistance": 62000.0,
            "bb_upper": 63000.0,
            "bb_middle": 61000.0,
            "bb_lower": 59000.0,
            "signal": "BUY"
        }
    }

    # Case A: Meta Model confidence is high (0.75).
    # Confidence Gate should override EXIT (4) to HOLD (0).
    monkeypatch.setattr(
        "btc_scraper.ml_engine.meta_model.predict_meta_confidence",
        lambda *args, **kwargs: {"probability": 0.75}
    )
    monkeypatch.setenv("RL_EXIT_SHADOW_MODE", "false")
    recs = pt.evaluate_positions(analysis_results)
    # Overridden to HOLD, so recommendation should be hold
    assert len(recs) == 1
    assert "GIU LENH" in recs[0]["recommendation"]

    # Case B: Meta Model confidence is low (0.30).
    # Confidence Gate should NOT override, so recommendation should be EXIT ([RL] DONG VI THE).
    monkeypatch.setattr(
        "btc_scraper.ml_engine.meta_model.predict_meta_confidence",
        lambda *args, **kwargs: {"probability": 0.30}
    )
    recs = pt.evaluate_positions(analysis_results)
    assert len(recs) == 1
    assert "[RL] DONG VI THE" in recs[0]["recommendation"]

    # Case C: Shadow mode is enabled and blocks live RL action.
    # Recommendation falls back to HOLD while still logging shadow prediction.
    monkeypatch.setenv("RL_EXIT_MODE", "shadow")
    monkeypatch.setenv("RL_EXIT_SHADOW_MODE", "true")
    recs = pt.evaluate_positions(analysis_results)
    assert len(recs) == 1
    assert "[SHADOW-RL] DONG VI THE" not in recs[0]["recommendation"]
    assert "GIU LENH" in recs[0]["recommendation"]


def test_rl_exit_shadow_logging(monkeypatch):
    import btc_scraper.trading.position_tracker as pt
    import scripts.shadow_log as sl

    mock_positions = [{
        "id": "test_pos_shadow",
        "coin": "BTC",
        "entry_price": 60000.0,
        "direction": "LONG",
        "invested_usdt": 100.0,
        "entry_time": "2026-01-01 00:00",
        "status": "open",
        "trailing_sl": None,
        "trailing_sl_active": False,
        "note": "[AUTO-TEST]"
    }]

    class DummyCol:
        def find(self, *args, **kwargs):
            return mock_positions
        def find_one(self, *args, **kwargs):
            return mock_positions[0]
        def update_one(self, filter_q, update_q):
            set_dict = update_q.get("$set", {})
            for k, v in set_dict.items():
                mock_positions[0][k] = v
        def update_many(self, filter_q, update_q):
            set_dict = update_q.get("$set", {})
            for k, v in set_dict.items():
                mock_positions[0][k] = v

    monkeypatch.setattr(pt, "positions_col", DummyCol())

    class DummyExitModel:
        def predict(self, obs, *args, **kwargs):
            return 4, None

    monkeypatch.setattr(pt, "get_ppo_model", lambda: DummyExitModel())

    class DummyCorrEngine:
        def get_correlation(self, a, b):
            return 0.5
    monkeypatch.setattr("btc_scraper.analysis.correlation.correlation_engine", DummyCorrEngine())

    called = []
    def fake_rl_log(symbol, rl_action, meta_prob, position_id=None, note=None):
        called.append((symbol, rl_action, meta_prob, position_id, note))
        return "rl_shadow_id"

    monkeypatch.setattr(sl, "log_rl_shadow_prediction", fake_rl_log)

    monkeypatch.setattr(
        "btc_scraper.ml_engine.meta_model.predict_meta_confidence",
        lambda *args, **kwargs: {"probability": 0.30}
    )
    monkeypatch.setenv("RL_EXIT_SHADOW_MODE", "true")

    analysis_results = {
        "BTC:Binance": {
            "close": 60100.0,
            "atr": 1000.0,
            "support": 59000.0,
            "resistance": 62000.0,
            "bb_upper": 63000.0,
            "bb_middle": 61000.0,
            "bb_lower": 59000.0,
            "signal": "BUY"
        }
    }

    recs = pt.evaluate_positions(analysis_results)
    assert len(recs) == 1
    assert called, "RL exit shadow log should be emitted"
    assert called[0][0] == "BTCUSDT"
    assert called[0][1] == 4
    assert called[0][2] == 0.30
    assert called[0][3] == "test_pos_shadow"
    assert called[0][4] == "RL Exit shadow recommendation"


# ─── PR 2 build_entry_decision E2E Tests ─────────────────────────────────────

from btc_scraper.trading.decision_types import (
    EntryRejectionReason,
    DecisionStage,
    TradeAction,
    FinalDecisionStatus,
)

def test_build_entry_decision_whitelist(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH")
    trader = AutoTrader()
    
    # Not in whitelist
    dec = trader.build_entry_decision({"signal": "STRONG BUY", "signal_score": {"score": 90, "action": "BUY"}}, "SOL")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.COIN_NOT_ALLOWED
    assert dec.breakdown.decision_stage == DecisionStage.NORMALIZATION


def test_build_entry_decision_direction_encoding_inconsistent(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    trader = AutoTrader()
    
    # raw_score 10 -> should be SELL, but upstream action claims BUY -> inconsistent
    analysis = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 10,
            "action": "BUY",
        }
    }
    dec = trader.build_entry_decision(analysis, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.DIRECTION_ENCODING_INCONSISTENT
    assert dec.breakdown.decision_stage == DecisionStage.NORMALIZATION


def test_build_entry_decision_low_meta_confidence(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.85")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    trader = AutoTrader()
    
    # 1. STRONG BUY, strength >= threshold, but meta_probability < threshold -> insufficient edge
    analysis = {
        "signal": "STRONG BUY (Confirmed Reversal)",
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.80, # below 0.85
        }
    }
    dec = trader.build_entry_decision(analysis, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE
    assert dec.breakdown.decision_stage == DecisionStage.ELIGIBILITY
    assert dec.breakdown.meta_probability == 0.80


def test_build_entry_decision_action_disagreement(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    trader = AutoTrader()
    
    # Action NEUTRAL despite raw text claiming STRONG BUY
    analysis = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 90,
            "action": "NEUTRAL",
        }
    }
    dec = trader.build_entry_decision(analysis, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.ACTION_DISAGREEMENT


def test_build_entry_decision_kelly_and_rr_gates(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.50")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.5")
    monkeypatch.setenv("AUTO_TRADE_USE_KELLY", "true")
    trader = AutoTrader()

    # Case A: Kelly fraction <= 0 -> rejected
    analysis_bad_kelly = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.80,
            "kelly_fraction": 0.0,
        },
        "tp_sl": {"rr1": 2.0}
    }
    dec = trader.build_entry_decision(analysis_bad_kelly, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY
    assert dec.breakdown.decision_stage == DecisionStage.ELIGIBILITY

    # Case B: RR below minimum -> rejected
    analysis_low_rr = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.80,
            "kelly_fraction": 0.1,
        },
        "tp_sl": {"rr1": 1.2} # below 1.5 min_rr
    }
    dec = trader.build_entry_decision(analysis_low_rr, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.RR_BELOW_MINIMUM


def test_build_entry_decision_net_ev_gate(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    # Low thresholds to pass eligibility stage
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.40")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "0.5")
    # Cost settings
    monkeypatch.setenv("AUTO_TRADE_ESTIMATED_FEE_RATIO", "0.01") # 1% fees
    monkeypatch.setenv("AUTO_TRADE_ESTIMATED_SLIPPAGE_RATIO", "0.01") # 1% slippage
    # Net EV target
    monkeypatch.setenv("AUTO_TRADE_MIN_EXPECTED_EDGE", "0.0")

    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *args, **kwargs: False)
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])

    # p_win = 0.50, rr = 1.0 -> gross_ev = 0.5 * 1.0 - 0.5 = 0.0
    # net_ev = 0.0 - 0.02 = -0.02 <= 0.0 -> insufficient statistical edge at stage EDGE
    analysis = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.50,
            "kelly_fraction": 0.2,
        },
        "tp_sl": {"rr1": 1.0}
    }
    dec = trader.build_entry_decision(analysis, "BTC")
    assert not dec.eligible
    assert dec.rejection_reason == EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE
    assert dec.breakdown.decision_stage == DecisionStage.EDGE
    assert dec.breakdown.gross_expected_value == 0.0
    assert dec.breakdown.net_expected_value == -0.02


def test_should_trade_compatibility_wrapper(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *args, **kwargs: False)
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])

    # Legacy call with individual arguments raises DeprecationWarning
    with pytest.deprecated_call():
        eligible, reason = trader.should_trade(
            coin="BTC",
            signal="STRONG BUY",
            meta_confidence=0.85,
            signal_score=90,
            sig_score_obj={"action": "BUY"},
        )
    assert eligible
    assert reason == "OK"

    # Call with analysis kwarg does NOT raise warning
    analysis = {
        "signal": "STRONG BUY",
        "signal_score": {
            "score": 90,
            "strength": 90,
            "action": "BUY",
            "meta_probability": 0.85,
        },
        "tp_sl": {"rr1": 2.0}
    }
    # Should not raise warning
    eligible, reason = trader.should_trade("BTC", analysis=analysis)
    assert eligible
    assert reason == "OK"


def test_process_signal_emits_decision_breakdown_logs(monkeypatch):
    import asyncio
    logged = []
    monkeypatch.setattr("btc_scraper.trading.auto_trader._append_log", lambda entry: logged.append(entry))
    monkeypatch.setattr("btc_scraper.trading.auto_trader.exposure_manager.get_open_positions", lambda: [])
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.calculate_max_size_by_var_limit",
        lambda *args, **kwargs: 100.0,
    )
    monkeypatch.setattr(
        "btc_scraper.trading.auto_trader.exposure_manager.get_portfolio_exposures",
        lambda balance: (0.0, {}, {}),
    )

    # Whitelist BTC
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC")
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.80")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_MIN_RR", "1.0")
    monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
    
    trader = AutoTrader()
    monkeypatch.setattr(trader, "_has_open_position", lambda *args, **kwargs: False)

    # 1. Skipped log case (low RR -> rejected at eligibility stage, but logs a skip entry)
    analysis_skipped = {
        "signal": "STRONG BUY",
        "history": _readiness_history(),
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.85,
        },
        "tp_sl": {"rr1": 0.5} # below 1.0 min_rr -> should reject and log skip
    }

    result = asyncio.run(trader._process_signal("BTC:Binance", analysis_skipped))
    assert result is not None
    assert result["status"] == "skipped"
    assert "decision_breakdown" in result
    bd = result["decision_breakdown"]
    assert bd["decision_stage"] == "eligibility"
    assert bd["technical_score"] == 90
    assert bd["meta_probability"] == 0.85
    assert bd["rr_ratio"] == 0.5
    assert bd["rejection_reason"] == "rr_below_minimum"

    # 2. Eligible and placed order case (simulated paper fill)
    analysis_placed = {
        "signal": "STRONG BUY",
        "close": 100.0,
        "history": _readiness_history(),
        "signal_score": {
            "score": 90,
            "action": "BUY",
            "meta_probability": 0.85,
            "position_size": 1.0,
        },
        "tp_sl": {"entry": 100.0, "sl": 95.0, "tp1": 110.0, "rr1": 2.0}
    }
    
    # Mock submit_paper
    class DummyRecord:
        def __init__(self):
            self.execution_id = "test-exec-123"
            self.status = "FILLED"
            self.avg_fill_price = 100.0
            self.guard_action = "ALLOW"
            self.expected_slippage_bps = 5.0
            self.liquidity_score = 10.0

    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
    # mock _get_execution_engine().submit_paper
    class DummyEngine:
        def submit_paper(self, *args, **kwargs):
            return DummyRecord()
    monkeypatch.setattr(trader, "_get_execution_engine", lambda: DummyEngine())

    result_placed = asyncio.run(trader._process_signal("BTC:Binance", analysis_placed))
    assert result_placed is not None
    assert "decision_breakdown" in result_placed
    bd_placed = result_placed["decision_breakdown"]
    assert bd_placed["decision_stage"] == "eligibility"
    assert bd_placed["rejection_reason"] is None
    assert result_placed["final_status"] == "eligible"
    assert result_placed["decision_id"] is not None
