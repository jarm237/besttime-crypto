from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from btc_scraper.collectors.alternative_data import normalize_alternative_payload
from btc_scraper.collectors.alternative_quality import CollectorHealthMonitor, DataQualityDashboard
from btc_scraper.collectors.collector_base import CollectorBase


def _required_values() -> dict[str, float]:
    return {"funding_rate": 0.0, "open_interest": 1.0, "stablecoin_supply": 1.0,
            "tvl": 1.0, "dxy": 100.0, "vix": 20.0, "us10y": 4.0,
            "gold": 2000.0, "fear_greed_raw": 50.0}


def test_metadata_distinguishes_real_zero_from_missing(tmp_path):
    payload = normalize_alternative_payload(
        {"timestamp": datetime.now(timezone.utc).isoformat(), **_required_values()},
        raw_store_dir=str(tmp_path),
    )
    assert payload["funding_rate"] == 0.0
    assert payload["feature_metadata"]["funding_rate"]["available"] is True
    assert payload["feature_metadata"]["etf_flow"]["available"] is False
    assert payload["feature_metadata"]["funding_rate"]["source"] == "binance"


def test_metadata_uses_collector_observation_time_not_snapshot_time():
    observed_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    payload = normalize_alternative_payload(
        {"timestamp": datetime.now(timezone.utc).isoformat(), **_required_values(),
         "_statuses": {"binance": {"status": "success", "observed_at": observed_at}}},
        raw_store_dir=None,
    )
    metadata = payload["feature_metadata"]["funding_rate"]
    assert metadata["observed_at"] == observed_at
    assert metadata["age_seconds"] >= 30


def test_stale_metadata_and_required_optional_health():
    payload = normalize_alternative_payload(
        {"timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), **_required_values()},
        raw_store_dir=None,
    )
    monitor = CollectorHealthMonitor(dashboard=DataQualityDashboard(quality_log_path=None))
    monitor.record_collection("alternative_data", payload)
    health = monitor.health_snapshot()
    assert health["snapshot_count_24h"] == 1
    assert health["required_health"]["healthy"] is False
    assert "etf_flow" not in health["required_health"]["missing"]


class _JsonCollector(CollectorBase):
    name = "json"

    def collect(self, force: bool = False):
        return {"value": float("nan")}


def test_nan_is_not_persisted(tmp_path):
    path = tmp_path / "payload.json"
    collector = _JsonCollector(output_path=path)
    collector._write_json(collector.collect())
    assert json.loads(path.read_text())["value"] is None
