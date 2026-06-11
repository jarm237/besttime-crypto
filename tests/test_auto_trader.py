import pytest
import os
import json
from pathlib import Path
from btc_scraper.auto_trader import AutoTrader, _load_circuit, _save_circuit, CIRCUIT_BREAKER_STATE

def test_should_trade():
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

def test_circuit_breaker():
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
