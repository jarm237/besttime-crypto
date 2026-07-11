"""
tests/test_phase5_paper_trading_validation.py
Phase 5 — Paper Trading Validation Acceptance Tests

Verifies that the generated validation report meets all Phase 5 Acceptance Criteria:
- PHASE5_PIPELINE_GATE evaluates to True (with synthetic data verification).
- PHASE5_LIVE_READINESS_GATE evaluates to False (due to zero real paper fills).
- Fills breakdown schema is populated.
- Completeness metric correctly yields NOT_MEASURED.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from btc_scraper.execution.phase5_report_generator import generate_all_reports

BASE_DIR = Path(__file__).parent.parent
REPORT_JSON = BASE_DIR / "data" / "execution" / "reports" / "phase5_report_latest.json"
REPORT_MD = BASE_DIR / "docs" / "remediation" / "Phase5_Completion_Report.md"


@pytest.fixture(scope="module")
def run_validation_report():
    """Trigger the report generation once for the test suite."""
    report = generate_all_reports()
    return report


def test_phase5_files_generated(run_validation_report):
    """Ensure the JSON and Markdown report files are created successfully."""
    assert REPORT_JSON.exists(), "JSON validation report not found"
    assert REPORT_MD.exists(), "Markdown validation report not found"

    # Verify JSON load
    data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    assert "fills_breakdown" in data
    assert "pipeline_gate" in data
    assert "live_readiness_gate" in data


def test_fills_breakdown_schema(run_validation_report):
    """Verify fills breakdown tracks categories: real_paper, synthetic, debug, total."""
    breakdown = run_validation_report["fills_breakdown"]
    assert "real_paper" in breakdown
    assert "synthetic" in breakdown
    assert "debug" in breakdown
    assert "total" in breakdown
    assert breakdown["total"] == breakdown["real_paper"] + breakdown["synthetic"] + breakdown["debug"]


def test_pipeline_gate_evaluation(run_validation_report):
    """Verify that the software pipeline gate passes (checked with replay/synth fills)."""
    gate = run_validation_report["pipeline_gate"]
    assert gate["passed"] is True, "Pipeline logic gate should pass under test conditions"
    assert gate["target_fills_achieved"] is True


def test_live_readiness_gate_evaluation(run_validation_report):
    """Verify that the live readiness gate is correctly PENDING (failed/blocked)."""
    gate = run_validation_report["live_readiness_gate"]
    assert gate["passed"] is False, "Live capital gate must not be passed without real paper fills"
    assert gate["real_paper_fills"] == 0, "No real paper fills should be on disk"
    assert gate["duration_days"] == 0


def test_data_completeness_not_measured(run_validation_report):
    """Verify that data completeness reports NOT_MEASURED when paid plan is not active."""
    assert run_validation_report["data_completeness_pct"] == "NOT_MEASURED"
    assert "glassnode" in run_validation_report["model_monitoring"]["missing_rate"]["skipped_providers"]


def test_causal_shadow_matched_records(run_validation_report):
    """Verify causal shadow matching does not raise errors and has matches."""
    shadow = run_validation_report["causal_shadow"]
    assert "summary" in shadow
    assert "net_benefit_usdt" in shadow["performance_impact"]
    assert shadow["summary"]["matched_aligned_decisions"] > 0

