from datetime import datetime, timedelta, timezone

from btc_scraper.collectors.alternative_reference import build_alternative_reference


def _payload(timestamp: datetime) -> dict:
    return {
        "timestamp": timestamp.isoformat(),
        "risk_on_score": -0.25,
        "macro_pressure": 0.4,
        "funding_pressure": None,
        "fear_greed_raw": 33,
        "feature_metadata": {
            "risk_on_score": {"available": True, "status": "available", "confidence": 0.8},
            "macro_pressure": {"available": True, "status": "available", "confidence": 0.8},
            "funding_pressure": {"available": False, "status": "missing", "confidence": 0.0},
            "fear_greed_raw": {"available": True, "status": "available", "confidence": 0.6},
        },
    }


def test_reference_contract_is_fail_closed_and_preserves_missing():
    now = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
    reference = build_alternative_reference(_payload(now), now=now)

    assert reference["mode"] == "reference_only"
    assert reference["affects_signal"] is False
    assert reference["decision_eligible"] is False
    assert reference["values"]["risk_on_score"] == -0.25
    assert reference["values"]["funding_pressure"] is None
    assert reference["features"]["funding_pressure"]["available"] is False


def test_stale_payload_exposes_no_current_reference_values():
    now = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
    reference = build_alternative_reference(
        _payload(now - timedelta(hours=2)),
        now=now,
        max_payload_age_seconds=900,
    )

    assert reference["status"] == "stale"
    assert reference["is_stale"] is True
    assert all(value is None for value in reference["values"].values())


def test_invalid_timestamp_fails_closed():
    payload = _payload(datetime.now(timezone.utc))
    payload["timestamp"] = "invalid"

    reference = build_alternative_reference(payload)

    assert reference["status"] == "stale"
    assert reference["timestamp"] is None
    assert reference["decision_eligible"] is False
