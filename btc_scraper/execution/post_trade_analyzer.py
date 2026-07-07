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

    def __init__(self, reports_dir: str = "data/execution/reports"):
        self.reports_dir = Path(reports_dir)
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
