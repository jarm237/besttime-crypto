import numpy as np
import pandas as pd
from typing import Dict, Any, List

class VectorizedEngine:
    """
    Fast vectorized backtesting engine for rapid signal threshold scanning.
    """
    def __init__(self, fee_bps: float = 5.0, slippage_bps: float = 1.0, spread_bps: float = 2.0):
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.spread_bps = spread_bps
        
    def run_backtest(
        self,
        df: pd.DataFrame,
        score_col: str = "signal_score",
        buy_threshold: float = 70.0,
        sell_threshold: float = 30.0,
        holding_period: int = 4
    ) -> Dict[str, Any]:
        """
        Runs a vectorized backtest on a signals DataFrame.
        """
        if df.empty:
            return {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "n_trades": 0}
            
        df = df.copy()
        
        # Determine signals
        df["position"] = 0
        df.loc[df[score_col] >= buy_threshold, "position"] = 1
        df.loc[df[score_col] <= sell_threshold, "position"] = -1
        
        # Forward fill position to simulate holding period (simple simplification)
        df["position"] = df["position"].replace(0, np.nan).ffill(limit=holding_period).fillna(0).astype(int)
        
        # Calculate returns (using 15m return as example)
        ret_col = "return_15m" if "return_15m" in df.columns else None
        if not ret_col:
            # Fallback to close price percent change
            if "close" in df.columns:
                df["ret"] = df["close"].pct_change()
                ret_col = "ret"
            else:
                return {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "n_trades": 0}
                
        # Strategy return (before costs)
        df["strategy_return_raw"] = df["position"].shift(1) * df[ret_col]
        df["strategy_return_raw"] = df["strategy_return_raw"].fillna(0.0)
        
        # Track trades (position changes)
        df["trades"] = df["position"].diff().abs().fillna(0.0)
        n_trades = int(df["trades"].sum())
        
        # Costs: fee + slippage + spread on each transaction
        # Cost per trade in bps
        cost_bps = self.fee_bps + self.slippage_bps + (self.spread_bps / 2.0)
        cost_fraction = cost_bps / 10000.0
        
        # Deduct costs when trades occur
        df["strategy_return"] = df["strategy_return_raw"] - (df["trades"] * cost_fraction)
        
        # Cumulative returns
        df["cum_return"] = (1.0 + df["strategy_return"]).cumprod() - 1.0
        
        total_return = float(df["cum_return"].iloc[-1]) if len(df) > 0 else 0.0
        
        # Sharpe
        std = df["strategy_return"].std()
        mean = df["strategy_return"].mean()
        # Annualized Sharpe (assuming 15m interval: 35040 bars per year)
        sharpe = (mean / std) * np.sqrt(35040) if (std > 0 and len(df) > 1) else 0.0
        
        # Max Drawdown
        df["peak"] = (1.0 + df["strategy_return"]).cumprod().cummax()
        df["drawdown"] = (df["peak"] - (1.0 + df["strategy_return"]).cumprod()) / df["peak"]
        max_dd = float(df["drawdown"].max()) if len(df) > 0 else 0.0
        
        return {
            "total_return": total_return,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "n_trades": n_trades
        }
