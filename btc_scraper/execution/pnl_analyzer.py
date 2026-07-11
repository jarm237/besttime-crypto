"""
btc_scraper/execution/pnl_analyzer.py
Phase 5 — Paper Trading Validation (Task 5.3)

Gross vs Net PnL Analysis:
  - Decomposes: fees, spread cost, slippage, latency drift
  - Computes gross and net PnL per fill pair (open+close)
  - Cost drag %
  - Summary statistics
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class FillCostBreakdown:
    """Cost breakdown for a single fill (one-sided: open or close)."""
    execution_id: str = ""
    coin: str = ""
    side: str = ""
    timestamp: str = ""

    # Notional
    intended_notional_usdt: float = 0.0
    filled_notional_usdt: float = 0.0   # avg_fill_price * filled_qty

    # Cost components (all in USDT absolute)
    fee_usdt: float = 0.0
    spread_cost_usdt: float = 0.0        # spread_bps / 2 * notional / 10000
    slippage_cost_usdt: float = 0.0      # realized_slippage_bps * notional / 10000
    latency_drift_usdt: float = 0.0      # latency_ms * 0.001 bps estimate

    # Cost components in bps
    fee_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    latency_bps: float = 0.0

    # Total transaction cost
    total_cost_usdt: float = 0.0
    total_cost_bps: float = 0.0
    cost_drag_pct: float = 0.0           # total_cost / gross_pnl (if applicable)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_fill_cost(fill: Dict[str, Any]) -> FillCostBreakdown:
    """Decompose a single fill into its cost components."""
    bd = FillCostBreakdown(
        execution_id=fill.get("execution_id", ""),
        coin=fill.get("coin", ""),
        side=str(fill.get("side", "BUY")).upper(),
        timestamp=fill.get("timestamp", ""),
    )

    dp = float(fill.get("decision_price") or 0.0)
    fp = float(fill.get("avg_fill_price") or 0.0)
    qty = float(fill.get("filled_qty") or 0.0)
    intended_notional = float(fill.get("intended_notional") or 0.0)

    if fp <= 0 or qty <= 0:
        return bd

    filled_notional = fp * qty
    bd.intended_notional_usdt = intended_notional
    bd.filled_notional_usdt = filled_notional

    notional = filled_notional if filled_notional > 0 else intended_notional
    if notional <= 0:
        return bd

    # ── Fee ──
    fee = float(fill.get("fee") or 0.0)
    bd.fee_usdt = fee
    bd.fee_bps = fee / notional * 10_000.0

    # ── Spread cost (half-spread paid to cross) ──
    spread_bps_submit = float(fill.get("spread_bps_at_submit") or 0.0)
    bd.spread_bps = spread_bps_submit / 2.0
    bd.spread_cost_usdt = bd.spread_bps / 10_000.0 * notional

    # ── Slippage cost ──
    expected_bps = float(fill.get("expected_slippage_bps") or 0.0)
    if dp > 0 and fp > 0:
        is_buy = bd.side in ("BUY", "LONG")
        sign = 1 if is_buy else -1
        realized_bps = max(0.0, sign * (fp - dp) / dp * 10_000.0)
    else:
        realized_bps = float(fill.get("submit_to_fill_slippage_bps") or 0.0)

    bd.slippage_bps = realized_bps
    bd.slippage_cost_usdt = realized_bps / 10_000.0 * notional

    # ── Latency drift ──
    latency_ms = int(fill.get("latency_ms") or 0)
    bd.latency_bps = latency_ms * 0.001   # rough: 1ms ≈ 0.001 bps
    bd.latency_drift_usdt = bd.latency_bps / 10_000.0 * notional

    # ── Total ──
    bd.total_cost_usdt = round(
        bd.fee_usdt + bd.spread_cost_usdt + bd.slippage_cost_usdt + bd.latency_drift_usdt, 6
    )
    bd.total_cost_bps = round(
        bd.fee_bps + bd.spread_bps + bd.slippage_bps + bd.latency_bps, 4
    )

    return bd


@dataclass
class PnLRecord:
    """Simulated round-trip PnL (single fill acting as entry; no close yet)."""
    execution_id: str = ""
    coin: str = ""
    side: str = ""
    timestamp: str = ""

    gross_pnl_usdt: float = 0.0          # Before any costs
    total_cost_usdt: float = 0.0
    net_pnl_usdt: float = 0.0            # gross - costs
    cost_drag_pct: float = 0.0           # cost / notional * 100

    fee_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    latency_bps: float = 0.0
    total_cost_bps: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_pnl_from_fills(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compute per-fill cost breakdown and net PnL estimate.

    Since paper fills are one-directional (no paired close), gross_pnl is
    estimated as the positive drift from decision_price to avg_fill_price
    in the favourable direction (or 0 if adverse).
    """
    records = []
    for fill in fills:
        if fill.get("status", "") != "FILLED":
            continue

        cost = compute_fill_cost(fill)

        dp = float(fill.get("decision_price") or 0.0)
        fp = float(fill.get("avg_fill_price") or 0.0)
        qty = float(fill.get("filled_qty") or 0.0)
        is_buy = cost.side in ("BUY", "LONG")

        if dp > 0 and fp > 0 and qty > 0:
            pnl_per_unit = (fp - dp) if is_buy else (dp - fp)
            gross_pnl = pnl_per_unit * qty
        else:
            gross_pnl = 0.0

        net_pnl = gross_pnl - cost.total_cost_usdt
        notional = cost.filled_notional_usdt or 1.0
        cost_drag_pct = cost.total_cost_usdt / notional * 100.0

        rec = PnLRecord(
            execution_id=cost.execution_id,
            coin=cost.coin,
            side=cost.side,
            timestamp=cost.timestamp,
            gross_pnl_usdt=round(gross_pnl, 6),
            total_cost_usdt=round(cost.total_cost_usdt, 6),
            net_pnl_usdt=round(net_pnl, 6),
            cost_drag_pct=round(cost_drag_pct, 4),
            fee_bps=round(cost.fee_bps, 4),
            spread_bps=round(cost.spread_bps, 4),
            slippage_bps=round(cost.slippage_bps, 4),
            latency_bps=round(cost.latency_bps, 4),
            total_cost_bps=round(cost.total_cost_bps, 4),
        )
        records.append(rec.to_dict())

    return records


