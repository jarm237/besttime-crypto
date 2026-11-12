"""Standalone, append-only, replayable public market-data recorder for N1.6.

Design rules (see docs/research/NEURAL_N1_6_FORWARD_CARRY_EVIDENCE.md, Phase B):

* Public / read-only REST endpoints only. No API keys, no order endpoints.
* Every observation stores: source, endpoint, symbol, local request-sent time, local receive time,
  exchange event / transaction time when the venue provides one, round-trip time and the raw payload.
* Spot and COIN-M snapshots are requested concurrently but are NEVER assumed to be simultaneous: each
  carries its own timestamps and the analysis layer measures cross-source skew explicitly.
* On any failure an explicit `fetch_error` record is appended. Nothing is forward-filled or
  synthesised. Stale sources are flagged in the health state.
* Control files: `data/neural_n1_6/control/PAUSE` pauses sampling (heartbeats continue),
  `data/neural_n1_6/control/STOP` requests a graceful stop. Restarts start a new `session_id` and
  append to the same daily files, so the raw store is resumable.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from neural_trading.n1_6.config import (
    COINBASE_USDT_USD,
    CONTROL_DIR,
    DAPI_BASE,
    KRAKEN_TICKER,
    MANIFEST_DIR,
    PAIR_TO_SPOT,
    RAW_DIR,
    SPOT_BASE,
    STATE_DIR,
    RecorderConfig,
)

RECORDER_VERSION = "n1_6_recorder_v1"


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y%m%d")


class AppendOnlyStore:
    """Thread-safe append-only JSONL writer partitioned by UTC day and stream."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self.counts: Dict[str, int] = {}

    def append(self, stream: str, record: Dict[str, Any]) -> None:
        day = utc_day(record.get("recv_ms") or now_ms())
        path = self.root / day / f"{stream}.jsonl"
        line = json.dumps(record, separators=(",", ":"), default=str)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self.counts[stream] = self.counts.get(stream, 0) + 1


