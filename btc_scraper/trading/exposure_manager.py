import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from btc_scraper.core.db import positions_col
from btc_scraper.analysis.correlation import SECTOR_MAP

# Ngưỡng giới hạn rủi ro danh mục (Portfolio Risk Caps)
MAX_TOTAL_EXPOSURE_PCT = 0.75          # 75% số dư tài khoản tối đa đầu tư
MAX_SECTOR_EXPOSURE_PCT = 0.35         # 35% số dư tài khoản tối đa cho 1 nhóm ngành (Sector)
MAX_SINGLE_ASSET_EXPOSURE_PCT = 0.15   # 15% số dư tài khoản tối đa cho 1 đồng coin
MAX_PORTFOLIO_VAR_PCT = 0.05           # 5% số dư tài khoản tối đa có thể chịu rủi ro ở 95% 1h VaR


class ExposureManager:
    """
    Bộ quản lý Exposure và rủi ro nhóm ngành của danh mục đầu tư.
    """

    def __init__(self, positions_collection=None):
        self.positions_col = positions_collection if positions_collection is not None else positions_col

    def get_open_positions(self) -> List[Dict]:
        """Lấy tất cả các vị thế đang mở từ DB."""
        try:
            if self.positions_col is not None:
                return list(self.positions_col.find({"status": "open"}, {"_id": 0}))
        except Exception as e:
            print(f"[Exposure Manager] Warning: Could not fetch open positions from MongoDB: {e}")
        return []

    def get_portfolio_exposures(self, current_balance: float) -> Tuple[float, Dict[str, float], Dict[str, float]]:
        """
        Tính toán:
        1. Tổng giá trị đầu tư (USDT) và tỷ lệ % danh mục.
        2. Exposure theo từng đồng coin (USDT và % danh mục).
        3. Exposure theo từng Sector (USDT và % danh mục).
        """
        open_positions = self.get_open_positions()
        
        total_exposure_usdt = 0.0
        coin_exposures_usdt: Dict[str, float] = {}
        sector_exposures_usdt: Dict[str, float] = {}
        
        # Initialize sectors
        for sector in set(SECTOR_MAP.values()):
            sector_exposures_usdt[sector] = 0.0
        sector_exposures_usdt["OTHER"] = 0.0

        for pos in open_positions:
            coin = pos.get("coin", "").upper()
            invested = float(pos.get("invested_usdt", 0.0))
            if invested <= 0:
                continue
                
            total_exposure_usdt += invested
            coin_exposures_usdt[coin] = coin_exposures_usdt.get(coin, 0.0) + invested
            
            sector = SECTOR_MAP.get(coin, "OTHER")
            sector_exposures_usdt[sector] = sector_exposures_usdt.get(sector, 0.0) + invested

        # Convert to percentage
        total_exposure_pct = total_exposure_usdt / current_balance if current_balance > 0 else 0.0
        coin_exposures_pct = {k: v / current_balance for k, v in coin_exposures_usdt.items() if current_balance > 0}
        sector_exposures_pct = {k: v / current_balance for k, v in sector_exposures_usdt.items() if current_balance > 0}
        
        return total_exposure_pct, coin_exposures_pct, sector_exposures_pct

    def validate_new_position(self, coin: str, usdt_amount: float, current_balance: float) -> Tuple[bool, Optional[str]]:
        """
        Xác thực xem vị thế mới có vi phạm bất kỳ cap rủi ro nào không:
        - Tổng exposure (sau lệnh mới) <= 75%
        - Exposure của sector (sau lệnh mới) <= 35%
        - Exposure của coin (sau lệnh mới) <= 15%
        
        Trả về (is_valid, reason)
        """
        coin = coin.upper()
        if current_balance <= 0:
            return False, f"Balance tai khoan khong hop le ({current_balance})"
            
        total_pct, coin_pct, sector_pct = self.get_portfolio_exposures(current_balance)
        
        # 1. Kiểm tra Single Asset Limit
        new_coin_exposure = (coin_pct.get(coin, 0.0) * current_balance) + usdt_amount
        new_coin_pct = new_coin_exposure / current_balance
        if new_coin_pct > MAX_SINGLE_ASSET_EXPOSURE_PCT:
            limit_val = MAX_SINGLE_ASSET_EXPOSURE_PCT * current_balance
            return False, f"Vi pham Single Asset Cap cho {coin}: {new_coin_pct:.1%} > {MAX_SINGLE_ASSET_EXPOSURE_PCT:.1%} (Limit: {limit_val:.2f} USDT, Expected: {new_coin_exposure:.2f} USDT)"
            
        # 2. Kiểm tra Sector Limit
        sector = SECTOR_MAP.get(coin, "OTHER")
        new_sector_exposure = (sector_pct.get(sector, 0.0) * current_balance) + usdt_amount
        new_sector_pct = new_sector_exposure / current_balance
        if new_sector_pct > MAX_SECTOR_EXPOSURE_PCT:
            limit_val = MAX_SECTOR_EXPOSURE_PCT * current_balance
            return False, f"Vi pham Sector Cap cho {sector}: {new_sector_pct:.1%} > {MAX_SECTOR_EXPOSURE_PCT:.1%} (Limit: {limit_val:.2f} USDT, Expected: {new_sector_exposure:.2f} USDT)"
            
        # 3. Kiểm tra Total Portfolio Exposure Limit
        new_total_exposure = (total_pct * current_balance) + usdt_amount
        new_total_pct = new_total_exposure / current_balance
        if new_total_pct > MAX_TOTAL_EXPOSURE_PCT:
            limit_val = MAX_TOTAL_EXPOSURE_PCT * current_balance
            return False, f"Vi pham Total Portfolio Cap: {new_total_pct:.1%} > {MAX_TOTAL_EXPOSURE_PCT:.1%} (Limit: {limit_val:.2f} USDT, Expected: {new_total_exposure:.2f} USDT)"
            
        return True, None

    def calculate_max_size_by_var_limit(
        self,
        coin: str,
        open_positions: List[Dict],
        current_balance: float,
        max_var_pct: float = MAX_PORTFOLIO_VAR_PCT
    ) -> float:
        """
        Tính kích thước lệnh tối đa (USDT) để Portfolio VaR (1h ở độ tin cậy 95%)
        không vượt quá max_var_pct * current_balance.
        """
        from btc_scraper.analysis.correlation import correlation_engine
        
        # Load matrices
        cov_matrix = correlation_engine.covariance_matrix
        
        # Ngưỡng VaR tối đa bằng USD
        max_var_usd = current_balance * max_var_pct
        z_score = 1.645
        
        # 1. Tính phương sai của danh mục đang mở (var_open)
        var_open = 0.0
        # Lưu trữ các vị thế đang mở dưới dạng list (coin, notional)
        open_notionals = []
        for pos in open_positions:
            c = pos.get("coin", "").upper()
            w = float(pos.get("invested_usdt", 0.0))
            if w > 0:
                open_notionals.append((c, w))
                
        # Nếu có các vị thế đang mở, tính var_open
        if open_notionals and cov_matrix is not None and not cov_matrix.empty:
            for c1, w1 in open_notionals:
                for c2, w2 in open_notionals:
                    # Lấy covariance từ matrix
                    cov = self._get_covariance_val(cov_matrix, c1, c2)
                    var_open += w1 * w2 * cov
        else:
            var_open = 0.0
            
        # 2. Xác định phương sai của coin mới (var_new) và covariance vector (c)
        if cov_matrix is not None and not cov_matrix.empty:
            var_new = self._get_covariance_val(cov_matrix, coin, coin)
        else:
            var_new = 0.0025  # 5% std dev mặc định -> 0.05^2 = 0.0025
            
        # Tránh phương sai <= 0
        if var_new <= 0:
            var_new = 0.0025
            
        cov_open_new = 0.0
        if open_notionals and cov_matrix is not None and not cov_matrix.empty:
            for c_open, w_open in open_notionals:
                cov = self._get_covariance_val(cov_matrix, c_open, coin)
                cov_open_new += w_open * cov
                
        # 3. Giải phương trình bậc hai: A * w^2 + B * w + C = 0
        # VaR = z * sqrt(var_open + 2 * w * cov_open_new + w^2 * var_new) <= max_var_usd
        # var_open + 2 * w * cov_open_new + w^2 * var_new <= (max_var_usd / z)^2
        limit_var_total = (max_var_usd / z_score) ** 2
        
        A = var_new
        B = 2.0 * cov_open_new
        C = var_open - limit_var_total
        
        # Nếu C >= 0, có nghĩa là danh mục hiện tại đã vượt quá giới hạn VaR
        if C >= 0:
            return 0.0
            
        delta = B**2 - 4*A*C
        if delta < 0:
            # Không có nghiệm thực, lý thuyết không xảy ra khi C < 0 và A > 0, nhưng phòng thủ:
            return 0.0
            
        # Nghiệm dương tối đa
        w_max = (-B + np.sqrt(delta)) / (2 * A)
        return float(max(0.0, w_max))

    def _get_covariance_val(self, cov_matrix: pd.DataFrame, c1: str, c2: str) -> float:
        """Lấy giá trị covariance từ matrix, fallback dùng correlation * std1 * std2 nếu thiếu."""
        from btc_scraper.analysis.correlation import correlation_engine
        
        # Nếu có trong matrix, lấy trực tiếp
        if c1 in cov_matrix.index and c2 in cov_matrix.columns:
            val = cov_matrix.loc[c1, c2]
            if not np.isnan(val):
                return float(val)
                
        # Fallback bằng cách tính từ correlation và standard deviations
        std1 = np.sqrt(self._get_variance_fallback(cov_matrix, c1))
        std2 = np.sqrt(self._get_variance_fallback(cov_matrix, c2))
        
        corr = correlation_engine.get_correlation(c1, c2)
        return corr * std1 * std2

    def _get_variance_fallback(self, cov_matrix: pd.DataFrame, coin: str) -> float:
        """Lấy variance của một coin, fallback bằng trung bình variance của nhóm ngành."""
        if cov_matrix is not None and not cov_matrix.empty and coin in cov_matrix.index:
            val = cov_matrix.loc[coin, coin]
            if not np.isnan(val) and val > 0:
                return float(val)
                
        # Lấy trung bình variance của các coin cùng sector
        sector = SECTOR_MAP.get(coin, "OTHER")
        sector_coins = [c for c, s in SECTOR_MAP.items() if s == sector]
        
        vars_list = []
        if cov_matrix is not None and not cov_matrix.empty:
            for sc in sector_coins:
                if sc in cov_matrix.index:
                    val = cov_matrix.loc[sc, sc]
                    if not np.isnan(val) and val > 0:
                        vars_list.append(val)
                        
        if vars_list:
            return float(np.mean(vars_list))
            
        return 0.0025  # 5% std dev mặc định


# Khởi tạo instance toàn cục
exposure_manager = ExposureManager()
