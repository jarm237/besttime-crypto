from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from btc_scraper.collectors.alternative_me_collector import AlternativeMeCollector
from btc_scraper.core.fear_greed import normalize_fear_greed, resolve_fear_greed_value
from btc_scraper.core.sentiment import _save_sentiment_to_history, get_sentiment_trend
from btc_scraper.ml_engine.causal_context_bridge import build_world_state_from_ana
from btc_scraper.ml_engine.feature_extractor import features_from_analysis


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, -1.0), (25, -0.5), (33, -0.34), (50, 0.0), (100, 1.0)],
)
def test_canonical_normalization(raw, expected):
    assert normalize_fear_greed(raw) == pytest.approx(expected)


@pytest.mark.parametrize("value", [0, 0.0, 50])
def test_resolver_preserves_valid_numeric_values(value):
    assert resolve_fear_greed_value(value, 99, default=50) == value


def test_trend_uses_previous_observation_date_not_current_record(tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(
        json.dumps({
            "2026-07-22T12:00:00Z": {"score": -0.34, "raw_value": 33, "label": "Fear"},
            "2026-07-21T00:00:00Z": {"score": -0.5, "raw_value": 25, "label": "Extreme Fear"},
            "2026-07-19T00:00:00Z": {"score": -0.44, "raw_value": 28, "label": "Fear"},
        })
    )
    current = {
        "normalized_score": -0.34,
        "raw_value": 33,
        "label": "Fear",
        "observation_date": "2026-07-22",
    }

    trend = get_sentiment_trend(str(history_file), current)

    assert trend["trend"] == "UP"
    assert trend["daily_momentum"] == pytest.approx(0.16)
    assert trend["recovery_signal"] is True


@pytest.mark.parametrize(
    ("previous, current, expected"),
    [(33, 25, "DOWN"), (33, 33, "STABLE")],
)
def test_daily_trend_directions(tmp_path, previous, current, expected):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "2026-07-20T00:00:00Z": {
            "raw_value": previous,
            "normalized_score": normalize_fear_greed(previous),
            "label": "Fear",
        }
    }))
    result = get_sentiment_trend(str(history_file), {
        "raw_value": current,
        "normalized_score": normalize_fear_greed(current),
        "label": "Fear",
        "observation_date": "2026-07-21",
    })
    assert result["trend"] == expected


def test_missing_previous_is_unknown(tmp_path):
    result = get_sentiment_trend(str(tmp_path / "missing.json"), {
        "raw_value": 33,
        "normalized_score": -0.34,
        "label": "Fear",
        "observation_date": "2026-07-22",
    })
    assert result["trend"] == "UNKNOWN"
    assert result["daily_momentum"] is None


def test_daily_history_deduplicates_replay_and_retains_days(tmp_path):
    history_file = tmp_path / "history.json"
    for raw in (25, 33):
        _save_sentiment_to_history({
            "raw_value": raw,
            "normalized_score": normalize_fear_greed(raw),
            "label": "Fear",
            "observation_date": "2026-07-22",
        }, str(history_file))

    history = json.loads(history_file.read_text())
    assert list(history) == ["2026-07-22T00:00:00Z"]
    assert history["2026-07-22T00:00:00Z"]["raw_value"] == 33


def test_history_retention_is_measured_in_days(tmp_path):
    history_file = tmp_path / "history.json"
    with patch.dict("os.environ", {"FEAR_GREED_HISTORY_RETENTION_DAYS": "2"}):
        for day in ("2026-07-20", "2026-07-21", "2026-07-22"):
            _save_sentiment_to_history({
                "raw_value": 25,
                "normalized_score": -0.5,
                "label": "Extreme Fear",
                "observation_date": day,
            }, str(history_file))
    assert list(json.loads(history_file.read_text())) == [
        "2026-07-21T00:00:00Z",
        "2026-07-22T00:00:00Z",
    ]


def test_missing_date_breaks_consecutive_extreme_days(tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "2026-07-19T00:00:00Z": {"raw_value": 20, "label": "Extreme Fear"},
        "2026-07-21T00:00:00Z": {"raw_value": 25, "label": "Extreme Fear"},
    }))
    result = get_sentiment_trend(str(history_file), {
        "raw_value": 20,
        "label": "Extreme Fear",
        "observation_date": "2026-07-22",
    })
    assert result["consecutive_extreme_days"] == 2