class ForwardRecorder:
    def __init__(self, cfg: Optional[RecorderConfig] = None, raw_dir: Path = RAW_DIR) -> None:
        self.cfg = cfg or RecorderConfig()
        self.store = AppendOnlyStore(raw_dir)
        self.session_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "besttime-crypto-n1_6-research-recorder/1 (read-only)"})
        self.pool = ThreadPoolExecutor(max_workers=self.cfg.max_workers)
        self.obs_seq = 0
        self._seq_lock = threading.Lock()
        self.universe: List[Dict[str, Any]] = []  # active quarterly contracts
        self.spot_symbols: List[str] = []
        self.last_good_recv: Dict[str, int] = {}
        self.consecutive_errors: Dict[str, int] = {}
        self.last_universe_ms = 0
        self.last_slow_ms = 0
        self.last_signal_hour_ms = 0
        self.started_ms = now_ms()
        self.paused = False

    # ------------------------------------------------------------------ helpers
    def _next_obs_id(self) -> str:
        with self._seq_lock:
            self.obs_seq += 1
            return f"{self.session_id}:{self.obs_seq}"

    def _get(
        self,
        stream: str,
        source: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        event_ms_fn=None,
        transact_ms_fn=None,
    ) -> Optional[Any]:
        sent = now_ms()
        try:
            resp = self.http.get(url, params=params, timeout=self.cfg.http_timeout_s)
            recv = now_ms()
            status = resp.status_code
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {resp.text[:300]}")
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never synthesised
            recv = now_ms()
            self.consecutive_errors[stream] = self.consecutive_errors.get(stream, 0) + 1
            self.store.append(
                "fetch_errors",
                {
                    "obs_id": self._next_obs_id(),
                    "session_id": self.session_id,
                    "stream": stream,
                    "source": source,
                    "endpoint": url,
                    "params": params,
                    "symbol": symbol,
                    "req_sent_ms": sent,
                    "recv_ms": recv,
                    "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                },
            )
            return None
        event_ms = None
        transact_ms = None
        try:
            event_ms = event_ms_fn(payload) if event_ms_fn else None
            transact_ms = transact_ms_fn(payload) if transact_ms_fn else None
        except Exception:  # noqa: BLE001
            pass
        self.consecutive_errors[stream] = 0
        self.last_good_recv[stream] = recv
        self.store.append(
            stream,
            {
                "obs_id": self._next_obs_id(),
                "session_id": self.session_id,
                "stream": stream,
                "source": source,
                "endpoint": url,
                "params": params,
                "symbol": symbol,
                "req_sent_ms": sent,
                "recv_ms": recv,
                "rtt_ms": recv - sent,
                "event_ms": event_ms,
                "transact_ms": transact_ms,
                # raw local age; clock-offset correction is applied at analysis time from the `clock` stream
                "raw_quote_age_ms": (recv - (transact_ms or event_ms)) if (transact_ms or event_ms) else None,
                "payload": payload,
            },
        )
        return payload

    # ------------------------------------------------------------------ universe
    def refresh_universe(self) -> None:
        info = self._get("cm_exchange_info", "binance_dapi", f"{DAPI_BASE}/dapi/v1/exchangeInfo",
                         event_ms_fn=lambda p: p.get("serverTime"))
        spot_info = self._get(
            "spot_exchange_info",
            "binance_spot",
            f"{SPOT_BASE}/api/v3/exchangeInfo",
            params={"symbols": json.dumps(sorted(PAIR_TO_SPOT.values()), separators=(",", ":"))},
            event_ms_fn=lambda p: p.get("serverTime"),
        )
        if info is not None:
            uni: List[Dict[str, Any]] = []
            for s in info.get("symbols", []):
                if s.get("pair") not in self.cfg.pairs:
                    continue
                if s.get("contractType") not in ("CURRENT_QUARTER", "NEXT_QUARTER"):
                    continue
                uni.append(
                    {
                        "symbol": s["symbol"],
                        "pair": s["pair"],
                        "contract_type": s.get("contractType"),
                        "contract_status": s.get("contractStatus"),
                        "delivery_ms": int(s.get("deliveryDate", 0)),
                        "onboard_ms": int(s.get("onboardDate", 0)),
                        "contract_size_usd": float(s.get("contractSize", 0)),
                    }
                )
            if uni:
                self.universe = sorted(uni, key=lambda r: (r["pair"], r["delivery_ms"]))
        if spot_info is not None:
            self.spot_symbols = [s["symbol"] for s in spot_info.get("symbols", []) if s.get("status") == "TRADING"]
        elif not self.spot_symbols:
            self.spot_symbols = sorted(PAIR_TO_SPOT.values())
        self.last_universe_ms = now_ms()
        self.store.append(
            "recorder_events",
            {
                "session_id": self.session_id,
                "recv_ms": now_ms(),
                "event": "universe_refresh",
                "cm_contracts": self.universe,
                "spot_symbols": self.spot_symbols,
            },
        )

    # ------------------------------------------------------------------ cycles
    def book_cycle(self) -> None:
        jobs = []
        for sym in self.spot_symbols:
            jobs.append(
                self.pool.submit(
                    self._get, "spot_depth", "binance_spot", f"{SPOT_BASE}/api/v3/depth",
                    {"symbol": sym, "limit": self.cfg.depth_limit}, sym,
                )
            )
        for c in self.universe:
            if c["contract_status"] != "TRADING":
                continue
            jobs.append(
                self.pool.submit(
                    self._get, "cm_depth", "binance_dapi", f"{DAPI_BASE}/dapi/v1/depth",
                    {"symbol": c["symbol"], "limit": self.cfg.depth_limit}, c["symbol"],
                    lambda p: p.get("E"), lambda p: p.get("T"),
                )
            )
        jobs.append(
            self.pool.submit(
                self._get, "cm_premium_index", "binance_dapi", f"{DAPI_BASE}/dapi/v1/premiumIndex",
                None, None, lambda p: max(int(r.get("time", 0)) for r in p) if p else None,
            )
        )
        for j in jobs:
            try:
                j.result(timeout=self.cfg.http_timeout_s * 2)
            except Exception:  # noqa: BLE001
                pass

    def slow_cycle(self) -> None:
        def _cb_time(p: Dict[str, Any]) -> Optional[int]:
            t = p.get("time")
            return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000) if t else None

        cb = self._get("usdt_usd", "coinbase_exchange", f"{COINBASE_USDT_USD}/ticker", event_ms_fn=_cb_time)
        if cb is None:
            self._get("usdt_usd_fallback", "kraken", KRAKEN_TICKER)
        self._get("clock", "binance_spot", f"{SPOT_BASE}/api/v3/time", event_ms_fn=lambda p: p.get("serverTime"))
        self._get("clock", "binance_dapi", f"{DAPI_BASE}/dapi/v1/time", event_ms_fn=lambda p: p.get("serverTime"))
        self.last_slow_ms = now_ms()

    def signal_inputs_cycle(self, hour_close_ms: int) -> None:
        """Hourly snapshot of the closed 1h bars required by the frozen H-1 signal (basis_ma24, yield_ma24).

        Earlier bars are needed only as causal moving-average inputs; opportunities are only counted at
        hour closes that occur while the recorder is running (no prospective backfill)."""
        start_ms = hour_close_ms - 30 * 3_600_000
        jobs = []
        for c in self.universe:
            if c["contract_type"] != "CURRENT_QUARTER":
                continue
            jobs.append(self.pool.submit(
                self._get, "signal_cm_klines", "binance_dapi", f"{DAPI_BASE}/dapi/v1/klines",
                {"symbol": c["symbol"], "interval": "1h", "startTime": start_ms, "endTime": hour_close_ms - 1},
                c["symbol"],
            ))
        for sym in self.spot_symbols:
            jobs.append(self.pool.submit(
                self._get, "signal_spot_klines", "binance_spot", f"{SPOT_BASE}/api/v3/klines",
                {"symbol": sym, "interval": "1h", "startTime": start_ms, "endTime": hour_close_ms - 1},
                sym,
            ))
        jobs.append(self.pool.submit(
            self._get, "signal_usdt_usd_candles", "coinbase_exchange", f"{COINBASE_USDT_USD}/candles",
            {"granularity": 3600,
             "start": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
             "end": datetime.fromtimestamp(hour_close_ms / 1000, tz=timezone.utc).isoformat()},
            "USDT-USD",
        ))
        for j in jobs:
            try:
                j.result(timeout=self.cfg.http_timeout_s * 2)
            except Exception:  # noqa: BLE001
                pass
        self.store.append("recorder_events", {"session_id": self.session_id, "recv_ms": now_ms(),
                                              "event": "signal_inputs_captured", "hour_close_ms": hour_close_ms})

    # ------------------------------------------------------------------ health
    def write_health(self) -> None:
        t = now_ms()
        streams = {}
        for s, last in self.last_good_recv.items():
            age_s = (t - last) / 1000.0
            limit = self.cfg.stale_after_s if s in ("spot_depth", "cm_depth", "cm_premium_index") else 3 * self.cfg.slow_interval_s
            streams[s] = {
                "last_good_recv_ms": last,
                "age_s": round(age_s, 1),
                "status": "STALE" if age_s > limit else "OK",
                "consecutive_errors": self.consecutive_errors.get(s, 0),
            }
        state = {
            "recorder_version": RECORDER_VERSION,
            "session_id": self.session_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_ms": self.started_ms,
            "updated_ms": t,
            "paused": self.paused,
            "universe_size": len(self.universe),
            "record_counts": dict(self.store.counts),
            "streams": streams,
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_DIR / "recorder_status.json.tmp"
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_DIR / "recorder_status.json")
        stale = [s for s, v in streams.items() if v["status"] == "STALE"]
        if stale:
            self.store.append("source_health", {"session_id": self.session_id, "recv_ms": t, "stale_streams": stale})

    def write_session_manifest(self, status: str) -> None:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        path = MANIFEST_DIR / f"session_{self.session_id}.json"
        path.write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "recorder_version": RECORDER_VERSION,
                    "status": status,
                    "started_ms": self.started_ms,
                    "ended_ms": now_ms(),
                    "config": self.cfg.__dict__,
                    "record_counts": dict(self.store.counts),
                    "universe": self.universe,
                    "spot_symbols": self.spot_symbols,
                    "endpoints": {
                        "spot_depth": f"{SPOT_BASE}/api/v3/depth",
                        "cm_depth": f"{DAPI_BASE}/dapi/v1/depth",
                        "cm_premium_index": f"{DAPI_BASE}/dapi/v1/premiumIndex",
                        "cm_exchange_info": f"{DAPI_BASE}/dapi/v1/exchangeInfo",
                        "spot_exchange_info": f"{SPOT_BASE}/api/v3/exchangeInfo",
                        "usdt_usd": f"{COINBASE_USDT_USD}/ticker",
                        "usdt_usd_fallback": KRAKEN_TICKER,
                        "clock": [f"{SPOT_BASE}/api/v3/time", f"{DAPI_BASE}/dapi/v1/time"],
                        "signal_klines": [f"{DAPI_BASE}/dapi/v1/klines", f"{SPOT_BASE}/api/v3/klines",
                                          f"{COINBASE_USDT_USD}/candles"],
                    },
                    "order_endpoints_used": [],
                    "api_keys_used": False,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ main loop
    def run(self, duration_s: Optional[float] = None) -> str:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        self.store.append("recorder_events", {"session_id": self.session_id, "recv_ms": now_ms(), "event": "session_start",
                                              "pid": os.getpid(), "config": self.cfg.__dict__})
        self.write_session_manifest("RUNNING")
        status = "COMPLETED"
        try:
            self.refresh_universe()
            self.slow_cycle()
            while True:
                t0 = now_ms()
                if (CONTROL_DIR / "STOP").exists():
                    status = "STOPPED_BY_CONTROL_FILE"
                    break
                if duration_s is not None and (t0 - self.started_ms) / 1000.0 >= duration_s:
                    break
                paused_now = (CONTROL_DIR / "PAUSE").exists()
                if paused_now != self.paused:
                    self.paused = paused_now
                    self.store.append("recorder_events", {"session_id": self.session_id, "recv_ms": t0,
                                                          "event": "paused" if paused_now else "resumed"})
                if not self.paused:
                    try:
                        if t0 - self.last_universe_ms >= self.cfg.universe_refresh_s * 1000:
                            self.refresh_universe()
                        if t0 - self.last_slow_ms >= self.cfg.slow_interval_s * 1000:
                            self.slow_cycle()
                        hour_close = (t0 // 3_600_000) * 3_600_000
                        if (
                            hour_close > self.last_signal_hour_ms
                            and t0 - hour_close >= self.cfg.signal_delay_after_hour_s * 1000
                            and hour_close > self.started_ms  # only hours closing after this session started
                        ):
                            self.signal_inputs_cycle(hour_close)
                            self.last_signal_hour_ms = hour_close
                        self.book_cycle()
                    except Exception as exc:  # noqa: BLE001
                        self.store.append("recorder_events", {"session_id": self.session_id, "recv_ms": now_ms(),
                                                              "event": "cycle_exception",
                                                              "error": f"{type(exc).__name__}: {exc}",
                                                              "trace": traceback.format_exc()[-2000:]})
                        time.sleep(2.0)
                self.write_health()
                elapsed = (now_ms() - t0) / 1000.0
                time.sleep(max(0.5, self.cfg.book_interval_s - elapsed))
        except KeyboardInterrupt:
            status = "INTERRUPTED"
        finally:
            self.store.append("recorder_events", {"session_id": self.session_id, "recv_ms": now_ms(), "event": "session_end",
                                                  "status": status, "record_counts": dict(self.store.counts)})
            self.write_session_manifest(status)
            self.pool.shutdown(wait=False)
        return status


def supervise(duration_s: Optional[float], max_restarts: int = 50) -> None:
    """Restart the recorder in a fresh child process after crashes (exponential back-off)."""
    import subprocess

    deadline = time.time() + duration_s if duration_s else None
    restarts = 0
    backoff = 5.0
    while True:
        if (CONTROL_DIR / "STOP").exists():
            return
        remaining = (deadline - time.time()) if deadline else None
        if remaining is not None and remaining <= 5:
            return
        cmd = [sys.executable, "-m", "neural_trading.n1_6.recorder"]
        if remaining is not None:
            cmd += ["--duration-s", str(int(remaining))]
        rc = subprocess.call(cmd)
        if rc == 0:
            return
        restarts += 1
        if restarts > max_restarts:
            return
        time.sleep(backoff)
        backoff = min(backoff * 2, 300.0)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="N1.6 read-only forward COIN-M carry market-data recorder")
    ap.add_argument("--duration-s", type=float, default=None)
    ap.add_argument("--supervise", action="store_true")
    a = ap.parse_args()
    if a.supervise:
        supervise(a.duration_s)
    else:
        sys.exit(0 if ForwardRecorder().run(a.duration_s) in ("COMPLETED", "STOPPED_BY_CONTROL_FILE", "INTERRUPTED") else 1)
