"""
btc_scraper/execution/slippage_analysis.py
Phase 5 — Paper Trading Validation (Task 5.2)

Expected vs Realized Slippage Analysis:
  - MAE, RMSE
  - P50, P90, P95 percentiles
  - Bias by coin / order type / regime
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Return the p-th percentile (0–100) of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def compute_slippage_errors(
    fills: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    For each fill, compute:
      - realized_slippage_bps: |avg_fill_price - decision_price| / decision_price * 10000
      - expected_slippage_bps: from fill record
      - error_bps: realized - expected
      - abs_error_bps: |error|
    """
    results = []
    for f in fills:
        dp = float(f.get("decision_price") or 0.0)
        fp = float(f.get("avg_fill_price") or 0.0)
        expected = float(f.get("expected_slippage_bps") or 0.0)

        if dp <= 0 or fp <= 0:
            continue

        side = str(f.get("side", "BUY")).upper()
        sign = 1 if side in ("BUY", "LONG") else -1
        realized = sign * (fp - dp) / dp * 10_000.0
        # Slippage magnitude (always ≥ 0 for cost purposes)
        realized_abs = max(0.0, realized)

        error = realized_abs - expected
        results.append({
            "execution_id": f.get("execution_id", ""),
            "coin": f.get("coin", ""),
            "side": side,
            "order_type": f.get("order_type", "MARKET"),
            "regime": f.get("regime", "UNKNOWN"),
            "guard_action": f.get("guard_action", ""),
            "synthetic": f.get("synthetic", False),
            "decision_price": dp,
            "avg_fill_price": fp,
            "expected_slippage_bps": round(expected, 4),
            "realized_slippage_bps": round(realized_abs, 4),
            "slippage_error_bps": round(error, 4),
            "abs_error_bps": round(abs(error), 4),
        })
    return results


def aggregate_slippage_stats(
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute aggregate slippage accuracy statistics.
    """
    if not errors:
        return {}

    abs_errs = [e["abs_error_bps"] for e in errors]
    realized = [e["realized_slippage_bps"] for e in errors]
    expected = [e["expected_slippage_bps"] for e in errors]
    signed_errs = [e["slippage_error_bps"] for e in errors]

    n = len(abs_errs)
    mae = sum(abs_errs) / n
    rmse = math.sqrt(sum(x ** 2 for x in abs_errs) / n)
    bias = sum(signed_errs) / n   # positive = underestimate

    s_abs_err = sorted(abs_errs)
    s_realized = sorted(realized)

    stats: Dict[str, Any] = {
        "n_fills": n,
        "mae_bps": round(mae, 4),
        "rmse_bps": round(rmse, 4),
        "bias_bps": round(bias, 4),
        "realized_slippage": {
            "p50_bps": round(_percentile(s_realized, 50), 4),
            "p90_bps": round(_percentile(s_realized, 90), 4),
            "p95_bps": round(_percentile(s_realized, 95), 4),
            "mean_bps": round(sum(realized) / n, 4),
            "max_bps": round(max(realized), 4),
        },
        "abs_error": {
            "p50_bps": round(_percentile(s_abs_err, 50), 4),
            "p90_bps": round(_percentile(s_abs_err, 90), 4),
            "p95_bps": round(_percentile(s_abs_err, 95), 4),
        },
        "avg_expected_bps": round(sum(expected) / n, 4),
        "avg_realized_bps": round(sum(realized) / n, 4),
    }

    return stats


def slippage_bias_by_group(
    errors: List[Dict[str, Any]],
    group_key: str = "coin",
) -> Dict[str, Dict[str, Any]]:
    """
    Break down MAE and bias by a grouping key (coin, order_type, regime).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in errors:
        key = str(e.get(group_key, "UNKNOWN"))
        groups.setdefault(key, []).append(e)

    result: Dict[str, Dict[str, Any]] = {}
    for key, group_errors in groups.items():
        n = len(group_errors)
        abs_errs = [e["abs_error_bps"] for e in group_errors]
        signed = [e["slippage_error_bps"] for e in group_errors]
        realized = [e["realized_slippage_bps"] for e in group_errors]
        result[key] = {
            "n": n,
            "mae_bps": round(sum(abs_errs) / n, 4),
            "bias_bps": round(sum(signed) / n, 4),
            "avg_realized_bps": round(sum(realized) / n, 4),
            "max_realized_bps": round(max(realized), 4),
            "rmse_bps": round(math.sqrt(sum(x ** 2 for x in abs_errs) / n), 4),
        }

    return result


def run_slippage_analysis(
    fills: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Full slippage analysis pipeline — call with fills from PaperTradingValidator.

    Returns report dict compatible with Phase5ReportGenerator.
    """
    errors = compute_slippage_errors(fills)
    overall = aggregate_slippage_stats(errors)
    by_coin = slippage_bias_by_group(errors, "coin")
    by_order_type = slippage_bias_by_group(errors, "order_type")
    by_regime = slippage_bias_by_group(errors, "regime")

    # Acceptance check: MAE ≤ 10 bps
    mae = overall.get("mae_bps", 999.0)
    criterion_pass = mae <= 10.0

    return {
        "overall": overall,
        "by_coin": by_coin,
        "by_order_type": by_order_type,
        "by_regime": by_regime,
        "acceptance": {
            "slippage_mae_le_10bps": criterion_pass,
            "slippage_mae_bps": mae,
        },
    }
