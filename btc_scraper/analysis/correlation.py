import os
import glob
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# Nhóm ngành (Sectors) định nghĩa cho hệ thống
SECTOR_MAP = {
    # Layer 1
    "BTC": "L1", "ETH": "L1", "BNB": "L1", "SOL": "L1", "AVAX": "L1",
    "ADA": "L1", "NEAR": "L1", "TRX": "L1", "XLM": "L1", "XRP": "L1",
    "ZEC": "L1", "LTC": "L1",
    # DeFi
    "AEVO": "DEFI", "ENA": "DEFI",
    # AI
    "TAO": "AI",
    # Meme
    "DOGE": "MEME",
    # Political
    "TRUMP": "POLITICAL",
    # RWA / Infrastructure
    "AR": "INFRA", "WLD": "INFRA", "IOTA": "INFRA", "TRB": "INFRA"
}

DEFAULT_CORRELATION = 0.5  # Hệ số tương quan mặc định giữa các tài sản bất kỳ khi hoàn toàn thiếu dữ liệu


class CorrelationEngine:
    """
    Bộ máy tính toán ma trận tương quan Pearson lăn 30 ngày và ma trận hiệp phương sai
    dựa trên nến 1h lịch sử.
    """

    def __init__(self, data_dir: str = "data/historical_18m", cache_path: str = "logs/portfolio_correlation.json"):
        self.data_dir = data_dir
        self.cache_path = cache_path
        self.correlation_matrix: Optional[pd.DataFrame] = None
        self.covariance_matrix: Optional[pd.DataFrame] = None
        self.last_updated: Optional[str] = None
        
        # Load cache if available
        self.load_cache()

    def load_cache(self) -> bool:
        """Tải dữ liệu ma trận từ file cache JSON."""
        if not os.path.exists(self.cache_path):
            return False
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.last_updated = data.get("last_updated")
            corr_dict = data.get("correlation")
            cov_dict = data.get("covariance")
            
            if corr_dict:
                self.correlation_matrix = pd.DataFrame.from_dict(corr_dict)
            if cov_dict:
                self.covariance_matrix = pd.DataFrame.from_dict(cov_dict)
                
            print(f"[Correlation Engine] Loaded correlation cache updated at {self.last_updated}")
            return True
        except Exception as e:
            print(f"[Correlation Engine] Error loading cache: {e}")
            return False

    def save_cache(self) -> None:
        """Lưu trữ ma trận vào file cache JSON."""
        if self.correlation_matrix is None or self.covariance_matrix is None:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            data = {
                "last_updated": datetime.now().isoformat(),
                "correlation": self.correlation_matrix.to_dict(),
                "covariance": self.covariance_matrix.to_dict()
            }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[Correlation Engine] Saved correlation cache to {self.cache_path}")
        except Exception as e:
            print(f"[Correlation Engine] Error saving cache: {e}")

    def calculate_correlation_matrix(self, lookback_days: int = 30) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Quét các file CSV nến 1h, căn chỉnh thời gian và tính toán
        ma trận tương quan & ma trận hiệp phương sai.
        """
        print(f"[Correlation Engine] Calculating correlation matrix for last {lookback_days} days...")
        
        csv_pattern = os.path.join(self.data_dir, "*_1h.csv")
        csv_files = glob.glob(csv_pattern)
        
        # Nhóm file theo coin
        coin_files: Dict[str, List[str]] = {}
        for f in csv_files:
            parts = os.path.basename(f).split("_")
            if len(parts) >= 3 and parts[-1] == "1h.csv":
                coin = parts[-2].upper()
                coin_files.setdefault(coin, []).append(f)
                
        if not coin_files:
            print("[Correlation Engine] Warning: No 1h candle files found. Using empty dataframes.")
            self.correlation_matrix = pd.DataFrame()
            self.covariance_matrix = pd.DataFrame()
            return self.correlation_matrix, self.covariance_matrix

        # Đọc dữ liệu đóng cửa cho mỗi coin
        close_prices = {}
        for coin, paths in coin_files.items():
            combined_rows = []
            for path in paths:
                try:
                    df_temp = pd.read_csv(path)
                    if "time" in df_temp.columns and "close" in df_temp.columns:
                        combined_rows.append(df_temp[["time", "close"]])
                except Exception as e:
                    print(f"[Correlation Engine] Error reading {path}: {e}")
                    
            if not combined_rows:
                continue
                
            # Gộp và sắp xếp theo thời gian
            df_coin = pd.concat(combined_rows).drop_duplicates(subset=["time"])
            df_coin = df_coin.sort_values(by="time").reset_index(drop=True)
            df_coin["time"] = pd.to_datetime(df_coin["time"])
            close_prices[coin] = df_coin
            
        if not close_prices:
            self.correlation_matrix = pd.DataFrame()
            self.covariance_matrix = pd.DataFrame()
            return self.correlation_matrix, self.covariance_matrix

        # Tạo DataFrame chung kết nối bằng time
        # Lấy mốc thời gian lớn nhất từ BTC (hoặc coin bất kỳ làm mốc)
        base_coin = "BTC" if "BTC" in close_prices else list(close_prices.keys())[0]
        merged_df = close_prices[base_coin][["time", "close"]].rename(columns={"close": base_coin})
        
        for coin, df_coin in close_prices.items():
            if coin == base_coin:
                continue
            df_temp = df_coin[["time", "close"]].rename(columns={"close": coin})
            merged_df = pd.merge(merged_df, df_temp, on="time", how="outer")
            
        merged_df = merged_df.sort_values(by="time").set_index("time")
        
        # Forward fill giá để xử lý lệch nến, sau đó điền 0 cho mốc đầu tiên
        merged_df = merged_df.ffill().bfill()
        
        # Chỉ lấy dữ liệu trong khoảng lookback (nến 1h -> lookback_days * 24 nến)
        max_rows = lookback_days * 24
        merged_df = merged_df.tail(max_rows)
        
        # Tính phần trăm thay đổi (returns)
        returns_df = merged_df.pct_change().dropna(how="all")
        
        # Tính tương quan và hiệp phương sai
        self.correlation_matrix = returns_df.corr(method="pearson")
        self.covariance_matrix = returns_df.cov()
        self.last_updated = datetime.now().isoformat()
        
        # Lưu cache
        self.save_cache()
        
        return self.correlation_matrix, self.covariance_matrix

    def get_correlation(self, coin_a: str, coin_b: str) -> float:
        """
        Trả về hệ số tương quan giữa 2 đồng coin.
        Nếu thiếu dữ liệu, lấy giá trị trung bình tương quan ngành.
        """
        coin_a = coin_a.upper()
        coin_b = coin_b.upper()
        
        if coin_a == coin_b:
            return 1.0
            
        # 1. Thử lấy trực tiếp từ ma trận tương quan đã tính
        if self.correlation_matrix is not None and not self.correlation_matrix.empty:
            if coin_a in self.correlation_matrix.index and coin_b in self.correlation_matrix.columns:
                val = self.correlation_matrix.loc[coin_a, coin_b]
                if not np.isnan(val):
                    return float(val)

        # 2. Fallback: Lấy trung bình tương quan nhóm ngành (Sector average correlation)
        return self._get_sector_average_correlation(coin_a, coin_b)

    def _get_sector_average_correlation(self, coin_a: str, coin_b: str) -> float:
        """Tính toán tương quan trung bình giữa 2 Sector đại diện cho coin_a và coin_b."""
        sector_a = SECTOR_MAP.get(coin_a)
        sector_b = SECTOR_MAP.get(coin_b)
        
        # Nếu cả 2 đều không có sector xác định, trả về mặc định
        if not sector_a or not sector_b:
            return DEFAULT_CORRELATION
            
        # Tìm tất cả các coin thuộc sector_a và sector_b có trong ma trận tương quan
        if self.correlation_matrix is None or self.correlation_matrix.empty:
            return DEFAULT_CORRELATION
            
        coins_in_a = [c for c, s in SECTOR_MAP.items() if s == sector_a and c in self.correlation_matrix.index]
        coins_in_b = [c for c, s in SECTOR_MAP.items() if s == sector_b and c in self.correlation_matrix.columns]
        
        corvals = []
        for ca in coins_in_a:
            for cb in coins_in_b:
                if ca == cb:
                    continue
                val = self.correlation_matrix.loc[ca, cb]
                if not np.isnan(val):
                    corvals.append(val)
                    
        if corvals:
            return float(np.mean(corvals))
            
        return DEFAULT_CORRELATION


# Khởi tạo engine toàn cục để chia sẻ tài nguyên
correlation_engine = CorrelationEngine()
