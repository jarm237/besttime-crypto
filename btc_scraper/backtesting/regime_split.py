from typing import List, Dict, Any
import pandas as pd
import numpy as np

class RegimeSplitAnalyzer:
    """
    Groups backtest trade outcomes by market regime and calculates metrics.
    """
    @staticmethod
    def analyze(trade_log: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not trade_log:
            return {}
            
        df = pd.DataFrame(trade_log)
        if "regime" not in df.columns:
            df["regime"] = "Unknown"
            
        results = {}
        grouped = df.groupby("regime")
        
        for regime, group in grouped:
            n_trades = len(group)
            wins = group[group["pnl"] > 0]
            losses = group[group["pnl"] <= 0]
            
            n_wins = len(wins)
            win_rate = n_wins / n_trades if n_trades > 0 else 0.0
            
            avg_pnl = float(group["pnl"].mean())
            total_pnl = float(group["pnl"].sum())
            
            gross_profit = float(wins["pnl"].sum())
            gross_loss = float(abs(losses["pnl"].sum()))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
            
            # Simple Sharpe based on trade PnLs in this regime
            pnl_std = group["pnl"].std()
            sharpe = (avg_pnl / pnl_std) * np.sqrt(252) if (pnl_std > 0 and len(group) > 1) else 0.0
            
            avg_hold = float(group["hold_bars"].mean()) if "hold_bars" in group.columns else 0.0
            
            results[str(regime)] = {
                "n_trades": n_trades,
                "win_rate": win_rate,
                "avg_return": avg_pnl,
                "total_return": total_pnl,
                "profit_factor": profit_factor,
                "sharpe": sharpe,
                "avg_hold_time": avg_hold
            }
            
        return results
