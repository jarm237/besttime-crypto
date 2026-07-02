#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.feature_engineering.label_quality import (
    LabelQualityThresholds,
    evaluate_label_quality_thresholds,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check label quality report thresholds for CI")
    parser.add_argument("--report", default="data/feature_store/labels/label_quality_report.json")
    parser.add_argument("--output", default="logs/label_quality_threshold_check.json")

    parser.add_argument("--min-triple-rows", type=int, default=100)
    parser.add_argument("--min-meta-rows", type=int, default=100)
    parser.add_argument("--min-trade-quality-rows", type=int, default=100)
    parser.add_argument("--min-executable-rate", type=float, default=0.80)
    parser.add_argument("--min-meta-execute-rate", type=float, default=0.40)
    parser.add_argument("--max-meta-imbalance", type=float, default=3.0)
    parser.add_argument("--max-warning-count", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    output_path = Path(args.output)

    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    thresholds = LabelQualityThresholds(
        min_triple_rows=int(args.min_triple_rows),
        min_meta_rows=int(args.min_meta_rows),
        min_trade_quality_rows=int(args.min_trade_quality_rows),
        min_executable_signal_rate=float(args.min_executable_rate),
        min_meta_execute_rate=float(args.min_meta_execute_rate),
        max_meta_class_imbalance_ratio=float(args.max_meta_imbalance),
        max_warning_count=int(args.max_warning_count),
    )
    result = evaluate_label_quality_thresholds(report, thresholds=thresholds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Threshold check output: {output_path}")
    print(f"Result: {'PASS' if result['ok'] else 'FAIL'}")
    if not result["ok"]:
        print(f"Failures: {list(result['failures'].keys())}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
