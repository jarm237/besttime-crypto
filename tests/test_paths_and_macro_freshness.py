import os
import time
from pathlib import Path

from btc_scraper.collectors.macro_collector import is_macro_state_fresh
from btc_scraper.core.paths import build_data_path


def test_build_data_path_uses_repo_root():
    repo_root = Path(__file__).resolve().parents[1]
    expected = repo_root / "data" / "latest_signals.json"
    assert build_data_path("latest_signals.json") == expected


def test_macro_state_is_fresh_with_recent_timestamp(tmp_path):
    fresh_path = tmp_path / "macro_state.json"
    fresh_path.write_text('{"timestamp": "' + time.strftime("%Y-%m-%dT%H:%M:%SZ") + '"}', encoding="utf-8")
    assert is_macro_state_fresh(fresh_path, max_age_seconds=3600)
