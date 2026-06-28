import pytest
import os
import json
from pathlib import Path
from btc_scraper.trading.auto_trader import AutoTrader, _load_circuit, _save_circuit, CIRCUIT_BREAKER_STATE

def test_should_trade(monkeypatch):
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.85")
    monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "75")
    monkeypatch.setenv("AUTO_TRADE_COINS", "")

    trader = AutoTrader()
    
    # Test wrong coin
    ok, reason = trader.should_trade("INVALID_COIN", "BUY", 0.9, 80)
    assert not ok
    assert "khong trong allowed_coins" in reason
    
    # Test weak signal
    ok, reason = trader.should_trade("BTC", "WEAK BUY", 0.9, 80)
    assert not ok
    assert "WEAK" in reason

    # Test confidence threshold
    ok, reason = trader.should_trade("BTC", "BUY", 0.5, 80)
    assert not ok
    assert "Meta confidence" in reason

    # Test score threshold
    ok, reason = trader.should_trade("BTC", "BUY", 0.9, 60)
    assert not ok
    assert "Score" in reason

    # Test OK signal
    ok, reason = trader.should_trade("BTC", "BUY", 0.86, 76)
    assert ok
    assert reason == "OK"

def test_compute_position_size():
    trader = AutoTrader()
    
    # Default parameters: account_usdt = 500, risk_pct = 2.0% (10 USDT risk)
    # entry_price = 100.0, sl_price = 98.0 (2% distance)
    # position_usdt = 10 / 0.02 = 500 USDT, capped by max_trade_usdt (100 USDT)
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0)
    assert size == 100.0
    
    # Entry = 100.0, sl_price = 90.0 (10% distance)
    # position_usdt = 10 / 0.10 = 100 USDT
    size = trader.compute_position_size(100.0, 90.0, current_balance=500.0)
    assert size == 100.0

    # Entry = 100.0, sl_price = 50.0 (50% distance)
    # position_usdt = 10 / 0.50 = 20 USDT
    size = trader.compute_position_size(100.0, 50.0, current_balance=500.0)
    assert size == 20.0

    # Test minimum order size cap
    # Entry = 100.0, sl_price = 1.0 (99% distance) -> size = 10 / 0.99 = 10.1 USDT
    size = trader.compute_position_size(100.0, 1.0, current_balance=500.0)
    assert size >= 10.0

    # Test with multiplier (e.g. Kelly fraction 0.5)
    # entry_price = 100.0, sl_price = 98.0 (2% distance)
    # risk = 500 * (2% * 0.5) = 5 USDT
    # position_usdt = 5 / 0.02 = 250 USDT, capped by max_trade_usdt (100 USDT)
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, multiplier=0.5)
    assert size == 100.0

    # Entry = 100.0, sl_price = 50.0 (50% distance)
    # multiplier = 0.5 -> risk = 5 USDT
    # size = 5 / 0.5 = 10 USDT (min cap)
    size = trader.compute_position_size(100.0, 50.0, current_balance=500.0, multiplier=0.5)
    assert size == 10.0

    # Test Kelly logic
    # win_prob = 0.6, rr_ratio = 1.5 -> f* = 0.6 - 0.4/1.5 = 0.6 - 0.2667 = 0.3333
    # kelly_fraction = 0.5 -> kelly_risk_pct = 0.3333 * 0.5 * 100 = 16.66%
    # But max risk is adjusted_risk_pct (default 2% * multiplier 1.0 = 2.0%)
    # So risk_usdt = 500 * 2.0% = 10 USDT
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.6, rr_ratio=1.5)
    assert size == 100.0  # (10 USDT / 0.02) = 500 capped to 100
    
    # Test Negative Kelly (win_prob = 0.4, rr_ratio = 1.0 -> f* = 0.4 - 0.6/1.0 = -0.2 <= 0)
    # size should be 0.0
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.4, rr_ratio=1.0)
    assert size == 0.0

    # Test Low Kelly bounded by risk_pct
    # win_prob = 0.51, rr_ratio = 1.0 -> f* = 0.51 - 0.49/1.0 = 0.02
    # kelly_fraction = 0.5 -> kelly_risk_pct = 0.01 * 100 = 1.0%
    # adjusted_risk_pct becomes 1.0%
    # risk_usdt = 500 * 1.0% = 5 USDT
    # position_usdt = 5 / 0.02 = 250 capped to 100 USDT
    size = trader.compute_position_size(100.0, 98.0, current_balance=500.0, win_prob=0.51, rr_ratio=1.0)
    assert size == 100.0

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



