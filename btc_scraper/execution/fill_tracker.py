"""
btc_scraper/execution/fill_tracker.py
Phase 10 – Sprint 10.1: Fill Tracker

Tracks order lifecycle states and serialises fill records to disk.

State machine:
  PENDING → PARTIAL_FILL → FILLED
           → CANCELLED
           → TIMEOUT
           → REJECTED
"""
from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timezone

from btc_scraper.core.paths import (
    build_execution_data_path,
    build_logs_path,
    runtime_deployment_id,
    runtime_environment,
    runtime_evidence_eligible,
    runtime_id,
    runtime_owner_metadata,
    runtime_paper_run_id,
)


# ── Enums ──────────────────────────────────────────────────────────────────────
class OrderStatus:
    PENDING = "PENDING"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


# ── Data schemas ───────────────────────────────────────────────────────────────
@dataclass
class FillEvent:
    """One partial fill from the exchange."""
    fill_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    execution_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    price: float = 0.0
    qty: float = 0.0
    fee: float = 0.0
    fee_asset: str = "USDT"
    is_maker: bool = False


@dataclass
class ExecutionRecord:
    """Full execution attempt log — one per submitted order."""

    # Identity
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    signal_id: str = ""
    prediction_id: str = ""
    entry_decision_id: str = ""
    reservation_id: str = ""
    idempotency_key: str = ""
    client_order_id: str = ""
    exchange_order_id: str = ""
    position_id: str = ""
    lifecycle_schema_version: str = "trade-lifecycle-v1"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Instrument
    coin: str = ""
    exchange: str = "binance"
    market_type: str = "futures"   # futures | spot
    side: str = "BUY"              # BUY | SELL

    # Sizing
    intended_qty: float = 0.0
    intended_notional: float = 0.0

    # Order spec
    order_type: str = "LIMIT"
    time_in_force: str = "GTC"

    # Prices
    decision_price: float = 0.0   # price when signal fired
    submitted_price: float = 0.0  # price of the limit order submitted
    avg_fill_price: float = 0.0   # volume-weighted avg fill price
    filled_qty: float = 0.0
    unfilled_qty: float = 0.0

    # Cost breakdown
    fee: float = 0.0
    fee_asset: str = "USDT"
    spread_bps_at_submit: float = 0.0
    orderbook_imbalance_at_submit: float = 0.0
    top_bid: float = 0.0
    top_ask: float = 0.0
    mid_price: float = 0.0
    latency_ms: int = 0

    # Timing
    submit_time: str = ""
    first_fill_time: str = ""
    last_fill_time: str = ""

    # Status
    status: str = OrderStatus.PENDING
    reason: str = ""
    fill_source: str = "real_paper"  # real_paper | synthetic | replay | debug
    # Provenance: records created by submit_paper are stored separately from
    # live/legacy execution records and can be used as Phase 5 evidence.
    execution_mode: str = "live"  # paper | live | replay | test
    paper_run_id: str = ""
    environment: str = field(default_factory=runtime_environment)
    deployment_id: str = field(default_factory=runtime_deployment_id)
    runtime_id: str = field(default_factory=runtime_id)
    process_id: int = 0
    hostname: str = ""
    started_at: str = ""
    evidence_eligible: bool = field(default_factory=runtime_evidence_eligible)

    # Fill events
    fills: List[FillEvent] = field(default_factory=list)


    # Derived metrics (populated by PostTradeAnalyzer)
    arrival_price: float = 0.0
    decision_to_submit_slippage_bps: float = 0.0
    submit_to_fill_slippage_bps: float = 0.0
    total_slippage_bps: float = 0.0
    implementation_shortfall_bps: float = 0.0
    market_impact_bps: float = 0.0
    opportunity_cost_bps: float = 0.0

    # Execution model predictions
    expected_slippage_bps: float = 0.0
    liquidity_score: float = 0.0
    max_safe_order_size: float = 0.0
    guard_action: str = "PASS"   # PASS | REDUCE | REJECT

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def add_fill(self, fill: FillEvent) -> None:
        self.fills.append(fill)
        # Update aggregate fill metrics
        total_qty = sum(f.qty for f in self.fills)
        total_value = sum(f.qty * f.price for f in self.fills)
        self.filled_qty = total_qty
        self.unfilled_qty = max(0.0, self.intended_qty - total_qty)
        self.avg_fill_price = total_value / total_qty if total_qty > 0 else 0.0
        self.fee = sum(f.fee for f in self.fills)

        if not self.first_fill_time:
            self.first_fill_time = fill.timestamp
        self.last_fill_time = fill.timestamp

        if self.unfilled_qty <= 1e-9:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIAL_FILL


