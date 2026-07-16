"""
btc_scraper/execution/causal_shadow_report.py
Phase 5 — Paper Trading Validation (Task 5.6)

Causal Impact Analysis:
  - Summarizes actual trade decisions and guard outcomes.
  - Compares RL exit shadow recommendations to actual trade exits.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
AUTO_TRADE_LOG = BASE_DIR / "btc_scraper" / "logs" / "auto_trade_log.json"


def load_rl_exit_shadow_predictions(log_dir: Path = LOG_DIR) -> List[Dict[str, Any]]:
    path = log_dir / "rl_exit_shadow_predictions.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_actual_trades(path: Path = AUTO_TRADE_LOG) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def parse_timestamp_str(ts_str: str) -> float:
    """Helper to parse varied ISO/str timestamps into epoch seconds."""
    try:
        # Standard ISO format: 2026-07-11T15:01:23.233032
        # Strip timezones if any for local/UTC parsing consistency
        clean_ts = ts_str.split("+")[0].split("Z")[0]
        if "T" in clean_ts:
            dt = datetime.fromisoformat(clean_ts)
        else:
            dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def analyze_causal_impact(
    rl_shadow_preds: List[Dict[str, Any]],
    actual_trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Summarize actual trade outcomes and RL Exit shadow recommendations.

    The removed Meta prediction-only baseline is no longer used here.
    """
    aligned_pairs = []
    
    # Track metrics
    blocked_by_slippage = 0
    blocked_by_kelly = 0
    blocked_by_correlation = 0
    blocked_by_other = 0

    total_adjustment_value = 0.0
    actual_executed_pnl = 0.0
    for trade in actual_trades:
        status = trade.get("status", "")
        is_skipped = status in ("skipped", "rejected", "rejected_by_guard", "error")
        adjusted_action = "SKIP" if is_skipped else "EXECUTE"

        if is_skipped:
            reason = str(trade.get("reason_skip", "") or trade.get("error", "")).lower()
            if "slippage" in reason:
                blocked_by_slippage += 1
            elif "kelly" in reason:
                blocked_by_kelly += 1
            elif "correlation" in reason or "tuong quan" in reason:
                blocked_by_correlation += 1
            else:
                blocked_by_other += 1
            realized_pnl = 0.0
        else:
            dp = float(trade.get("decision_price") or trade.get("entry_price") or 0.0)
            fp = float(trade.get("avg_fill_price") or trade.get("filled_price") or dp)
            qty = float(trade.get("intended_qty") or 0.0)
            side = str(trade.get("side") or trade.get("direction") or "BUY").upper()
            sign = 1 if side in ("BUY", "LONG") else -1
            realized_pnl = sign * (fp - dp) * qty if dp > 0 and fp > 0 and qty > 0 else 0.0

        actual_executed_pnl += realized_pnl
        aligned_pairs.append({
            "signal_id": trade.get("signal_id") or trade.get("decision_id") or trade.get("order_id") or "",
            "baseline_action": None,
            "adjusted_action": adjusted_action,
            "baseline_simulated_pnl": None,
            "adjusted_realized_pnl": round(realized_pnl, 4),
            "adjustment_value": None,
        })

    rl_exits = [p for p in rl_shadow_preds if p.get("action_label") == "EXIT"]

    return {
        "summary": {
            "total_signals_emitted": 0,
            "actual_trades_logged": len(actual_trades),
            "matched_aligned_decisions": len(aligned_pairs),
            "rl_exit_shadow_recommendations": len(rl_exits),
        },
        "blocked_reasons": {
            "slippage_guard": blocked_by_slippage,
            "kelly_fraction_limit": blocked_by_kelly,
            "correlation_filter": blocked_by_correlation,
            "other": blocked_by_other,
        },
        "performance_impact": {
            "actual_pnl_usdt": round(actual_executed_pnl, 4),
            "counterfactual_baseline_pnl_usdt": 0.0,
            "net_benefit_usdt": round(total_adjustment_value, 4),
            "benefit_description": "Meta prediction-only baseline has been removed; net benefit is not estimated here.",
        },
        "aligned_decisions": aligned_pairs[:20], # limit sample for JSON reports
    }


def run_causal_shadow_analysis() -> Dict[str, Any]:
    rl_shadow = load_rl_exit_shadow_predictions()
    actual = load_actual_trades()
    return analyze_causal_impact(rl_shadow, actual)
