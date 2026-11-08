"""Prospective Paper Shadow Logger for VOL_COMPRESSION_BREAKOUT_V1 (NO_TRADE_SHADOW).

Implements strictly passive, closed-candle-only prospective shadow logging:
- Immutable locked candidate specification (`version`, `spec_sha256`, `evidence_epoch_id`,
  `collection_start_timestamp`, `lock_timestamp`, `last_used_historical_timestamp`,
  `last_parameter_fit_timestamp`).
- Evaluates ONLY closed 15m candles; never generates orders and never alters final
  runtime trading decisions (`PAPER_ECONOMIC_POLICY=NO_TRADE_SHADOW`).
- Two-stream data separation: receives strictly closed shadow candles for candidate coins;
  does not contaminate or mutate the 210-bar main analysis stream.
- Strict candle validation: 15m UTC boundaries, finite OHLCV, positivity, and internal consistency.
- True Global (timestamp, symbol) Batch Processing: merges unseen closed bars across all candidate
  symbols (BTC, ETH, BNB), sorts them chronologically by (c_ts, symbol), and steps through them
  in global order to guarantee authentic portfolio concurrency and cooldown accounting.
- Global Health Gate: strictly enforces that all candidate symbols (BTC, ETH, BNB) must achieve
  valid continuous warmup (>= 386 bars) and be in `ACTIVE` state before ANY prospective signal
  can be admitted (otherwise rejected with `REJECTED_GLOBAL_HEALTH_{status}`).
- Robust gap handling: in bootstrap, discards pre-gap prefix and retains only the continuous
  valid suffix. In production, missing-bar gaps immediately invalidate any active open position
  with `SHADOW_LIFECYCLE_INVALIDATED_DATA_GAP` (excluded from evidence metrics) and trigger
  buffer reset and cooldown.
- Transactional Outbox & Bounded Crash Consistency: atomic state checkpointing (.tmp + fsync + os.replace),
  committed watermark tracking (`last_committed_event_sequence`), WAL outbox flush to JSONL,
  collision-free deterministic event IDs, bounded tail recovery (reading <= 64KB, never scanning
  entire file into memory), and automatic partial trailing line truncation at EOF.
- Automatic Epoch Quarantine: relocates pre-epoch legacy logs into `logs/quarantine/`.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Deque, Mapping

from btc_scraper.core.paths import build_logs_path


def _canonical_spec_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _streaming_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class LockedCandidateSpec:
    """Immutable prospective shadow specification (zero retuning allowed in epoch)."""

    candidate_id: str = "VOL_COMPRESSION_BREAKOUT_V1"
    spec_version: str = "2.0.0-passive-shadow"
    lock_timestamp: str = "2026-11-02T10:20:00+00:00"
    last_used_historical_timestamp: str = "2026-06-30T23:45:00+00:00"
    last_parameter_fit_timestamp: str = "2025-12-31T23:45:00+00:00"
    universe: tuple[str, ...] = ("BTC", "ETH", "BNB")
    bar_interval_minutes: int = 15
    donchian_bars: int = 96
    sma_fast_bars: int = 96
    sma_slow_bars: int = 384
    min_vol_ratio_96: float = 1.2
    atr_compression_bars: int = 192
    atr_compression_q65_max_bps: float = 38.305
    tp_bps: float = 350.0
    sl_bps: float = 150.0
    max_hold_bars: int = 192
    max_concurrent_positions: int = 3
    max_positions_per_asset: int = 1
    cooldown_bars: int = 96
    cost_tiers_bps: tuple[float, ...] = (10.0, 14.0, 20.0, 30.0)
    execution_timing: str = "SIGNAL_AT_BAR_I_CLOSE__EARLIEST_ENTRY_AT_BAR_I_PLUS_1_OPEN"
    collision_policy: str = "SL_FIRST_CONSERVATIVE"
    gap_stop_policy: str = "ADVERSE_OPEN_PRICE_FILL_SL_GAP"
    epoch_policy: str = "NO_TRADE_SHADOW_IMMUTABLE_NO_RETUNING"
    strategy_spec_sha256: str = ""
    spec_sha256: str = ""

    def canonical_strategy_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "spec_version": self.spec_version,
            "universe": list(self.universe),
            "bar_interval_minutes": self.bar_interval_minutes,
            "donchian_bars": self.donchian_bars,
            "sma_fast_bars": self.sma_fast_bars,
            "sma_slow_bars": self.sma_slow_bars,
            "min_vol_ratio_96": self.min_vol_ratio_96,
            "atr_compression_bars": self.atr_compression_bars,
            "atr_compression_q65_max_bps": self.atr_compression_q65_max_bps,
            "tp_bps": self.tp_bps,
            "sl_bps": self.sl_bps,
            "max_hold_bars": self.max_hold_bars,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_positions_per_asset": self.max_positions_per_asset,
            "cooldown_bars": self.cooldown_bars,
            "cost_tiers_bps": list(self.cost_tiers_bps),
            "execution_timing": self.execution_timing,
            "collision_policy": self.collision_policy,
            "gap_stop_policy": self.gap_stop_policy,
            "epoch_policy": self.epoch_policy,
            "last_used_historical_timestamp": self.last_used_historical_timestamp,
            "last_parameter_fit_timestamp": self.last_parameter_fit_timestamp,
            "lock_timestamp": self.lock_timestamp,
        }

    def canonical_payload(self) -> dict[str, Any]:
        return self.canonical_strategy_payload()

    def verify_integrity(self) -> None:
        expected = _canonical_spec_sha256(self.canonical_strategy_payload())
        if not self.strategy_spec_sha256 or self.strategy_spec_sha256 != expected:
            raise ValueError(
                f"LockedCandidateSpec strategy_spec_sha256 integrity mismatch: got={self.strategy_spec_sha256!r}, expected={expected!r}"
            )
        if not self.spec_sha256 or self.spec_sha256 != expected:
            raise ValueError(
                f"LockedCandidateSpec spec_sha256 integrity mismatch: got={self.spec_sha256!r}, expected={expected!r}"
            )

    def to_frozen_mapping(self) -> Mapping[str, Any]:
        data = self.canonical_strategy_payload()
        data["strategy_spec_sha256"] = self.strategy_spec_sha256
        data["spec_sha256"] = self.spec_sha256
        return MappingProxyType(data)


@dataclass(frozen=True)
class EvidenceActivationManifest:
    """Runtime evidence activation manifest created upon verified live daemon activation."""

    evidence_epoch_id: str
    activated_at_utc: str
    collection_start_utc: str
    strategy_spec_sha256: str
    git_head: str
    staged_manifest_identity: str
    runtime_environment: str
    process_runtime_id: str
    paper_policy: str
    first_complete_fresh_batch_utc: str
    first_checkpoint_generation: int
    state_path: str
    log_path: str
    manifest_sha256: str = ""

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "evidence_epoch_id": self.evidence_epoch_id,
            "activated_at_utc": self.activated_at_utc,
            "collection_start_utc": self.collection_start_utc,
            "strategy_spec_sha256": self.strategy_spec_sha256,
            "git_head": self.git_head,
            "staged_manifest_identity": self.staged_manifest_identity,
            "runtime_environment": self.runtime_environment,
            "process_runtime_id": self.process_runtime_id,
            "paper_policy": self.paper_policy,
            "first_complete_fresh_batch_utc": self.first_complete_fresh_batch_utc,
            "first_checkpoint_generation": self.first_checkpoint_generation,
            "state_path": self.state_path,
            "log_path": self.log_path,
        }

    def verify_integrity(self) -> None:
        expected = _canonical_spec_sha256(self.canonical_payload())
        if not self.manifest_sha256 or self.manifest_sha256 != expected:
            raise ValueError(
                f"EvidenceActivationManifest SHA256 integrity mismatch: got={self.manifest_sha256!r}, expected={expected!r}"
            )


def load_activation_manifest(path: Path | str) -> EvidenceActivationManifest:
    """Loads and verifies an EvidenceActivationManifest from disk."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Activation manifest not found at: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    manifest = EvidenceActivationManifest(**data)
    manifest.verify_integrity()
    return manifest


def create_activation_manifest(
    *,
    evidence_epoch_id: str,
    activated_at_utc: str,
    collection_start_utc: str,
    strategy_spec_sha256: str,
    git_head: str,
    staged_manifest_identity: str,
    runtime_environment: str,
    process_runtime_id: str,
    paper_policy: str,
    first_complete_fresh_batch_utc: str,
    first_checkpoint_generation: int,
    state_path: str,
    log_path: str,
) -> EvidenceActivationManifest:
    unsigned = EvidenceActivationManifest(
        evidence_epoch_id=evidence_epoch_id,
        activated_at_utc=activated_at_utc,
        collection_start_utc=collection_start_utc,
        strategy_spec_sha256=strategy_spec_sha256,
        git_head=git_head,
        staged_manifest_identity=staged_manifest_identity,
        runtime_environment=runtime_environment,
        process_runtime_id=process_runtime_id,
        paper_policy=paper_policy,
        first_complete_fresh_batch_utc=first_complete_fresh_batch_utc,
        first_checkpoint_generation=first_checkpoint_generation,
        state_path=state_path,
        log_path=log_path,
    )
    digest = _canonical_spec_sha256(unsigned.canonical_payload())
    manifest = EvidenceActivationManifest(
        evidence_epoch_id=evidence_epoch_id,
        activated_at_utc=activated_at_utc,
        collection_start_utc=collection_start_utc,
        strategy_spec_sha256=strategy_spec_sha256,
        git_head=git_head,
        staged_manifest_identity=staged_manifest_identity,
        runtime_environment=runtime_environment,
        process_runtime_id=process_runtime_id,
        paper_policy=paper_policy,
        first_complete_fresh_batch_utc=first_complete_fresh_batch_utc,
        first_checkpoint_generation=first_checkpoint_generation,
        state_path=state_path,
        log_path=log_path,
        manifest_sha256=digest,
    )
    manifest.verify_integrity()
    return manifest


def _build_default_locked_spec() -> LockedCandidateSpec:
    unsigned = LockedCandidateSpec()
    digest = _canonical_spec_sha256(unsigned.canonical_strategy_payload())
    locked = LockedCandidateSpec(strategy_spec_sha256=digest, spec_sha256=digest)
    locked.verify_integrity()
    return locked


LOCKED_VCB_V1_SPEC: LockedCandidateSpec = _build_default_locked_spec()


@dataclass
class _PendingShadowSignal:
    shadow_id: str
    symbol: str
    side: str
    signal_seq: int
    signal_timestamp: datetime
    signal_close_timestamp: datetime
    earliest_entry_timestamp: datetime
    signal_close_price: float
    next_bar_open_reference: float | None
    feature_conditions: dict[str, Any]
    data_quality_flags: dict[str, Any]


@dataclass
class _OpenShadowPosition:
    shadow_id: str
    symbol: str
    side: str
    signal_seq: int
    entry_seq: int
    signal_timestamp: datetime
    signal_close_timestamp: datetime
    earliest_entry_timestamp: datetime
    entry_timestamp: datetime
    signal_close_price: float
    entry_price: float
    tp_target: float
    sl_target: float
    bars_checked: int
    feature_conditions: dict[str, Any]
    data_quality_flags: dict[str, Any]


