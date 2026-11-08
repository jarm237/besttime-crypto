import pytest
import numpy as np
import pandas as pd
import os
import json
import tempfile
from datetime import datetime, timedelta, timezone
from btc_scraper.analysis.correlation import CorrelationEngine, SECTOR_MAP
from btc_scraper.trading.exposure_manager import ExposureManager
from btc_scraper.trading.auto_trader import AutoTrader


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


class MockCollection:
    def __init__(self, data):
        self._data = data

    def find(self, query, projection=None):
        return [dict(x) for x in self._data]


@pytest.fixture
def mock_cov_corr():
    # Setup mock correlation & covariance matrix
    coins = ["BTC", "ETH", "SOL", "NEAR"]
    corr_data = [
        [1.0, 0.8, 0.4, 0.3],
        [0.8, 1.0, 0.5, 0.4],
        [0.4, 0.5, 1.0, 0.8], # SOL and NEAR are highly correlated (0.8 > 0.75)
        [0.3, 0.4, 0.8, 1.0]
    ]
    
    # 1h return variances: BTC = 2% (0.0004), ETH = 3% (0.0009), SOL = 4% (0.0016), NEAR = 5% (0.0025)
    stds = [0.02, 0.03, 0.04, 0.05]
    cov_data = np.zeros((4, 4))
    for i in range(4):
        for j in range(4):
            cov_data[i, j] = corr_data[i][j] * stds[i] * stds[j]
            
    corr_df = pd.DataFrame(corr_data, index=coins, columns=coins)
    cov_df = pd.DataFrame(cov_data, index=coins, columns=coins)
    return corr_df, cov_df


def test_correlation_engine_computations():
    # Test correlation engine on actual 1h CSV data in data/historical_18m
    # Use a temporary file for JSON cache
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = os.path.join(tmp_dir, "test_correlation.json")
        engine = CorrelationEngine(data_dir="data/historical_18m", cache_path=cache_path)
        
        # Calculate
        corr, cov = engine.calculate_correlation_matrix(lookback_days=10)
        
        assert corr is not None
        assert cov is not None
        if not corr.empty:
            assert "BTC" in corr.index
            assert corr.loc["BTC", "BTC"] == 1.0
            assert os.path.exists(cache_path)


def test_correlation_engine_fallbacks(mock_cov_corr):
    corr_df, cov_df = mock_cov_corr
    
    engine = CorrelationEngine()
    engine.correlation_matrix = corr_df
    engine.covariance_matrix = cov_df
    
    # Direct check
    assert engine.get_correlation("BTC", "ETH") == 0.8
    assert engine.get_correlation("SOL", "NEAR") == 0.8
    
    # Missing coin fallback (using sector averages)
    # AEVO is DEFI, ENA is DEFI. If we ask correlation between AEVO and ENA (both DEFI), 
    # but they are not in the matrix, it defaults to DEFAULT_CORRELATION (0.5) because 
    # no other DEFI coins exist in the matrix.
    assert engine.get_correlation("AEVO", "ENA") == 0.5
    
    # If ca == cb, always 1.0
    assert engine.get_correlation("AEVO", "AEVO") == 1.0


def test_correlation_does_not_backfill_before_listing(tmp_path):
    times = pd.date_range("2026-01-01", periods=8, freq="h")
    pd.DataFrame({"time": times, "close": [100, 101, 99, 103, 100, 106, 102, 109]}).to_csv(
        tmp_path / "BTC_1h_2026-01.csv", index=False
    )
    sol_prices = [10, 12, 11, 15, 13]
    pd.DataFrame({"time": times[3:], "close": sol_prices}).to_csv(
        tmp_path / "SOL_1h_2026-01.csv", index=False
    )
    engine = CorrelationEngine(
        data_dir=str(tmp_path),
        cache_path=str(tmp_path / "correlation.json"),
    )

    correlation, _ = engine.calculate_correlation_matrix(lookback_days=30)
    expected = pd.Series([103, 100, 106, 102, 109]).pct_change().corr(
        pd.Series(sol_prices).pct_change()
    )

    assert correlation.loc["BTC", "SOL"] == pytest.approx(expected)


