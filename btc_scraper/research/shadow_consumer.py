"""
btc_scraper/research/shadow_consumer.py
Phase C3 & Phase C4 / Phase D: Isolated Prospective Shadow Consumer & Crash-Safe Runtime Adapter.

Provides:
1. ShadowConsumer: Stateful, isolated adapter driving the shadow evaluation path:
   `Incoming 15m closed candles -> ClosedCandleAggregator -> 1h closed candle -> Feature extraction -> ProspectiveShadowEvaluator -> Isolated evidence persistence`
2. Crash-Safe & Idempotent Checkpointing:
   - Atomic temporary-file replacement for all checkpoint and evidence writes.
   - Preserves evaluator internal position state across restarts (evaluator_position).
   - Preserves in-flight aggregator bucket across restarts (in_flight_15m_bars).
   - Deduplicates opportunities via deterministic opportunity_id tracking (processed_opportunity_ids).
   - Maintains append-only resolved trade ledger (resolved_trades_{candidate}_{symbol}.jsonl).
3. Strict Isolation:
   - Completely decoupled from canonical AutoTrader, ExecutionEngine, and MongoDB closed_positions.
   - Generates simulated execution intent only (is_simulated_shadow=True, is_actual_paper_fill=False).
   - Read-only ingestion; never modifies collector state or transmits real orders.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.candidate_freeze import FrozenCandidateSnapshot
from btc_scraper.research.candle_aggregator import ClosedCandleAggregator
from btc_scraper.research.prospective_shadow_evaluator import (
    ProspectiveOpportunity,
    ProspectiveShadowEvaluator,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsumerCheckpoint:
    """Immutable state representation of the shadow consumer checkpoint."""
    candidate_id: str
    symbol: str
    freeze_hash: str
    last_processed_15m_timestamp: str
    last_emitted_1h_timestamp: str
    total_15m_ingested: int
    total_1h_emitted: int
    total_evaluations: int
    total_signals: int
    resolved_trade_count: int
    cumulative_net_pnl: float
    updated_at_utc: str
    in_flight_15m_bars: Tuple[Mapping[str, Any], ...] = ()
    evaluator_position: Optional[Mapping[str, Any]] = None
    processed_opportunity_ids: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
            "freeze_hash": self.freeze_hash,
            "last_processed_15m_timestamp": self.last_processed_15m_timestamp,
            "last_emitted_1h_timestamp": self.last_emitted_1h_timestamp,
            "total_15m_ingested": self.total_15m_ingested,
            "total_1h_emitted": self.total_1h_emitted,
            "total_evaluations": self.total_evaluations,
            "total_signals": self.total_signals,
            "resolved_trade_count": self.resolved_trade_count,
            "cumulative_net_pnl": round(self.cumulative_net_pnl, 4),
            "updated_at_utc": self.updated_at_utc,
            "in_flight_15m_bars": [dict(b) for b in self.in_flight_15m_bars],
            "evaluator_position": dict(self.evaluator_position) if self.evaluator_position else None,
            "processed_opportunity_ids": list(self.processed_opportunity_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConsumerCheckpoint":
        return cls(
            candidate_id=str(data["candidate_id"]),
            symbol=str(data["symbol"]),
            freeze_hash=str(data.get("freeze_hash", "")),
            last_processed_15m_timestamp=str(data.get("last_processed_15m_timestamp", "")),
            last_emitted_1h_timestamp=str(data.get("last_emitted_1h_timestamp", "")),
            total_15m_ingested=int(data.get("total_15m_ingested", 0)),
            total_1h_emitted=int(data.get("total_1h_emitted", 0)),
            total_evaluations=int(data.get("total_evaluations", 0)),
            total_signals=int(data.get("total_signals", 0)),
            resolved_trade_count=int(data.get("resolved_trade_count", 0)),
            cumulative_net_pnl=float(data.get("cumulative_net_pnl", 0.0)),
            updated_at_utc=str(data.get("updated_at_utc", "")),
            in_flight_15m_bars=tuple(data.get("in_flight_15m_bars", ())),
            evaluator_position=data.get("evaluator_position"),
            processed_opportunity_ids=tuple(data.get("processed_opportunity_ids", ())),
        )


class ShadowConsumer:
    """
    Consumer driving prospective shadow evaluation from stream or stored closed 15m candles.
    """

    def __init__(
        self,
        candidate_snapshot: FrozenCandidateSnapshot,
        freeze_boundary_timestamp: str,
        evidence_dir: Optional[Path] = None,
        warmup_1h_candles: Optional[Sequence[Mapping[str, Any]]] = None,
        initial_capital: float = 10_000.0,
    ):
        self.candidate = candidate_snapshot
        self.freeze_boundary_timestamp = freeze_boundary_timestamp
        
        if evidence_dir is None:
            evidence_dir = Path(__file__).resolve().parent.parent.parent / "data" / "prospective_shadow_evidence"
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        self.checkpoint_path = (
            self.evidence_dir / f"checkpoint_{self.candidate.candidate_id}_{self.candidate.symbol}.json"
        )
        self.trade_ledger_path = (
            self.evidence_dir / f"resolved_trades_{self.candidate.candidate_id}_{self.candidate.symbol}.jsonl"
        )

        # Evaluator instance
        self.evaluator = ProspectiveShadowEvaluator(
            candidate_snapshot=candidate_snapshot,
            freeze_boundary_timestamp=freeze_boundary_timestamp,
            initial_capital=initial_capital,
        )

        # Aggregator instance
        self.aggregator = ClosedCandleAggregator(symbol=candidate_snapshot.symbol)

        # Historical 1h sliding window (for technical indicators e.g. SMA50, BB20, RSI14)
        self._window_1h_bars: List[Dict[str, Any]] = list(dict(c) for c in (warmup_1h_candles or []))
        self._max_window_size = 100

        # State counters & deduplication sets
        self.total_15m_ingested = 0
        self.total_1h_emitted = 0
        self.total_evaluations = 0
        self.total_signals = 0
        self.resolved_trade_count = 0
        self.cumulative_net_pnl = 0.0
        self.last_processed_15m_timestamp = ""
        self.last_emitted_1h_timestamp = ""
        self._processed_opp_ids: set[str] = set()

        # Load existing checkpoint if present
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Loads state checkpoint if exists and valid for this candidate."""
        if not self.checkpoint_path.exists():
            return
        try:
            raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            cp = ConsumerCheckpoint.from_dict(raw)
            if cp.candidate_id != self.candidate.candidate_id or cp.symbol != self.candidate.symbol:
                return
            if cp.freeze_hash and cp.freeze_hash != self.candidate.freeze_hash:
                _logger.warning("Checkpoint freeze_hash mismatch; resetting consumer cursor.")
                return

            self.last_processed_15m_timestamp = cp.last_processed_15m_timestamp
            self.last_emitted_1h_timestamp = cp.last_emitted_1h_timestamp
            self.total_15m_ingested = cp.total_15m_ingested
            self.total_1h_emitted = cp.total_1h_emitted
            self.total_evaluations = cp.total_evaluations
            self.total_signals = cp.total_signals
            self.resolved_trade_count = cp.resolved_trade_count
            self.cumulative_net_pnl = cp.cumulative_net_pnl
            self._processed_opp_ids = set(cp.processed_opportunity_ids)

            # Restore evaluator position state
            if cp.evaluator_position:
                self.evaluator._current_position = dict(cp.evaluator_position)
            else:
                self.evaluator._current_position = None

            # Restore in-flight aggregator bars
            if cp.in_flight_15m_bars:
                self.aggregator.reset()
                for b in cp.in_flight_15m_bars:
                    self.aggregator.add_15m_candle(b)

        except Exception as e:
            _logger.warning("Failed to load checkpoint from %s: %s", self.checkpoint_path, e)

    def _save_checkpoint(self) -> None:
        """Atomically saves state checkpoint via temporary file replacement."""
        in_flight = tuple(self.aggregator._bucket_15m_bars)
        cp = ConsumerCheckpoint(
            candidate_id=self.candidate.candidate_id,
            symbol=self.candidate.symbol,
            freeze_hash=self.candidate.freeze_hash,
            last_processed_15m_timestamp=self.last_processed_15m_timestamp,
            last_emitted_1h_timestamp=self.last_emitted_1h_timestamp,
            total_15m_ingested=self.total_15m_ingested,
            total_1h_emitted=self.total_1h_emitted,
            total_evaluations=self.total_evaluations,
            total_signals=self.total_signals,
            resolved_trade_count=self.resolved_trade_count,
            cumulative_net_pnl=self.cumulative_net_pnl,
            updated_at_utc=datetime.now(timezone.utc).isoformat(),
            in_flight_15m_bars=in_flight,
            evaluator_position=self.evaluator.current_position,
            processed_opportunity_ids=tuple(sorted(list(self._processed_opp_ids))),
        )
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cp.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
        temp_path.replace(self.checkpoint_path)

    def _record_resolved_trade(self, trade_fill: Mapping[str, Any]) -> None:
        """Appends a resolved simulated trade to the immutable ledger."""
        trade_record = {
            "candidate_id": self.candidate.candidate_id,
            "symbol": self.candidate.symbol,
            "freeze_hash": self.candidate.freeze_hash,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "trade_event": "SIMULATED_EXIT_FILLED",
            "entry_time": trade_fill.get("entry_time"),
            "exit_time": trade_fill.get("exit_time"),
            "entry_price": trade_fill.get("entry_price"),
            "exit_price": trade_fill.get("exit_price"),
            "qty": trade_fill.get("qty"),
            "gross_pnl": trade_fill.get("gross_pnl"),
            "total_fees": trade_fill.get("total_fees"),
            "net_pnl": trade_fill.get("net_pnl"),
            "bars_held": trade_fill.get("bars_held"),
            "exit_reason": trade_fill.get("exit_reason"),
            "is_simulated_shadow": True,
            "is_actual_paper_fill": False,
        }
        with open(self.trade_ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade_record, ensure_ascii=False) + "\n")
            f.flush()

        self.resolved_trade_count += 1
        self.cumulative_net_pnl += float(trade_fill.get("net_pnl", 0.0))

    def process_15m_candle(self, candle_15m: Mapping[str, Any]) -> Optional[ProspectiveOpportunity]:
        """
        Ingests a single closed 15m candle.
        If a new 1h candle is formed:
        1. Executes pending simulated order at next bar open price.
        2. Evaluates candidate strategy on closed 1h bar.
        3. Persists isolated evidence.
        4. Updates checkpoint atomically.
        """
        bar_time = str(candle_15m.get("time", candle_15m.get("open_time_utc", "")))
        if not bar_time:
            raise ValueError("15m candle missing timestamp ('time' or 'open_time_utc')")

        # Idempotency check: ignore already processed candle
        if self.last_processed_15m_timestamp and bar_time <= self.last_processed_15m_timestamp:
            return None

        # Verify closed candle invariant
        is_closed = candle_15m.get("is_closed", candle_15m.get("closed", True))
        if not is_closed:
            raise ValueError(f"Unclosed 15m candle rejected at {bar_time}")

        # Feed to aggregator
        bar_1h = self.aggregator.add_15m_candle(candle_15m)
        self.total_15m_ingested += 1
        self.last_processed_15m_timestamp = bar_time

        opp: Optional[ProspectiveOpportunity] = None

        if bar_1h is not None:
            self.total_1h_emitted += 1
            self.last_emitted_1h_timestamp = bar_1h["time"]

            # 1. Process simulated fill on next bar open (Next-Bar-Open execution)
            fill_result = self.evaluator.process_next_bar_open(bar_1h)
            if fill_result and fill_result.get("event") == "SIMULATED_EXIT_FILLED":
                self._record_resolved_trade(fill_result)

            # 2. Update historical sliding window
            self._window_1h_bars.append(bar_1h)
            if len(self._window_1h_bars) > self._max_window_size:
                self._window_1h_bars.pop(0)

            # 3. Evaluate candidate strategy on closed 1h bar
            opp = self.evaluator.evaluate_closed_bar(bar_1h, self._window_1h_bars)

            # 4. Deduplicate and persist isolated evidence
            if opp.opportunity_id not in self._processed_opp_ids:
                self.total_evaluations += 1
                if opp.decision_action in ("BUY", "CLOSE"):
                    self.total_signals += 1
                self.evaluator.persist_evidence(opp, output_dir=self.evidence_dir)
                self._processed_opp_ids.add(opp.opportunity_id)

        # 5. Save checkpoint atomically
        self._save_checkpoint()
        return opp

    def process_15m_batch(
        self,
        candles_15m: Sequence[Mapping[str, Any]],
    ) -> List[ProspectiveOpportunity]:
        """
        Processes a sequence of closed 15m candles in chronological order.
        Returns list of opportunities evaluated.
        """
        opps: List[ProspectiveOpportunity] = []
        for c in candles_15m:
            res = self.process_15m_candle(c)
            if res is not None:
                opps.append(res)
        return opps
