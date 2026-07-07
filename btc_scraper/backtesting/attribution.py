from typing import List, Dict, Any
import pandas as pd

class AttributionAnalyzer:
    """
    Categorizes backtest outcomes by different metadata dimensions.
    """
    
    DIMENSIONS = [
        "coin",
        "type",  # direction (LONG/SHORT)
        "regime",
        "causal_risk_level",
        "meta_confidence_bucket"
    ]

    @classmethod
    def analyze(cls, trade_log: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not trade_log:
            return {}
            
        df = pd.DataFrame(trade_log)
        attribution_results = {}
        
        for dim in cls.DIMENSIONS:
            if dim not in df.columns:
                continue
                
            dim_results = {}
            grouped = df.groupby(dim)
            
            for key, group in grouped:
                n_trades = len(group)
                wins = group[group["pnl"] > 0]
                losses = group[group["pnl"] <= 0]
                
                n_wins = len(wins)
                win_rate = n_wins / n_trades if n_trades > 0 else 0.0
                
                total_pnl = float(group["pnl"].sum())
                avg_pnl = float(group["pnl"].mean())
                
                gross_profit = float(wins["pnl"].sum())
                gross_loss = float(abs(losses["pnl"].sum()))
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
                
                dim_results[str(key)] = {
                    "n_trades": n_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "avg_pnl": avg_pnl,
                    "profit_factor": profit_factor
                }
                
            attribution_results[dim] = dim_results
            
        return attribution_results
