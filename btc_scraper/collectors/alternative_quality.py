"""Data quality dashboard and alerting for the alternative-data pipeline.

This module provides:
- ``DataQualityChecker``: validates a normalized payload against expected
  field presence, freshness, and value-range thresholds.
- ``DataQualityDashboard``: accumulates check results over time and
  produces a summary report.
- ``CollectorHealthMonitor``: tracks collector uptime, stale-value counts,
  and missing-data events; emits structured alert records that can be
  forwarded to Telegram or any other notification channel.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from btc_scraper.collectors.alternative_data import _default_payload
from btc_scraper.core.paths import build_data_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

DEFAULT_QUALITY_LOG_PATH = str(build_data_path("alternative_quality.json"))

# (min_value, max_value) for each field. None means no bound check.
FIELD_BOUNDS: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    # directional scores: bearish → bullish
    "funding_pressure": (-1.0, 1.0),
    "open_interest_pressure": (-1.0, 1.0),
    "liquidity_pressure": (-1.0, 1.0),
    "macro_pressure": (-1.0, 1.0),
    "risk_on_score": (-1.0, 1.0),
    "orderbook_imbalance": (-1.0, 1.0),
    "stablecoin_momentum": (-1.0, 1.0),
    "etf_momentum": (-1.0, 1.0),

    # risk magnitude scores
    "macro_risk_score": (0.0, 1.0),
    "defi_liquidity_score": (-1.0, 1.0),

    # raw positive values
    "stablecoin_supply_total": (0.0, None),
    "tvl": (0.0, None),
    "chain_tvl": (0.0, None),
    "hashrate": (0.0, None),
    "active_addresses": (0.0, None),
    "open_interest": (0.0, None),
    
    # original raw values bounds for compatibility
    "funding_rate": (-0.1, 0.1),
    "stablecoin_supply": (0.0, None),
    "etf_flow": (None, None),
    "options_iv": (0.0, 5.0),
    "whale_score": (0.0, 1.0),
    "exchange_netflow": (None, None),
    "dxy": (60.0, 160.0),
    "vix": (5.0, 200.0),
    "us10y": (0.0, 20.0),
    "gold": (500.0, 5000.0),
}

# Fields that must be present in every payload
REQUIRED_FIELDS: List[str] = [
    "timestamp",
    "funding_rate",
    "open_interest",
    "stablecoin_supply",
    "tvl",
    "dxy",
    "vix",
    "us10y",
    "gold",
    "fear_greed_raw",
    "fear_greed_score",
]

# Maximum age (seconds) before a payload is considered stale
DEFAULT_MAX_AGE_SECONDS: int = 900  # 15 minutes


# ---------------------------------------------------------------------------
# Data Quality Checker
# ---------------------------------------------------------------------------

class QualityIssue:
    """Represents a single data-quality problem in a payload."""

    def __init__(self, field: str, issue_type: str, detail: str) -> None:
        self.field = field
        self.issue_type = issue_type  # "missing", "stale", "out_of_range", "type_error"
        self.detail = detail

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "issue_type": self.issue_type, "detail": self.detail}

    def __repr__(self) -> str:
        return f"QualityIssue({self.issue_type}:{self.field} – {self.detail})"


class QualityReport:
    """Result of a single payload quality check."""

    def __init__(
        self,
        timestamp: datetime,
        issues: List[QualityIssue],
        payload_timestamp: Optional[datetime] = None,
    ) -> None:
        self.timestamp = timestamp
        self.issues = issues
        self.payload_timestamp = payload_timestamp
        self.is_healthy = len(issues) == 0

    @property
    def missing_fields(self) -> List[str]:
        return [i.field for i in self.issues if i.issue_type == "missing"]

    @property
    def stale_fields(self) -> List[str]:
        return [i.field for i in self.issues if i.issue_type == "stale"]

    @property
    def out_of_range_fields(self) -> List[str]:
        return [i.field for i in self.issues if i.issue_type == "out_of_range"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked_at": self.timestamp.isoformat(),
            "payload_timestamp": self.payload_timestamp.isoformat() if self.payload_timestamp else None,
            "is_healthy": self.is_healthy,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
        }


class DataQualityChecker:
    """Validate a single alternative-data payload for quality issues."""

    def __init__(
        self,
        required_fields: Optional[List[str]] = None,
        field_bounds: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self.required_fields = required_fields or REQUIRED_FIELDS
        self.field_bounds = field_bounds or FIELD_BOUNDS
        self.max_age_seconds = max_age_seconds

    def check(self, payload: Dict[str, Any]) -> QualityReport:
        """Run all quality checks and return a ``QualityReport``."""
        issues: List[QualityIssue] = []
        now = datetime.now(timezone.utc)

        # --- Freshness check ---
        payload_ts: Optional[datetime] = None
        raw_ts = payload.get("timestamp")
        if raw_ts:
            try:
                payload_ts = datetime.fromisoformat(str(raw_ts))
                if payload_ts.tzinfo is None:
                    payload_ts = payload_ts.replace(tzinfo=timezone.utc)
                age = (now - payload_ts).total_seconds()
                if age > self.max_age_seconds:
                    issues.append(
                        QualityIssue(
                            "timestamp",
                            "stale",
                            f"Payload is {age:.0f}s old (max {self.max_age_seconds}s).",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    QualityIssue("timestamp", "type_error", f"Cannot parse timestamp: {raw_ts!r}")
                )
        else:
            issues.append(QualityIssue("timestamp", "missing", "No timestamp field in payload."))

        # --- Required-field presence check ---
        for field in self.required_fields:
            if field == "timestamp":
                continue
            if field not in payload:
                issues.append(QualityIssue(field, "missing", f"Field '{field}' is absent."))

        # --- Value-range check ---
        for field, (lo, hi) in self.field_bounds.items():
            raw_val = payload.get(field)
            if raw_val is None:
                continue  # Already caught by presence check if required
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                issues.append(QualityIssue(field, "type_error", f"Cannot cast '{raw_val!r}' to float."))
                continue
            # Skip range check for sentinel 0.0 (means "no data collected yet")
            if val == 0.0:
                continue
            if lo is not None and val < lo:
                issues.append(
                    QualityIssue(field, "out_of_range", f"{val} < lower bound {lo}.")
                )
            if hi is not None and val > hi:
                issues.append(
                    QualityIssue(field, "out_of_range", f"{val} > upper bound {hi}.")
                )

        return QualityReport(timestamp=now, issues=issues, payload_timestamp=payload_ts)


# ---------------------------------------------------------------------------
# Data Quality Dashboard
# ---------------------------------------------------------------------------

class DataQualityDashboard:
    """Accumulate quality reports and produce summary statistics.

    Reports are stored in memory (bounded by ``max_history``) and optionally
    persisted to a JSON log file for later review.
    """

    def __init__(
        self,
        quality_log_path: Optional[str] = DEFAULT_QUALITY_LOG_PATH,
        max_history: int = 1000,
        checker: Optional[DataQualityChecker] = None,
    ) -> None:
        self.quality_log_path = Path(quality_log_path) if quality_log_path else None
        self.max_history = max_history
        self.checker = checker or DataQualityChecker()
        self._history: List[QualityReport] = []

    # ------------------------------------------------------------------

    def ingest(self, payload: Dict[str, Any]) -> QualityReport:
        """Check *payload* and record the result."""
        report = self.checker.check(payload)
        self._history.append(report)
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]
        if self.quality_log_path is not None:
            self._append_log(report)
        if not report.is_healthy:
            logger.warning(
                "Alternative-data quality issues (%d): %s",
                len(report.issues),
                [str(i) for i in report.issues],
            )
        return report

    def summary(self, window_hours: float = 24.0) -> Dict[str, Any]:
        """Return aggregated quality statistics for the past *window_hours*."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        recent = [r for r in self._history if r.timestamp >= cutoff]

        total = len(recent)
        if total == 0:
            return {
                "window_hours": window_hours,
                "total_checks": 0,
                "healthy_checks": 0,
                "unhealthy_checks": 0,
                "health_rate": 1.0,
                "top_issues": [],
            }

        healthy = sum(1 for r in recent if r.is_healthy)
        issue_counts: Dict[str, int] = defaultdict(int)
        for r in recent:
            for issue in r.issues:
                issue_counts[f"{issue.issue_type}:{issue.field}"] += 1

        top_issues = sorted(
            [{"key": k, "count": v} for k, v in issue_counts.items()],
            key=lambda x: -x["count"],
        )[:10]

        return {
            "window_hours": window_hours,
            "total_checks": total,
            "healthy_checks": healthy,
            "unhealthy_checks": total - healthy,
            "health_rate": round(healthy / total, 4),
            "top_issues": top_issues,
        }

    def print_dashboard(self, window_hours: float = 24.0) -> None:
        """Print a human-readable quality dashboard to stdout."""
        s = self.summary(window_hours=window_hours)
        print("=" * 55)
        print(f"  Alternative Data Quality Dashboard (last {window_hours}h)")
        print("=" * 55)
        print(f"  Total checks   : {s['total_checks']}")
        print(f"  Healthy        : {s['healthy_checks']}")
        print(f"  Unhealthy      : {s['unhealthy_checks']}")
        print(f"  Health rate    : {s['health_rate']:.1%}")
        
        # Print ETF Flow Status block (Kế hoạch §14)
        print("-" * 55)
        print("  ETF Flow Status (Cache / DB):")
        try:
            from btc_scraper.collectors.parsebot_farside_collector import get_etf_feature_for_scoring
            for sym in ["BTC", "ETH", "SOL"]:
                feat = get_etf_feature_for_scoring(sym, mode="recent")
                status = feat["etf_flow_status"]
                val_m = feat["total_flow_usd_m"]
                val_str = f"{val_m:+.1f}M" if val_m is not None else "N/A"
                print(f"    {sym:5s}: {status:12s} | Net Flow: {val_str:10s} | Quality: {1.0 if status == 'ok' else 0.0:.1f}")
        except Exception as e:
            print(f"    Error printing ETF flow status: {e}")
            
        if s["top_issues"]:
            print("-" * 55)
            print("  Top issues:")
            for item in s["top_issues"]:
                print(f"    {item['key']:40s}  x{item['count']}")
        print("=" * 55)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _append_log(self, report: QualityReport) -> None:
        if self.quality_log_path is None:
            return
        self.quality_log_path.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if self.quality_log_path.exists():
            try:
                with open(self.quality_log_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        existing.append(report.to_dict())
        # Keep last 5 000 entries on disk
        existing = existing[-5000:]
        with open(self.quality_log_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Collector Health Monitor
# ---------------------------------------------------------------------------

class AlertRecord:
    """A single alert emitted by the health monitor."""

    LEVELS = {"info", "warning", "critical"}

    def __init__(self, level: str, source: str, message: str) -> None:
        self.level = level if level in self.LEVELS else "warning"
        self.source = source
        self.message = message
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, str]:
        return {
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }

    def __repr__(self) -> str:
        return f"[{self.level.upper()}] {self.source}: {self.message}"


class CollectorHealthMonitor:
    """Track collector uptime, stale-value events, and missing-data alerts.

    The monitor wraps a ``DataQualityDashboard`` and adds:
    - Uptime / failure-rate tracking per named collector.
    - Alert generation for critical quality degradation.
    - Optional external alert callback (e.g. Telegram forwarder).
    """

    def __init__(
        self,
        dashboard: Optional[DataQualityDashboard] = None,
        on_alert: Optional[Callable[[AlertRecord], None]] = None,
        unhealthy_threshold: float = 0.8,  # health rate below this triggers alert
    ) -> None:
        self.dashboard = dashboard or DataQualityDashboard()
        self.on_alert = on_alert
        self.unhealthy_threshold = unhealthy_threshold

        self._run_counts: Dict[str, int] = defaultdict(int)
        self._failure_counts: Dict[str, int] = defaultdict(int)
        self._alerts: List[AlertRecord] = []

    # ------------------------------------------------------------------

    def record_collection(
        self,
        collector_name: str,
        payload: Dict[str, Any],
        success: bool = True,
    ) -> QualityReport:
        """Record a collection event and run quality checks.

        Args:
            collector_name: Identifier of the collector (e.g. ``"binance"``).
            payload: The collected/normalized payload.
            success: Whether the underlying API call succeeded.

        Returns:
            The quality report for this payload.
        """
        self._run_counts[collector_name] += 1
        if not success:
            self._failure_counts[collector_name] += 1
            alert = AlertRecord(
                "warning",
                collector_name,
                f"Collection failed (run #{self._run_counts[collector_name]}).",
            )
            self._emit_alert(alert)

        report = self.dashboard.ingest(payload)

        if not report.is_healthy:
            # Check if missing fields are critical
            if report.missing_fields:
                alert = AlertRecord(
                    "warning",
                    collector_name,
                    f"Missing fields: {report.missing_fields}.",
                )
                self._emit_alert(alert)
            if report.stale_fields:
                alert = AlertRecord(
                    "warning",
                    collector_name,
                    f"Stale data detected.",
                )
                self._emit_alert(alert)

        # Check overall health rate and escalate if needed
        summary = self.dashboard.summary(window_hours=1.0)
        if summary["total_checks"] >= 5:
            if summary["health_rate"] < self.unhealthy_threshold:
                alert = AlertRecord(
                    "critical",
                    collector_name,
                    f"Health rate {summary['health_rate']:.1%} below threshold "
                    f"{self.unhealthy_threshold:.1%} in the last hour.",
                )
                self._emit_alert(alert)

        # Perform ETF specific alert checks (Phase F Gap)
        if collector_name == "alternative_data":
            try:
                etf_alert = self.check_etf_alert_conditions()
                if etf_alert:
                    self._emit_alert(etf_alert)
            except Exception as e:
                logger.warning("Failed to run ETF alert checks: %s", e)

        return report

    def check_etf_alert_conditions(self) -> Optional[AlertRecord]:
        """Check MongoDB fetch logs and cache status for ETF specific alert conditions.
        Emits alert if:
        - ETF flow has failed for more than 2 consecutive days (last 48 hours).
        - ETF flow data is stale (>36 hours).
        - Parse.bot returns 401/403 (Authentication error).
        """
        try:
            from btc_scraper.core.db import db
            logs_col = db["alternative_data_fetch_logs"]
            flows_col = db["alternative_data_etf_flows"]
        except Exception:
            return None

        # 1. Check for 401/403 authentication error in last 24 hours
        try:
            auth_errors = list(logs_col.find({
                "source": "parsebot_farside",
                "status": "failed",
                "error": {"$regex": "401|403|Unauthorized|Forbidden", "$options": "i"}
            }).sort("fetched_at", -1).limit(5))
            if auth_errors:
                return AlertRecord(
                    "critical",
                    "parsebot_farside",
                    f"Authentication error detected (401/403) in Parse.bot requests: {auth_errors[0].get('error')}"
                )
        except Exception:
            pass

        # 2. Check for failed > 2 days (48 hours) consecutive
        try:
            last_attempts = list(logs_col.find({"source": "parsebot_farside"}).sort("fetched_at", -1).limit(20))
            if last_attempts:
                limit_dt = datetime.now(timezone.utc) - timedelta(days=2)
                recent_attempts = []
                for attempt in last_attempts:
                    fetched_at_str = attempt.get("fetched_at")
                    if fetched_at_str:
                        attempt_dt = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
                        if attempt_dt > limit_dt:
                            recent_attempts.append(attempt)
                
                if recent_attempts and all(att.get("status") == "failed" for att in recent_attempts):
                    return AlertRecord(
                        "critical",
                        "parsebot_farside",
                        f"ETF flow has failed consecutively for more than 2 days (total {len(recent_attempts)} failed attempts)."
                    )
        except Exception:
            pass

        # 3. Check for stale data > 36 hours
        try:
            latest_flow = flows_col.find_one({"source": "parsebot_farside", "status": "ok"}, sort=[("fetched_at", -1)])
            if latest_flow:
                fetched_at_str = latest_flow.get("fetched_at")
                if fetched_at_str:
                    fetched_dt = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - fetched_dt).total_seconds() / 3600.0
                    if age_hours > 36:
                        return AlertRecord(
                            "warning",
                            "parsebot_farside",
                            f"ETF flow data is stale: last successful fetch was {age_hours:.1f} hours ago (exceeds 36-hour threshold)."
                        )
        except Exception:
            pass

        return None

    def uptime_stats(self) -> Dict[str, Any]:
        """Return uptime statistics per collector."""
        stats: Dict[str, Any] = {}
        for name, runs in self._run_counts.items():
            failures = self._failure_counts.get(name, 0)
            stats[name] = {
                "runs": runs,
                "failures": failures,
                "uptime": round(1.0 - failures / max(runs, 1), 4),
            }
        return stats

    def recent_alerts(self, n: int = 20) -> List[Dict[str, str]]:
        """Return the last *n* alert records as dicts."""
        return [a.to_dict() for a in self._alerts[-n:]]

    def clear_alerts(self) -> None:
        """Clear the in-memory alert log."""
        self._alerts.clear()

    # ------------------------------------------------------------------

    def _emit_alert(self, alert: AlertRecord) -> None:
        self._alerts.append(alert)
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]
        logger.warning("ALERT %s", alert)
        if self.on_alert is not None:
            try:
                self.on_alert(alert)
            except Exception:  # pragma: no cover
                logger.exception("on_alert callback raised an exception.")


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def build_default_monitor(
    on_alert: Optional[Callable[[AlertRecord], None]] = None,
) -> CollectorHealthMonitor:
    """Build a fully-configured health monitor with default paths."""
    dashboard = DataQualityDashboard()
    return CollectorHealthMonitor(dashboard=dashboard, on_alert=on_alert)
