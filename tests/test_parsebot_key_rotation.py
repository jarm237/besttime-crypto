from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from btc_scraper.collectors.etf_providers import ParseBotFarsideProvider
from btc_scraper.collectors.parsebot_farside_collector import (
    ParsebotFarsideETFCollector,
    _reserve_parsebot_request,
)
from btc_scraper.collectors.parsebot_key_rotation import (
    ParsebotKeyManager,
    is_parsebot_key_exhaustion_error,
    load_parsebot_api_keys,
)


def _response(*, status_code: int = 200, payload=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} response",
            response=SimpleNamespace(status_code=status_code),
        )
    return response


def test_load_parsebot_keys_prefers_numbered_keys_and_deduplicates(monkeypatch):
    monkeypatch.setenv("PARSEBOT_API_KEY_1", " key-1 ")
    monkeypatch.setenv("PARSEBOT_API_KEY_2", "key-2")
    monkeypatch.setenv("PARSEBOT_API_KEY_3", "key-1")
    monkeypatch.setenv("PARSEBOT_API_KEY", "legacy")
    monkeypatch.delenv("PARSEBOT_API_KEY_4", raising=False)
    monkeypatch.delenv("PARSEBOT_API_KEY_5", raising=False)

    assert load_parsebot_api_keys() == ["key-1", "key-2", "legacy"]


def test_key_manager_round_robin_exhaustion_and_daily_reset():
    clock = [datetime(2026, 7, 29, 10, 0)]
    manager = ParsebotKeyManager(["key-1", "key-2"], now=lambda: clock[0])

    assert manager.next_key() == "key-1"
    assert manager.next_key() == "key-2"
    manager.mark_exhausted("key-1")
    assert manager.next_key() == "key-2"
    manager.mark_exhausted("key-2")
    assert manager.available is False
    assert manager.pause_info == "2026-07-30T00:05:00"

    clock[0] += timedelta(days=1)
    assert manager.available is True
    assert manager.next_key() == "key-1"


def test_key_exhaustion_detection_matches_gemini_signals():
    assert is_parsebot_key_exhaustion_error(RuntimeError("429 Too Many Requests"))
    assert is_parsebot_key_exhaustion_error(RuntimeError("RESOURCE_EXHAUSTED"))
    assert not is_parsebot_key_exhaustion_error(RuntimeError("500 Internal Server Error"))


def test_collector_rotates_immediately_after_429(monkeypatch):
    monkeypatch.setenv("PARSEBOT_ENABLED", "true")
    monkeypatch.setenv("PARSEBOT_BASE_URL", "https://parsebot.test")
    collector = ParsebotFarsideETFCollector(api_keys=["key-1", "key-2"])
    responses = [
        _response(status_code=429),
        _response(payload={"total_flow": 123.0}),
    ]
    get_mock = MagicMock(side_effect=responses)
    monkeypatch.setattr(requests, "get", get_mock)
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._reserve_parsebot_request",
        lambda **kwargs: (True, 1, 180),
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._save_cache",
        lambda result: None,
    )

    result = collector.fetch("BTC", "recent")

    assert result["status"] == "ok"
    assert [call.kwargs["headers"]["X-API-Key"] for call in get_mock.call_args_list] == [
        "key-1",
        "key-2",
    ]


def test_collector_round_robins_successful_requests(monkeypatch):
    monkeypatch.setenv("PARSEBOT_ENABLED", "true")
    monkeypatch.setenv("PARSEBOT_BASE_URL", "https://parsebot.test")
    collector = ParsebotFarsideETFCollector(api_keys=["key-1", "key-2"])
    get_mock = MagicMock(
        side_effect=[
            _response(payload={"total_flow": 1.0}),
            _response(payload={"total_flow": 2.0}),
        ]
    )
    monkeypatch.setattr(requests, "get", get_mock)
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._reserve_parsebot_request",
        lambda **kwargs: (True, 1, 180),
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._save_cache",
        lambda result: None,
    )

    assert collector.fetch("BTC", "recent")["status"] == "ok"
    assert collector.fetch("ETH", "recent")["status"] == "ok"
    assert [call.kwargs["headers"]["X-API-Key"] for call in get_mock.call_args_list] == [
        "key-1",
        "key-2",
    ]


def test_collector_pauses_after_all_keys_return_429(monkeypatch):
    monkeypatch.setenv("PARSEBOT_ENABLED", "true")
    monkeypatch.setenv("PARSEBOT_BASE_URL", "https://parsebot.test")
    collector = ParsebotFarsideETFCollector(api_keys=["key-1", "key-2"])
    get_mock = MagicMock(side_effect=[_response(status_code=429), _response(status_code=429)])
    monkeypatch.setattr(requests, "get", get_mock)
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._reserve_parsebot_request",
        lambda **kwargs: (True, 1, 180),
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._save_cache",
        lambda result: None,
    )

    result = collector.fetch("BTC", "recent")

    assert result["status"] == "quota_exhausted"
    assert "All 2 Parse.bot API keys" in result["error"]
    assert collector._key_manager.available is False
    assert get_mock.call_count == 2


def test_monthly_request_guard_tracks_each_key_without_storing_secrets(monkeypatch, tmp_path):
    usage_path = tmp_path / "parsebot_usage.json"
    monkeypatch.setenv("PARSEBOT_MONTHLY_REQUEST_LIMIT", "2")
    monkeypatch.setenv("PARSEBOT_REQUEST_USAGE_PATH", str(usage_path))
    now = datetime(2026, 7, 29)

    assert _reserve_parsebot_request(now, api_key="secret-key-1") == (True, 1, 2)
    assert _reserve_parsebot_request(now, api_key="secret-key-1") == (True, 2, 2)
    assert _reserve_parsebot_request(now, api_key="secret-key-1") == (False, 2, 2)
    assert _reserve_parsebot_request(now, api_key="secret-key-2") == (True, 1, 2)

    stored = usage_path.read_text(encoding="utf-8")
    payload = json.loads(stored)
    assert payload["month"] == "2026-07"
    assert sorted(payload["counts"].values()) == [1, 2]
    assert payload["total_count"] == 3
    assert "secret-key" not in stored


def test_provider_chain_parsebot_provider_rotates_after_429(monkeypatch):
    monkeypatch.setenv("PARSEBOT_API_KEY_1", "provider-key-1")
    monkeypatch.setenv("PARSEBOT_API_KEY_2", "provider-key-2")
    monkeypatch.delenv("PARSEBOT_API_KEY", raising=False)
    provider = ParseBotFarsideProvider()
    get_mock = MagicMock(
        side_effect=[
            _response(status_code=429),
            _response(payload={"total_flow": 42.5}),
        ]
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.etf_providers.requests.get",
        get_mock,
    )
    monkeypatch.setattr(
        "btc_scraper.collectors.parsebot_farside_collector._reserve_parsebot_request",
        lambda **kwargs: (True, 1, 180),
    )

    result = provider.fetch()

    assert result is not None
    assert result.etf_flow == 42.5
    assert [call.kwargs["headers"]["X-API-Key"] for call in get_mock.call_args_list] == [
        "provider-key-1",
        "provider-key-2",
    ]