def aggregate_pnl_stats(pnl_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate PnL and cost stats across all fills."""
    if not pnl_records:
        return {}

    n = len(pnl_records)
    gross_pnl = [r["gross_pnl_usdt"] for r in pnl_records]
    net_pnl = [r["net_pnl_usdt"] for r in pnl_records]
    costs = [r["total_cost_usdt"] for r in pnl_records]
    cost_bps = [r["total_cost_bps"] for r in pnl_records]
    fee_bps = [r["fee_bps"] for r in pnl_records]
    slippage_bps = [r["slippage_bps"] for r in pnl_records]
    spread_bps = [r["spread_bps"] for r in pnl_records]
    latency_bps = [r["latency_bps"] for r in pnl_records]
    cost_drag_pct = [r["cost_drag_pct"] for r in pnl_records]

    def _avg(lst: List[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "n_fills": n,
        "total_gross_pnl_usdt": round(sum(gross_pnl), 4),
        "total_net_pnl_usdt": round(sum(net_pnl), 4),
        "total_cost_usdt": round(sum(costs), 4),
        "avg_gross_pnl_usdt": round(_avg(gross_pnl), 4),
        "avg_net_pnl_usdt": round(_avg(net_pnl), 4),
        "avg_cost_drag_pct": round(_avg(cost_drag_pct), 4),
        "cost_breakdown_bps": {
            "avg_fee_bps": round(_avg(fee_bps), 4),
            "avg_spread_bps": round(_avg(spread_bps), 4),
            "avg_slippage_bps": round(_avg(slippage_bps), 4),
            "avg_latency_bps": round(_avg(latency_bps), 4),
            "avg_total_cost_bps": round(_avg(cost_bps), 4),
        },
        "pnl_win_rate_pct": round(
            sum(1 for p in net_pnl if p > 0) / n * 100, 2
        ),
    }


def run_pnl_analysis(fills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full PnL analysis pipeline for Phase 5."""
    pnl_records = compute_pnl_from_fills(fills)
    overall = aggregate_pnl_stats(pnl_records)

    # Break down by coin
    by_coin: Dict[str, List] = {}
    for r in pnl_records:
        c = r.get("coin", "UNK")
        by_coin.setdefault(c, []).append(r)

    coin_stats = {c: aggregate_pnl_stats(recs) for c, recs in by_coin.items()}

    return {
        "overall": overall,
        "by_coin": coin_stats,
        "records": pnl_records,
    }
