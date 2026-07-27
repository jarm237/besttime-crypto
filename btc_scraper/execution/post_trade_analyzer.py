"""
btc_scraper/execution/post_trade_analyzer.py
Phase 10 – Sprint 10.7: Post-Trade Analyzer

Computes implementation shortfall and decomposes execution cost
for every filled ExecutionRecord.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
from datetime import datetime, timezone

from btc_scraper.core.paths import build_execution_data_path


@dataclass
class ExecutionCostBreakdown:
    execution_id: str = ""
    coin: str = ""
    side: str = ""
    timestamp: str = ""

    # Prices
    decision_price: float = 0.0
    avg_fill_price: float = 0.0

    # Implementation shortfall (bps)
    # IS = (avg_fill - decision_price) / decision_price * 10000  [for BUY]
    # IS = (decision_price - avg_fill) / decision_price * 10000  [for SELL]
    implementation_shortfall_bps: float = 0.0

    # Component breakdown (bps)
    spread_cost_bps: float = 0.0
    slippage_cost_bps: float = 0.0
    fee_cost_bps: float = 0.0
    latency_drift_bps: float = 0.0
    opportunity_cost_bps: float = 0.0

    # Slippage model accuracy
    expected_slippage_bps: float = 0.0
    realized_slippage_bps: float = 0.0
    slippage_prediction_error_bps: float = 0.0

    # Quality rating
    quality_score: float = 0.0     # 0–100 (100 = perfect)
    quality_label: str = ""         # "EXCELLENT" | "GOOD" | "POOR"


class PostTradeAnalyzer:
    """
    Analyzes completed execution records to generate quality metrics.
    """

    # Threshold for a "good" execution (bps)
    SHORTFALL_EXCELLENT_BPS: float = 5.0
    SHORTFALL_GOOD_BPS: float = 15.0

    def __init__(self, reports_dir: str | None = None):
        self.reports_dir = Path(reports_dir) if reports_dir is not None else build_execution_data_path("reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, record: Dict[str, Any]) -> ExecutionCostBreakdown:
        """
        Compute full execution cost breakdown from a fill record dict.
        """
        breakdown = ExecutionCostBreakdown(
            execution_id=record.get("execution_id", ""),
            coin=record.get("coin", ""),
            side=record.get("side", ""),
            timestamp=record.get("timestamp", ""),
            decision_price=record.get("decision_price", 0.0),
            avg_fill_price=record.get("avg_fill_price", 0.0),
        )

        dp = breakdown.decision_price
        fp = breakdown.avg_fill_price
        is_buy = breakdown.side.upper() in ("BUY", "LONG")

        if dp <= 0:
            return breakdown

        # ── Implementation shortfall ──────────────────────────────────────
        # Positive = slippage cost (paid more to buy / received less to sell)
        sign = 1 if is_buy else -1
        breakdown.implementation_shortfall_bps = sign * (fp - dp) / dp * 10_000.0

        # ── Fee cost ──────────────────────────────────────────────────────
        fee = record.get("fee", 0.0)
        notional = record.get("intended_notional", fp * record.get("intended_qty", 0.0))
        breakdown.fee_cost_bps = (fee / notional * 10_000.0) if notional > 0 else 0.0

        # ── Spread cost ───────────────────────────────────────────────────
        breakdown.spread_cost_bps = record.get("spread_bps_at_submit", 0.0) / 2.0

        # ── Latency drift ─────────────────────────────────────────────────
        latency_ms = record.get("latency_ms", 0)
        # Rough estimate: 1ms latency ≈ 0.001 bps for BTC-level volatility
        breakdown.latency_drift_bps = latency_ms * 0.001

        # ── Slippage cost (IS minus spread and fee)  ──────────────────────
        breakdown.slippage_cost_bps = max(0.0,
            breakdown.implementation_shortfall_bps
            - breakdown.spread_cost_bps
            - breakdown.fee_cost_bps
            - breakdown.latency_drift_bps
        )

        # ── Expected vs realized slippage ─────────────────────────────────
        breakdown.expected_slippage_bps = record.get("expected_slippage_bps", 0.0)
        breakdown.realized_slippage_bps = breakdown.slippage_cost_bps
        breakdown.slippage_prediction_error_bps = (
            breakdown.realized_slippage_bps - breakdown.expected_slippage_bps
        )

        # ── Quality rating ────────────────────────────────────────────────
        is_bps = abs(breakdown.implementation_shortfall_bps)
        if is_bps <= self.SHORTFALL_EXCELLENT_BPS:
            breakdown.quality_score = 100.0 - is_bps * 4.0
            breakdown.quality_label = "EXCELLENT"
        elif is_bps <= self.SHORTFALL_GOOD_BPS:
            breakdown.quality_score = 80.0 - (is_bps - self.SHORTFALL_EXCELLENT_BPS) * 2.0
            breakdown.quality_label = "GOOD"
        else:
            breakdown.quality_score = max(0.0, 60.0 - (is_bps - self.SHORTFALL_GOOD_BPS))
            breakdown.quality_label = "POOR"

        return breakdown

    def analyze_batch(self, records: List[Dict[str, Any]]) -> List[ExecutionCostBreakdown]:
        return [self.analyze(r) for r in records]

    def generate_report(
        self,
        records: List[Dict[str, Any]],
        report_name: str = None,
    ) -> Dict[str, Any]:
        """
        Generates an aggregate execution quality report from a list of records.
        """
        breakdowns = self.analyze_batch(records)
        if not breakdowns:
            return {}

        by_coin: Dict[str, List[ExecutionCostBreakdown]] = {}
        for b in breakdowns:
            by_coin.setdefault(b.coin, []).append(b)

        coin_stats = {}
        for coin, bds in by_coin.items():
            is_vals = [abs(b.implementation_shortfall_bps) for b in bds]
            slip_err = [b.slippage_prediction_error_bps for b in bds]
            coin_stats[coin] = {
                "n_fills": len(bds),
                "avg_is_bps": round(sum(is_vals) / len(is_vals), 3),
                "max_is_bps": round(max(is_vals), 3),
                "p95_is_bps": round(sorted(is_vals)[int(len(is_vals) * 0.95)], 3),
                "avg_slippage_prediction_error_bps": round(sum(slip_err) / len(slip_err), 3),
                "pct_excellent": round(sum(1 for b in bds if b.quality_label == "EXCELLENT") / len(bds) * 100, 1),
                "pct_good": round(sum(1 for b in bds if b.quality_label == "GOOD") / len(bds) * 100, 1),
                "pct_poor": round(sum(1 for b in bds if b.quality_label == "POOR") / len(bds) * 100, 1),
            }

        all_is = [abs(b.implementation_shortfall_bps) for b in breakdowns]
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_total_fills": len(breakdowns),
            "avg_implementation_shortfall_bps": round(sum(all_is) / len(all_is), 3) if all_is else 0,
            "p95_implementation_shortfall_bps": round(sorted(all_is)[int(len(all_is) * 0.95)], 3) if all_is else 0,
            "by_coin": coin_stats,
        }

        # Save report to disk
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        fname = report_name or f"execution_quality_{date_str}.json"
        out_path = self.reports_dir / fname
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        return report

    def generate_phase5_report(
        self,
        exec_records: List[Dict[str, Any]],
        fills: List[Dict[str, Any]],
        report_name: str = None,
    ) -> Dict[str, Any]:
        """
        Generates Phase 5 compliance/acceptance report with execution metrics.
        - Reject rate
        - Fill rate
        - Partial fill rate
        - Latency percentiles
        - Implementation shortfall percentiles
        """
        total_orders = len(exec_records)
        rejected = sum(1 for r in exec_records if r.get("status") == "REJECTED")
        filled = sum(1 for r in exec_records if r.get("status") == "FILLED")
        partial = sum(1 for r in exec_records if r.get("status") == "PARTIAL_FILL")

        reject_rate = rejected / total_orders if total_orders > 0 else 0.0
        fill_rate = filled / total_orders if total_orders > 0 else 0.0
        partial_fill_rate = partial / total_orders if total_orders > 0 else 0.0

        latencies = [r.get("latency_ms", 0) for r in exec_records if r.get("latency_ms") is not None]
        latencies.sort()
        n_lat = len(latencies)
        mean_latency = sum(latencies) / n_lat if n_lat > 0 else 0.0
        p50_latency = latencies[int(n_lat * 0.5)] if n_lat > 0 else 0.0
        p90_latency = latencies[int(n_lat * 0.9)] if n_lat > 0 else 0.0
        p95_latency = latencies[int(n_lat * 0.95)] if n_lat > 0 else 0.0
        max_latency = max(latencies) if n_lat > 0 else 0.0

        breakdowns = self.analyze_batch(fills)
        is_vals = [abs(b.implementation_shortfall_bps) for b in breakdowns]
        is_vals.sort()
        n_is = len(is_vals)
        mean_is = sum(is_vals) / n_is if n_is > 0 else 0.0
        p50_is = is_vals[int(n_is * 0.5)] if n_is > 0 else 0.0
        p90_is = is_vals[int(n_is * 0.9)] if n_is > 0 else 0.0
        p95_is = is_vals[int(n_is * 0.95)] if n_is > 0 else 0.0
        max_is = max(is_vals) if n_is > 0 else 0.0

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_total_attempts": total_orders,
            "n_filled": filled,
            "n_rejected": rejected,
            "n_partial_fill": partial,
            "reject_rate_pct": round(reject_rate * 100, 2),
            "fill_rate_pct": round(fill_rate * 100, 2),
            "partial_fill_rate_pct": round(partial_fill_rate * 100, 2),
            "latency": {
                "mean_ms": round(mean_latency, 2),
                "p50_ms": p50_latency,
                "p90_ms": p90_latency,
                "p95_ms": p95_latency,
                "max_ms": max_latency,
            },
            "implementation_shortfall_bps": {
                "mean_bps": round(mean_is, 3),
                "p50_bps": round(p50_is, 3),
                "p90_bps": round(p90_is, 3),
                "p95_bps": round(p95_is, 3),
                "max_bps": round(max_is, 3),
            },
            "acceptance": {
                "reject_rate_le_20": reject_rate <= 0.20,
                "fill_rate_ge_80": fill_rate >= 0.80,
                "shortfall_mae_le_10": mean_is <= 10.0,
            }
        }

        # Save report to reports_dir
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        fname = report_name or f"execution_quality_phase5_{date_str}.json"
        out_path = self.reports_dir / fname
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        return report

    def format_summary(self, breakdown: ExecutionCostBreakdown) -> str:
        """Human-readable cost breakdown like the plan example."""
        lines = [
            f"Trade {breakdown.execution_id} [{breakdown.coin} {breakdown.side}] lost {breakdown.implementation_shortfall_bps:.1f} bps to execution:",
            f"  {breakdown.spread_cost_bps:.1f} bps spread",
            f"  {breakdown.slippage_cost_bps:.1f} bps slippage",
            f"  {breakdown.fee_cost_bps:.1f} bps fee",
            f"  {breakdown.latency_drift_bps:.1f} bps latency drift",
            f"  Quality: {breakdown.quality_label} ({breakdown.quality_score:.0f}/100)",
        ]
        return "\n".join(lines)
