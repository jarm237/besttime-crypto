import time

from btc_scraper.collectors.macro_collector import is_macro_state_fresh
from btc_scraper.collectors.parsebot_farside_collector import (
    _cache_path,
    _request_usage_path,
)
from btc_scraper.core.paths import REPO_ROOT, build_data_path, get_runtime_paths


def test_build_data_path_uses_runtime_root():
    expected = get_runtime_paths().data_root / "latest_signals.json"
    assert build_data_path("latest_signals.json") == expected


def test_full_suite_uses_isolated_runtime_paths():
    runtime_paths = get_runtime_paths()
    assert runtime_paths.environment == "test"
    assert runtime_paths.data_root != REPO_ROOT / "data"
    assert runtime_paths.logs_root != REPO_ROOT / "logs"
    assert runtime_paths.evidence_eligible is False
    assert runtime_paths.paper_run_id


def test_parsebot_runtime_files_use_owned_log_root(monkeypatch):
    monkeypatch.delenv("PARSEBOT_CACHE_DIR", raising=False)
    monkeypatch.delenv("PARSEBOT_REQUEST_USAGE_PATH", raising=False)
    logs_root = get_runtime_paths().logs_root

    assert _cache_path("BTC", "recent") == logs_root / "etf_flow_cache" / "BTC_recent.json"
    assert _request_usage_path() == logs_root / "parsebot_request_usage.json"
    assert logs_root != REPO_ROOT / "logs"


def test_macro_state_is_fresh_with_recent_timestamp(tmp_path):
    fresh_path = tmp_path / "macro_state.json"
    fresh_path.write_text('{"timestamp": "' + time.strftime("%Y-%m-%dT%H:%M:%SZ") + '"}', encoding="utf-8")
    assert is_macro_state_fresh(fresh_path, max_age_seconds=3600)