def test_exposure_manager_caps():
    # 1. Test basic calculations
    mock_data = [
        {"coin": "BTC", "invested_usdt": 100.0, "status": "open"},
        {"coin": "ETH", "invested_usdt": 100.0, "status": "open"},
        {"coin": "DOGE", "invested_usdt": 100.0, "status": "open"}
    ]
    col = MockCollection(mock_data)
    manager = ExposureManager(positions_collection=col)
    
    total_pct, coin_pct, sector_pct = manager.get_portfolio_exposures(current_balance=1000.0)
    assert total_pct == 0.30
    assert coin_pct["BTC"] == 0.10
    assert sector_pct["L1"] == 0.20
    assert sector_pct["MEME"] == 0.10
    
    # Test valid new position: BNB (L1) with 50 USDT
    # New L1 = 200 + 50 = 250 (25% < 35%) -> OK
    is_ok, reason = manager.validate_new_position("BNB", 50.0, current_balance=1000.0)
    assert is_ok
    assert reason is None
    
    # Test violating Single Asset cap: BTC with 60 USDT
    # New BTC = 100 + 60 = 160 (16% > 15%) -> Fail
    is_ok, reason = manager.validate_new_position("BTC", 60.0, current_balance=1000.0)
    assert not is_ok
    assert "Single Asset Cap" in reason

    # 2. Test violating Sector cap (L1 limit: 35%)
    # Current L1 is 120 + 120 = 240 (24%). Adding BNB with 120 makes L1 = 360 (36% > 35%).
    # Since BNB is 120, it is < 15% (150 USDT) single limit -> Passes Single check, fails Sector check.
    mock_sector_violating = [
        {"coin": "BTC", "invested_usdt": 120.0, "status": "open"},
        {"coin": "ETH", "invested_usdt": 120.0, "status": "open"},
    ]
    col_sec = MockCollection(mock_sector_violating)
    manager_sec = ExposureManager(positions_collection=col_sec)
    is_ok, reason = manager_sec.validate_new_position("BNB", 120.0, current_balance=1000.0)
    assert not is_ok
    assert "Sector Cap" in reason
    
    # 3. Test violating Total Portfolio cap (limit: 75%)
    # Current total is 6 * 120 = 720 (72%). Adding BNB with 50 makes total = 770 (77% > 75%).
    # BNB is 50 (< 150 single limit), L1 sector is 240 + 50 = 290 (< 350 sector limit).
    # So it passes single and sector, but fails total.
    mock_total_violating = [
        {"coin": "BTC", "invested_usdt": 120.0, "status": "open"},
        {"coin": "ETH", "invested_usdt": 120.0, "status": "open"},
        {"coin": "DOGE", "invested_usdt": 120.0, "status": "open"},
        {"coin": "TAO", "invested_usdt": 120.0, "status": "open"},
        {"coin": "AR", "invested_usdt": 120.0, "status": "open"},
        {"coin": "WLD", "invested_usdt": 120.0, "status": "open"}
    ]
    col_tot = MockCollection(mock_total_violating)
    manager_tot = ExposureManager(positions_collection=col_tot)
    is_ok, reason = manager_tot.validate_new_position("BNB", 50.0, current_balance=1000.0)
    assert not is_ok
    assert "Total Portfolio Cap" in reason


def test_exposure_manager_var_scaling(mock_cov_corr):
    corr_df, cov_df = mock_cov_corr
    from btc_scraper.analysis.correlation import correlation_engine
    
    # Inject mock matrices
    original_corr = correlation_engine.correlation_matrix
    original_cov = correlation_engine.covariance_matrix
    correlation_engine.correlation_matrix = corr_df
    correlation_engine.covariance_matrix = cov_df
    
    try:
        # Balance: 1000 USDT. Max VaR = 50 USDT (5%).
        # Open positions: BTC (100 USDT).
        # Open VaR = 1.645 * sqrt(100^2 * 0.0004) = 1.645 * sqrt(4) = 3.29 USDT.
        # We propose to open ETH (with 80% correlation with BTC).
        # We check maximum size for ETH.
        mock_data = [
            {"coin": "BTC", "invested_usdt": 100.0, "status": "open"}
        ]
        col = MockCollection(mock_data)
        manager = ExposureManager(positions_collection=col)
        
        # Standard Var limit
        max_size = manager.calculate_max_size_by_var_limit("ETH", mock_data, current_balance=1000.0)
        assert max_size > 0.0
        # VaR constraints should cap it below the infinite limits
        assert max_size < 1000.0
        
        # Test case where existing portfolio already violates VaR cap (e.g. BTC = 800 USDT, open VaR = 26 USDT?)
        # Let's say balance is very small, e.g. 100 USDT, so max VaR is 5 USDT.
        # Open position: BTC = 200 USDT. BTC 1h std = 2% (0.02).
        # BTC VaR = 1.645 * (200 * 0.02) = 1.645 * 4 = 6.58 USDT (> 5 USDT).
        # In this case, max size should be 0.0
        mock_data_violating = [
            {"coin": "BTC", "invested_usdt": 200.0, "status": "open"}
        ]
        col_violating = MockCollection(mock_data_violating)
        manager_violating = ExposureManager(positions_collection=col_violating)
        max_size_violating = manager_violating.calculate_max_size_by_var_limit("ETH", mock_data_violating, current_balance=100.0)
        assert max_size_violating == 0.0
        
    finally:
        correlation_engine.correlation_matrix = original_corr
        correlation_engine.covariance_matrix = original_cov


