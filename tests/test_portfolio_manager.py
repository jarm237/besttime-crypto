import numpy as np
import pandas as pd
import pytest
from btc_scraper.trading import portfolio_manager

def test_compute_returns_df():
    # Giả lập dữ liệu nến cho 2 coin
    candles_dict = {
        "BTC": [
            {"close": 100.0},
            {"close": 101.0},
            {"close": 102.01},
        ],
        "ETH": [
            {"close": 10.0},
            {"close": 9.9},
            {"close": 9.999},
        ]
    }
    
    df = portfolio_manager.compute_returns_df(candles_dict, limit=10)
    assert "BTC" in df.columns
    assert "ETH" in df.columns
    # Lợi nhuận BTC: 1% (101/100 - 1) và 1% (102.01/101 - 1)
    assert df["BTC"].iloc[0] == pytest.approx(0.01)
    assert df["BTC"].iloc[1] == pytest.approx(0.01)
    # Lợi nhuận ETH: -1% (9.9/10 - 1) và 1% (9.999/9.9 - 1)
    assert df["ETH"].iloc[0] == pytest.approx(-0.01)
    assert df["ETH"].iloc[1] == pytest.approx(0.01)

def test_optimize_mvo():
    # 2 assets, 1 kỳ vọng sinh lời cao và 1 thấp
    expected_returns = np.array([0.05, 0.01])
    cov_matrix = np.array([
        [0.0004, 0.0001],
        [0.0001, 0.0002]
    ])
    
    weights = portfolio_manager.optimize_mvo(
        expected_returns,
        cov_matrix,
        risk_aversion=500.0,
        max_weight=0.40
    )
    
    assert len(weights) == 2
    # Tổng tỷ trọng <= 1.0
    assert np.sum(weights) <= 1.0001
    # Từng tỷ trọng không vượt quá max_weight
    assert weights[0] <= 0.4001
    assert weights[1] <= 0.4001
    # Asset 0 có expected return cao hơn nhiều nên trọng số của nó phải lớn hơn asset 1
    assert weights[0] > weights[1]

def test_optimize_risk_parity():
    # Covariance matrix cho 2 assets
    cov_matrix = np.array([
        [0.0004, 0.0001],
        [0.0001, 0.0002]
    ])
    
    weights = portfolio_manager.optimize_risk_parity(cov_matrix, max_weight=0.60)
    
    assert len(weights) == 2
    assert np.sum(weights) == pytest.approx(1.0, abs=1e-4)
    assert weights[0] <= 0.60
    assert weights[1] <= 0.60
    
    # Asset 0 có biến động (variance 0.0004) lớn hơn Asset 1 (0.0002)
    # Để cân bằng rủi ro, Asset 0 phải nhận tỷ trọng vốn nhỏ hơn Asset 1
    assert weights[0] < weights[1]

def test_portfolio_manager_allocate_weights():
    # Test case 1: Không có tín hiệu nào hoạt động
    pm = portfolio_manager.PortfolioManager(method="MVO", max_weight=0.30)
    alloc_1 = pm.allocate_weights([], {})
    assert alloc_1 == {}
    
    # Test case 2: Chỉ có 1 tín hiệu hoạt động
    signals_2 = [
        {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.25, "close": 50000.0, "atr": 1000.0, "meta_confidence": 0.80}
    ]
    alloc_2 = pm.allocate_weights(signals_2, {})
    assert alloc_2 == {"BTC": 0.25}
    
    # Test case 3: Nhiều tín hiệu hoạt động
    signals_3 = [
        {"coin": "BTC", "action": "BUY", "kelly_fraction": 0.25, "close": 50000.0, "atr": 1000.0, "meta_confidence": 0.80},
        {"coin": "ETH", "action": "BUY", "kelly_fraction": 0.20, "close": 3000.0, "atr": 90.0, "meta_confidence": 0.70}
    ]
    
    # Giả lập nến để tính tương quan
    candles_dict = {
        "BTC": [{"close": 50000.0 + i * 100} for i in range(10)],
        "ETH": [{"close": 3000.0 + i * 5} for i in range(10)]
    }
    
    alloc_3 = pm.allocate_weights(signals_3, candles_dict)
    assert "BTC" in alloc_3
    assert "ETH" in alloc_3
    assert alloc_3["BTC"] <= 0.30
    assert alloc_3["ETH"] <= 0.30