class FillTracker:
    """
    Manages active orders and persists fill records.
    """

    def __init__(self, log_dir: str | None = None, fills_dir: str | None = None):
        self.log_dir = Path(log_dir) if log_dir is not None else build_logs_path("execution")
        self.fills_dir = Path(fills_dir) if fills_dir is not None else build_execution_data_path("fills")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.fills_dir.mkdir(parents=True, exist_ok=True)

        # Active orders keyed by execution_id
        self._active: Dict[str, ExecutionRecord] = {}
        # All completed (filled/cancelled/rejected)
        self._history: List[ExecutionRecord] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def register(self, record: ExecutionRecord) -> None:
        """Register a new pending order."""
        self._active[record.execution_id] = record
        self._write_jsonl(record)

    def apply_fill(self, execution_id: str, fill: FillEvent) -> Optional[ExecutionRecord]:
        rec = self._active.get(execution_id)
        if rec is None:
            return None
        rec.add_fill(fill)
        self._write_jsonl(rec)
        if rec.status == OrderStatus.FILLED:
            self._complete(rec)
        return rec

    def cancel(self, execution_id: str, reason: str = "cancelled") -> Optional[ExecutionRecord]:
        rec = self._active.pop(execution_id, None)
        if rec:
            rec.status = OrderStatus.CANCELLED
            rec.reason = reason
            self._complete(rec)
            self._write_jsonl(rec)
        return rec

    def timeout(self, execution_id: str) -> Optional[ExecutionRecord]:
        rec = self._active.pop(execution_id, None)
        if rec:
            rec.status = OrderStatus.TIMEOUT
            rec.reason = "limit_order_timeout"
            self._complete(rec)
            self._write_jsonl(rec)
        return rec

    def reject(self, record: ExecutionRecord, reason: str) -> ExecutionRecord:
        record.status = OrderStatus.REJECTED
        record.reason = reason
        self._history.append(record)
        self._write_jsonl(record)
        return record

    def simulate_fill(self, record: ExecutionRecord, fill_price: float) -> ExecutionRecord:
        """
        Convenience method for paper/backtest mode.
        Creates a single full fill at fill_price.
        """
        fill = FillEvent(
            execution_id=record.execution_id,
            price=fill_price,
            qty=record.intended_qty,
            fee=record.intended_notional * 0.0005,  # 5 bps taker default
        )
        record.add_fill(fill)
        record.submit_time = record.timestamp
        record.status = OrderStatus.FILLED
        self._history.append(record)
        self._write_fills_jsonl(record)
        self._write_jsonl(record)
        return record

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_active(self) -> List[ExecutionRecord]:
        return list(self._active.values())

    def get_history(self, limit: int = 200) -> List[ExecutionRecord]:
        return self._history[-limit:]

    def reject_rate(self) -> float:
        total = len(self._history)
        if total == 0:
            return 0.0
        rejected = sum(1 for r in self._history if r.status == OrderStatus.REJECTED)
        return rejected / total

    # ── Persistence ───────────────────────────────────────────────────────────

    def _complete(self, record: ExecutionRecord) -> None:
        self._active.pop(record.execution_id, None)
        self._history.append(record)
        self._write_fills_jsonl(record)

    def _write_jsonl(self, record: ExecutionRecord) -> None:
        """Append to daily execution JSONL log."""
        self._apply_runtime_metadata(record)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for_record(self.log_dir, "execution", date_str, record)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _write_fills_jsonl(self, record: ExecutionRecord) -> None:
        """Write completed fill record to fills dataset for ML training."""
        self._apply_runtime_metadata(record)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for_record(self.fills_dir, "fills", date_str, record)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def _path_for_record(base_dir: Path, prefix: str, date_str: str, record: ExecutionRecord) -> Path:
        """Return a provenance-specific JSONL path without trusting arbitrary modes."""
        if record.execution_mode == "paper":
            target_dir = base_dir / "paper"
        elif record.execution_mode == "replay":
            target_dir = base_dir / "replay"
        elif record.execution_mode == "test":
            target_dir = base_dir / "test"
        else:
            target_dir = base_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{prefix}_{date_str}.jsonl"

    @staticmethod
    def _apply_runtime_metadata(record: ExecutionRecord) -> None:
        record.environment = runtime_environment()
        record.deployment_id = runtime_deployment_id()
        record.runtime_id = runtime_id()
        owner = runtime_owner_metadata()
        record.process_id = int(owner["process_id"])
        record.hostname = str(owner["hostname"])
        record.started_at = str(owner["started_at"])
        record.evidence_eligible = runtime_evidence_eligible()
        if not record.paper_run_id:
            record.paper_run_id = runtime_paper_run_id() or ""
