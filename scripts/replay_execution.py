#!/usr/bin/env python3
"""
scripts/replay_execution.py
Phase 10 — Execution Replay

Re-analyzes historical fill records using the current (potentially updated)
post-trade analyzer and slippage model. Useful for validating model updates.

Usage:
    python scripts/replay_execution.py [--date 2026-07-08]
"""
import sys
import json
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.execution.post_trade_analyzer import PostTradeAnalyzer
from btc_scraper.execution.slippage_predictor import SlippagePredictor


def main():
    parser = argparse.ArgumentParser(description="Replay execution logs for quality analysis")
    parser.add_argument("--date", type=str, default=None,
                        help="Filter by date YYYY-MM-DD (default: all dates)")
    parser.add_argument("--fills-dir", type=str,
                        default=str(REPO_ROOT / "data" / "execution" / "fills"))
    args = parser.parse_args()

    fills_dir = Path(args.fills_dir)
    if not fills_dir.exists():
        print(f"❌ No fills directory: {fills_dir}")
        return

    # Collect records
    records = []
    pattern = f"fills_{args.date}.jsonl" if args.date else "fills_*.jsonl"
    for f in sorted(fills_dir.glob(pattern)):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("status") == "FILLED":
                        records.append(r)
                except Exception:
                    pass

    if not records:
        print("⚠️  No filled records found for the given date filter.")
        return

    print(f"🔄 Replaying {len(records)} fill records...")
    predictor = SlippagePredictor()
    analyzer = PostTradeAnalyzer(
        reports_dir=str(REPO_ROOT / "data" / "execution" / "reports")
    )

    breakdowns = analyzer.analyze_batch(records)

    # Print worst 10 executions
    breakdowns_sorted = sorted(
        breakdowns,
        key=lambda b: abs(b.implementation_shortfall_bps),
        reverse=True,
    )

    print("\n── Top 10 Worst Executions ──")
    for b in breakdowns_sorted[:10]:
        print(analyzer.format_summary(b))
        print()

    # Generate report
    report = analyzer.generate_report(records, report_name=f"replay_{'_'.join(b.coin for b in breakdowns_sorted[:3])}.json")
    print(f"📊 Avg IS: {report.get('avg_implementation_shortfall_bps', 0):.2f} bps")
    print(f"   P95 IS: {report.get('p95_implementation_shortfall_bps', 0):.2f} bps")
    print(f"\n✅ Replay report saved to data/execution/reports/")


if __name__ == "__main__":
    main()
