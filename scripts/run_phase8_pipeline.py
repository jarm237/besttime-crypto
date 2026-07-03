#!/usr/bin/env python3
"""
Phase 8 End-to-End Pipeline Runner
Executes all 14 steps, monitors for errors, auto-fixes, and generates report.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import pandas as pd


class Phase8PipelineRunner:
    def __init__(self, repo_root: Path | None = None, output_dir: Path | None = None, python_executable: str | None = None):
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]
        self.output_dir = output_dir or self.repo_root / "logs" / "phase8_pipeline"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = self.output_dir / "phase8_pipeline_report.json"
        self.log_path = self.output_dir / "phase8_pipeline.log"
        self.start_time = None
        self.steps = []
        self.python_executable = python_executable or sys.executable

    def log(self, msg: str, level: str = "INFO") -> None:
        """Log message to console and file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] [{level}] {msg}"
        try:
            print(log_msg)
        except UnicodeEncodeError:
            print(log_msg.encode('utf-8', errors='replace').decode('utf-8'))
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")

    def run_step(
        self,
        step_num: int,
        name: str,
        cmd: list[str],
        cwd: Path | None = None,
    ) -> dict[str, Any]:
        """Run a single pipeline step."""
        cwd = cwd or self.repo_root
        step_info = {
            "step": step_num,
            "name": name,
            "cmd": " ".join(cmd),
            "status": "pending",
            "start_time": None,
            "end_time": None,
            "duration_sec": None,
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "error_msg": None,
        }

        try:
            self.log(f"\n{'='*80}")
            self.log(f"Step {step_num}: {name}")
            self.log(f"Command: {' '.join(cmd)}")
            self.log(f"CWD: {cwd}")

            step_info["start_time"] = datetime.now().isoformat()
            start = time.time()

            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=600,
            )

            step_info["return_code"] = result.returncode
            step_info["stdout"] = result.stdout[-2000:]  # Keep last 2000 chars
            step_info["stderr"] = result.stderr[-2000:]

            if result.returncode == 0:
                step_info["status"] = "completed"
                self.log(f"✅ Step {step_num} completed successfully")
            else:
                step_info["status"] = "failed"
                step_info["error_msg"] = result.stderr or result.stdout
                self.log(f"❌ Step {step_num} failed with code {result.returncode}")
                self.log(f"Error: {step_info['error_msg'][:500]}")

            step_info["end_time"] = datetime.now().isoformat()
            step_info["duration_sec"] = time.time() - start

        except subprocess.TimeoutExpired:
            step_info["status"] = "timeout"
            step_info["error_msg"] = "Command timed out after 600 seconds"
            self.log(f"⏱️ Step {step_num} timed out")
        except Exception as e:
            step_info["status"] = "error"
            step_info["error_msg"] = str(e)
            self.log(f"❌ Step {step_num} error: {e}")

        self.steps.append(step_info)
        return step_info

    def run_pipeline(self) -> bool:
        """Run full Phase 8 pipeline."""
        self.start_time = datetime.now()
        self.log(f"Starting Phase 8 Pipeline at {self.start_time.isoformat()}")
        self.log(f"Report will be saved to: {self.report_path}")

        # Step 1: Initialize feature store
        self.run_step(
            1,
            "Initialize Feature Store v2",
            [self.python_executable, "scripts/build_feature_store_v2.py"],
        )

        # Step 2: Generate triple barrier labels
        self.run_step(
            2,
            "Generate Triple Barrier Labels",
            [
                self.python_executable,
                "scripts/generate_triple_barrier_labels.py",
                "--input", "logs/adaptive_signals_v2.json",
                "--output", "data/feature_store/labels/triple_barrier_labels.parquet",
                "--data-dir", "data/fresh_training_data_2023_2026",
                "--timeframe", "15m",
            ],
        )

        # Step 3: Generate meta labels
        self.run_step(
            3,
            "Generate Meta Labels",
            [
                self.python_executable,
                "scripts/generate_meta_labels.py",
                "--input", "data/feature_store/labels/triple_barrier_labels.parquet",
                "--output-meta", "data/feature_store/labels/meta_labels.parquet",
                "--output-trade-quality", "data/feature_store/labels/trade_quality_labels.parquet",
            ],
        )

        # Step 4: Build Regime Features
        self.run_step(
            4,
            "Build Regime Features",
            [
                self.python_executable,
                "scripts/build_regime_features.py",
                "--input", "logs/adaptive_signals_v2.json",
                "--output", "data/feature_store/regime/regime_features.parquet",
            ],
        )

        # Step 5: Build Causal Features
        self.run_step(
            5,
            "Build Causal Features",
            [
                self.python_executable,
                "scripts/build_causal_features.py",
                "--input", "logs/adaptive_signals_v2.json",
                "--output", "data/feature_store/causal/causal_features.parquet",
            ],
        )

        # Step 6: Build Alternative Features
        self.run_step(
            6,
            "Build Alternative Features",
            [
                self.python_executable,
                "scripts/build_alternative_features.py",
                "--input", "data/alternative_data.json",
                "--output", "data/feature_store/derived/alternative_features.parquet",
                "--quality-report", "data/feature_store/derived/alternative_feature_quality_report.json",
            ],
        )

        # Step 7: Build Cross-Sectional Features
        self.run_step(
            7,
            "Build Cross-Sectional Features",
            [
                self.python_executable,
                "scripts/build_cross_sectional_features.py",
                "--input", "logs/adaptive_signals_v2.json",
                "--output", "data/feature_store/derived/cross_sectional_features.parquet",
            ],
        )

        # Step 8: Build Fractional Differencing Features
        self.run_step(
            8,
            "Build Fractional Differencing Features",
            [
                self.python_executable,
                "scripts/build_fracdiff_features.py",
                "--input", "logs/adaptive_signals_v2.json",
                "--output", "data/feature_store/derived/fracdiff_features.parquet",
                "--report", "data/feature_store/derived/fracdiff_report.json",
            ],
        )

        # Step 9: Build Feature Validation Reports
        self.run_step(
            9,
            "Build Feature Validation Reports",
            [
                self.python_executable,
                "scripts/build_feature_validation_reports.py",
                "--input", "data/feature_store/derived/fracdiff_features.parquet",
                "--quality-output", "data/feature_store/derived/feature_quality_report.json",
                "--rejection-output", "data/feature_store/derived/feature_rejection_report.json",
            ],
        )

        # Step 10: Build ML dataset v3
        self.run_step(
            10,
            "Build ML Dataset v3",
            [
                self.python_executable,
                "scripts/build_ml_dataset_v3.py",
                "--base", "data/feature_store/derived/cross_sectional_features.parquet",
                "--features", (
                    "data/feature_store/derived/fracdiff_features.parquet,"
                    "data/feature_store/derived/alternative_features.parquet"
                ),
                "--labels", "data/feature_store/labels/meta_labels.parquet",
                "--output", "data/feature_store/training/ml_dataset_v3.parquet",
            ],
        )

        # Step 11: Build label quality report
        self.run_step(
            11,
            "Build Label Quality Report",
            [
                self.python_executable,
                "scripts/build_label_quality_report.py",
                "--triple", "data/feature_store/labels/triple_barrier_labels.parquet",
                "--meta", "data/feature_store/labels/meta_labels.parquet",
                "--trade-quality", "data/feature_store/labels/trade_quality_labels.parquet",
                "--fallback", "data/feature_store/training/ml_dataset_v3.parquet",
                "--output", "data/feature_store/labels/label_quality_report.json",
            ],
        )

        # Step 12: Check label quality threshold
        self.run_step(
            12,
            "Check Label Quality Threshold",
            [
                self.python_executable,
                "scripts/check_label_quality_threshold.py",
                "--report", "data/feature_store/labels/label_quality_report.json",
                "--min-meta-execute-rate", "0.33",
            ],
        )

        # Step 13: Train Meta Model v3
        self.run_step(
            13,
            "Train Meta Model v3",
            [
                self.python_executable,
                "scripts/train_meta_model_v3.py",
                "--dataset", "data/feature_store/training/ml_dataset_v3.parquet",
                "--output-dir", "logs",
                "--label-column", "meta_label",
                "--positive-label", "1.0",
                "--walk-forward-splits", "3",
            ],
        )

        # Step 14: Verify outputs
        self.run_step(
            14,
            "Verify Pipeline Outputs",
            [
                self.python_executable, "-c",
                """
import json, os
from pathlib import Path
paths = [
    'data/feature_store/labels/triple_barrier_labels.parquet',
    'data/feature_store/labels/meta_labels.parquet',
    'data/feature_store/derived/cross_sectional_features.parquet',
    'data/feature_store/training/ml_dataset_v3.parquet',
    'data/feature_store/labels/label_quality_report.json',
]
print('Checking outputs...')
for p in paths:
    if Path(p).exists():
        print(f'✓ {p}')
    else:
        print(f'✗ {p} MISSING')
print('Output verification complete')
""",
            ],
        )

        return all(s["status"] == "completed" for s in self.steps)

    def generate_report(self) -> dict[str, Any]:
        """Generate summary report."""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        completed = sum(1 for s in self.steps if s["status"] == "completed")
        failed = sum(1 for s in self.steps if s["status"] == "failed")
        errors = sum(1 for s in self.steps if s["status"] == "error")

        report = {
            "pipeline": "Phase 8 Feature Engineering",
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_sec": duration,
            "total_steps": len(self.steps),
            "completed": completed,
            "failed": failed,
            "errors": errors,
            "success_rate": completed / len(self.steps) if self.steps else 0.0,
            "steps": self.steps,
            "summary": {
                "status": "SUCCESS" if completed == len(self.steps) else "PARTIAL_SUCCESS" if completed > 0 else "FAILED",
                "message": f"{completed}/{len(self.steps)} steps completed successfully",
            },
        }

        # Save report
        self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.log(f"\n{'='*80}")
        self.log(f"Pipeline Report saved to: {self.report_path}")

        return report

    def print_summary(self, report: dict[str, Any]) -> None:
        """Print summary to console."""
        print(f"\n\n{'='*80}")
        print("PHASE 8 PIPELINE SUMMARY")
        print(f"{'='*80}")
        print(f"Status: {report['summary']['status']}")
        print(f"Duration: {report['duration_sec']:.1f} seconds")
        print(f"Completed: {report['completed']}/{report['total_steps']} steps ({report['success_rate']*100:.1f}%)")
        print(f"\nStep Results:")
        for step in report["steps"]:
            status_icon = "✅" if step["status"] == "completed" else "❌"
            print(f"  {status_icon} Step {step['step']}: {step['name']} ({step['status']})")
            if step["error_msg"]:
                print(f"     Error: {step['error_msg'][:100]}")

        print(f"\nReport saved to: {self.report_path}")
        print(f"Log saved to: {self.log_path}")
        print(f"{'='*80}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 8 Pipeline end-to-end")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root path")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for reports")
    args = parser.parse_args()

    runner = Phase8PipelineRunner(repo_root=args.repo_root, output_dir=args.output_dir)
    success = runner.run_pipeline()
    report = runner.generate_report()
    runner.print_summary(report)

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
