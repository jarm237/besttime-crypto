import pytest
from btc_scraper.ml_engine.signal_score import score_signal
from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

def test_buy_preserves_win_probability():
    meta = {
        "probability": 0.80,
        "expected_return": 0.10,
        "expected_drawdown": 0.05,
        "expected_hold_time": 4.0,
        "prediction_id": "pred-123",
        "signal_id": "sig-123",
        "action": "BUY"
    }
    
    # We call score_signal with a BUY signal text
    res = score_signal("BUY", data={}, context={}, meta_prediction=meta)
    
    assert res["action"] == "BUY"
    assert res["meta_probability"] == 0.80
    assert res["meta_decision"]["execution_probability"] == 0.80

def test_sell_preserves_win_probability():
    meta = {
        "probability": 0.80,
        "expected_return": 0.10,
        "expected_drawdown": 0.05,
        "expected_hold_time": 4.0,
        "prediction_id": "pred-123",
        "signal_id": "sig-123",
        "action": "SELL"
    }
    
    # We call score_signal with a SELL signal text
    res = score_signal("SELL", data={}, context={}, meta_prediction=meta)
    
    assert res["action"] == "SELL"
    assert res["meta_probability"] == 0.80
    assert res["meta_decision"]["execution_probability"] == 0.80

def test_sell_does_not_invert_win_probability():
    meta = {
        "probability": 0.20,
        "expected_return": 0.10,
        "expected_drawdown": 0.05,
        "expected_hold_time": 4.0,
        "prediction_id": "pred-123",
        "signal_id": "sig-123",
        "action": "SELL"
    }
    
    res = score_signal("SELL", data={}, context={}, meta_prediction=meta)
    
    assert res["meta_probability"] == 0.20
    assert res["meta_decision"]["execution_probability"] == 0.20

def test_fallback_execution_probability():
    # test the fallback method in decision_engine.py
    # Under P(up) default fallback semantics, SELL execution prob is inverted:
    assert MetaDecisionEngine._execution_probability("SELL", 0.75) == 0.25
    assert MetaDecisionEngine._execution_probability("BUY", 0.75) == 0.75