def test_collector_uses_cache_within_ttl(monkeypatch):
    import btc_scraper.collectors.alternative_me_collector as module

    monkeypatch.setattr(module, "_CACHE_VALUE", None)
    monkeypatch.setattr(module, "_CACHE_FETCHED_AT", 0.0)
    payload = {"data": [{
        "value": "33",
        "value_classification": "Fear",
        "timestamp": "1784678400",
    }]}
    with patch.object(module, "_fetch_json", return_value=payload) as fetch:
        first = AlternativeMeCollector().collect()
        second = AlternativeMeCollector().collect()

    assert fetch.call_count == 1
    assert first["fear_greed_score"] == pytest.approx(-0.34)
    assert second["cache_hit"] is True


def test_collector_returns_stale_on_error(monkeypatch):
    import btc_scraper.collectors.alternative_me_collector as module

    monkeypatch.setattr(module, "_CACHE_VALUE", None)
    monkeypatch.setattr(module, "_CACHE_FETCHED_AT", 0.0)
    payload = {"data": [{
        "value": "33",
        "value_classification": "Fear",
        "timestamp": "1784678400",
    }]}
    with patch.object(module, "_fetch_json", return_value=payload):
        AlternativeMeCollector().collect(force=True)
    with patch.object(module, "_fetch_json", side_effect=RuntimeError("offline")):
        stale = AlternativeMeCollector().collect(force=True)

    assert stale["status"] == "stale"
    assert stale["stale"] is True
    assert stale["fear_greed_raw"] == 33


def test_force_refresh_bypasses_collector_cache(monkeypatch):
    import btc_scraper.collectors.alternative_me_collector as module

    monkeypatch.setattr(module, "_CACHE_VALUE", None)
    monkeypatch.setattr(module, "_CACHE_FETCHED_AT", 0.0)
    payload = {"data": [{"value": "50", "value_classification": "Neutral"}]}
    with patch.object(module, "_fetch_json", return_value=payload) as fetch:
        AlternativeMeCollector().collect(force=True)
        AlternativeMeCollector().collect(force=True)
    assert fetch.call_count == 2


def test_api_error_without_cache_is_unavailable_not_fake_neutral(monkeypatch):
    import btc_scraper.collectors.alternative_me_collector as module

    monkeypatch.setattr(module, "_CACHE_VALUE", None)
    monkeypatch.setattr(module, "_CACHE_FETCHED_AT", 0.0)
    with patch.object(module, "_fetch_json", side_effect=RuntimeError("offline")):
        result = AlternativeMeCollector().collect(force=True)
    assert result["status"] == "unavailable"
    assert result["data"] is None
    assert "fear_greed_raw" not in result


def test_core_api_error_is_unavailable_not_fake_neutral():
    import btc_scraper.core.sentiment as module

    empty_cache = {
        "score": None,
        "normalized_score": None,
        "raw_value": None,
        "label": None,
        "observed_at": None,
        "observation_date": None,
        "status": "empty",
        "timestamp": 0.0,
        "trend": [],
    }
    with (
        patch.dict(module._cache, empty_cache, clear=True),
        patch.object(module, "_fetch_fear_and_greed", side_effect=RuntimeError("offline")),
    ):
        result = module.get_market_sentiment()
    assert result["status"] == "unavailable"
    assert result["raw_value"] is None
    assert result["normalized_score"] is None


@pytest.mark.parametrize("value", [0, 0.0])
def test_feature_extractor_preserves_raw_zero(value):
    features = features_from_analysis({"sentiment_raw": value})
    assert features["fear_greed"] == value


@pytest.mark.parametrize("value", [0, 0.0])
def test_causal_bridge_preserves_raw_zero(value):
    state = build_world_state_from_ana({"sentiment": {"raw_value": value}})
    assert state.sentiment.FearGreed == value


@pytest.mark.parametrize("value", [0, 0.0])
def test_main_consumer_preserves_raw_zero(value):
    from main import _resolve_analysis_fear_greed

    assert _resolve_analysis_fear_greed({"sentiment": {"raw_value": value}}) == value