class _SymbolRollingState:
    """Bounded O(1) incremental rolling window state for a single symbol (`<= 384` bars)."""

    __slots__ = (
        "symbol",
        "closes_96",
        "sum_close_96",
        "closes_384",
        "sum_close_384",
        "prev_vols_96",
        "sum_vol_96",
        "prev_trs_192",
        "sum_tr_192",
        "prev_high_max_dq",
        "prev_low_min_dq",
        "prev_close",
        "next_seq",
        "last_closed_ts",
        "last_exit_ts",
        "pending_signal",
        "open_position",
        "last_signal_evaluation",
        "last_summary",
        "health_status",
    )

    def __init__(self, symbol: str, spec: LockedCandidateSpec) -> None:
        self.symbol = symbol
        self.closes_96: Deque[float] = deque(maxlen=spec.sma_fast_bars)
        self.sum_close_96: float = 0.0
        self.closes_384: Deque[float] = deque(maxlen=spec.sma_slow_bars)
        self.sum_close_384: float = 0.0
        self.prev_vols_96: Deque[float] = deque(maxlen=spec.donchian_bars)
        self.sum_vol_96: float = 0.0
        self.prev_trs_192: Deque[float] = deque(maxlen=spec.atr_compression_bars)
        self.sum_tr_192: float = 0.0
        self.prev_high_max_dq: Deque[tuple[int, float]] = deque()
        self.prev_low_min_dq: Deque[tuple[int, float]] = deque()
        self.prev_close: float | None = None
        self.next_seq: int = 0
        self.last_closed_ts: datetime | None = None
        self.last_exit_ts: datetime | None = None
        self.pending_signal: _PendingShadowSignal | None = None
        self.open_position: _OpenShadowPosition | None = None
        self.last_signal_evaluation: dict[str, Any] | None = None
        self.last_summary: dict[str, Any] | None = None
        self.health_status: str = "WARMING_UP"

    def reset_buffers(self, spec: LockedCandidateSpec, health_status: str = "WARMING_UP") -> None:
        self.closes_96.clear()
        self.sum_close_96 = 0.0
        self.closes_384.clear()
        self.sum_close_384 = 0.0
        self.prev_vols_96.clear()
        self.sum_vol_96 = 0.0
        self.prev_trs_192.clear()
        self.sum_tr_192 = 0.0
        self.prev_high_max_dq.clear()
        self.prev_low_min_dq.clear()
        self.prev_close = None
        self.next_seq = 0
        self.pending_signal = None
        self.last_signal_evaluation = None
        self.last_summary = None
        self.health_status = health_status
        self.sum_tr_192 = 0.0
        self.prev_high_max_dq.clear()
        self.prev_low_min_dq.clear()
        self.prev_close = None
        self.next_seq = 0
        self.health_status = health_status


def _serialize_pending_signal(p: _PendingShadowSignal | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "shadow_id": p.shadow_id,
        "symbol": p.symbol,
        "side": p.side,
        "signal_seq": p.signal_seq,
        "signal_timestamp": p.signal_timestamp.isoformat(),
        "signal_close_timestamp": p.signal_close_timestamp.isoformat(),
        "earliest_entry_timestamp": p.earliest_entry_timestamp.isoformat(),
        "signal_close_price": p.signal_close_price,
        "next_bar_open_reference": p.next_bar_open_reference,
        "feature_conditions": p.feature_conditions,
        "data_quality_flags": p.data_quality_flags,
    }


def _deserialize_pending_signal(data: dict[str, Any] | None) -> _PendingShadowSignal | None:
    if not data:
        return None
    return _PendingShadowSignal(
        shadow_id=data["shadow_id"],
        symbol=data["symbol"],
        side=data["side"],
        signal_seq=int(data["signal_seq"]),
        signal_timestamp=datetime.fromisoformat(data["signal_timestamp"]).astimezone(timezone.utc),
        signal_close_timestamp=datetime.fromisoformat(data["signal_close_timestamp"]).astimezone(timezone.utc),
        earliest_entry_timestamp=datetime.fromisoformat(data["earliest_entry_timestamp"]).astimezone(timezone.utc),
        signal_close_price=float(data["signal_close_price"]),
        next_bar_open_reference=float(data["next_bar_open_reference"]) if data.get("next_bar_open_reference") is not None else None,
        feature_conditions=data.get("feature_conditions", {}),
        data_quality_flags=data.get("data_quality_flags", {}),
    )


def _serialize_open_position(pos: _OpenShadowPosition | None) -> dict[str, Any] | None:
    if pos is None:
        return None
    return {
        "shadow_id": pos.shadow_id,
        "symbol": pos.symbol,
        "side": pos.side,
        "signal_seq": pos.signal_seq,
        "entry_seq": pos.entry_seq,
        "signal_timestamp": pos.signal_timestamp.isoformat(),
        "signal_close_timestamp": pos.signal_close_timestamp.isoformat(),
        "earliest_entry_timestamp": pos.earliest_entry_timestamp.isoformat(),
        "entry_timestamp": pos.entry_timestamp.isoformat(),
        "signal_close_price": pos.signal_close_price,
        "entry_price": pos.entry_price,
        "tp_target": pos.tp_target,
        "sl_target": pos.sl_target,
        "bars_checked": pos.bars_checked,
        "feature_conditions": pos.feature_conditions,
        "data_quality_flags": pos.data_quality_flags,
    }


def _deserialize_open_position(data: dict[str, Any] | None) -> _OpenShadowPosition | None:
    if not data:
        return None
    return _OpenShadowPosition(
        shadow_id=data["shadow_id"],
        symbol=data["symbol"],
        side=data["side"],
        signal_seq=int(data["signal_seq"]),
        entry_seq=int(data["entry_seq"]),
        signal_timestamp=datetime.fromisoformat(data["signal_timestamp"]).astimezone(timezone.utc),
        signal_close_timestamp=datetime.fromisoformat(data["signal_close_timestamp"]).astimezone(timezone.utc),
        earliest_entry_timestamp=datetime.fromisoformat(data["earliest_entry_timestamp"]).astimezone(timezone.utc),
        entry_timestamp=datetime.fromisoformat(data["entry_timestamp"]).astimezone(timezone.utc),
        signal_close_price=float(data["signal_close_price"]),
        entry_price=float(data["entry_price"]),
        tp_target=float(data["tp_target"]),
        sl_target=float(data["sl_target"]),
        bars_checked=int(data["bars_checked"]),
        feature_conditions=data.get("feature_conditions", {}),
        data_quality_flags=data.get("data_quality_flags", {}),
    )


def _sanitize_signal_eval(val: Any) -> dict[str, Any] | None:
    if not isinstance(val, dict):
        return None
    # Strip any cycle envelope keys and wall-clock timestamps to guarantee flat bounded deterministic signal evaluation snapshot
    cleaned = {}
    for k, v in val.items():
        if k in ("last_signal_evaluation", "current_cycle_envelope", "last_summary", "blockers", "logged_at_utc"):
            continue
        if isinstance(v, dict) and ("last_signal_evaluation" in v or "cycle_id" in v):
            continue
        cleaned[k] = v
    return cleaned if cleaned else None


def _serialize_symbol_state(st: _SymbolRollingState) -> dict[str, Any]:
    sanitized_eval = _sanitize_signal_eval(st.last_signal_evaluation or st.last_summary)
    return {
        "symbol": st.symbol,
        "next_seq": st.next_seq,
        "last_closed_ts": st.last_closed_ts.isoformat() if st.last_closed_ts else None,
        "last_exit_ts": st.last_exit_ts.isoformat() if st.last_exit_ts else None,
        "health_status": st.health_status,
        "prev_close": st.prev_close,
        "closes_96": list(st.closes_96),
        "sum_close_96": st.sum_close_96,
        "closes_384": list(st.closes_384),
        "sum_close_384": st.sum_close_384,
        "prev_vols_96": list(st.prev_vols_96),
        "sum_vol_96": st.sum_vol_96,
        "prev_trs_192": list(st.prev_trs_192),
        "sum_tr_192": st.sum_tr_192,
        "prev_high_max_dq": [list(item) for item in st.prev_high_max_dq],
        "prev_low_min_dq": [list(item) for item in st.prev_low_min_dq],
        "pending_signal": _serialize_pending_signal(st.pending_signal),
        "open_position": _serialize_open_position(st.open_position),
        "last_signal_evaluation": sanitized_eval,
        "last_summary": sanitized_eval,
    }


def _deserialize_symbol_state(st: _SymbolRollingState, data: dict[str, Any], spec: LockedCandidateSpec) -> None:
    st.next_seq = int(data.get("next_seq", 0))
    st.last_closed_ts = datetime.fromisoformat(data["last_closed_ts"]).astimezone(timezone.utc) if data.get("last_closed_ts") else None
    st.last_exit_ts = datetime.fromisoformat(data["last_exit_ts"]).astimezone(timezone.utc) if data.get("last_exit_ts") else None
    st.health_status = str(data.get("health_status", "ACTIVE"))
    st.prev_close = float(data["prev_close"]) if data.get("prev_close") is not None else None
    st.closes_96 = deque(data.get("closes_96", []), maxlen=spec.sma_fast_bars)
    st.sum_close_96 = float(data.get("sum_close_96", 0.0))
    st.closes_384 = deque(data.get("closes_384", []), maxlen=spec.sma_slow_bars)
    st.sum_close_384 = float(data.get("sum_close_384", 0.0))
    st.prev_vols_96 = deque(data.get("prev_vols_96", []), maxlen=spec.donchian_bars)
    st.sum_vol_96 = float(data.get("sum_vol_96", 0.0))
    st.prev_trs_192 = deque(data.get("prev_trs_192", []), maxlen=spec.atr_compression_bars)
    st.sum_tr_192 = float(data.get("sum_tr_192", 0.0))
    st.prev_high_max_dq = deque([tuple(item) for item in data.get("prev_high_max_dq", [])])
    st.prev_low_min_dq = deque([tuple(item) for item in data.get("prev_low_min_dq", [])])
    st.pending_signal = _deserialize_pending_signal(data.get("pending_signal"))
    st.open_position = _deserialize_open_position(data.get("open_position"))
    raw_eval = data.get("last_signal_evaluation") or data.get("last_summary")
    st.last_signal_evaluation = _sanitize_signal_eval(raw_eval)
    st.last_summary = st.last_signal_evaluation


