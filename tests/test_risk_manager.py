import json
import pytest
from pathlib import Path
from btc_scraper.trading import risk_manager

def test_calculate_risk_metrics_no_file(tmp_path, monkeypatch):
    # Mock CLOSED_POS_PATH to a non-existent file
    test_path = tmp_path / "closed_positions_test.json"
    monkeypatch.setattr(risk_manager, "CLOSED_POS_PATH", test_path)
    
    metrics = risk_manager.calculate_risk_metrics()
    assert metrics["consecutive_losses"] == 0
    assert metrics["drawdown_pct"] == 0.0
    assert metrics["risk_multiplier"] == 1.0
    assert not metrics["blocked"]

def test_calculate_risk_metrics_with_trades(tmp_path, monkeypatch):
    test_path = tmp_path / "closed_positions_test.json"
    monkeypatch.setattr(risk_manager, "CLOSED_POS_PATH", test_path)
    
    # Case 1: Less than 3 consecutive losses, no drawdown block
    trades_1 = [
        {"result": "WIN", "pnl_usd_actual": 100.0},
        {"result": "LOSS", "pnl_usd_actual": -50.0},
        {"result": "WIN", "pnl_usd_actual": 20.0},
        {"result": "LOSS", "pnl_usd_actual": -30.0},
    ]
    with open(test_path, "w", encoding="utf-8") as f:
        json.dump(trades_1, f)
        
    metrics_1 = risk_manager.calculate_risk_metrics(base_capital=1000.0)
    assert metrics_1["consecutive_losses"] == 1
    assert metrics_1["risk_multiplier"] == 1.0
    # capital history: 1000 -> 1100 -> 1050 -> 1070 -> 1040
    # peak is 1100, current is 1040. Drawdown = (1100-1040)/1100 * 100 = 5.45%
    assert metrics_1["drawdown_pct"] == pytest.approx(5.45, abs=0.01)
    assert not metrics_1["blocked"]

    # Case 2: 3 consecutive losses, drawdown >= 10%
    trades_2 = [
        {"result": "WIN", "pnl_usd_actual": 100.0},
        {"result": "LOSS", "pnl_usd_actual": -50.0},
        {"result": "LOSS", "pnl_usd_actual": -50.0},
        {"result": "LOSS", "pnl_usd_actual": -50.0},
    ]
    with open(test_path, "w", encoding="utf-8") as f:
        json.dump(trades_2, f)
        
    metrics_2 = risk_manager.calculate_risk_metrics(base_capital=1000.0)
    assert metrics_2["consecutive_losses"] == 3
    assert metrics_2["risk_multiplier"] == 0.5
    # capital history: 1000 -> 1100 (peak) -> 1050 -> 1000 -> 950
    # peak is 1100, current is 950. Drawdown = (1100-950)/1100 * 100 = 13.64%
    assert metrics_2["drawdown_pct"] == pytest.approx(13.64, abs=0.01)
    assert metrics_2["blocked"] is True
