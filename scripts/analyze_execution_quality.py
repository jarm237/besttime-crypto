#!/usr/bin/env python3
"""
scripts/analyze_execution_quality.py
Phase 10 – Sprint 10.7

Loads all fill records from data/execution/fills/ and generates
a comprehensive execution quality report per coin / session.
"""
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.execution.post_trade_analyzer import PostTradeAnalyzer


def main():
    fills_dir = REPO_ROOT / "data" / "execution" / "fills"
    if not fills_dir.exists():
        print("❌ No fills directory found at", fills_dir)
        print("   Run some paper executions first.")
        return

    # Load all JSONL fill records
    records = []
    for f in sorted(fills_dir.glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # Keep only FILLED records
    records = [r for r in records if r.get("status") == "FILLED"]

    if not records:
        print("⚠️  No filled execution records found. Run paper backtesting first.")
        return

    print(f"📊 Analyzing {len(records)} filled executions...")
    analyzer = PostTradeAnalyzer(
        reports_dir=str(REPO_ROOT / "data" / "execution" / "reports")
    )

    report = analyzer.generate_report(records)

    print("\n═══ EXECUTION QUALITY REPORT ═══")
    print(f"Total fills analyzed:        {report['n_total_fills']}")
    print(f"Avg Implementation Shortfall:{report['avg_implementation_shortfall_bps']:.2f} bps")
    print(f"P95 Implementation Shortfall:{report['p95_implementation_shortfall_bps']:.2f} bps")
    print()

    print("── Per-Coin Breakdown ──")
    for coin, stats in report.get("by_coin", {}).items():
        print(f"  {coin:10s}: fills={stats['n_fills']:4d}  avg IS={stats['avg_is_bps']:.2f} bps  "
              f"p95 IS={stats['p95_is_bps']:.2f} bps  "
              f"slip err={stats['avg_slippage_prediction_error_bps']:+.2f} bps  "
              f"[{stats['pct_excellent']:.0f}% excellent | {stats['pct_good']:.0f}% good | {stats['pct_poor']:.0f}% poor]")

    print(f"\n✅ Full report saved to data/execution/reports/")


if __name__ == "__main__":
    main()
