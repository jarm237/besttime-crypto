from __future__ import annotations

import pandas as pd

from btc_scraper.feature_engineering.label_quality import (
    LabelQualityReporter,
    LabelQualityThresholds,
    evaluate_label_quality_thresholds,
)


def test_label_quality_reporter_builds_distributions_from_fallback():
    fallback = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "result": "WIN", "pnl_pct": 1.1},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "result": "LOSS", "pnl_pct": -0.4},
            {"coin": "ETH", "entry_time": "2026-01-01 00:30", "result": "WIN", "pnl_pct": 0.7},
        ]
    )

    report = LabelQualityReporter().build_report(fallback_frame=fallback)
    assert report["counts"]["triple_barrier_rows"] == 3
    assert report["distributions"]["triple_barrier_label"]["WIN"] == 2
    assert report["distributions"]["meta_label"]["1"] == 2
    assert report["quality_metrics"]["meta_execute_rate"] is not None


def test_label_quality_reporter_warns_on_low_samples():
    triple = pd.DataFrame([{"triple_barrier_label": "WIN"}])
    report = LabelQualityReporter().build_report(triple_labels=triple)
    assert any("Low triple-barrier sample count" in w for w in report["warnings"])


def test_label_quality_thresholds_pass_for_balanced_report():
    report = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "counts": {
            "triple_barrier_rows": 300,
            "meta_label_rows": 300,
            "trade_quality_rows": 300,
        },
        "quality_metrics": {
            "executable_signal_rate": 0.95,
            "meta_execute_rate": 0.50,
            "meta_class_imbalance_ratio": 1.2,
        },
        "warnings": [],
    }
    result = evaluate_label_quality_thresholds(report, LabelQualityThresholds())
    assert result["ok"] is True
    assert result["failures"] == {}


def test_label_quality_thresholds_fail_when_rates_too_low():
    report = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "counts": {
            "triple_barrier_rows": 20,
            "meta_label_rows": 15,
            "trade_quality_rows": 10,
        },
        "quality_metrics": {
            "executable_signal_rate": 0.40,
            "meta_execute_rate": 0.10,
            "meta_class_imbalance_ratio": 5.5,
        },
        "warnings": ["Low sample count"],
    }
    result = evaluate_label_quality_thresholds(report, LabelQualityThresholds())
    assert result["ok"] is False
    assert "counts.triple_barrier_rows" in result["failures"]
    assert "quality_metrics.executable_signal_rate" in result["failures"]
    assert "quality_metrics.meta_class_imbalance_ratio" in result["failures"]
