from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from btc_scraper.feature_engineering.label_quality import LabelQualityReporter


def test_phase8_pipeline_label_quality_smoke(tmp_path: Path):
    dataset = pd.DataFrame(
        [
            {"coin": "BTC", "entry_time": "2026-01-01 00:00", "result": "WIN", "pnl_pct": 0.9},
            {"coin": "BTC", "entry_time": "2026-01-01 00:15", "result": "LOSS", "pnl_pct": -0.7},
            {"coin": "ETH", "entry_time": "2026-01-01 00:30", "result": "WIN", "pnl_pct": 1.2},
            {"coin": "ETH", "entry_time": "2026-01-01 00:45", "result": "LOSS", "pnl_pct": -0.1},
        ]
    )

    report = LabelQualityReporter().build_report(fallback_frame=dataset)
    out_path = tmp_path / "label_quality_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["counts"]["meta_label_rows"] == 4
    assert "quality_metrics" in loaded
    assert "executable_signal_rate" in loaded["quality_metrics"]
