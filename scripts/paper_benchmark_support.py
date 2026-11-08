"""
scripts/paper_benchmark_support.py

Lightweight runner and harness support for offline paper trading benchmarks.
Contains NetworkInterceptor, minimal synthetic candle generator with interval-aware spacing,
and network audit utilities without importing heavy numerical or async framework dependencies.
"""

from __future__ import annotations

import csv
import json
import math
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


INTERVAL_SECONDS: Dict[str, int] = {
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def make_synthetic_candles(
    base_price: float = 50000.0,
    n: int = 210,
    interval: str = "15m",
    end_time: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Generate synthetic candles with strictly interval-aware timestamps.
    15m -> 900s step
    1h  -> 3600s step
    4h  -> 14400s step
    1d  -> 86400s step
    """
    step_seconds = INTERVAL_SECONDS.get(interval, 900)
    candles = []
    end_ts = int(end_time if end_time is not None else time.time())
    start_ts = end_ts - n * step_seconds
    for i in range(n):
        ts = start_ts + i * step_seconds
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        close_iso = datetime.fromtimestamp(ts + step_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        open_iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        candles.append({
            "open_ts": ts,
            "close_ts": ts + step_seconds,
            "time": dt_str,
            "time_utc": open_iso,
            "open_time_utc": open_iso,
            "close_time_utc": close_iso,
            "open": base_price + i * 0.5,
            "high": base_price + i * 0.5 + 5.0,
            "low": base_price + i * 0.5 - 5.0,
            "close": base_price + i * 0.5 + 1.0,
            "volume": 1000.0 + i,
            "closed": True,
            "is_closed": True,
        })
    return candles


def parse_utc_15m_timestamp(raw_time: Any) -> int:
    """Parse a 15m bar open timestamp in UTC and verify alignment to a 900s UTC boundary."""
    text = str(raw_time).strip()
    dt: Optional[datetime] = None
    if len(text) == 16 and text[4] == "-" and text[10] == " ":
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    else:
        iso_text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_text)
        dt = dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    epoch_sec = int(dt.timestamp())
    if epoch_sec % 900 != 0:
        raise ValueError(f"15m timestamp '{raw_time}' ({epoch_sec}) is not aligned to a 900s UTC boundary")
    return epoch_sec


def merge_and_audit_replay_15m_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    allowlisted_gaps: Optional[Set[Tuple[int, int]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Globally sort, deduplicate, conflict-check, and spacing-audit 15m historical rows.

    Fails closed (ValueError) on:
    - empty input,
    - non-finite or invalid OHLCV invariants,
    - duplicate timestamp with conflicting OHLCV,
    - non-15m spacing not explicitly present in ``allowlisted_gaps``.
    """
    allowed = allowlisted_gaps or set()
    raw_rows = 0
    duplicate_rows = 0
    by_ts: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        raw_rows += 1
        open_ts = parse_utc_15m_timestamp(row["time"])
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        v = float(row.get("volume", 0.0))
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            raise ValueError(f"[{symbol}] Non-finite OHLCV at ts={open_ts}")
        if o <= 0.0 or h <= 0.0 or l <= 0.0 or c <= 0.0 or v < 0.0:
            raise ValueError(f"[{symbol}] Non-positive price or negative volume at ts={open_ts}")
        if h + 1e-9 < max(o, c) or l - 1e-9 > min(o, c) or h + 1e-9 < l:
            raise ValueError(f"[{symbol}] Invalid OHLC envelope at ts={open_ts}: O={o}, H={h}, L={l}, C={c}")

        if open_ts in by_ts:
            prev = by_ts[open_ts]
            if (
                abs(prev["open"] - o) > 1e-9
                or abs(prev["high"] - h) > 1e-9
                or abs(prev["low"] - l) > 1e-9
                or abs(prev["close"] - c) > 1e-9
                or abs(prev["volume"] - v) > 1e-9
            ):
                raise ValueError(
                    f"[{symbol}] Conflicting OHLCV on duplicate timestamp {prev['time']} ({open_ts}): "
                    f"existing={(prev['open'], prev['high'], prev['low'], prev['close'], prev['volume'])} vs "
                    f"incoming={(o, h, l, c, v)}"
                )
            duplicate_rows += 1
            continue

        dt_str = datetime.fromtimestamp(open_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        open_iso = datetime.fromtimestamp(open_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        close_iso = datetime.fromtimestamp(open_ts + 900, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bar_entry: Dict[str, Any] = {
            "open_ts": open_ts,
            "close_ts": open_ts + 900,
            "time": dt_str,
            "time_utc": open_iso,
            "open_time_utc": open_iso,
            "close_time_utc": close_iso,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "closed": True,
            "is_closed": True,
        }
        if "bar_id" in row:
            bar_entry["bar_id"] = row["bar_id"]
        by_ts[open_ts] = bar_entry

    if not by_ts:
        raise ValueError(f"[{symbol}] Replay dataset is empty after parsing")

    sorted_ts = sorted(by_ts.keys())
    sorted_bars = [by_ts[ts] for ts in sorted_ts]
    audited_gaps: List[Dict[str, Any]] = []
    for idx in range(len(sorted_ts) - 1):
        t0, t1 = sorted_ts[idx], sorted_ts[idx + 1]
        if t1 <= t0:
            raise ValueError(f"[{symbol}] Non-monotonic timestamps {t0} -> {t1}")
        delta = t1 - t0
        if delta != 900:
            if (t0, t1) not in allowed:
                raise ValueError(
                    f"[{symbol}] Unallowlisted 15m spacing gap: {by_ts[t0]['time']} -> {by_ts[t1]['time']} "
                    f"({delta}s != 900s)"
                )
            audited_gaps.append({"from_ts": t0, "to_ts": t1, "gap_seconds": delta})

    audit_stats = {
        "symbol": symbol,
        "raw_rows": raw_rows,
        "duplicate_rows": duplicate_rows,
        "unique_rows": len(sorted_bars),
        "audited_gap_count": len(audited_gaps),
        "audited_gaps": audited_gaps,
        "first_open_time_utc": sorted_bars[0]["open_time_utc"],
        "last_open_time_utc": sorted_bars[-1]["open_time_utc"],
        "last_close_time_utc": sorted_bars[-1]["close_time_utc"],
    }
    return sorted_bars, audit_stats


def load_and_audit_replay_15m_csvs(
    csv_paths: Sequence[Path | str],
    *,
    symbol: str,
    allowlisted_gaps: Optional[Set[Tuple[int, int]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load multiple monthly 15m CSV files for a symbol and audit/deduplicate globally."""
    if not csv_paths:
        raise FileNotFoundError(f"[{symbol}] No CSV files supplied for historical replay")
    collected_rows: List[Dict[str, Any]] = []
    source_files: List[str] = []
    for p in csv_paths:
        path_obj = Path(p)
        if not path_obj.exists():
            raise FileNotFoundError(f"[{symbol}] Missing historical CSV file: {path_obj}")
        source_files.append(path_obj.name)
        with open(path_obj, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                collected_rows.append(row)
    bars, stats = merge_and_audit_replay_15m_rows(
        collected_rows,
        symbol=symbol,
        allowlisted_gaps=allowlisted_gaps,
    )
    stats["source_files"] = source_files
    return bars, stats


def build_replay_progression_plan(
    bars: Sequence[Dict[str, Any]],
    *,
    seed_count: int = 210,
    replay_cycles: int = 20,
) -> Dict[str, Any]:
    """Select an exact contiguous window of ``seed_count + replay_cycles`` 15m bars.

    Seed consumes indices ``0 .. seed_count - 1``.
    Replay cycle ``i`` (1-indexed, ``1 .. replay_cycles``) consumes index ``seed_count + (i - 1)``,
    guaranteeing zero skipped bars, zero repeated bars, and exact 900s progression.
    """
    required = seed_count + replay_cycles
    if len(bars) < required:
        raise ValueError(
            f"Insufficient audited 15m bars for replay: have {len(bars)}, need >= {required}"
        )
    window = list(bars[-required:])
    for idx in range(len(window) - 1):
        delta = int(window[idx + 1]["open_ts"]) - int(window[idx]["open_ts"])
        if delta != 900:
            raise ValueError(
                f"Replay window requires contiguous 900s bars without gaps, found {delta}s at offset {idx}"
            )
    seed_bars = [dict(b) for b in window[:seed_count]]
    replay_step_bars = [dict(window[seed_count + (i - 1)]) for i in range(1, replay_cycles + 1)]
    seed_close_ts = int(seed_bars[-1]["open_ts"]) + 900
    return {
        "seed_bars": seed_bars,
        "replay_step_bars": replay_step_bars,
        "seed_close_ts": seed_close_ts,
        "window_first_open_utc": seed_bars[0]["open_time_utc"],
        "seed_last_open_utc": seed_bars[-1]["open_time_utc"],
        "replay_first_open_utc": replay_step_bars[0]["open_time_utc"] if replay_step_bars else None,
        "replay_last_open_utc": replay_step_bars[-1]["open_time_utc"] if replay_step_bars else None,
        "replay_last_close_utc": replay_step_bars[-1]["close_time_utc"] if replay_step_bars else None,
    }


def aggregate_closed_utc_htf_candle(
    bars_15m_by_open_ts: Mapping[int, Mapping[str, Any]],
    *,
    interval: str,
    closed_15m_open_ts: int,
) -> Optional[Dict[str, Any]]:
    """Emit a closed HTF kline strictly on exact UTC bucket close with full constituent 15m bars.

    - 1h (3600s): closes at :00 UTC, requires 4 contiguous 15m bars [close_ts - 3600, close_ts).
    - 4h (14400s): closes at 00/04/08/12/16/20:00 UTC, requires 16 contiguous 15m bars.
    - 1d (86400s): closes at 00:00 UTC midnight, requires 96 contiguous 15m bars.
    Never reads any bar with open_ts >= close_ts (zero lookahead) and never emits partial buckets.
    """
    if interval not in ("1h", "4h", "1d"):
        raise ValueError(f"Unsupported HTF aggregation interval: {interval}")
    step = INTERVAL_SECONDS[interval]
    if closed_15m_open_ts % 900 != 0:
        raise ValueError(f"closed_15m_open_ts ({closed_15m_open_ts}) is not 15m UTC-aligned")
    bucket_close_ts = int(closed_15m_open_ts) + 900
    if bucket_close_ts % step != 0:
        return None

    bucket_open_ts = bucket_close_ts - step
    n_constituents = step // 900
    constituents: List[Mapping[str, Any]] = []
    for k in range(n_constituents):
        req_open_ts = bucket_open_ts + k * 900
        bar = bars_15m_by_open_ts.get(req_open_ts)
        if bar is None:
            return None
        constituents.append(bar)

    open_dt_str = datetime.fromtimestamp(bucket_open_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    open_iso = datetime.fromtimestamp(bucket_open_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    close_iso = datetime.fromtimestamp(bucket_close_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "open_ts": bucket_open_ts,
        "close_ts": bucket_close_ts,
        "time": open_dt_str,
        "time_utc": open_iso,
        "open_time_utc": open_iso,
        "close_time_utc": close_iso,
        "open": float(constituents[0]["open"]),
        "high": max(float(b["high"]) for b in constituents),
        "low": min(float(b["low"]) for b in constituents),
        "close": float(constituents[-1]["close"]),
        "volume": sum(float(b.get("volume", 0.0)) for b in constituents),
        "constituent_count": n_constituents,
        "closed": True,
        "is_closed": True,
    }


class NetworkInterceptor:
    """Intercepts all external non-loopback outbound network attempts during offline benchmark."""

    def __init__(self):
        self.outbound_attempts = 0
        self.blocked_targets: List[str] = []
        self._orig_sock_connect = socket.socket.connect
        self._orig_sock_gai = socket.getaddrinfo
        self._orig_async_resolve = None
        self._orig_threaded_resolve = None
        self.active = False

    def _is_loopback(self, host: Any) -> bool:
        return str(host).lower() in ("127.0.0.1", "localhost", "::1")

    def __enter__(self):
        self.active = True

        def patched_connect(sock, address):
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else address
            if self._is_loopback(host):
                return self._orig_sock_connect(sock, address)
            self.outbound_attempts += 1
            self.blocked_targets.append(str(address))
            raise ConnectionRefusedError(f"Benchmark network block: outbound connection to {address} is prohibited")

        def patched_gai(host, port, *args, **kwargs):
            if self._is_loopback(host):
                return self._orig_sock_gai(host, port, *args, **kwargs)
            self.outbound_attempts += 1
            self.blocked_targets.append(f"{host}:{port}")
            raise OSError(f"Benchmark network block: DNS resolution for {host}:{port} is prohibited")

        socket.socket.connect = patched_connect
        socket.getaddrinfo = patched_gai

        # If aiohttp is already imported, patch its resolvers; otherwise do not import it.
        if "aiohttp" in sys.modules:
            try:
                import aiohttp.resolver
                self._orig_async_resolve = getattr(aiohttp.resolver.AsyncResolver, "resolve", None)
                self._orig_threaded_resolve = getattr(aiohttp.resolver.ThreadedResolver, "resolve", None)

                async def patched_async_resolve(resolver_self, host, port=0, family=socket.AF_INET):
                    if self._is_loopback(host):
                        return await self._orig_async_resolve(resolver_self, host, port, family)
                    self.outbound_attempts += 1
                    self.blocked_targets.append(f"{host}:{port}")
                    raise OSError(f"Benchmark network block: aiohttp DNS resolution for {host}:{port} is prohibited")

                def patched_threaded_resolve(resolver_self, host, port=0, family=socket.AF_INET):
                    if self._is_loopback(host):
                        return self._orig_threaded_resolve(resolver_self, host, port, family)
                    self.outbound_attempts += 1
                    self.blocked_targets.append(f"{host}:{port}")
                    raise OSError(f"Benchmark network block: aiohttp threaded resolution for {host}:{port} is prohibited")

                if self._orig_async_resolve:
                    aiohttp.resolver.AsyncResolver.resolve = patched_async_resolve
                if self._orig_threaded_resolve:
                    aiohttp.resolver.ThreadedResolver.resolve = patched_threaded_resolve
            except Exception:
                pass

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        socket.socket.connect = self._orig_sock_connect
        socket.getaddrinfo = self._orig_sock_gai
        if "aiohttp" in sys.modules:
            try:
                import aiohttp.resolver
                if self._orig_async_resolve:
                    aiohttp.resolver.AsyncResolver.resolve = self._orig_async_resolve
                if self._orig_threaded_resolve:
                    aiohttp.resolver.ThreadedResolver.resolve = self._orig_threaded_resolve
            except Exception:
                pass
        self.active = False


def write_network_audit(interceptor: NetworkInterceptor, audit_file_path: Optional[Path | str] = None) -> None:
    """Write structured network audit to disk."""
    if audit_file_path is None:
        runtime_root = os.getenv("BTC_RUNTIME_ROOT")
        if not runtime_root:
            return
        audit_file_path = Path(runtime_root) / "logs" / "network_audit.json"
    target = Path(audit_file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(
            {
                "network_interceptor_active": True,
                "outbound_network_attempts": interceptor.outbound_attempts,
                "blocked_targets": interceptor.blocked_targets,
            },
            f,
            indent=2,
        )