def parse_candle_open_utc(candle: Mapping[str, Any]) -> datetime | None:
    """Parses a 15m candle dict's open timestamp into timezone-aware UTC datetime."""
    raw_utc = candle.get("time_utc") or candle.get("timestamp")
    if raw_utc is not None:
        if isinstance(raw_utc, datetime):
            return raw_utc.astimezone(timezone.utc) if raw_utc.tzinfo else raw_utc.replace(tzinfo=timezone.utc)
        if hasattr(raw_utc, "to_pydatetime"):
            dt_obj = raw_utc.to_pydatetime()
            return dt_obj.astimezone(timezone.utc) if dt_obj.tzinfo else dt_obj.replace(tzinfo=timezone.utc)
        if isinstance(raw_utc, str):
            try:
                dt_obj = datetime.fromisoformat(raw_utc.replace("Z", "+00:00"))
                return dt_obj.astimezone(timezone.utc) if dt_obj.tzinfo else dt_obj.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    val = candle.get("time")
    if isinstance(val, (int, float)):
        sec = float(val if val < 1e11 else val / 1000.0)
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    if isinstance(val, str):
        txt = val.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(txt, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            dt_obj = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            return dt_obj.astimezone(timezone.utc) if dt_obj.tzinfo else dt_obj.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def validate_15m_candle(candle: Mapping[str, Any]) -> tuple[bool, str, datetime | None, dict[str, float] | None]:
    """Validates 15m candle integrity: 15m UTC boundary, finite positive prices, volume, and OHLC consistency."""
    c_ts = parse_candle_open_utc(candle)
    if c_ts is None:
        return False, "UNPARSEABLE_TIMESTAMP", None, None

    # UTC 15m boundary check (timestamp seconds must be a multiple of 900)
    ts_sec = int(c_ts.timestamp())
    if ts_sec % 900 != 0:
        return False, "NOT_15M_UTC_BOUNDARY", c_ts, None

    try:
        b_open = float(candle["open"])
        b_high = float(candle["high"])
        b_low = float(candle["low"])
        b_close = float(candle["close"])
        b_vol = float(candle.get("volume", 0.0))
    except (KeyError, TypeError, ValueError):
        return False, "INVALID_NUMERIC_TYPES", c_ts, None

    if not (math.isfinite(b_open) and math.isfinite(b_high) and math.isfinite(b_low) and math.isfinite(b_close) and math.isfinite(b_vol)):
        return False, "NON_FINITE_VALUES", c_ts, None

    if b_open <= 0.0 or b_high <= 0.0 or b_low <= 0.0 or b_close <= 0.0 or b_vol < 0.0:
        return False, "NON_POSITIVE_PRICE_OR_VOL", c_ts, None

    if b_high < max(b_open, b_close) or b_low > min(b_open, b_close) or b_high < b_low:
        return False, "INCONSISTENT_OHLC", c_ts, None

    parsed = {
        "open": b_open,
        "high": b_high,
        "low": b_low,
        "close": b_close,
        "volume": b_vol,
    }
    return True, "VALID", c_ts, parsed


def is_15m_candle_closed(
    candle: Mapping[str, Any],
    *,
    candle_open_utc: datetime,
    has_newer_candle_after: bool,
    now_utc: datetime,
    bar_interval_minutes: int = 15,
    allow_future_replay: bool = False,
) -> bool:
    """Determines strictly whether a 15m candle is closed (never admits incomplete forming bars or future candles)."""
    close_time_utc = candle_open_utc + timedelta(minutes=bar_interval_minutes)
    if not allow_future_replay and close_time_utc > now_utc:
        return False
    if "closed" in candle and candle["closed"] is not None:
        return bool(candle["closed"])
    if "is_closed" in candle and candle["is_closed"] is not None:
        return bool(candle["is_closed"])
    if has_newer_candle_after:
        return True
    return allow_future_replay or (close_time_utc <= now_utc)


class ProspectiveShadowLogger:
    """Bounded, O(1) incremental prospective shadow logger for VOL_COMPRESSION_BREAKOUT_V1."""

    def __init__(
        self,
        *,
        spec: LockedCandidateSpec = LOCKED_VCB_V1_SPEC,
        activation_manifest: EvidenceActivationManifest | Path | str | None = None,
        manifest_path: Path | str | None = None,
        log_path: Path | str | None = None,
        state_path: Path | str | None = None,
        log_rejected_closed_candles: bool = True,
    ) -> None:
        spec.verify_integrity()
        self._spec = spec
        self._schema_version = "2.0.0"

        # Resolve activation manifest
        resolved_manifest: EvidenceActivationManifest | None = None
        if isinstance(activation_manifest, EvidenceActivationManifest):
            resolved_manifest = activation_manifest
        elif activation_manifest is not None:
            resolved_manifest = load_activation_manifest(activation_manifest)
        elif manifest_path is not None:
            resolved_manifest = load_activation_manifest(manifest_path)
        else:
            env_path = os.environ.get("PROSPECTIVE_ACTIVATION_MANIFEST_PATH")
            if env_path and Path(env_path).exists():
                try:
                    resolved_manifest = load_activation_manifest(env_path)
                except Exception:
                    resolved_manifest = None

        if resolved_manifest is not None:
            resolved_manifest.verify_integrity()
            if resolved_manifest.strategy_spec_sha256 != self._spec.strategy_spec_sha256:
                raise ValueError(
                    f"Activation manifest strategy_spec_sha256 mismatch: "
                    f"manifest={resolved_manifest.strategy_spec_sha256!r}, "
                    f"spec={self._spec.strategy_spec_sha256!r}"
                )
            if resolved_manifest.paper_policy != "NO_TRADE_SHADOW":
                raise ValueError(
                    f"Activation manifest paper_policy must be NO_TRADE_SHADOW, "
                    f"got {resolved_manifest.paper_policy!r}"
                )
            self._activation_manifest: EvidenceActivationManifest | None = resolved_manifest
            self._epoch_id = resolved_manifest.evidence_epoch_id
            self._collection_start_timestamp = resolved_manifest.collection_start_utc
            self._collection_start_cutoff: datetime | None = datetime.fromisoformat(
                resolved_manifest.collection_start_utc.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            self._runtime_status = "ACTIVE_COLLECTING"
        else:
            self._activation_manifest = None
            self._epoch_id = "NOT_ACTIVATED"
            self._collection_start_timestamp = ""
            self._collection_start_cutoff = None
            self._runtime_status = "CODE_READY_NOT_ACTIVATED"

        self._log_rejected = bool(log_rejected_closed_candles)
        self._lock = threading.RLock()
        self._health_status: str = "WARMING_UP"
        self._checkpoint_generation: int = 0
        self._event_sequence: int = 0
        self._last_committed_event_sequence: int = 0
        self._outbox: list[dict[str, Any]] = []
        self._flushed_event_ids: Deque[str] = deque(maxlen=2000)
        self._flushed_event_ids_set: set[str] = set()
        self._current_cycle_blockers: dict[str, list[str]] = {
            "missing_candidates": [],
            "stale_candidates": [],
        }

        self._counters: dict[str, Any] = {
            "raw_bars_observed": 0,
            "actual_new_bars_processed": 0,
            "duplicate_bars": 0,
            "out_of_order_bars": 0,
            "missing_bar_gaps": 0,
            "invalid_bars": 0,
            "signals_accepted": 0,
            "signals_rejected": 0,
            "positions_opened": 0,
            "positions_resolved": 0,
            "positions_invalidated": 0,
            "write_failures": 0,
            "restarts_recovered": 0,
            "missing_candidate_cycles": 0,
            "stale_candidate_cycles": 0,
            "gap_recovery_bars": 0,
            "gap_recoveries_completed": 0,
            "global_admission_blocked_cycles": 0,
            "future_candles_rejected": 0,
            "last_successful_persist_timestamp": None,
        }
        self._states: dict[str, _SymbolRollingState] = {
            sym: _SymbolRollingState(sym, spec) for sym in spec.universe
        }

        if log_path is not None:
            self._log_path = Path(log_path)
            self._state_path = (
                Path(state_path)
                if state_path is not None
                else self._log_path.with_name(f"{self._log_path.stem}_state.json")
            )
        else:
            self._log_path = build_logs_path("prospective_shadow_vcb_v1.jsonl")
            self._state_path = (
                Path(state_path)
                if state_path is not None
                else build_logs_path("prospective_shadow_state.json")
            )

        self._quarantine_previous_epoch_files_if_needed()

        self._last_historical_cutoff = datetime.fromisoformat(
            spec.last_used_historical_timestamp.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        self._lock_ts_cutoff = datetime.fromisoformat(
            spec.lock_timestamp.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

        if self._collection_start_cutoff is not None:
            self._admission_cutoff = max(
                self._last_historical_cutoff,
                self._lock_ts_cutoff,
                self._collection_start_cutoff,
            )
        else:
            self._admission_cutoff = max(self._last_historical_cutoff, self._lock_ts_cutoff)
        self._bar_delta = timedelta(minutes=spec.bar_interval_minutes)
        self._min_warmup_seq = max(
            spec.sma_slow_bars + 2,
            spec.atr_compression_bars + 2,
            spec.donchian_bars + 2,
        )
        self._restore_state()

    @property
    def spec(self) -> LockedCandidateSpec:
        return self._spec

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def evidence_epoch_id(self) -> str:
        return self._epoch_id

    @property
    def collection_start_timestamp(self) -> str:
        return self._collection_start_timestamp

    @property
    def collection_start_cutoff(self) -> datetime | None:
        return self._collection_start_cutoff

    @property
    def activation_manifest(self) -> EvidenceActivationManifest | None:
        return self._activation_manifest

    @property
    def runtime_status(self) -> str:
        return self._runtime_status

    @property
    def is_activated(self) -> bool:
        return bool(self._activation_manifest is not None and self._runtime_status == "ACTIVE_COLLECTING")

    def _quarantine_previous_epoch_files_if_needed(self) -> None:
        """Quarantines logs and state from older epochs, spec mismatches, corrupt files, or orphan archives into quarantine/.
        
        Guarantee:
        - Files <= 256 KB are fully scanned line-by-line via streaming iterator to detect mixed epochs anywhere in the file.
        - Files > 256 KB use bounded O(1) memory sampling (checking head line, a 4KB sample around midpoint, and 4KB tail sample)
          to detect mixed epochs without full file scans.
        """
        if self._log_path is None or self._state_path is None:
            return

        quarantine_dir = self._log_path.parent / "quarantine"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        state_needs_quarantine = False
        state_reason = ""
        detected_state_epoch = None
        detected_state_spec = None

        log_needs_quarantine = False
        log_reason = ""
        detected_log_epoch = None
        detected_log_spec = None

        self._cached_state_data = None
        # 1. Inspect state file independently
        if self._state_path.exists():
            try:
                content = self._state_path.read_text(encoding="utf-8")
                if not content.strip():
                    state_needs_quarantine = True
                    state_reason = "EMPTY_STATE_FILE"
                else:
                    data = json.loads(content)
                    self._cached_state_data = data
                    detected_state_epoch = data.get("evidence_epoch_id")
                    detected_state_spec = data.get("spec_sha256") or data.get("strategy_spec_sha256")
                    if detected_state_epoch != self._epoch_id:
                        state_needs_quarantine = True
                        state_reason = f"EPOCH_MISMATCH_{detected_state_epoch}"
                    elif detected_state_spec != self._spec.strategy_spec_sha256 and detected_state_spec != self._spec.spec_sha256:
                        state_needs_quarantine = True
                        state_reason = f"SPEC_MISMATCH_{detected_state_spec}"
            except Exception as e:
                state_needs_quarantine = True
                state_reason = f"CORRUPT_STATE_JSON_{e}"

        # 2. Inspect log file independently
        if self._log_path.exists() and self._log_path.stat().st_size > 0:
            if not self._state_path.exists() or state_needs_quarantine:
                log_needs_quarantine = True
                log_reason = "ORPHAN_LOG_WITHOUT_VALID_STATE"
            else:
                try:
                    with self._log_path.open("rb") as fh:
                        first_line = fh.readline().strip().decode("utf-8", errors="replace")
                        if first_line:
                            try:
                                first_rec = json.loads(first_line)
                                first_epoch = first_rec.get("evidence_epoch_id")
                                first_spec = first_rec.get("spec_sha256") or first_rec.get("strategy_spec_sha256")
                                detected_log_epoch = first_epoch
                                detected_log_spec = first_spec
                                if first_epoch != self._epoch_id:
                                    log_needs_quarantine = True
                                    log_reason = f"LOG_EPOCH_MISMATCH_{first_epoch}"
                                elif first_spec != self._spec.strategy_spec_sha256 and first_spec != self._spec.spec_sha256:
                                    log_needs_quarantine = True
                                    log_reason = f"LOG_SPEC_MISMATCH_{first_spec}"
                            except Exception as e:
                                log_needs_quarantine = True
                                log_reason = f"CORRUPT_LOG_JSON_{e}"

                        if not log_needs_quarantine:
                            f_size = self._log_path.stat().st_size
                            if f_size <= 262144:
                                # Stream through lines for files <= 256KB to detect mixed epochs anywhere (head, middle, tail)
                                for line_bytes in fh:
                                    line_str = line_bytes.strip().decode("utf-8", errors="replace")
                                    if not line_str:
                                        continue
                                    try:
                                        rec = json.loads(line_str)
                                        rec_epoch = rec.get("evidence_epoch_id")
                                        rec_spec = rec.get("spec_sha256") or rec.get("strategy_spec_sha256")
                                        if rec_epoch and rec_epoch != self._epoch_id:
                                            log_needs_quarantine = True
                                            log_reason = f"LOG_MIXED_EPOCH_DETECTED_{rec_epoch}"
                                            detected_log_epoch = "MIXED"
                                            break
                                        if rec_spec and (rec_spec != self._spec.strategy_spec_sha256 and rec_spec != self._spec.spec_sha256):
                                            log_needs_quarantine = True
                                            log_reason = f"LOG_SPEC_MISMATCH_{rec_spec}"
                                            break
                                    except json.JSONDecodeError:
                                        continue
                            else:
                                # For archives > 256KB: bounded check at midpoint window and tail window (<= 8KB samples)
                                for sample_offset in (max(0, f_size // 2 - 4096), max(0, f_size - 4096)):
                                    fh.seek(sample_offset)
                                    chunk = fh.read(8192)
                                    for line_bytes in chunk.splitlines():
                                        line_str = line_bytes.strip().decode("utf-8", errors="replace")
                                        if not line_str or not (line_str.startswith("{") and line_str.endswith("}")):
                                            continue
                                        try:
                                            rec = json.loads(line_str)
                                            rec_epoch = rec.get("evidence_epoch_id")
                                            rec_spec = rec.get("spec_sha256") or rec.get("strategy_spec_sha256")
                                            if rec_epoch and rec_epoch != self._epoch_id:
                                                log_needs_quarantine = True
                                                log_reason = f"LOG_MIXED_EPOCH_DETECTED_{rec_epoch}"
                                                detected_log_epoch = "MIXED"
                                                break
                                            if rec_spec and (rec_spec != self._spec.strategy_spec_sha256 and rec_spec != self._spec.spec_sha256):
                                                log_needs_quarantine = True
                                                log_reason = f"LOG_SPEC_MISMATCH_{rec_spec}"
                                                break
                                        except json.JSONDecodeError:
                                            continue
                                    if log_needs_quarantine:
                                        break
                except Exception as e:
                    log_needs_quarantine = True
                    log_reason = f"CORRUPT_LOG_JSON_{e}"

        if not (state_needs_quarantine or log_needs_quarantine):
            return

        try:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            tag = f"{stamp}_{detected_state_epoch or detected_log_epoch or 'legacy'}"
            manifest_records = []

            if state_needs_quarantine and self._state_path.exists():
                dest_state = quarantine_dir / f"quarantined_{tag}_{self._state_path.name}"
                state_size = self._state_path.stat().st_size
                state_hash = _streaming_sha256(self._state_path)
                shutil.move(str(self._state_path), str(dest_state))
                manifest_records.append({
                    "source": str(self._state_path),
                    "destination": str(dest_state),
                    "size_bytes": state_size,
                    "sha256": state_hash,
                    "reason": state_reason,
                    "detected_epoch": detected_state_epoch,
                    "detected_spec_sha256": detected_state_spec,
                })

            if log_needs_quarantine and self._log_path.exists():
                dest_log = quarantine_dir / f"quarantined_{tag}_{self._log_path.name}"
                log_size = self._log_path.stat().st_size
                log_hash = _streaming_sha256(self._log_path)
                shutil.move(str(self._log_path), str(dest_log))
                manifest_records.append({
                    "source": str(self._log_path),
                    "destination": str(dest_log),
                    "size_bytes": log_size,
                    "sha256": log_hash,
                    "reason": log_reason,
                    "detected_epoch": detected_log_epoch,
                    "detected_spec_sha256": detected_log_spec,
                })

            manifest_path = quarantine_dir / f"quarantine_manifest_{tag}.json"
            manifest_path.write_text(
                json.dumps({
                    "quarantine_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "active_epoch_id": self._epoch_id,
                    "active_spec_sha256": self._spec.spec_sha256,
                    "quarantined_files": manifest_records,
                }, indent=2),
                encoding="utf-8"
            )
        except Exception:
            self._counters["write_failures"] += 1
            self._health_status = "DEGRADED_QUARANTINE_FAILURE"

    def _next_event_sequence(self) -> int:
        self._event_sequence += 1
        return self._event_sequence

    def _queue_event(
        self,
        event_type: str,
        *,
        symbol: str,
        c_ts: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Constructs a deterministic, collision-free event and queues it to the transactional outbox."""
        iso_ts = c_ts.isoformat()
        event_seq = self._next_event_sequence()
        sh_id = payload.get("shadow_id") or "none"
        event_id = f"{self._epoch_id}:{symbol}:{iso_ts}:{event_type}:{sh_id}:{event_seq}"
        rec = {
            "event_id": event_id,
            "event_sequence": event_seq,
            "checkpoint_generation": self._checkpoint_generation,
            "evidence_epoch_id": self._epoch_id,
            "logger_schema_version": self._schema_version,
            "event_type": event_type,
            "logged_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_id": self._spec.candidate_id,
            "spec_version": self._spec.spec_version,
            "spec_sha256": self._spec.spec_sha256,
            "lock_timestamp": self._spec.lock_timestamp,
            "last_used_historical_timestamp": self._spec.last_used_historical_timestamp,
            "collection_start_timestamp": self._collection_start_timestamp,
            "symbol": symbol,
            **payload,
        }
        self._outbox.append(rec)
        return rec

    def _persist_state(self) -> None:
        """Atomically commits state with outbox WAL, followed by JSONL flushing and watermark commit."""
        if self._state_path is None:
            return
        if os.getenv("PROSPECTIVE_SHADOW_DISABLE_DISK_WRITE", "").strip().lower() in {"1", "true", "yes"}:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._checkpoint_generation += 1

            # Phase 1: Write state checkpoint with uncommitted outbox
            payload = {
                "candidate_id": self._spec.candidate_id,
                "spec_version": self._spec.spec_version,
                "strategy_spec_sha256": self._spec.strategy_spec_sha256,
                "spec_sha256": self._spec.spec_sha256,
                "evidence_epoch_id": self._epoch_id,
                "runtime_status": self._runtime_status,
                "collection_start_timestamp": self._collection_start_timestamp,
                "logger_schema_version": self._schema_version,
                "checkpoint_generation": self._checkpoint_generation,
                "event_sequence": self._event_sequence,
                "last_committed_event_sequence": self._last_committed_event_sequence,
                "last_persisted_utc": datetime.now(timezone.utc).isoformat(),
                "global_health_status": self._health_status,
                "blockers": dict(self._current_cycle_blockers),
                "symbols": {
                    sym: _serialize_symbol_state(st) for sym, st in self._states.items()
                },
                "counters": dict(self._counters),
                "outbox": list(self._outbox),
            }
            tmp_path = self._state_path.with_name(f"{self._state_path.name}.tmp")
            content = json.dumps(payload, separators=(",", ":"))
            with tmp_path.open("w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_path.replace(self._state_path)
            self._counters["last_successful_persist_timestamp"] = payload["last_persisted_utc"]

            # Phase 2: Flush outbox to JSONL and fsync
            if self._outbox and self._log_path is not None:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as fh:
                    for ev in self._outbox:
                        ev_id = ev.get("event_id")
                        if ev_id and ev_id in self._flushed_event_ids_set:
                            continue
                        fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
                        if ev_id:
                            if len(self._flushed_event_ids) == self._flushed_event_ids.maxlen:
                                oldest = self._flushed_event_ids.popleft()
                                self._flushed_event_ids_set.discard(oldest)
                            self._flushed_event_ids.append(ev_id)
                            self._flushed_event_ids_set.add(ev_id)
                    fh.flush()
                    os.fsync(fh.fileno())

                # Phase 3: Seal commit watermark and clear outbox in state
                self._last_committed_event_sequence = self._event_sequence
                self._outbox.clear()
                payload["last_committed_event_sequence"] = self._last_committed_event_sequence
                payload["outbox"] = []
                content = json.dumps(payload, separators=(",", ":"))
                with tmp_path.open("w", encoding="utf-8") as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
                tmp_path.replace(self._state_path)
        except Exception:
            self._counters["write_failures"] += 1
            self._health_status = "DEGRADED_WRITE_FAILURE"

    def _inspect_and_clean_jsonl_tail(self) -> int:
        """Inspects bounded tail (<= 64KB) of JSONL file, truncates partial trailing lines at EOF,
        and returns the highest event_sequence recorded in JSONL. Bounded O(1) memory and time."""
        if self._log_path is None or not self._log_path.exists():
            return 0
        try:
            file_size = self._log_path.stat().st_size
            if file_size == 0:
                return 0

            tail_bytes_to_read = min(file_size, 65536)
            with self._log_path.open("rb+") as fh:
                fh.seek(file_size - tail_bytes_to_read)
                tail_bytes = fh.read(tail_bytes_to_read)

                # Check if file ends with clean newline
                if not tail_bytes.endswith(b"\n"):
                    last_nl = tail_bytes.rfind(b"\n")
                    if last_nl == -1:
                        # No newline in 64KB tail: truncate corrupt tail in O(1)
                        truncate_pos = file_size - tail_bytes_to_read
                        fh.seek(truncate_pos)
                        fh.truncate()
                        self._counters["write_failures"] += 1
                        return 0
                    else:
                        truncate_pos = (file_size - tail_bytes_to_read) + last_nl + 1
                        fh.seek(truncate_pos)
                        fh.truncate()

                # Read clean tail lines to locate max_seq
                fh.seek(max(0, fh.tell() - 65536))
                clean_tail = fh.read().decode("utf-8", errors="replace")

            max_seq = 0
            for line in clean_tail.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("evidence_epoch_id") != self._epoch_id or (
                        entry.get("spec_sha256") != self._spec.strategy_spec_sha256
                        and entry.get("spec_sha256") != self._spec.spec_sha256
                    ):
                        continue
                    ev_id = entry.get("event_id")
                    if ev_id:
                        if len(self._flushed_event_ids) == self._flushed_event_ids.maxlen:
                            oldest = self._flushed_event_ids.popleft()
                            self._flushed_event_ids_set.discard(oldest)
                        self._flushed_event_ids.append(ev_id)
                        self._flushed_event_ids_set.add(ev_id)
                    seq = entry.get("event_sequence")
                    if isinstance(seq, int) and seq > max_seq:
                        max_seq = seq
                except json.JSONDecodeError:
                    continue
            return max_seq
        except Exception:
            self._counters["write_failures"] += 1
            return 0

    def _restore_state(self) -> None:
        """Restores state from checkpoint, flushes outbox WAL, and performs strict invariant verification."""
        max_tail_seq = self._inspect_and_clean_jsonl_tail()

        if self._state_path is None or not self._state_path.exists():
            self._event_sequence = max_tail_seq
            self._last_committed_event_sequence = max_tail_seq
            return
        try:
            if hasattr(self, "_cached_state_data") and self._cached_state_data is not None:
                data = self._cached_state_data
            else:
                content = self._state_path.read_text(encoding="utf-8")
                if not content.strip():
                    return
                data = json.loads(content)
            saved_spec = data.get("spec_sha256") or data.get("strategy_spec_sha256")
            if saved_spec != self._spec.strategy_spec_sha256 and saved_spec != self._spec.spec_sha256:
                self._health_status = "RESTORE_FAILED_SPEC_MISMATCH"
                return
            if data.get("evidence_epoch_id") != self._epoch_id:
                self._health_status = "RESTORE_FAILED_EPOCH_MISMATCH"
                return

            if "global_health_status" in data:
                self._health_status = data["global_health_status"]
            if "blockers" in data and isinstance(data["blockers"], dict):
                self._current_cycle_blockers = data["blockers"]

            self._checkpoint_generation = int(data.get("checkpoint_generation", 0))
            state_event_seq = int(data.get("event_sequence", 0))
            last_committed_seq = int(data.get("last_committed_event_sequence", 0))
            self._event_sequence = max(state_event_seq, max_tail_seq)
            self._last_committed_event_sequence = max(last_committed_seq, max_tail_seq)

            syms_data = data.get("symbols", {})
            for sym, s_data in syms_data.items():
                if sym in self._states and isinstance(s_data, dict):
                    st = self._states[sym]
                    _deserialize_symbol_state(st, s_data, self._spec)
                    # Strict rolling invariant verification
                    if len(st.closes_96) > 0:
                        calc_s96 = math.fsum(st.closes_96)
                        if not math.isclose(st.sum_close_96, calc_s96, rel_tol=1e-3, abs_tol=1e-3):
                            self._health_status = "RESTORE_FAILED_DATA_CORRUPTION"
                            return
                    if len(st.closes_384) > 0:
                        calc_s384 = math.fsum(st.closes_384)
                        if not math.isclose(st.sum_close_384, calc_s384, rel_tol=1e-3, abs_tol=1e-3):
                            self._health_status = "RESTORE_FAILED_DATA_CORRUPTION"
                            return

            saved_counters = data.get("counters", {})
            if isinstance(saved_counters, dict):
                for k, v in saved_counters.items():
                    if k in self._counters:
                        self._counters[k] = v

            # Recover any unwritten outbox events from state WAL
            unflushed = data.get("outbox", [])
            if isinstance(unflushed, list) and unflushed:
                to_append = [
                    ev for ev in unflushed
                    if int(ev.get("event_sequence", 0)) > max_tail_seq
                    and ev.get("event_id") not in self._flushed_event_ids_set
                ]
                if to_append and self._log_path is not None:
                    with self._log_path.open("a", encoding="utf-8") as fh:
                        for ev in to_append:
                            fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
                            ev_id = ev.get("event_id")
                            if ev_id:
                                if len(self._flushed_event_ids) == self._flushed_event_ids.maxlen:
                                    oldest = self._flushed_event_ids.popleft()
                                    self._flushed_event_ids_set.discard(oldest)
                                self._flushed_event_ids.append(ev_id)
                                self._flushed_event_ids_set.add(ev_id)
                        fh.flush()
                        os.fsync(fh.fileno())
                    max_tail_seq = max(max_tail_seq, max(int(ev.get("event_sequence", 0)) for ev in to_append))

                self._event_sequence = max(self._event_sequence, max_tail_seq)
                self._last_committed_event_sequence = max_tail_seq
                self._outbox = []

                # Atomically reseal checkpoint state on disk with committed watermark and empty outbox
                try:
                    payload = json.loads(self._state_path.read_text(encoding="utf-8"))
                    payload["last_committed_event_sequence"] = self._last_committed_event_sequence
                    payload["event_sequence"] = self._event_sequence
                    payload["outbox"] = []
                    payload["last_persisted_utc"] = datetime.now(timezone.utc).isoformat()
                    tmp_path = self._state_path.with_name(f"{self._state_path.name}.tmp")
                    with tmp_path.open("w", encoding="utf-8") as fh:
                        fh.write(json.dumps(payload, separators=(",", ":")))
                        fh.flush()
                        os.fsync(fh.fileno())
                    tmp_path.replace(self._state_path)
                except Exception:
                    self._counters["write_failures"] += 1
                    self._health_status = "DEGRADED_WRITE_FAILURE"
                    return

            self._counters["restarts_recovered"] += 1
            self._evaluate_global_health()
        except Exception:
            if self._health_status not in ("DEGRADED_QUARANTINE_FAILURE", "DEGRADED_WRITE_FAILURE"):
                self._health_status = "RESTORE_FAILED"

    def _evaluate_global_health(self) -> None:
        """Evaluates global health: ACTIVE requires ALL candidate symbols to be warm and continuous,
        with zero gaps, zero missing candidates, and fresh data stores."""
        if self._health_status in (
            "RESTORE_FAILED",
            "RESTORE_FAILED_SPEC_MISMATCH",
            "RESTORE_FAILED_EPOCH_MISMATCH",
            "RESTORE_FAILED_DATA_CORRUPTION",
            "DEGRADED_WRITE_FAILURE",
            "DEGRADED_QUARANTINE_FAILURE",
        ):
            return

        if self._current_cycle_blockers.get("missing_candidates"):
            self._health_status = "DEGRADED_MISSING_CANDIDATE"
            return
        if self._current_cycle_blockers.get("stale_candidates"):
            self._health_status = "DEGRADED_STALE"
            return

        if any(st.health_status == "DEGRADED_GAP" for st in self._states.values()):
            self._health_status = "DEGRADED_GAP"
        elif any(st.health_status == "RECOVERING_GAP" for st in self._states.values()):
            self._health_status = "RECOVERING_GAP"
        elif not all(st.health_status == "ACTIVE" for st in self._states.values()):
            self._health_status = "WARMING_UP"
        else:
            self._health_status = "ACTIVE"

    def get_health_status(self, symbol: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._evaluate_global_health()
            active_pos = self.active_open_positions_count()
            symbols_health = {}
            warm_count = 0
            for sym, st in self._states.items():
                is_warm = bool(
                    st.next_seq >= self._min_warmup_seq
                    and len(st.closes_384) == self._spec.sma_slow_bars
                    and len(st.prev_vols_96) == self._spec.donchian_bars
                    and len(st.prev_trs_192) == self._spec.atr_compression_bars
                )
                if is_warm and st.health_status == "ACTIVE":
                    warm_count += 1
                symbols_health[sym] = {
                    "health_status": st.health_status,
                    "last_closed_ts": st.last_closed_ts.isoformat() if st.last_closed_ts else None,
                    "last_exit_ts": st.last_exit_ts.isoformat() if st.last_exit_ts else None,
                    "has_pending_signal": st.pending_signal is not None,
                    "has_open_position": st.open_position is not None,
                    "next_seq": st.next_seq,
                    "bars_buffered_384": len(st.closes_384),
                    "warmup_ready": is_warm,
                }

            if symbol is not None:
                sym_upper = symbol.upper().removesuffix("USDT")
                return symbols_health.get(sym_upper, {})

            pending_count = sum(1 for st in self._states.values() if st.pending_signal is not None)
            return {
                "health_status": self._health_status,
                "evidence_epoch_id": self._epoch_id,
                "collection_start_timestamp": self._collection_start_timestamp,
                "spec_version": self._spec.spec_version,
                "spec_sha256": self._spec.spec_sha256,
                "gauges": {
                    "pending_signals_count": pending_count,
                    "open_positions_count": active_pos,
                    "active_symbols_warm_count": warm_count,
                    "candidate_symbols_count": len(self._spec.universe),
                    "global_health_status": self._health_status,
                },
                "active_open_positions_count": active_pos,
                "counters": dict(self._counters),
                "symbols": symbols_health,
            }

    def active_open_positions_count(self) -> int:
        with self._lock:
            return sum(
                1
                for st in self._states.values()
                if st.open_position is not None
            )

    def observe_cycle_candidate_batch(
        self,
        batch_candles: Mapping[str, list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]],
        *,
        data_quality_flags: Mapping[str, Mapping[str, Any]] | None = None,
        now_utc: datetime | None = None,
        allow_historical_replay: bool = False,
    ) -> dict[str, Any]:
        """Observes candidate coins in true global (timestamp, symbol) order with single-commit persistence."""
        if now_utc is not None:
            ref_now = (
                now_utc.astimezone(timezone.utc)
                if now_utc.tzinfo is not None
                else now_utc.replace(tzinfo=timezone.utc)
            )
        elif allow_historical_replay:
            # Replay mode without explicit now_utc: synchronize reference clock with newest closed candle in batch
            max_c_ts: datetime | None = None
            for clist in batch_candles.values():
                if clist:
                    last_c = clist[-1]
                    ok, _, c_ts, _ = validate_15m_candle(last_c)
                    if ok and c_ts is not None:
                        if max_c_ts is None or c_ts > max_c_ts:
                            max_c_ts = c_ts
            if max_c_ts is not None:
                ref_now = max_c_ts + timedelta(minutes=self._spec.bar_interval_minutes)
            else:
                ref_now = datetime.now(timezone.utc)
        else:
            ref_now = datetime.now(timezone.utc)

        with self._lock:
            initial_health = self._health_status
            initial_sym_health = {sym: self._states[sym].health_status for sym in self._spec.universe}

            # Phase 1: Bootstrap & unseen bar extraction per candidate symbol
            unseen_bars_by_symbol: dict[str, list[tuple[datetime, dict[str, float], dict[str, Any]]]] = {}
            forming_candles: dict[str, tuple[datetime, Mapping[str, Any]] | None] = {}

            for sym in self._spec.universe:
                candles = batch_candles.get(sym) or batch_candles.get(f"{sym}USDT")
                state = self._states[sym]
                if not candles:
                    unseen_bars_by_symbol[sym] = []
                    forming_candles[sym] = None
                    continue

                self._counters["raw_bars_observed"] += len(candles)
                n = len(candles)
                last_c = candles[-1]
                v_last, _, last_ts, _ = validate_15m_candle(last_c)
                if not v_last or last_ts is None:
                    self._counters["invalid_bars"] += 1
                    unseen_bars_by_symbol[sym] = []
                    forming_candles[sym] = None
                    continue

                last_closed = is_15m_candle_closed(
                    last_c,
                    candle_open_utc=last_ts,
                    has_newer_candle_after=False,
                    now_utc=ref_now,
                    bar_interval_minutes=self._spec.bar_interval_minutes,
                    allow_future_replay=allow_historical_replay,
                )
                if not allow_historical_replay and last_ts > ref_now:
                    self._counters["future_candles_rejected"] += 1
                f_candle = (last_ts, last_c) if not last_closed else None
                forming_candles[sym] = f_candle

                raw_flags = data_quality_flags.get(sym) if isinstance(data_quality_flags, dict) else None
                q_flags = self._normalize_quality_flags(raw_flags)

                if state.last_closed_ts is not None:
                    # Incremental cycle: extract closed bars > state.last_closed_ts
                    end_idx = n if last_closed else (n - 1)
                    new_bars: list[tuple[datetime, dict[str, float], dict[str, Any]]] = []
                    for idx in range(end_idx - 1, -1, -1):
                        c = candles[idx]
                        v_ok, _, c_ts, p_dict = validate_15m_candle(c)
                        if not v_ok or c_ts is None or p_dict is None:
                            continue
                        if c_ts <= state.last_closed_ts:
                            break
                        if not allow_historical_replay and c_ts > ref_now:
                            self._counters["future_candles_rejected"] += 1
                            continue
                        if is_15m_candle_closed(
                            c,
                            candle_open_utc=c_ts,
                            has_newer_candle_after=(idx < n - 1),
                            now_utc=ref_now,
                            bar_interval_minutes=self._spec.bar_interval_minutes,
                            allow_future_replay=allow_historical_replay,
                        ):
                            new_bars.append((c_ts, p_dict, q_flags))
                    new_bars.reverse()
                    unseen_bars_by_symbol[sym] = new_bars
                else:
                    # Initial bootstrap: validate all candles, locate last gap, keep continuous suffix
                    end_idx = n if last_closed else (n - 1)
                    valid_closed: list[tuple[datetime, dict[str, float]]] = []
                    for idx in range(max(0, end_idx)):
                        c = candles[idx]
                        v_ok, _, c_ts, p_dict = validate_15m_candle(c)
                        if not v_ok or c_ts is None or p_dict is None:
                            self._counters["invalid_bars"] += 1
                            continue
                        if not allow_historical_replay and c_ts > ref_now:
                            self._counters["future_candles_rejected"] += 1
                            continue
                        if is_15m_candle_closed(
                            c,
                            candle_open_utc=c_ts,
                            has_newer_candle_after=(idx < n - 1),
                            now_utc=ref_now,
                            bar_interval_minutes=self._spec.bar_interval_minutes,
                            allow_future_replay=allow_historical_replay,
                        ):
                            valid_closed.append((c_ts, p_dict))

                    deduped: list[tuple[datetime, dict[str, float]]] = []
                    last_gap_idx = 0
                    for idx, (c_ts, p_dict) in enumerate(valid_closed):
                        if not deduped:
                            deduped.append((c_ts, p_dict))
                            continue
                        prev_ts = deduped[-1][0]
                        if c_ts == prev_ts:
                            self._counters["duplicate_bars"] += 1
                            continue
                        if c_ts < prev_ts:
                            self._counters["out_of_order_bars"] += 1
                            continue
                        if c_ts > prev_ts + self._bar_delta:
                            self._counters["missing_bar_gaps"] += 1
                            last_gap_idx = len(deduped)
                        deduped.append((c_ts, p_dict))

                    suffix = deduped[last_gap_idx:]
                    if allow_historical_replay:
                        # Replay unit tests: process all suffix bars through prospective stream
                        unseen_bars_by_symbol[sym] = [(c_ts, p_dict, q_flags) for c_ts, p_dict in suffix]
                    else:
                        # Production: warm up silent historical prefix, leaving only newest closed bar as unseen
                        if len(suffix) > 1:
                            silent_prefix = suffix[:-1]
                            for c_ts, p_dict in silent_prefix:
                                self._process_single_closed_candle(
                                    state,
                                    c_ts=c_ts,
                                    c_dict=p_dict,
                                    next_open_hint=None,
                                    quality_flags=q_flags,
                                    warmup_only=True,
                                )
                            unseen_bars_by_symbol[sym] = [(suffix[-1][0], suffix[-1][1], q_flags)]
                        elif suffix:
                            unseen_bars_by_symbol[sym] = [(suffix[0][0], suffix[0][1], q_flags)]
                        else:
                            unseen_bars_by_symbol[sym] = []
                    self._evaluate_symbol_health(state)

            # Phase 1.5: Candidate presence and freshness checks across entire candidate universe
            missing_candidates = []
            stale_candidates = []
            freshness_tolerance = timedelta(minutes=45)

            for sym in self._spec.universe:
                flags = data_quality_flags.get(sym) if isinstance(data_quality_flags, dict) else None
                candles = batch_candles.get(sym) or batch_candles.get(f"{sym}USDT")

                is_present = (flags.get("present") if (flags and "present" in flags) else bool(candles and len(candles) > 0))
                # Candidate missing in current cycle must be detected regardless of history
                if not is_present:
                    missing_candidates.append(sym)

                is_store_fresh = (flags.get("candle_store_fresh") if (flags and "candle_store_fresh" in flags) else True)
                if not is_store_fresh:
                    stale_candidates.append(sym)

                st = self._states[sym]
                if not allow_historical_replay and st.last_closed_ts is not None and (ref_now - st.last_closed_ts) > freshness_tolerance:
                    stale_candidates.append(sym)

            self._current_cycle_blockers = {
                "missing_candidates": list(missing_candidates),
                "stale_candidates": list(stale_candidates),
            }

            if missing_candidates:
                self._counters["missing_candidate_cycles"] += 1
                self._health_status = "DEGRADED_MISSING_CANDIDATE"
            elif stale_candidates:
                self._counters["stale_candidate_cycles"] += 1
                self._health_status = "DEGRADED_STALE"
            else:
                self._evaluate_global_health()

            # Phase 2: Merge all unseen bars across candidate symbols and sort by (c_ts, symbol)
            merged_unseen: list[tuple[datetime, str, dict[str, float], dict[str, Any]]] = []
            for sym, bar_list in unseen_bars_by_symbol.items():
                for c_ts, p_dict, q_flags in bar_list:
                    merged_unseen.append((c_ts, sym, p_dict, q_flags))

            # Stably sort by (timestamp, symbol)
            merged_unseen.sort(key=lambda item: (item[0], item[1]))

            # Phase 3: Step sequentially through merged chronological stream
            evaluated_symbols_this_cycle: set[str] = set()
            for c_ts, sym, c_dict, q_flags in merged_unseen:
                state = self._states[sym]

                # Check continuity against state.last_closed_ts
                if state.last_closed_ts is not None:
                    if c_ts == state.last_closed_ts:
                        self._counters["duplicate_bars"] += 1
                        continue
                    if c_ts < state.last_closed_ts:
                        self._counters["out_of_order_bars"] += 1
                        continue
                    if c_ts > state.last_closed_ts + self._bar_delta:
                        self._handle_missing_bar_gap(state, gap_ts=c_ts, flags=q_flags)

                # Re-evaluate global health before each bar step
                if missing_candidates:
                    self._health_status = "DEGRADED_MISSING_CANDIDATE"
                elif stale_candidates:
                    self._health_status = "DEGRADED_STALE"
                else:
                    self._evaluate_global_health()

                # Determine next_open_hint from forming candle if adjacent
                next_open_hint: float | None = None
                f_candle = forming_candles.get(sym)
                if f_candle is not None and f_candle[0] == c_ts + self._bar_delta:
                    try:
                        next_open_hint = float(f_candle[1]["open"])
                    except (KeyError, TypeError, ValueError):
                        pass

                is_warmup_only = (not allow_historical_replay) and (c_ts < self._admission_cutoff)
                self._process_single_closed_candle(
                    state,
                    c_ts=c_ts,
                    c_dict=c_dict,
                    next_open_hint=next_open_hint,
                    quality_flags=q_flags,
                    warmup_only=is_warmup_only,
                )
                evaluated_symbols_this_cycle.add(sym)
                self._evaluate_symbol_health(state)

            # Phase 4: Capture forming references, evaluate global health & persist at most one commit
            for sym in self._spec.universe:
                self._capture_forming_open_reference(self._states[sym], forming_candles.get(sym))

            if missing_candidates:
                self._health_status = "DEGRADED_MISSING_CANDIDATE"
            elif stale_candidates:
                self._health_status = "DEGRADED_STALE"
            else:
                self._evaluate_global_health()

            health_changed = (self._health_status != initial_health) or any(
                self._states[sym].health_status != initial_sym_health[sym] for sym in self._spec.universe
            )
            dirty = bool(merged_unseen or self._outbox or health_changed)
            if dirty:
                self._persist_state()

            cycle_id = f"cycle_{self._checkpoint_generation}_{ref_now.strftime('%Y%m%dT%H%M%SZ')}"
            envelope = {}
            for sym in self._spec.universe:
                st = self._states[sym]
                is_present = sym not in missing_candidates
                is_fresh = sym not in stale_candidates
                latest_closed_ts_str = st.last_closed_ts.isoformat() if st.last_closed_ts else None
                sym_blockers = []
                if not is_present:
                    sym_blockers.append("MISSING_IN_CYCLE")
                if not is_fresh:
                    sym_blockers.append("STALE_DATA_STORE")
                if self._health_status != "ACTIVE":
                    sym_blockers.append(f"GLOBAL_{self._health_status}")
                if st.health_status != "ACTIVE":
                    sym_blockers.append(f"SYMBOL_{st.health_status}")

                signal_evaluated_this_cycle = bool(sym in evaluated_symbols_this_cycle)
                last_eval = _sanitize_signal_eval(st.last_signal_evaluation or st.last_summary)

                if self._health_status != "ACTIVE":
                    accepted = False
                    decision_reason = f"REJECTED_GLOBAL_HEALTH_{self._health_status}"
                elif st.health_status != "ACTIVE":
                    accepted = False
                    decision_reason = f"REJECTED_SYMBOL_{st.health_status}"
                elif last_eval:
                    accepted = bool(last_eval.get("accepted", False))
                    decision_reason = str(last_eval.get("decision_reason") or "HOLD_NO_BREAKOUT")
                else:
                    accepted = False
                    decision_reason = "HOLD_NO_BREAKOUT"

                f_candle = forming_candles.get(sym)
                forming_ts_str = f_candle[0].isoformat() if f_candle is not None else None

                sym_envelope = {
                    "cycle_id": cycle_id,
                    "symbol": sym,
                    "candidate_id": self._spec.candidate_id,
                    "spec_version": self._spec.spec_version,
                    "strategy_spec_sha256": self._spec.strategy_spec_sha256,
                    "spec_sha256": self._spec.spec_sha256,
                    "evidence_epoch_id": self._epoch_id,
                    "runtime_status": self._runtime_status,
                    "observed_this_cycle": bool(batch_candles.get(sym) or batch_candles.get(f"{sym}USDT")),
                    "unseen_closed_bars_processed": len(unseen_bars_by_symbol.get(sym, [])),
                    "candidate_present": is_present,
                    "candidate_fresh": is_fresh,
                    "latest_closed_timestamp": latest_closed_ts_str,
                    "symbol_health": st.health_status,
                    "global_health": self._health_status,
                    "blockers": sym_blockers,
                    "signal_evaluated_this_cycle": signal_evaluated_this_cycle,
                    "accepted": accepted,
                    "decision_reason": decision_reason,
                    "last_signal_evaluation": last_eval,
                    "forming_candle_open_ts": forming_ts_str,
                    "active_position": bool(st.open_position is not None),
                }
                envelope[sym] = sym_envelope

            return envelope

    def observe_symbol_candles(
        self,
        symbol: str,
        candles: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
        *,
        now_utc: datetime | None = None,
        data_quality_flags: Mapping[str, Any] | None = None,
        allow_historical_replay: bool = False,
    ) -> dict[str, Any] | None:
        """Internal/test-only single-symbol observation. Production must use observe_cycle_candidate_batch."""
        sym = str(symbol or "").strip().upper().removesuffix("USDT")
        flags = {sym: data_quality_flags} if data_quality_flags else None
        res_dict = self.observe_cycle_candidate_batch(
            {sym: candles},
            data_quality_flags=flags,
            now_utc=now_utc,
            allow_historical_replay=allow_historical_replay,
        )
        return res_dict.get(sym)

    def _handle_missing_bar_gap(
        self,
        state: _SymbolRollingState,
        *,
        gap_ts: datetime,
        flags: Mapping[str, Any] | None,
    ) -> None:
        """Handles a missing-bar gap: invalidates open positions, cancels pending signals, and resets buffers."""
        self._counters["missing_bar_gaps"] += 1
        state.health_status = "DEGRADED_GAP"
        self._health_status = "DEGRADED_GAP"

        # Invalidate any active open position
        if state.open_position is not None:
            pos = state.open_position
            self._counters["positions_invalidated"] += 1
            self._queue_event(
                "SHADOW_LIFECYCLE_INVALIDATED_DATA_GAP",
                symbol=state.symbol,
                c_ts=gap_ts,
                payload={
                    "shadow_id": pos.shadow_id,
                    "side": pos.side,
                    "signal_timestamp": pos.signal_timestamp.isoformat(),
                    "entry_timestamp": pos.entry_timestamp.isoformat(),
                    "gap_timestamp": gap_ts.isoformat(),
                    "observed_gap_at_seq": state.next_seq,
                    "outcome": "INVALIDATED_OPEN_POSITION_DATA_GAP",
                    "evidence_eligible": False,
                    "gross_pnl_bps": None,
                    "net_pnl_by_cost_tier_bps": None,
                    "data_quality_flags": pos.data_quality_flags,
                },
            )
            state.open_position = None
            state.last_exit_ts = gap_ts

        # Cancel any pending signal
        if state.pending_signal is not None:
            pend = state.pending_signal
            self._queue_event(
                "SHADOW_PENDING_CANCELLED_GAP",
                symbol=state.symbol,
                c_ts=gap_ts,
                payload={
                    "shadow_id": pend.shadow_id,
                    "side": pend.side,
                    "signal_timestamp": pend.signal_timestamp.isoformat(),
                    "earliest_entry_timestamp": pend.earliest_entry_timestamp.isoformat(),
                    "observed_bar_timestamp": gap_ts.isoformat(),
                    "outcome": "CANCELLED_MISSING_NEXT_BAR_GAP",
                    "data_quality_flags": pend.data_quality_flags,
                },
            )
            state.pending_signal = None

        state.reset_buffers(self._spec, health_status="DEGRADED_GAP")

    def _evaluate_symbol_health(self, state: _SymbolRollingState) -> None:
        is_warm = bool(
            state.next_seq >= self._min_warmup_seq
            and len(state.closes_384) == self._spec.sma_slow_bars
            and len(state.prev_vols_96) == self._spec.donchian_bars
            and len(state.prev_trs_192) == self._spec.atr_compression_bars
        )
        if is_warm:
            if state.health_status in ("DEGRADED_GAP", "RECOVERING_GAP"):
                self._counters["gap_recoveries_completed"] += 1
            state.health_status = "ACTIVE"
        else:
            if state.health_status not in ("DEGRADED_GAP", "RECOVERING_GAP"):
                state.health_status = "WARMING_UP"

    def _capture_forming_open_reference(
        self,
        state: _SymbolRollingState,
        forming_candle: tuple[datetime, Mapping[str, Any]] | None,
    ) -> None:
        if forming_candle is None or state.pending_signal is None:
            return
        f_ts, f_dict = forming_candle
        if (
            f_ts == state.pending_signal.earliest_entry_timestamp
            and state.pending_signal.next_bar_open_reference is None
        ):
            try:
                open_val = float(f_dict["open"])
                if math.isfinite(open_val) and open_val > 0.0:
                    state.pending_signal.next_bar_open_reference = open_val
                    if state.last_signal_evaluation is not None:
                        state.last_signal_evaluation["next_bar_open_reference"] = open_val
                    if state.last_summary is not None:
                        state.last_summary["next_bar_open_reference"] = open_val
            except (KeyError, TypeError, ValueError):
                pass

    def _normalize_quality_flags(self, raw_flags: Mapping[str, Any] | None) -> dict[str, Any]:
        if not raw_flags:
            return {
                "macro_quality_status": "UNKNOWN",
                "sentiment_quality_status": "UNKNOWN",
                "funding_quality_status": "UNKNOWN",
                "candle_store_fresh": True,
                "any_degraded_input": True,
            }
        macro_q = str(raw_flags.get("macro_quality_status") or "UNKNOWN")
        sent_q = str(raw_flags.get("sentiment_quality_status") or "UNKNOWN")
        fund_q = str(raw_flags.get("funding_quality_status") or "UNKNOWN")
        c_fresh = bool(raw_flags.get("candle_store_fresh", True))
        degraded = bool(
            raw_flags.get("any_degraded_input")
            or (not c_fresh)
            or any(s not in ("FRESH",) for s in (macro_q, sent_q, fund_q))
        )
        return {
            "macro_quality_status": macro_q,
            "sentiment_quality_status": sent_q,
            "funding_quality_status": fund_q,
            "candle_store_fresh": c_fresh,
            "any_degraded_input": degraded,
        }

    def _process_single_closed_candle(
        self,
        state: _SymbolRollingState,
        *,
        c_ts: datetime,
        c_dict: Mapping[str, float],
        next_open_hint: float | None,
        quality_flags: dict[str, Any],
        warmup_only: bool,
    ) -> None:
        self._counters["actual_new_bars_processed"] += 1
        if state.health_status in ("DEGRADED_GAP", "RECOVERING_GAP"):
            state.health_status = "RECOVERING_GAP"
            self._counters["gap_recovery_bars"] += 1

        b_open = c_dict["open"]
        b_high = c_dict["high"]
        b_low = c_dict["low"]
        b_close = c_dict["close"]
        b_vol = c_dict["volume"]
        seq = state.next_seq

        # ── 1. Advance existing OPEN position first ──
        if state.open_position is not None:
            self._advance_open_position_on_closed_bar(
                state,
                seq=seq,
                c_ts=c_ts,
                b_open=b_open,
                b_high=b_high,
                b_low=b_low,
                b_close=b_close,
                quality_flags=quality_flags,
            )

        # ── 2. Fill PENDING_NEXT_OPEN at open of bar i+1 (`entry_seq = signal_seq + 1`) ──
        if state.pending_signal is not None:
            pend = state.pending_signal
            if c_ts == pend.earliest_entry_timestamp and seq == pend.signal_seq + 1:
                state.pending_signal = None
                self._enter_and_check_entry_bar(
                    state,
                    pend=pend,
                    entry_seq=seq,
                    entry_ts=c_ts,
                    b_open=b_open,
                    b_high=b_high,
                    b_low=b_low,
                    b_close=b_close,
                    quality_flags=quality_flags,
                )
            elif c_ts >= pend.earliest_entry_timestamp:
                state.pending_signal = None
                self._queue_event(
                    "SHADOW_PENDING_CANCELLED_MISSING_NEXT_BAR",
                    symbol=state.symbol,
                    c_ts=c_ts,
                    payload={
                        "shadow_id": pend.shadow_id,
                        "side": pend.side,
                        "signal_timestamp": pend.signal_timestamp.isoformat(),
                        "earliest_entry_timestamp": pend.earliest_entry_timestamp.isoformat(),
                        "observed_bar_timestamp": c_ts.isoformat(),
                        "outcome": "CANCELLED_MISSING_NEXT_BAR_OPEN",
                        "data_quality_flags": quality_flags,
                    },
                )

        # ── 3. Incremental O(1) rolling feature computation on closed bar `seq` ──
        if len(state.closes_96) == self._spec.sma_fast_bars:
            state.sum_close_96 -= state.closes_96[0]
        state.closes_96.append(b_close)
        state.sum_close_96 += b_close

        if len(state.closes_384) == self._spec.sma_slow_bars:
            state.sum_close_384 -= state.closes_384[0]
        state.closes_384.append(b_close)
        state.sum_close_384 += b_close

        # Periodic float drift resync once every 4096 bars
        if seq > 0 and (seq & 4095) == 0:
            state.sum_close_96 = math.fsum(state.closes_96)
            state.sum_close_384 = math.fsum(state.closes_384)
            state.sum_vol_96 = math.fsum(state.prev_vols_96)
            state.sum_tr_192 = math.fsum(state.prev_trs_192)

        donchian_n = self._spec.donchian_bars
        while state.prev_high_max_dq and state.prev_high_max_dq[0][0] < seq - donchian_n:
            state.prev_high_max_dq.popleft()
        while state.prev_low_min_dq and state.prev_low_min_dq[0][0] < seq - donchian_n:
            state.prev_low_min_dq.popleft()

        warmup_ready = (
            seq >= self._min_warmup_seq
            and len(state.closes_384) == self._spec.sma_slow_bars
            and len(state.prev_vols_96) == donchian_n
            and len(state.prev_trs_192) == self._spec.atr_compression_bars
            and bool(state.prev_high_max_dq)
            and bool(state.prev_low_min_dq)
        )

        if not warmup_only:
            summary = self._evaluate_closed_signal_bar(
                state,
                seq=seq,
                c_ts=c_ts,
                b_close=b_close,
                b_vol=b_vol,
                warmup_ready=warmup_ready,
                next_open_hint=next_open_hint,
                quality_flags=quality_flags,
            )
            state.last_signal_evaluation = summary
            state.last_summary = summary
        elif state.last_signal_evaluation is None:
            state.last_signal_evaluation = {
                "candidate_id": self._spec.candidate_id,
                "spec_version": self._spec.spec_version,
                "spec_sha256": self._spec.spec_sha256,
                "evidence_epoch_id": self._epoch_id,
                "symbol": state.symbol,
                "last_warmup_bar_timestamp": c_ts.isoformat(),
                "bars_ingested": seq + 1,
                "outcome": "WARMUP_ONLY",
            }
            state.last_summary = state.last_signal_evaluation

        # ── 4. Push closed bar `seq` into strictly-prior (`shift(1)`) buffers for `seq + 1` ──
        tr_curr = (
            (b_high - b_low)
            if state.prev_close is None
            else max(b_high - b_low, abs(b_high - state.prev_close), abs(b_low - state.prev_close))
        )
        if len(state.prev_vols_96) == donchian_n:
            state.sum_vol_96 -= state.prev_vols_96[0]
        state.prev_vols_96.append(b_vol)
        state.sum_vol_96 += b_vol

        if len(state.prev_trs_192) == self._spec.atr_compression_bars:
            state.sum_tr_192 -= state.prev_trs_192[0]
        state.prev_trs_192.append(tr_curr)
        state.sum_tr_192 += tr_curr

        while state.prev_high_max_dq and state.prev_high_max_dq[-1][1] <= b_high:
            state.prev_high_max_dq.pop()
        state.prev_high_max_dq.append((seq, b_high))

        while state.prev_low_min_dq and state.prev_low_min_dq[-1][1] >= b_low:
            state.prev_low_min_dq.pop()
        state.prev_low_min_dq.append((seq, b_low))

        state.prev_close = b_close
        state.last_closed_ts = c_ts
        state.next_seq = seq + 1

    def _evaluate_closed_signal_bar(
        self,
        state: _SymbolRollingState,
        *,
        seq: int,
        c_ts: datetime,
        b_close: float,
        b_vol: float,
        warmup_ready: bool,
        next_open_hint: float | None,
        quality_flags: dict[str, Any],
    ) -> dict[str, Any]:
        signal_close_ts = c_ts + self._bar_delta
        earliest_entry_ts = signal_close_ts

        # Global health gate check: admissions strictly prohibited unless global health is ACTIVE
        if self._health_status != "ACTIVE":
            self._counters["signals_rejected"] += 1
            self._counters["global_admission_blocked_cycles"] += 1
            rec_payload = {
                "symbol": state.symbol,
                "side": "NONE",
                "signal_timestamp": c_ts.isoformat(),
                "signal_close_timestamp": signal_close_ts.isoformat(),
                "earliest_entry_timestamp": earliest_entry_ts.isoformat(),
                "next_bar_open_reference": next_open_hint,
                "feature_conditions": {
                    "global_health": {
                        "passed": False,
                        "global_health_status": self._health_status,
                        "required": "ACTIVE",
                    }
                },
                "accepted": False,
                "decision_reason": f"REJECTED_GLOBAL_HEALTH_{self._health_status}",
                "hypothetical_lifecycle": "NO_POSITION",
                "gross_pnl_bps": None,
                "net_pnl_by_cost_tier_bps": None,
                "outcome": "REJECTED",
                "data_quality_flags": quality_flags,
            }
            if self._log_rejected:
                return self._queue_event(
                    "SHADOW_CLOSED_BAR_EVALUATED",
                    symbol=state.symbol,
                    c_ts=c_ts,
                    payload=rec_payload,
                )
            return {
                "candidate_id": self._spec.candidate_id,
                "spec_version": self._spec.spec_version,
                "spec_sha256": self._spec.spec_sha256,
                "evidence_epoch_id": self._epoch_id,
                **rec_payload,
            }

        if not warmup_ready or state.sum_vol_96 <= 0.0 or state.sum_tr_192 <= 0.0 or b_close <= 0.0:
            self._counters["signals_rejected"] += 1
            rec_payload = {
                "symbol": state.symbol,
                "side": "NONE",
                "signal_timestamp": c_ts.isoformat(),
                "signal_close_timestamp": signal_close_ts.isoformat(),
                "earliest_entry_timestamp": earliest_entry_ts.isoformat(),
                "next_bar_open_reference": next_open_hint,
                "feature_conditions": {
                    "warmup_ready": {
                        "passed": False,
                        "bars_seen": seq + 1,
                        "required_bars": self._min_warmup_seq + 1,
                    }
                },
                "accepted": False,
                "decision_reason": "INSUFFICIENT_WARMUP_BARS",
                "hypothetical_lifecycle": "NO_POSITION",
                "gross_pnl_bps": None,
                "net_pnl_by_cost_tier_bps": None,
                "outcome": "REJECTED",
                "data_quality_flags": quality_flags,
            }
            if self._log_rejected:
                return self._queue_event(
                    "SHADOW_CLOSED_BAR_EVALUATED",
                    symbol=state.symbol,
                    c_ts=c_ts,
                    payload=rec_payload,
                )
            return {
                "candidate_id": self._spec.candidate_id,
                "spec_version": self._spec.spec_version,
                "spec_sha256": self._spec.spec_sha256,
                "evidence_epoch_id": self._epoch_id,
                **rec_payload,
            }

        prev_hi = state.prev_high_max_dq[0][1]
        prev_lo = state.prev_low_min_dq[0][1]
        sma_fast = state.sum_close_96 / float(self._spec.sma_fast_bars)
        sma_slow = state.sum_close_384 / float(self._spec.sma_slow_bars)
        vol_ma = state.sum_vol_96 / float(self._spec.donchian_bars)
        atr_192 = state.sum_tr_192 / float(self._spec.atr_compression_bars)
        vol_ratio = b_vol / vol_ma
        atr_bps = atr_192 / b_close * 10000.0

        vol_pass = bool(vol_ratio >= self._spec.min_vol_ratio_96)
        buy_breakout = bool(b_close > prev_hi)
        sell_breakout = bool(b_close < prev_lo)
        buy_trend = bool(b_close > sma_slow and sma_fast > sma_slow)
        sell_trend = bool(b_close < sma_slow and sma_fast < sma_slow)
        atr_pass = bool(atr_bps <= self._spec.atr_compression_q65_max_bps)

        side = "NONE"
        if vol_pass and buy_breakout and buy_trend:
            side = "BUY"
        elif vol_pass and sell_breakout and sell_trend:
            side = "SELL"

        symbol_busy = (state.open_position is not None) or (state.pending_signal is not None)
        cooldown_active = False
        cooldown_rem_bars = 0
        if state.last_exit_ts is not None:
            cooldown_end = state.last_exit_ts + timedelta(
                minutes=self._spec.cooldown_bars * self._spec.bar_interval_minutes
            )
            if earliest_entry_ts < cooldown_end:
                cooldown_active = True
                cooldown_rem_bars = int(
                    math.ceil((cooldown_end - earliest_entry_ts).total_seconds() / (self._spec.bar_interval_minutes * 60))
                )
        active_total = self.active_open_positions_count()
        capacity_pass = bool(
            (not symbol_busy)
            and (not cooldown_active)
            and (active_total < self._spec.max_concurrent_positions)
        )

        feature_conditions = {
            "warmup_ready": {"passed": True, "bars_seen": seq + 1, "required_bars": self._min_warmup_seq + 1},
            "vol_expansion": {
                "passed": vol_pass,
                "vol_ratio": round(vol_ratio, 4),
                "min_required": self._spec.min_vol_ratio_96,
            },
            "donchian_breakout": {
                "buy_passed": buy_breakout,
                "sell_passed": sell_breakout,
                "close": round(b_close, 6),
                "prev_high_96": round(prev_hi, 6),
                "prev_low_96": round(prev_lo, 6),
            },
            "trend_alignment": {
                "buy_passed": buy_trend,
                "sell_passed": sell_trend,
                "sma_fast_96": round(sma_fast, 6),
                "sma_slow_384": round(sma_slow, 6),
            },
            "atr_compression": {
                "passed": atr_pass,
                "atr_192_bps": round(atr_bps, 4),
                "locked_q65_max_bps": self._spec.atr_compression_q65_max_bps,
            },
            "portfolio_capacity_and_cooldown": {
                "passed": capacity_pass,
                "symbol_busy": symbol_busy,
                "cooldown_active": cooldown_active,
                "cooldown_remaining_bars": cooldown_rem_bars,
                "active_positions_global": active_total,
                "max_concurrent_positions": self._spec.max_concurrent_positions,
            },
        }

        accepted = False
        if not vol_pass:
            reason = "VOL_RATIO_BELOW_MIN"
        elif side == "NONE":
            reason = "NO_DONCHIAN_TREND_BREAKOUT"
        elif not atr_pass:
            reason = "ATR_ABOVE_COMPRESSION_Q65"
        elif symbol_busy:
            reason = "REJECTED_SYMBOL_ALREADY_OPEN"
        elif cooldown_active:
            reason = "REJECTED_COOLDOWN_ACTIVE"
        elif active_total >= self._spec.max_concurrent_positions:
            reason = "REJECTED_MAX_CONCURRENT_POSITIONS"
        else:
            accepted = True
            reason = "ACCEPTED_PENDING_NEXT_BAR_OPEN"

        shadow_id = f"SHADOW_VCB1_{state.symbol}_{c_ts.strftime('%Y%m%dT%H%M')}_{side}"
        if accepted:
            self._counters["signals_accepted"] += 1
            state.pending_signal = _PendingShadowSignal(
                shadow_id=shadow_id,
                symbol=state.symbol,
                side=side,
                signal_seq=seq,
                signal_timestamp=c_ts,
                signal_close_timestamp=signal_close_ts,
                earliest_entry_timestamp=earliest_entry_ts,
                signal_close_price=b_close,
                next_bar_open_reference=next_open_hint,
                feature_conditions=feature_conditions,
                data_quality_flags=quality_flags,
            )
        else:
            self._counters["signals_rejected"] += 1

        rec_payload = {
            "shadow_id": shadow_id if accepted else None,
            "symbol": state.symbol,
            "side": side,
            "signal_timestamp": c_ts.isoformat(),
            "signal_close_timestamp": signal_close_ts.isoformat(),
            "earliest_entry_timestamp": earliest_entry_ts.isoformat(),
            "next_bar_open_reference": next_open_hint,
            "feature_conditions": feature_conditions,
            "accepted": accepted,
            "decision_reason": reason,
            "hypothetical_lifecycle": "PENDING_NEXT_OPEN" if accepted else "REJECTED",
            "gross_pnl_bps": None,
            "net_pnl_by_cost_tier_bps": None,
            "outcome": "PENDING_NEXT_OPEN" if accepted else "REJECTED",
            "data_quality_flags": quality_flags,
        }

        ev_type = "SHADOW_SIGNAL_ACCEPTED" if accepted else "SHADOW_CLOSED_BAR_EVALUATED"
        if accepted or self._log_rejected:
            return self._queue_event(
                ev_type,
                symbol=state.symbol,
                c_ts=c_ts,
                payload=rec_payload,
            )
        return {
            "candidate_id": self._spec.candidate_id,
            "spec_version": self._spec.spec_version,
            "spec_sha256": self._spec.spec_sha256,
            "evidence_epoch_id": self._epoch_id,
            **rec_payload,
        }

    def _enter_and_check_entry_bar(
        self,
        state: _SymbolRollingState,
        *,
        pend: _PendingShadowSignal,
        entry_seq: int,
        entry_ts: datetime,
        b_open: float,
        b_high: float,
        b_low: float,
        b_close: float,
        quality_flags: dict[str, Any],
    ) -> None:
        tp_frac = self._spec.tp_bps / 10000.0
        sl_frac = self._spec.sl_bps / 10000.0
        if pend.side == "BUY":
            tp_target = b_open * (1.0 + tp_frac)
            sl_target = b_open * (1.0 - sl_frac)
        else:
            tp_target = b_open * (1.0 - tp_frac)
            sl_target = b_open * (1.0 + sl_frac)

        self._counters["positions_opened"] += 1
        pos = _OpenShadowPosition(
            shadow_id=pend.shadow_id,
            symbol=pend.symbol,
            side=pend.side,
            signal_seq=pend.signal_seq,
            entry_seq=entry_seq,
            signal_timestamp=pend.signal_timestamp,
            signal_close_timestamp=pend.signal_close_timestamp,
            earliest_entry_timestamp=pend.earliest_entry_timestamp,
            entry_timestamp=entry_ts,
            signal_close_price=pend.signal_close_price,
            entry_price=b_open,
            tp_target=tp_target,
            sl_target=sl_target,
            bars_checked=0,
            feature_conditions=pend.feature_conditions,
            data_quality_flags=pend.data_quality_flags,
        )
        state.open_position = pos

        self._queue_event(
            "SHADOW_LIFECYCLE_ENTERED_NEXT_OPEN",
            symbol=pos.symbol,
            c_ts=pos.entry_timestamp,
            payload={
                "shadow_id": pos.shadow_id,
                "side": pos.side,
                "signal_timestamp": pos.signal_timestamp.isoformat(),
                "earliest_entry_timestamp": pos.earliest_entry_timestamp.isoformat(),
                "entry_timestamp": pos.entry_timestamp.isoformat(),
                "signal_close_price": pos.signal_close_price,
                "next_bar_open_reference": b_open,
                "entry_price": b_open,
                "tp_target": tp_target,
                "sl_target": sl_target,
                "hypothetical_lifecycle": "OPEN",
                "outcome": "OPEN",
                "data_quality_flags": quality_flags,
            },
        )

        # Entry bar (`step = 0`) barrier check with conservative SL-first collision resolution
        self._check_bar_barriers(
            state,
            pos=pos,
            step=0,
            c_ts=entry_ts,
            b_open=b_open,
            b_high=b_high,
            b_low=b_low,
            b_close=b_close,
            quality_flags=quality_flags,
        )

    def _advance_open_position_on_closed_bar(
        self,
        state: _SymbolRollingState,
        *,
        seq: int,
        c_ts: datetime,
        b_open: float,
        b_high: float,
        b_low: float,
        b_close: float,
        quality_flags: dict[str, Any],
    ) -> None:
        pos = state.open_position
        if pos is None:
            return
        step = seq - pos.entry_seq
        if step < 1:
            return
        self._check_bar_barriers(
            state,
            pos=pos,
            step=step,
            c_ts=c_ts,
            b_open=b_open,
            b_high=b_high,
            b_low=b_low,
            b_close=b_close,
            quality_flags=quality_flags,
        )

    def _check_bar_barriers(
        self,
        state: _SymbolRollingState,
        *,
        pos: _OpenShadowPosition,
        step: int,
        c_ts: datetime,
        b_open: float,
        b_high: float,
        b_low: float,
        b_close: float,
        quality_flags: dict[str, Any],
    ) -> None:
        exit_price: float | None = None
        exit_ts: datetime | None = None
        exit_reason: str | None = None
        bars_held = step + 1
        same_bar_collision = False
        gap_through_stop = False

        if pos.side == "BUY":
            if step >= 1 and b_open <= pos.sl_target:
                exit_price = b_open
                exit_ts = c_ts
                exit_reason = "SL_GAP"
                bars_held = step
                gap_through_stop = True
            elif b_low <= pos.sl_target:
                exit_price = min(b_open, pos.sl_target)
                exit_ts = c_ts + self._bar_delta
                exit_reason = "SL"
                bars_held = step + 1
                same_bar_collision = bool(b_high >= pos.tp_target)
            elif b_high >= pos.tp_target:
                exit_price = pos.tp_target
                exit_ts = c_ts + self._bar_delta
                exit_reason = "TP"
                bars_held = step + 1
        else:
            if step >= 1 and b_open >= pos.sl_target:
                exit_price = b_open
                exit_ts = c_ts
                exit_reason = "SL_GAP"
                bars_held = step
                gap_through_stop = True
            elif b_high >= pos.sl_target:
                exit_price = max(b_open, pos.sl_target)
                exit_ts = c_ts + self._bar_delta
                exit_reason = "SL"
                bars_held = step + 1
                same_bar_collision = bool(b_low <= pos.tp_target)
            elif b_low <= pos.tp_target:
                exit_price = pos.tp_target
                exit_ts = c_ts + self._bar_delta
                exit_reason = "TP"
                bars_held = step + 1

        if exit_reason is None and (step + 1) >= self._spec.max_hold_bars:
            exit_price = b_close
            exit_ts = c_ts + self._bar_delta
            exit_reason = "TIMEOUT"
            bars_held = self._spec.max_hold_bars

        pos.bars_checked = step + 1
        if exit_reason is None or exit_price is None or exit_ts is None:
            return

        gross_frac = (
            (exit_price - pos.entry_price) / pos.entry_price
            if pos.side == "BUY"
            else (pos.entry_price - exit_price) / pos.entry_price
        )
        gross_bps = gross_frac * 10000.0
        cost_tiers = {
            f"{int(tier)}bps": round(gross_bps - float(tier), 4)
            for tier in self._spec.cost_tiers_bps
        }

        state.open_position = None
        state.last_exit_ts = exit_ts
        self._counters["positions_resolved"] += 1

        self._queue_event(
            "SHADOW_LIFECYCLE_RESOLVED",
            symbol=pos.symbol,
            c_ts=exit_ts,
            payload={
                "shadow_id": pos.shadow_id,
                "side": pos.side,
                "signal_timestamp": pos.signal_timestamp.isoformat(),
                "signal_close_timestamp": pos.signal_close_timestamp.isoformat(),
                "earliest_entry_timestamp": pos.earliest_entry_timestamp.isoformat(),
                "entry_timestamp": pos.entry_timestamp.isoformat(),
                "exit_timestamp": exit_ts.isoformat(),
                "signal_close_price": pos.signal_close_price,
                "next_bar_open_reference": pos.entry_price,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "bars_held": bars_held,
                "same_bar_collision": same_bar_collision,
                "gap_through_stop": gap_through_stop,
                "feature_conditions": pos.feature_conditions,
                "accepted": True,
                "decision_reason": "ACCEPTED_PENDING_NEXT_BAR_OPEN",
                "hypothetical_lifecycle": "CLOSED",
                "evidence_eligible": bool(self._activation_manifest is not None and self._health_status == "ACTIVE"),
                "gross_return_fraction": round(gross_frac, 8),
                "gross_pnl_bps": round(gross_bps, 4),
                "net_pnl_by_cost_tier_bps": cost_tiers,
                "outcome": exit_reason,
                "data_quality_flags": {
                    "at_signal": pos.data_quality_flags,
                    "at_exit": quality_flags,
                },
            },
        )


_DEFAULT_SHADOW_LOGGER: ProspectiveShadowLogger | None = None
_DEFAULT_LOGGER_LOCK = threading.Lock()


def get_prospective_shadow_logger(
    *,
    manifest_path: Path | str | None = None,
    activation_manifest: EvidenceActivationManifest | None = None,
    reset_singleton: bool = False,
) -> ProspectiveShadowLogger:
    """Returns the singleton bounded prospective shadow logger."""
    global _DEFAULT_SHADOW_LOGGER
    with _DEFAULT_LOGGER_LOCK:
        if reset_singleton or _DEFAULT_SHADOW_LOGGER is None:
            resolved_manifest = activation_manifest
            if resolved_manifest is None and manifest_path is not None:
                try:
                    resolved_manifest = load_activation_manifest(manifest_path)
                except Exception:
                    resolved_manifest = None
            elif resolved_manifest is None:
                env_manifest = os.environ.get("PROSPECTIVE_ACTIVATION_MANIFEST_PATH")
                if env_manifest and Path(env_manifest).exists():
                    try:
                        resolved_manifest = load_activation_manifest(env_manifest)
                    except Exception:
                        resolved_manifest = None
                else:
                    default_path = build_logs_path("prospective_shadow_manifest.json")
                    if default_path.exists():
                        try:
                            resolved_manifest = load_activation_manifest(default_path)
                        except Exception:
                            resolved_manifest = None

            _DEFAULT_SHADOW_LOGGER = ProspectiveShadowLogger(
                activation_manifest=resolved_manifest
            )
        return _DEFAULT_SHADOW_LOGGER
