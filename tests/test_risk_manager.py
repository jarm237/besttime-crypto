import pytest
from btc_scraper.trading import risk_manager

def test_calculate_risk_metrics_no_file():
    metrics = risk_manager.calculate_risk_metrics(trades_cache=[])
    assert metrics["consecutive_losses"] == 0
    assert metrics["drawdown_pct"] == 0.0
    assert metrics["risk_multiplier"] == 1.0
    assert not metrics["blocked"]

def test_calculate_risk_metrics_with_trades():
    # Case 1: Less than 3 consecutive losses, no drawdown block
    trades_1 = [
        {"result": "WIN", "pnl_usd_actual": 100.0},
        {"result": "LOSS", "pnl_usd_actual": -50.0},
        {"result": "WIN", "pnl_usd_actual": 20.0},
        {"result": "LOSS", "pnl_usd_actual": -30.0},
    ]
        
    metrics_1 = risk_manager.calculate_risk_metrics(base_capital=1000.0, trades_cache=trades_1)
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
        
    metrics_2 = risk_manager.calculate_risk_metrics(base_capital=1000.0, trades_cache=trades_2)
    assert metrics_2["consecutive_losses"] == 3
    assert metrics_2["risk_multiplier"] == 0.5
    # capital history: 1000 -> 1100 (peak) -> 1050 -> 1000 -> 950
    # peak is 1100, current is 950. Drawdown = (1100-950)/1100 * 100 = 13.64%
    assert metrics_2["drawdown_pct"] == pytest.approx(13.64, abs=0.01)
    assert metrics_2["blocked"] is True


def test_risk_database_failure_blocks_entry(monkeypatch):
    class BrokenCollection:
        def find(self, *args, **kwargs):
            raise TimeoutError("risk database locked")

    monkeypatch.setattr(risk_manager, "closed_positions_col", BrokenCollection())
    metrics = risk_manager.calculate_risk_metrics()

    assert metrics["status"] == "UNAVAILABLE"
    assert metrics["blocked"] is True
    assert metrics["risk_multiplier"] == 0.0
    assert metrics["block_action"] == "BLOCK_ENTRY"
    assert "risk_database_unavailable" in metrics["failure_reason"]


@pytest.mark.parametrize("invalid_pnl", [float("nan"), float("inf"), "not-a-number"])
def test_invalid_risk_values_block_entry(invalid_pnl):
    metrics = risk_manager.calculate_risk_metrics(
        trades_cache=[{"result": "LOSS", "pnl_usd_actual": invalid_pnl}],
    )
    assert metrics["status"] == "UNAVAILABLE"
    assert metrics["blocked"] is True
    assert metrics["risk_multiplier"] == 0.0


def test_stale_drawdown_data_blocks_entry():
    metrics = risk_manager.calculate_risk_metrics(
        trades_cache=[],
        data_observed_at="2026-01-01T00:00:00+00:00",
        max_data_age_seconds=60,
        now=risk_manager.datetime(2026, 1, 1, 0, 2, tzinfo=risk_manager.timezone.utc),
    )
    assert metrics["status"] == "UNAVAILABLE"
    assert metrics["failure_reason"] == "drawdown_data_stale"
    assert metrics["blocked"] is True
