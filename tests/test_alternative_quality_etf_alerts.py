from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from btc_scraper.collectors.alternative_quality import CollectorHealthMonitor


class _FakeCursor(list):
    def sort(self, key, direction):
        reverse = direction < 0
        return _FakeCursor(sorted(self, key=lambda doc: doc.get(key) or "", reverse=reverse))

    def limit(self, count):
        return _FakeCursor(self[:count])


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, *args, **kwargs):
        query = query or {}
        return _FakeCursor([doc for doc in self.docs if self._matches(doc, query)])

    def find_one(self, query=None, sort=None):
        matches = self.find(query)
        if sort:
            for key, direction in reversed(sort):
                matches = matches.sort(key, direction)
        return matches[0] if matches else None

    def _matches(self, doc, query):
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                    return False
                if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$regex" in expected:
                    flags = re.IGNORECASE if "i" in expected.get("$options", "") else 0
                    if actual is None or re.search(expected["$regex"], str(actual), flags) is None:
                        return False
            elif actual != expected:
                return False
        return True


def _log(status, hours_ago, symbol="BTC", mode="recent", error=None):
    return {
        "source": "parsebot_farside",
        "endpoint": f"{symbol.lower()}_{mode}",
        "symbol": symbol,
        "mode": mode,
        "status": status,
        "error": error,
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(),
    }


def test_etf_alert_reports_parsebot_billing_error(monkeypatch):
    fake_db = {
        "alternative_data_fetch_logs": _FakeCollection([
            _log(
                "failed",
                1,
                error="402 Client Error: Payment Required for url: https://api.parse.bot/scraper/x",
            )
        ]),
        "alternative_data_etf_flows": _FakeCollection([]),
    }
    import btc_scraper.core.db as db_module

    monkeypatch.setattr(db_module, "db", fake_db)

    alert = CollectorHealthMonitor().check_etf_alert_conditions()

    assert alert is not None
    assert alert.level == "critical"
    assert "Billing/quota error" in alert.message


def test_etf_alert_does_not_claim_two_days_for_short_failure_streak(monkeypatch):
    fake_db = {
        "alternative_data_fetch_logs": _FakeCollection([
            _log("failed", 1, symbol="BTC"),
            _log("failed", 1, symbol="ETH"),
            _log("failed", 1, symbol="SOL"),
        ]),
        "alternative_data_etf_flows": _FakeCollection([]),
    }
    import btc_scraper.core.db as db_module

    monkeypatch.setattr(db_module, "db", fake_db)

    alert = CollectorHealthMonitor().check_etf_alert_conditions()

    assert alert is not None
    assert alert.level == "warning"
    assert "currently failing" in alert.message
    assert "more than 2 days" not in alert.message
