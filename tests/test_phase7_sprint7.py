"""Tests for Sprint 7 gap-closure modules:
- alternative_scheduler.py (AlternativeDataScheduler)
- alternative_backfill.py (AlternativeDataBackfiller, AlternativeDataReplayer)
- alternative_quality.py  (DataQualityChecker, DataQualityDashboard, CollectorHealthMonitor)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest



# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

class TestAlternativeDataScheduler:
    def test_parsebot_schedule_runs_once_per_due_slot(self):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler()
        tuesday_9am = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)

        with (
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_recent_job") as recent,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_all_job") as all_history,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_fund_info_job") as fund,
        ):
            sched._run_scheduled_parsebot_jobs(tuesday_9am)
            sched._run_scheduled_parsebot_jobs(tuesday_9am.replace(minute=15))

        recent.assert_called_once_with()
        all_history.assert_not_called()
        fund.assert_not_called()

    def test_parsebot_recent_schedule_runs_six_slots_per_publication_day(self):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler()
        tuesday = datetime(2026, 7, 21, tzinfo=timezone.utc)

        with (
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_recent_job") as recent,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_all_job"),
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_fund_info_job"),
        ):
            for hour in (9, 11, 13, 15, 17, 19):
                sched._run_scheduled_parsebot_jobs(tuesday.replace(hour=hour))
                sched._run_scheduled_parsebot_jobs(tuesday.replace(hour=hour, minute=15))

        assert recent.call_count == 6

    def test_parsebot_schedule_honors_environment_cron_override(self):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler()
        monday = datetime(2026, 7, 20, tzinfo=timezone.utc)

        with (
            patch.dict("os.environ", {"PARSEBOT_ETF_RECENT_CRON": "30 8 * * 1"}),
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_recent_job") as recent,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_all_job"),
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_fund_info_job"),
        ):
            sched._run_scheduled_parsebot_jobs(monday.replace(hour=8, minute=29))
            sched._run_scheduled_parsebot_jobs(monday.replace(hour=8, minute=30))
            sched._run_scheduled_parsebot_jobs(monday.replace(hour=8, minute=45))

        recent.assert_called_once_with()

    def test_parsebot_weekly_jobs_only_run_on_weekend(self):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler()
        saturday = datetime(2026, 7, 25, 9, 30, tzinfo=timezone.utc)
        sunday = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)

        with (
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_recent_job") as recent,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_etf_all_job") as all_history,
            patch("scripts.fetch_parsebot_etf_jobs.fetch_parsebot_fund_info_job") as fund,
        ):
            sched._run_scheduled_parsebot_jobs(saturday)
            sched._run_scheduled_parsebot_jobs(sunday)

        recent.assert_called_once_with()
        all_history.assert_called_once_with()
        fund.assert_called_once_with()

    @pytest.mark.network
    def test_run_once_returns_payload(self, tmp_path):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler(
            interval_seconds=3600,
            output_path=str(tmp_path / "alt.json"),
            raw_store_dir=str(tmp_path / "raw"),
            feature_snapshot_path=str(tmp_path / "snap.json"),
        )
        result = sched.run_once(force=True)
        assert isinstance(result, dict)
        assert "timestamp" in result

    @pytest.mark.network
    def test_status_reports_counts(self, tmp_path):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler(
            interval_seconds=3600,
            output_path=str(tmp_path / "alt.json"),
            raw_store_dir=str(tmp_path / "raw"),
            feature_snapshot_path=str(tmp_path / "snap.json"),
        )
        sched.run_once(force=True)
        st = sched.status()
        assert st["run_count"] == 1
        assert st["success_count"] == 1
        assert st["failure_count"] == 0
        assert st["running"] is False

    @pytest.mark.network
    def test_on_success_callback_invoked(self, tmp_path):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        received: List[Dict[str, Any]] = []
        sched = AlternativeDataScheduler(
            interval_seconds=3600,
            output_path=str(tmp_path / "alt.json"),
            raw_store_dir=str(tmp_path / "raw"),
            feature_snapshot_path=str(tmp_path / "snap.json"),
            on_success=received.append,
        )
        sched.run_once(force=True)
        assert len(received) == 1
        assert "timestamp" in received[0]

    @pytest.mark.network
    def test_scheduler_starts_and_stops(self, tmp_path):
        from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler

        sched = AlternativeDataScheduler(
            interval_seconds=60,
            output_path=str(tmp_path / "alt.json"),
            raw_store_dir=str(tmp_path / "raw"),
            feature_snapshot_path=str(tmp_path / "snap.json"),
        )
        sched.start(daemon=True)
        assert sched.is_running()
        sched.stop(timeout=3.0)
        # After stop the thread may still be briefly alive; give it a moment
        time.sleep(0.2)
        # Just verify stop() doesn't raise
        assert sched.status()["interval_seconds"] == 60

    def test_registry_status_all(self, tmp_path):
        from btc_scraper.collectors.alternative_scheduler import (
            AlternativeDataScheduler,
            SchedulerRegistry,
        )

        reg = SchedulerRegistry()
        s1 = AlternativeDataScheduler(
            interval_seconds=300,
            output_path=str(tmp_path / "a.json"),
            raw_store_dir=str(tmp_path / "raw_a"),
            feature_snapshot_path=str(tmp_path / "snap_a.json"),
        )
        s2 = AlternativeDataScheduler(
            interval_seconds=600,
            output_path=str(tmp_path / "b.json"),
            raw_store_dir=str(tmp_path / "raw_b"),
            feature_snapshot_path=str(tmp_path / "snap_b.json"),
        )
        reg.register("primary", s1)
        reg.register("secondary", s2)

        statuses = reg.status_all()
        assert "primary" in statuses
        assert "secondary" in statuses


def test_parsebot_monthly_request_guard_persists_and_resets(tmp_path):
    from btc_scraper.collectors.parsebot_farside_collector import _reserve_parsebot_request

    usage_path = tmp_path / "parsebot_usage.json"
    july = datetime(2026, 7, 22, tzinfo=timezone.utc)
    august = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with patch.dict(
        "os.environ",
        {
            "PARSEBOT_MONTHLY_REQUEST_LIMIT": "2",
            "PARSEBOT_REQUEST_USAGE_PATH": str(usage_path),
        },
    ):
        assert _reserve_parsebot_request(july) == (True, 1, 2)
        assert _reserve_parsebot_request(july) == (True, 2, 2)
        assert _reserve_parsebot_request(july) == (False, 2, 2)
        assert _reserve_parsebot_request(august) == (True, 1, 2)

    assert json.loads(usage_path.read_text(encoding="utf-8")) == {
        "counts": {
            "c49fea7425fa": 1,
        },
        "month": "2026-08",
        "total_count": 1,
    }


# ---------------------------------------------------------------------------
# Backfill / Replay tests
# ---------------------------------------------------------------------------

class TestAlternativeDataBackfiller:
    def test_backfill_creates_files(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataBackfiller

        start = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, 3, 0, 0, tzinfo=timezone.utc)
        bf = AlternativeDataBackfiller(raw_store_dir=str(tmp_path / "raw"), interval_minutes=60)
        written = bf.backfill(start, end)
        assert len(written) == 4  # 00:00, 01:00, 02:00, 03:00
        for p in written:
            assert p.exists()
            data = json.loads(p.read_text())
            assert "timestamp" in data

    def test_backfill_skips_existing_by_default(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataBackfiller

        start = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, 1, 0, 0, tzinfo=timezone.utc)
        raw_dir = tmp_path / "raw"
        bf = AlternativeDataBackfiller(raw_store_dir=str(raw_dir), interval_minutes=60)

        written_first = bf.backfill(start, end)
        written_second = bf.backfill(start, end)  # should skip
        assert len(written_first) == 2
        assert len(written_second) == 0

    def test_backfill_overwrite_replaces_files(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataBackfiller

        start = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        raw_dir = tmp_path / "raw"
        bf = AlternativeDataBackfiller(raw_store_dir=str(raw_dir), interval_minutes=60)
        bf.backfill(start, end)
        written = bf.backfill(start, end, overwrite=True)
        assert len(written) == 1

    def test_backfill_days_convenience(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataBackfiller

        raw_dir = tmp_path / "raw"
        bf = AlternativeDataBackfiller(raw_store_dir=str(raw_dir), interval_minutes=360)
        written = bf.backfill_days(days=1)
        assert len(written) >= 4  # at least 4 intervals in 24h at 6h cadence


class TestAlternativeDataReplayer:
    def _seed_raw_dir(self, raw_dir: Path, n: int = 3) -> List[datetime]:
        raw_dir.mkdir(parents=True, exist_ok=True)
        timestamps = []
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(n):
            ts = base + timedelta(hours=i)
            payload = {
                "timestamp": ts.isoformat(),
                "exchange_netflow": float(-i * 1000),
                "whale_score": 0.5,
            }
            ts_str = ts.isoformat().replace(":", "_")
            (raw_dir / f"alternative_{ts_str}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            timestamps.append(ts)
        return timestamps

    def test_iter_payloads_yields_all(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        raw_dir = tmp_path / "raw"
        self._seed_raw_dir(raw_dir, n=3)
        replayer = AlternativeDataReplayer(raw_store_dir=str(raw_dir))
        payloads = list(replayer.iter_payloads())
        assert len(payloads) == 3

    def test_iter_payloads_with_date_filter(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        raw_dir = tmp_path / "raw"
        timestamps = self._seed_raw_dir(raw_dir, n=5)
        replayer = AlternativeDataReplayer(raw_store_dir=str(raw_dir))

        start = timestamps[2]
        payloads = list(replayer.iter_payloads(start=start))
        assert len(payloads) == 3  # slots 2, 3, 4

    def test_replay_calls_callback(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        raw_dir = tmp_path / "raw"
        self._seed_raw_dir(raw_dir, n=4)
        replayer = AlternativeDataReplayer(raw_store_dir=str(raw_dir))

        seen: List[Dict[str, Any]] = []
        count = replayer.replay(on_payload=seen.append)
        assert count == 4
        assert len(seen) == 4

    def test_replay_into_world_state(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        raw_dir = tmp_path / "raw"
        self._seed_raw_dir(raw_dir, n=2)
        replayer = AlternativeDataReplayer(raw_store_dir=str(raw_dir))

        states = []
        count = replayer.replay_into_world_state(on_world_state=states.append)
        assert count == 2
        for state in states:
            assert state.source == "replay"

    def test_list_available_range_empty(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        replayer = AlternativeDataReplayer(raw_store_dir=str(tmp_path / "missing"))
        info = replayer.list_available_range()
        assert info["count"] == 0
        assert info["earliest"] is None

    def test_list_available_range_populated(self, tmp_path):
        from btc_scraper.collectors.alternative_backfill import AlternativeDataReplayer

        raw_dir = tmp_path / "raw"
        self._seed_raw_dir(raw_dir, n=5)
        replayer = AlternativeDataReplayer(raw_store_dir=str(raw_dir))
        info = replayer.list_available_range()
        assert info["count"] == 5
        assert info["earliest"] is not None
        assert info["latest"] is not None


# ---------------------------------------------------------------------------
# Data Quality tests
# ---------------------------------------------------------------------------

class TestDataQualityChecker:
    def _fresh_payload(self) -> Dict[str, Any]:
        from btc_scraper.collectors.alternative_data import _default_payload

        p = _default_payload()
        # Override timestamp to "now" so freshness check passes
        p["timestamp"] = datetime.now(timezone.utc).isoformat()
        p.update({"funding_rate": 0.0, "open_interest": 1.0, "stablecoin_supply": 1.0,
                  "tvl": 1.0, "dxy": 100.0, "vix": 20.0, "us10y": 4.0,
                  "gold": 2000.0, "fear_greed_raw": 50.0, "fear_greed_score": 0.0})
        return p

    def test_healthy_payload_has_no_issues(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        checker = DataQualityChecker()
        report = checker.check(self._fresh_payload())
        assert report.is_healthy
        assert len(report.issues) == 0

    def test_stale_payload_detected(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        payload = self._fresh_payload()
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        payload["timestamp"] = old_ts

        checker = DataQualityChecker(max_age_seconds=300)
        report = checker.check(payload)
        assert not report.is_healthy
        assert any(i.issue_type == "stale" for i in report.issues)

    def test_missing_field_detected(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        payload = self._fresh_payload()
        del payload["funding_rate"]

        checker = DataQualityChecker()
        report = checker.check(payload)
        assert not report.is_healthy
        assert "funding_rate" in report.missing_fields

    def test_out_of_range_detected(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        payload = self._fresh_payload()
        payload["vix"] = 999.0  # way above upper bound of 200

        checker = DataQualityChecker()
        report = checker.check(payload)
        assert not report.is_healthy
        assert "vix" in report.out_of_range_fields

    def test_bad_timestamp_type_error(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        payload = self._fresh_payload()
        payload["timestamp"] = "not-a-timestamp"

        checker = DataQualityChecker()
        report = checker.check(payload)
        assert not report.is_healthy
        assert any(i.issue_type == "type_error" for i in report.issues)

    def test_to_dict_serializable(self):
        from btc_scraper.collectors.alternative_quality import DataQualityChecker

        checker = DataQualityChecker()
        report = checker.check(self._fresh_payload())
        d = report.to_dict()
        assert "is_healthy" in d
        # Must be JSON-serializable
        json.dumps(d)


class TestDataQualityDashboard:
    def _fresh_payload(self) -> Dict[str, Any]:
        from btc_scraper.collectors.alternative_data import _default_payload

        p = _default_payload()
        p["timestamp"] = datetime.now(timezone.utc).isoformat()
        p.update({"funding_rate": 0.0, "open_interest": 1.0, "stablecoin_supply": 1.0,
                  "tvl": 1.0, "dxy": 100.0, "vix": 20.0, "us10y": 4.0,
                  "gold": 2000.0, "fear_greed_raw": 50.0, "fear_greed_score": 0.0})
        return p

    def test_ingest_healthy_payload(self, tmp_path):
        from btc_scraper.collectors.alternative_quality import DataQualityDashboard

        dash = DataQualityDashboard(quality_log_path=str(tmp_path / "quality.json"))
        report = dash.ingest(self._fresh_payload())
        assert report.is_healthy

    def test_summary_after_ingests(self, tmp_path):
        from btc_scraper.collectors.alternative_quality import DataQualityDashboard

        dash = DataQualityDashboard(quality_log_path=str(tmp_path / "quality.json"))
        for _ in range(5):
            dash.ingest(self._fresh_payload())
        s = dash.summary(window_hours=24)
        assert s["total_checks"] == 5
        assert s["healthy_checks"] == 5
        assert s["health_rate"] == 1.0

    def test_quality_log_written(self, tmp_path):
        from btc_scraper.collectors.alternative_quality import DataQualityDashboard

        log_path = tmp_path / "quality.json"
        dash = DataQualityDashboard(quality_log_path=str(log_path))
        dash.ingest(self._fresh_payload())
        assert log_path.exists()
        entries = json.loads(log_path.read_text())
        assert len(entries) == 1

    def test_print_dashboard_runs(self, tmp_path, capsys):
        from btc_scraper.collectors.alternative_quality import DataQualityDashboard

        dash = DataQualityDashboard(quality_log_path=None)
        dash.ingest(self._fresh_payload())
        dash.print_dashboard()
        captured = capsys.readouterr()
        assert "Quality Dashboard" in captured.out


class TestCollectorHealthMonitor:
    def _fresh_payload(self) -> Dict[str, Any]:
        from btc_scraper.collectors.alternative_data import _default_payload

        p = _default_payload()
        p["timestamp"] = datetime.now(timezone.utc).isoformat()
        p.update({"funding_rate": 0.0, "open_interest": 1.0, "stablecoin_supply": 1.0,
                  "tvl": 1.0, "dxy": 100.0, "vix": 20.0, "us10y": 4.0,
                  "gold": 2000.0, "fear_greed_raw": 50.0, "fear_greed_score": 0.0})
        return p

    def test_record_collection_success(self, tmp_path):
        from btc_scraper.collectors.alternative_quality import (
            CollectorHealthMonitor,
            DataQualityDashboard,
        )

        dash = DataQualityDashboard(quality_log_path=None)
        monitor = CollectorHealthMonitor(dashboard=dash)
        report = monitor.record_collection("binance", self._fresh_payload(), success=True)
        assert report.is_healthy
        stats = monitor.uptime_stats()
        assert stats["binance"]["runs"] == 1
        assert stats["binance"]["failures"] == 0
        assert stats["binance"]["uptime"] == 1.0

    def test_record_collection_failure_triggers_alert(self, tmp_path):
        from btc_scraper.collectors.alternative_quality import (
            CollectorHealthMonitor,
            DataQualityDashboard,
        )

        alerts = []
        dash = DataQualityDashboard(quality_log_path=None)
        monitor = CollectorHealthMonitor(dashboard=dash, on_alert=alerts.append)
        monitor.record_collection("binance", self._fresh_payload(), success=False)
        assert len(alerts) >= 1
        assert alerts[0].source == "binance"

    def test_uptime_decreases_on_failures(self):
        from btc_scraper.collectors.alternative_quality import (
            CollectorHealthMonitor,
            DataQualityDashboard,
        )

        dash = DataQualityDashboard(quality_log_path=None)
        monitor = CollectorHealthMonitor(dashboard=dash)
        payload = self._fresh_payload()
        monitor.record_collection("fred", payload, success=True)
        monitor.record_collection("fred", payload, success=True)
        monitor.record_collection("fred", payload, success=False)
        stats = monitor.uptime_stats()
        assert stats["fred"]["uptime"] < 1.0

    def test_build_default_monitor_factory(self):
        from btc_scraper.collectors.alternative_quality import build_default_monitor

        monitor = build_default_monitor()
        assert monitor is not None
