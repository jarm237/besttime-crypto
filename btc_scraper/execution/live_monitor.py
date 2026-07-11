"""
btc_scraper/execution/live_monitor.py
Phase 6 — Task 6.6: Real-Time Live Monitor

Pulls from source-of-truth sources:
    - Positions + PnL: exchange + position tracker
    - Risk usage: HardRiskLimits
    - Kill-switch state: KillSwitch
    - Model health: last prediction timestamp log
    - Data health: alt data freshness
    - DB health: Phase 4 resilience layer

Event-driven hooks for kill-switch triggers:
    on_fill, on_pnl_change, on_reject, on_health_change

Dashboard snapshot written to data/execution/live_monitor_snapshot.json every 30s.
Kill-switch decisions are event-driven, NOT snapshot-based.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable, Dict, List, Optional

from .hard_risk_limits import HardRiskLimits
from .kill_switch import KillSwitch
from .alerting import AlertManager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
SNAPSHOT_PATH = BASE_DIR / "data" / "execution" / "live_monitor_snapshot.json"
PREDICTIONS_LOG = BASE_DIR / "logs"
ALT_DATA_DIR = BASE_DIR / "data" / "raw_alternative"
FILLS_DIR = BASE_DIR / "data" / "execution" / "fills"

DATA_STALE_THRESHOLD_MINUTES = 15
MODEL_STALE_THRESHOLD_MINUTES = 10


@dataclass
class PositionSnapshot:
    symbol: str
    side: str
    size_usdt: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    updated_at: str


@dataclass
class MonitorSnapshot:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_equity_change: float = 0.0
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    risk_state: Dict[str, Any] = field(default_factory=dict)
    kill_switch_state: str = "ARMED"
    system_health: Dict[str, Any] = field(default_factory=dict)
    fill_count_today: int = 0
    last_fill_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LiveMonitor:
    """
    Real-time live trading monitor.

    Runs a background thread that collects a snapshot every `snapshot_interval_s` seconds.
    Exposes event hooks for immediate kill-switch evaluation.

    Usage:
        monitor = LiveMonitor(kill_switch=ks, risk_limits=rl, alert_manager=am)
        monitor.start()
        # From fill handler:
        monitor.on_fill(pnl=12.5, fee=0.1, symbol="BTCUSDT")
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        risk_limits: Optional[HardRiskLimits] = None,
        alert_manager: Optional[AlertManager] = None,
        exchange_client=None,
        snapshot_interval_s: int = 30,
        daily_loss_alert_threshold_pct: float = 0.75,  # alert at 75% of limit
    ):
        self._ks = kill_switch or KillSwitch()
        self._risk = risk_limits or HardRiskLimits()
        self._alerts = alert_manager or AlertManager()
        self._exchange = exchange_client
        self._interval = snapshot_interval_s
        self._loss_alert_pct = daily_loss_alert_threshold_pct

        self._lock = RLock()
        self._running = False
        self._thread: Optional[Thread] = None

        # Accumulated in-process metrics
        self._fills_today: List[Dict[str, Any]] = []
        self._positions: List[PositionSnapshot] = []

    # ── Event hooks (event-driven, called immediately) ────────────────────────

    def on_fill(self, pnl: float = 0.0, fee: float = 0.0, funding: float = 0.0,
                symbol: str = "", is_loss: bool = False) -> None:
        """Called immediately after a fill is confirmed."""
        with self._lock:
            self._fills_today.append({
                "symbol": symbol, "pnl": pnl, "fee": fee,
                "funding": funding, "at": datetime.now(timezone.utc).isoformat()
            })
            self._risk.record_fill(realized_pnl=pnl, fee=fee, funding=funding)
            self._ks.record_loss(is_loss=is_loss)

        # Check loss limits immediately (not on next snapshot)
        self._evaluate_loss_limits()

    def on_pnl_change(self, unrealized_pnl: float) -> None:
        """Called when unrealized PnL changes significantly."""
        self._risk.update_unrealized(unrealized_pnl)
        self._evaluate_loss_limits()

    def on_reject(self) -> None:
        """Called on order rejection."""
        self._ks.record_execution_error()

    def on_health_change(self, component: str, is_healthy: bool) -> None:
        """Called when a system component health changes."""
        if not is_healthy:
            trigger_map = {
                "model": "model_unavailable",
                "data": "data_stale",
                "db": "db_degraded",
            }
            trigger = trigger_map.get(component, "execution_anomaly")
            self._ks.trigger(trigger)
            self._alerts.critical("system_health_degraded",
                                  f"Component unhealthy: {component}", symbol=None)

    def on_position_mismatch(self, severity: str = "minor") -> None:
        """Called when position reconciliation fails."""
        trigger = "position_mismatch_severe" if severity == "severe" else "position_mismatch_minor"
        self._ks.trigger(trigger)
        self._alerts.critical("position_mismatch", f"Position mismatch detected (severity={severity})")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _evaluate_loss_limits(self) -> None:
        state = self._risk.get_state_summary()
        cal_loss = state.get("calendar_equity_loss", 0.0)
        limit = state.get("limits", {}).get("max_daily_loss_usdt", 5.0)

        # Alert at threshold
        if cal_loss < 0 and abs(cal_loss) >= abs(limit) * self._loss_alert_pct:
            self._alerts.warning(
                "daily_loss_approaching",
                f"Daily equity loss {cal_loss:.2f} is {abs(cal_loss)/abs(limit)*100:.0f}% of limit {limit:.2f}",
            )

        # Trigger kill-switch at breach
        if cal_loss <= -limit:
            self._ks.trigger("daily_loss_breach", value=cal_loss, threshold=-limit)
            self._alerts.critical(
                "daily_loss_breach",
                f"Daily equity loss {cal_loss:.2f} breached limit {limit:.2f}",
            )

        # Rolling 24h
        rolling_loss = state.get("rolling_24h_loss", 0.0)
        rolling_limit = state.get("limits", {}).get("max_rolling_24h_loss_usdt", 7.0)
        if rolling_loss <= -rolling_limit:
            self._ks.trigger("daily_loss_breach", value=rolling_loss, threshold=-rolling_limit)

    def _collect_system_health(self) -> Dict[str, Any]:
        """Pull health from source-of-truth components."""
        now = time.time()
        health: Dict[str, bool] = {}

        # Model health: look for recent prediction log
        try:
            log_files = sorted(PREDICTIONS_LOG.glob("predictions_*.log"), reverse=True)
            if log_files:
                age_m = (now - log_files[0].stat().st_mtime) / 60
                health["model"] = age_m < MODEL_STALE_THRESHOLD_MINUTES
            else:
                health["model"] = False
        except Exception:
            health["model"] = False

        # Data health: look for recent alt-data snapshot
        try:
            alt_files = sorted(ALT_DATA_DIR.glob("alternative_*.json"), reverse=True)
            if alt_files:
                age_m = (now - alt_files[0].stat().st_mtime) / 60
                health["data"] = age_m < DATA_STALE_THRESHOLD_MINUTES
            else:
                health["data"] = False
        except Exception:
            health["data"] = False

        # DB health: check execution fills dir writeable
        try:
            test_path = FILLS_DIR / ".health_check"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_text("ok")
            test_path.unlink()
            health["db"] = True
        except Exception:
            health["db"] = False

        ready = all(health.values())
        return {"ready": ready, "dependencies": health}

    def _collect_snapshot(self) -> MonitorSnapshot:
        sys_health = self._collect_system_health()
        risk_state = self._risk.get_state_summary()
        ks_state = self._ks.state

        with self._lock:
            fills = list(self._fills_today)

        realized = sum(f.get("pnl", 0) for f in fills)
        fees = sum(f.get("fee", 0) + f.get("funding", 0) for f in fills)
        unrealized = risk_state.get("unrealized_pnl", 0.0)
        last_fill_at = fills[-1]["at"] if fills else None

        snap = MonitorSnapshot(
            realized_pnl=round(realized, 4),
            unrealized_pnl=round(unrealized, 4),
            total_equity_change=round(realized + unrealized - fees, 4),
            open_positions=[asdict(p) for p in self._positions],
            risk_state=risk_state,
            kill_switch_state=ks_state,
            system_health=sys_health,
            fill_count_today=len(fills),
            last_fill_at=last_fill_at,
        )
        return snap

    def _write_snapshot(self, snap: MonitorSnapshot) -> None:
        try:
            SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = SNAPSHOT_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(SNAPSHOT_PATH)
        except Exception as exc:
            logger.error(f"[LiveMonitor] Snapshot write failed: {exc}")

    # ── Background thread ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                snap = self._collect_snapshot()
                self._write_snapshot(snap)

                # Check health-based triggers
                if not snap.system_health.get("ready", True):
                    for comp, ok in snap.system_health.get("dependencies", {}).items():
                        if not ok:
                            self.on_health_change(comp, False)
                            break

            except Exception as exc:
                logger.error(f"[LiveMonitor] Loop error: {exc}")

            time.sleep(self._interval)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True, name="LiveMonitor")
        self._thread.start()
        logger.info("[LiveMonitor] Started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[LiveMonitor] Stopped")

    def get_snapshot(self) -> Dict[str, Any]:
        snap = self._collect_snapshot()
        return snap.to_dict()
