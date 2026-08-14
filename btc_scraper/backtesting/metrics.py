import numpy as np
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime

def calculate_metrics(
    trade_log: List[Dict[str, Any]],
    equity_history: List[Dict[str, Any]],
    initial_capital: float,
    timeframe: str = "15m"
) -> Dict[str, Any]:
    """
    Computes professional performance metrics from trade logs and equity curve.
    """
    if not equity_history:
        return {}

    # 1. Equity history processing
    df_eq = pd.DataFrame(equity_history)
    df_eq["time"] = pd.to_datetime(df_eq["time"])
    df_eq.set_index("time", inplace=True)
    
    # Calculate daily returns
    df_daily = df_eq.resample("D").last().ffill()
    df_daily["returns"] = df_daily["equity"].pct_change()
    
    total_days = (df_eq.index[-1] - df_eq.index[0]).days
    years = total_days / 365.25 if total_days > 0 else 0.0
    
    final_capital = df_eq["equity"].iloc[-1]
    total_return = (final_capital - initial_capital) / initial_capital
    
    if years > 0 and final_capital > 0:
        annualized_return = (final_capital / initial_capital) ** (1.0 / years) - 1.0
    else:
        annualized_return = total_return
        
    # Volatility & Sharpe
    daily_returns = df_daily["returns"].dropna()
    volatility = daily_returns.std() * np.sqrt(365) if len(daily_returns) > 1 else 0.0
    
    mean_daily = daily_returns.mean() if len(daily_returns) > 0 else 0.0
    std_daily = daily_returns.std() if len(daily_returns) > 1 else 0.0
    
    sharpe = (mean_daily / std_daily) * np.sqrt(365) if std_daily > 0 else 0.0
    
    # Downside risk for Sortino
    downside_returns = daily_returns[daily_returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0.0
    sortino = (mean_daily / downside_std) * np.sqrt(365) if downside_std > 0 else 0.0
    
    # Drawdown
    df_eq["peak"] = df_eq["equity"].cummax()
    df_eq["drawdown"] = (df_eq["peak"] - df_eq["equity"]) / df_eq["peak"]
    max_drawdown = float(df_eq["drawdown"].max())
    
    # Calmar
    calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

    # 2. Trade statistics
    n_trades = len(trade_log)
    if n_trades == 0:
        return {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "volatility": volatility,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_drawdown,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "n_trades": 0,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "cost_drag": 0.0
        }
        
    df_trades = pd.DataFrame(trade_log)
    
    # Win rate & counts
    wins_df = df_trades[df_trades["pnl"] > 0]
    losses_df = df_trades[df_trades["pnl"] <= 0]
    
    n_wins = len(wins_df)
    n_losses = len(losses_df)
    win_rate = n_wins / n_trades if n_trades > 0 else 0.0
    
    avg_win = float(wins_df["pnl"].mean()) if n_wins > 0 else 0.0
    avg_loss = float(abs(losses_df["pnl"].mean())) if n_losses > 0 else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    gross_profit = float(wins_df["pnl"].sum())
    gross_loss = float(abs(losses_df["pnl"].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    
    # Expectancy
    expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
    
    # Fee, spread, slippage drags
    avg_fee_bps = float(df_trades["fee_bps"].mean()) if "fee_bps" in df_trades else 0.0
    avg_spread_bps = float(df_trades["spread_bps"].mean()) if "spread_bps" in df_trades else 0.0
    avg_slippage_bps = float(df_trades["slippage_bps"].mean()) if "slippage_bps" in df_trades else 0.0
    avg_latency_ms = float(df_trades["latency_ms"].mean()) if "latency_ms" in df_trades else 0.0
    
    total_fees = float(df_trades["fee_paid"].sum()) if "fee_paid" in df_trades else 0.0
    total_slippage_cost = float(df_trades["slippage_paid"].sum()) if "slippage_paid" in df_trades else 0.0
    total_spread_cost = float(df_trades["spread_paid"].sum()) if "spread_paid" in df_trades else 0.0
    
    net_pnl = float(df_trades["pnl"].sum())
    market_impact_attribution = total_slippage_cost + total_spread_cost
    total_costs = total_fees + market_impact_attribution
    # Fill prices already include spread and slippage. They are attribution
    # metrics, not additional ledger debits.
    gross_pnl = net_pnl + total_fees
    reference_gross_pnl = gross_pnl + market_impact_attribution
    cost_drag = total_costs / reference_gross_pnl if reference_gross_pnl > 0 else 0.0
    
    # Exposure time: bars occupied
    exposure_bars = sum(df_trades["hold_bars"]) if "hold_bars" in df_trades else 0
    total_candles = len(equity_history)
    exposure_time = exposure_bars / total_candles if total_candles > 0 else 0.0
    
    # Hold times
    avg_hold_time = float(df_trades["hold_bars"].mean()) if "hold_bars" in df_trades else 0.0
    median_hold_time = float(df_trades["hold_bars"].median()) if "hold_bars" in df_trades else 0.0
    
    # Hit rates
    tp1_hits = len(df_trades[df_trades["result"].str.contains("TP1|TP2", na=False)])
    tp1_hit_rate = tp1_hits / n_trades if n_trades > 0 else 0.0
    tp2_hits = len(df_trades[df_trades["result"].str.contains("TP2", na=False)])
    tp2_hit_rate = tp2_hits / n_trades if n_trades > 0 else 0.0
    sl_hits = len(df_trades[df_trades["result"].str.contains("SL", na=False)])
    sl_hit_rate = sl_hits / n_trades if n_trades > 0 else 0.0
    timeout_hits = len(df_trades[df_trades["result"].str.contains("TIMEOUT|EXIT_SIGNAL", na=False)])
    timeout_rate = timeout_hits / n_trades if n_trades > 0 else 0.0

    return {
        # Core
        "total_return": total_return,
        "annualized_return": annualized_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "exposure_time": exposure_time,
        "n_trades": n_trades,
        "trades_per_day": n_trades / total_days if total_days > 0 else 0.0,
        
        # Hold
        "avg_hold_time": avg_hold_time,
        "median_hold_time": median_hold_time,
        "tp1_hit_rate": tp1_hit_rate,
        "tp2_hit_rate": tp2_hit_rate,
        "sl_hit_rate": sl_hit_rate,
        "timeout_rate": timeout_rate,
        
        # Execution
        "avg_fee_bps": avg_fee_bps,
        "avg_spread_bps": avg_spread_bps,
        "avg_slippage_bps": avg_slippage_bps,
        "avg_latency_ms": avg_latency_ms,
        "gross_pnl": gross_pnl,
        "reference_gross_pnl": reference_gross_pnl,
        "net_pnl": net_pnl,
        "total_fees": total_fees,
        "total_slippage_attribution": total_slippage_cost,
        "total_spread_attribution": total_spread_cost,
        "total_costs": total_costs,
        "cost_drag": cost_drag
    }
