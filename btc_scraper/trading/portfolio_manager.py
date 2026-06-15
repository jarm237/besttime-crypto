"""
Portfolio Manager — Phân bổ vốn tối ưu sử dụng Mean-Variance Optimization (MVO) và Risk Parity.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Literal

def compute_returns_df(candles_dict: dict[str, list[dict]], limit: int = 100) -> pd.DataFrame:
    """
    Tính toán DataFrame tỷ suất lợi nhuận (returns) từ danh sách nến của các coin.
    """
    returns_data = {}
    for coin, candles in candles_dict.items():
        if not candles or len(candles) < 2 or "error" in candles[0]:
            continue
        # Lấy giá đóng cửa của 'limit' nến gần nhất
        closes = [float(c["close"]) for c in candles[-limit:]]
        # Tính tỷ suất lợi nhuận
        rets = np.diff(closes) / closes[:-1]
        returns_data[coin] = rets
        
    # Tạo DataFrame, điền giá trị thiếu (nếu có) bằng 0
    df = pd.DataFrame(returns_data)
    return df.fillna(0.0)

def optimize_mvo(
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_aversion: float = 1.0,
    max_weight: float = 0.30
) -> np.ndarray:
    """
    Tối ưu hóa Mean-Variance (MVO) để tìm tỷ trọng danh mục tối đa hóa Sharpe.
    """
    n = len(expected_returns)
    if n == 0:
        return np.array([])

    # Hàm mục tiêu: cực tiểu hóa âm của Utility (Utility = Return - 0.5 * Risk_Aversion * Variance)
    def objective(w):
        port_return = np.dot(w, expected_returns)
        port_variance = np.dot(w.T, np.dot(cov_matrix, w))
        utility = port_return - 0.5 * risk_aversion * port_variance
        return -utility

    # Điểm khởi đầu: phân bổ đều
    w0 = np.ones(n) / n

    # Ràng buộc: tổng tỷ trọng <= 1.0 (không đòn bẩy)
    cons = ({'type': 'ineq', 'fun': lambda w: 1.0 - np.sum(w)})

    # Biên: 0 <= w_i <= max_weight (chỉ LONG các cơ hội tín hiệu)
    bounds = [(0.0, max_weight) for _ in range(n)]

    res = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=cons, options={'ftol': 1e-15})
    if res.success:
        return res.x
    else:
        # Fallback: phân bổ đều trong giới hạn
        return np.clip(w0, 0.0, max_weight)

def optimize_risk_parity(cov_matrix: np.ndarray, max_weight: float = 0.30) -> np.ndarray:
    """
    Tối ưu hóa Risk Parity để tìm tỷ trọng đóng góp rủi ro bằng nhau.
    """
    n = cov_matrix.shape[0]
    if n == 0:
        return np.array([])

    # Hàm mục tiêu: cực tiểu hóa tổng bình phương độ lệch của các đóng góp rủi ro
    def objective(w):
        port_variance = np.dot(w.T, np.dot(cov_matrix, w))
        port_vol = np.sqrt(max(1e-8, port_variance))
        
        # Đóng góp rủi ro biên
        marginal_risk = np.dot(cov_matrix, w) / port_vol
        # Đóng góp rủi ro của từng tài sản
        risk_contrib = w * marginal_risk
        
        # Rủi ro mục tiêu cho mỗi tài sản (bằng nhau)
        target_risk = port_vol / n
        return np.sum((risk_contrib - target_risk) ** 2)

    # Điểm khởi đầu: phân bổ đều
    w0 = np.ones(n) / n

    # Ràng buộc: tổng tỷ trọng = 1.0
    cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})

    # Biên: 0.01 <= w_i <= max_weight (tránh tỷ trọng bằng 0)
    bounds = [(0.01, max_weight) for _ in range(n)]

    res = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=cons, options={'ftol': 1e-15})
    if res.success:
        return res.x
    else:
        return w0

class PortfolioManager:
    """
    Bộ quản lý và tối ưu hóa danh mục đầu tư.
    """
    def __init__(
        self,
        method: Literal["MVO", "RISK_PARITY"] = "MVO",
        risk_aversion: float = 2.0,
        max_weight: float = 0.30
    ):
        self.method = method
        self.risk_aversion = risk_aversion
        self.max_weight = max_weight

    def allocate_weights(
        self,
        signals_info: list[dict],
        candles_dict: dict[str, list[dict]]
    ) -> dict[str, float]:
        """
        Phân bổ tỷ trọng vốn cho các đồng coin có tín hiệu dựa trên phân tích tương quan.
        
        Args:
            signals_info: List các dict chứa thông tin tín hiệu (coin, action, meta_confidence, atr, close)
            candles_dict: Dict chứa dữ liệu nến lịch sử của các coin để tính tương quan
            
        Returns:
            Dict mapping coin -> tỷ trọng vốn tối ưu (từ 0.0 đến max_weight)
        """
        # Chỉ giữ lại các coin có tín hiệu BUY hoặc SELL rõ ràng
        active_signals = [
            s for s in signals_info 
            if s.get("action") in ("BUY", "SELL")
        ]
        
        if not active_signals:
            return {}
            
        if len(active_signals) == 1:
            # Fallback nếu chỉ có 1 tín hiệu: sử dụng max_weight hoặc tỷ lệ Kelly mặc định
            coin = active_signals[0]["coin"]
            # Lấy kelly_fraction làm điểm xuất phát, giới hạn bởi max_weight
            kelly = active_signals[0].get("kelly_fraction", 0.25)
            return {coin: min(self.max_weight, float(kelly))}

        active_coins = [s["coin"] for s in active_signals]
        
        # 1. Tính toán returns DataFrame và Covariance matrix
        returns_df = compute_returns_df(candles_dict, limit=100)
        
        # Lọc DataFrame chỉ lấy các cột của các đồng coin đang có tín hiệu
        # Nếu thiếu coin nào thì thêm cột chứa toàn 0
        for coin in active_coins:
            if coin not in returns_df.columns:
                returns_df[coin] = 0.0
                
        df_active = returns_df[active_coins]
        
        # Tính covariance matrix, nhân với 1e4 để tránh số quá nhỏ ảnh hưởng tới solver
        cov_matrix = df_active.cov().values * 1e4
        # Add small regularization to diagonal to ensure positive-definiteness
        cov_matrix += np.eye(len(active_coins)) * 1e-6

        # 2. Xây dựng vector expected returns dựa trên model confidence & volatility (ATR)
        expected_returns = []
        for s in active_signals:
            meta_prob = float(s.get("meta_confidence", 0.5))
            # net probability advantage
            prob_factor = 2.0 * meta_prob - 1.0
            
            # Ước lượng expected move dựa trên ATR%
            close = float(s.get("close", 1.0))
            atr = float(s.get("atr", 0.0))
            atr_pct = (atr / close * 100) if close > 0 else 0.0
            
            # Expected return = Net advantage * ATR%
            exp_ret = prob_factor * atr_pct
            # Đảm bảo expected return dương cho solver (vì chúng ta chỉ xem xét chiều có lợi)
            expected_returns.append(max(0.01, exp_ret))
            
        expected_returns = np.array(expected_returns)

        # 3. Chạy thuật toán tối ưu hóa
        if self.method == "MVO":
            weights = optimize_mvo(
                expected_returns,
                cov_matrix,
                risk_aversion=self.risk_aversion,
                max_weight=self.max_weight
            )
        else:  # RISK_PARITY
            weights = optimize_risk_parity(
                cov_matrix,
                max_weight=self.max_weight
            )

        # Trả về kết quả mapping coin -> weight
        allocation = {}
        for idx, coin in enumerate(active_coins):
            allocation[coin] = round(float(weights[idx]), 4)
            
        return allocation
