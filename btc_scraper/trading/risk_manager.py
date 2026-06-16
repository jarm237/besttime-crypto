from pathlib import Path
from btc_scraper.core.db import closed_positions_col

BASE_DIR = Path(__file__).parent.parent

def calculate_risk_metrics(base_capital: float = 5000.0, trades_cache: list = None) -> dict:
    """Read closed_positions from MongoDB and compute consecutive losses and current drawdown percentage.
    
    Returns a dict:
        consecutive_losses (int)
        drawdown_pct (float)
        risk_multiplier (float)
        blocked (bool)
        peak_equity (float)
        current_equity (float)
    """
    default_res = {
        "consecutive_losses": 0,
        "drawdown_pct": 0.0,
        "risk_multiplier": 1.0,
        "blocked": False,
        "peak_equity": base_capital,
        "current_equity": base_capital,
    }

    try:
        if trades_cache is not None:
            trades = trades_cache
        else:
            # Sort by _id to ensure chronological order (insertion order)
            trades = list(closed_positions_col.find({}, {"_id": 0}).sort("_id", 1))
    except Exception:
        return default_res
        
    if not trades:
        return default_res
        
    # 1. Compute consecutive losses (iterate backwards starting from most recent closed position)
    consecutive_losses = 0
    for t in reversed(trades):
        res = str(t.get("result", "")).upper()
        # manual trades might have result status, ignore BREAKEVEN
        if res == "LOSS":
            consecutive_losses += 1
        elif res == "WIN":
            break
        
    # 2. Reconstruct equity curve to compute drawdown
    current_equity = base_capital
    equity_history = [current_equity]
    
    for t in trades:
        pnl = float(t.get("pnl_usd_actual", 0.0))
        current_equity += pnl
        equity_history.append(current_equity)
        
    peak = max(equity_history)
    drawdown_pct = 0.0
    if peak > 0:
        drawdown_pct = (peak - current_equity) / peak * 100.0
        
    # 3. Apply risk rules
    risk_multiplier = 1.0
    blocked = False
    
    # Rule 1: Consecutive losses
    if consecutive_losses >= 3:
        risk_multiplier = 0.5
        
    # Rule 2: Drawdown limits
    if drawdown_pct >= 10.0:
        blocked = True
        
    return {
        "consecutive_losses": consecutive_losses,
        "drawdown_pct": round(drawdown_pct, 2),
        "risk_multiplier": risk_multiplier,
        "blocked": blocked,
        "peak_equity": round(peak, 2),
        "current_equity": round(current_equity, 2),
    }