def test_autotrader_correlation_and_sizing_filters(mock_cov_corr, monkeypatch):
    import asyncio
    
    async def run_async_test():
        corr_df, cov_df = mock_cov_corr
        from btc_scraper.analysis.correlation import correlation_engine
        from btc_scraper.trading.exposure_manager import exposure_manager
        
        # Inject mock correlation/covariance matrices
        original_corr = correlation_engine.correlation_matrix
        original_cov = correlation_engine.covariance_matrix
        correlation_engine.correlation_matrix = corr_df
        correlation_engine.covariance_matrix = cov_df
        
        try:
            # Mock active open positions: SOL is open.
            # If we try to buy NEAR, it should be skipped because R_SOL,NEAR = 0.8 > 0.75.
            mock_data = [
                {"coin": "SOL", "invested_usdt": 100.0, "status": "open"}
            ]
            mock_col = MockCollection(mock_data)
            
            # Patch exposure manager database collection
            monkeypatch.setattr(exposure_manager, "positions_col", mock_col)
            
            # Setup AutoTrader config via env
            monkeypatch.setenv("PAPER_ECONOMIC_POLICY", "ACTIVE_PAPER")
            monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")
            monkeypatch.setenv("AUTO_TRADE_ACCOUNT_USDT", "1000.0")
            monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0.5")
            monkeypatch.setenv("AUTO_TRADE_SCORE_THRESHOLD", "50")
            monkeypatch.setenv("DISABLE_KELLY", "1")  # Disable Kelly to isolate VaR & exposure
            monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH,SOL,NEAR")
            
            class MockCCXTClient:
                async def get_usdt_balance(self):
                    return 1000.0
                async def get_symbol_price(self, symbol):
                    return 100.0
                async def create_market_buy(self, symbol, usdt_amount):
                    return {"id": "mock-buy-id", "status": "placed", "price": 100.0}
                async def create_market_sell(self, symbol, usdt_amount):
                    return {"id": "mock-sell-id", "status": "placed", "price": 100.0}
            
            trader = AutoTrader()
            monkeypatch.setattr(trader, "_has_open_position", lambda c, d: False)
            
            # Test signal for NEAR (should fail correlation filter due to SOL)
            mock_ana_near = {
                "signal": "BUY",
                "history": _readiness_history(),
                "signal_score": {"score": 80, "meta_confidence": 0.8, "position_size": 1.0},
                "tp_sl": {"entry": 5.0, "sl": 4.5, "rr1": 2.0}
            }
            res_near = await trader._process_signal("NEAR:Binance", mock_ana_near)
            assert res_near is not None
            assert "Tuong quan cao" in res_near.get("reason_skip", "")
            
            # Test signal for ETH (R_SOL,ETH = 0.5 <= 0.75, should pass correlation, but check size limits)
            # Entry = 100, SL = 80 (20% distance).
            # Standard position_usdt = (1000 * 2%) / 0.20 = 20 / 0.20 = 100 USDT.
            # Exposure single cap is 15% (150 USDT), L1 sector cap is 35% (350 USDT), total is 75% (750 USDT).
            # Current open SOL is L1? Wait, SOL is INFRA. ETH is L1.
            # So remaining caps are large enough to fit 100 USDT.
            mock_ana_eth = {
                "signal": "BUY",
                "history": _readiness_history(),
                "signal_score": {"score": 80, "meta_confidence": 0.8, "position_size": 1.0},
                "tp_sl": {"entry": 100.0, "sl": 80.0, "rr1": 2.0}
            }
            res_eth = await trader._process_signal("ETH:Binance", mock_ana_eth)
            print("res_eth ERROR:", res_eth.get("error") if res_eth else None)
            print("res_eth full:", res_eth)
            assert res_eth is not None
            # It should place a dry run order
            assert "error" not in res_eth or res_eth["error"] is None
            
        finally:
            correlation_engine.correlation_matrix = original_corr
            correlation_engine.covariance_matrix = original_cov

    asyncio.run(run_async_test())
