import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from btc_scraper.core.db import closed_positions_col

BASE_DIR = Path(__file__).parent.parent

def _unavailable(reason: str, *, base_capital: Any = None) -> dict:
    """Return the only safe result when account-risk state cannot be trusted."""
    equity = float(base_capital) if isinstance(base_capital, (int, float)) and math.isfinite(float(base_capital)) else None
    return {
        "status": "UNAVAILABLE",
        "failure_reason": reason,
        "consecutive_losses": None,
        "drawdown_pct": None,
        "risk_multiplier": 0.0,
        "blocked": True,
        "block_action": "BLOCK_ENTRY",
        "peak_equity": equity,
        "current_equity": equity,
    }


def _parse_observed_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def calculate_risk_metrics(
    base_capital: float = 5000.0,
    trades_cache: list | None = None,
    *,
    data_observed_at: datetime | str | None = None,
    max_data_age_seconds: float | None = None,
    now: datetime | None = None,
) -> dict:
    """Read closed_positions from MongoDB and compute consecutive losses and current drawdown percentage.
    
    Returns a dict:
        consecutive_losses (int)
        drawdown_pct (float)
        risk_multiplier (float)
        blocked (bool)
        peak_equity (float)
        current_equity (float)
    """
    try:
        base_capital = float(base_capital)
    except (TypeError, ValueError):
        return _unavailable("invalid_base_capital", base_capital=base_capital)
    if not math.isfinite(base_capital) or base_capital <= 0:
        return _unavailable("invalid_base_capital", base_capital=base_capital)

    if max_data_age_seconds is not None:
        try:
            observed_at = _parse_observed_at(data_observed_at)
            current_time = now or datetime.now(timezone.utc)
            current_time = _parse_observed_at(current_time)
            age_seconds = (current_time - observed_at).total_seconds()
            if not math.isfinite(float(max_data_age_seconds)) or age_seconds < 0 or age_seconds > float(max_data_age_seconds):
                return _unavailable("drawdown_data_stale", base_capital=base_capital)
        except (TypeError, ValueError):
            return _unavailable("drawdown_timestamp_unavailable", base_capital=base_capital)

    default_res = {
        "status": "HEALTHY",
        "failure_reason": None,
        "consecutive_losses": 0,
        "drawdown_pct": 0.0,
        "risk_multiplier": 1.0,
        "blocked": False,
        "block_action": None,
        "peak_equity": base_capital,
        "current_equity": base_capital,
    }

    try:
        if trades_cache is not None:
            trades = trades_cache
        else:
            # Sort by _id to ensure chronological order (insertion order)
            trades = list(closed_positions_col.find({}, {"_id": 0}).sort("_id", 1))
    except Exception as exc:
        return _unavailable(f"risk_database_unavailable:{type(exc).__name__}", base_capital=base_capital)
        
    if not trades:
        return default_res
        
    # 1. Compute consecutive losses (iterate backwards starting from most recent closed position)
    consecutive_losses = 0
    for t in reversed(trades):
        if not isinstance(t, Mapping):
            return _unavailable("invalid_trade_record", base_capital=base_capital)
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
        if not isinstance(t, Mapping):
            return _unavailable("invalid_trade_record", base_capital=base_capital)
        try:
            pnl = float(t.get("pnl_usd_actual", 0.0))
        except (TypeError, ValueError):
            return _unavailable("invalid_trade_pnl", base_capital=base_capital)
        if not math.isfinite(pnl):
            return _unavailable("invalid_trade_pnl", base_capital=base_capital)
        current_equity += pnl
        if not math.isfinite(current_equity) or current_equity < 0:
            return _unavailable("invalid_equity", base_capital=base_capital)
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
        "status": "HEALTHY",
        "failure_reason": None,
        "consecutive_losses": consecutive_losses,
        "drawdown_pct": round(drawdown_pct, 2),
        "risk_multiplier": risk_multiplier,
        "blocked": blocked,
        "block_action": "BLOCK_ENTRY" if blocked else None,
        "peak_equity": round(peak, 2),
        "current_equity": round(current_equity, 2),
    }
