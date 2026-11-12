"""
neural_trading/n1/acquisition.py

Independent raw-data acquisition for N1 from the official Binance public data
archive (https://data.binance.vision). Every payload is verified against the
SHA-256 `.CHECKSUM` file Binance publishes next to it. Nothing is normalised
here: raw zip payloads are stored byte-for-byte and described in a manifest.

Hard boundary: no period after 2025-12-31 is ever requested (2026 is burned).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional

import requests
from requests.adapters import HTTPAdapter

ARCHIVE_BASE = "https://data.binance.vision/data"
HARD_END = dt.date(2025, 12, 31)  # burned-holdout boundary; never exceeded
DATASET_VERSION = "n1-acq-v1"

_TLS = threading.local()


def _session() -> requests.Session:
    s = getattr(_TLS, "session", None)
    if s is None:
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _TLS.session = s
    return s


@dataclass
class RawFileRecord:
    source_identity: str
    dataset: str
    symbol: str
    period: str
    official_download_location: str
    published_checksum: Optional[str]
    raw_payload_hash: Optional[str]
    checksum_verified: bool
    bytes: int
    ingestion_time: str
    local_path: str
    status: str  # OK | MISSING_404 | CHECKSUM_MISMATCH | ERROR
    error: Optional[str] = None
    dataset_version: str = DATASET_VERSION


def _get(url: str, retries: int = 3, timeout: int = 45) -> Optional[bytes]:
    sess = _session()
    for attempt in range(retries):
        try:
            r = sess.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt == retries - 1:
                raise
        time.sleep(1.0 * (attempt + 1))
    return None


def fetch_verified(url: str, dest: Path, source_identity: str, dataset: str,
                   symbol: str, period: str) -> RawFileRecord:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rec = RawFileRecord(source_identity, dataset, symbol, period, url, None, None,
                        False, 0, now, str(dest), "ERROR")
    try:
        if dest.exists() and dest.with_suffix(dest.suffix + ".sha256").exists():
            payload = dest.read_bytes()
            published = dest.with_suffix(dest.suffix + ".sha256").read_text().strip()
        else:
            payload = _get(url)
            if payload is None:
                rec.status = "MISSING_404"
                return rec
            chk = _get(url + ".CHECKSUM")
            published = chk.decode("ascii").split()[0].lower() if chk else None
        digest = hashlib.sha256(payload).hexdigest()
        rec.raw_payload_hash = digest
        rec.published_checksum = published
        rec.bytes = len(payload)
        rec.checksum_verified = bool(published) and published == digest
        if not rec.checksum_verified:
            rec.status = "CHECKSUM_MISMATCH" if published else "NO_PUBLISHED_CHECKSUM"
            return rec
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(payload)
            dest.with_suffix(dest.suffix + ".sha256").write_text(published)
        rec.status = "OK"
    except Exception as e:  # pragma: no cover - network failure path
        rec.error = repr(e)
    return rec


def month_range(start: dt.date, end: dt.date) -> Iterable[str]:
    end = min(end, HARD_END)
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def day_range(start: dt.date, end: dt.date) -> Iterable[str]:
    end = min(end, HARD_END)
    d = start
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def spot_kline_jobs(symbol: str, first_month: str, raw_root: Path):
    y, m = map(int, first_month.split("-"))
    for ym in month_range(dt.date(y, m, 1), HARD_END):
        url = f"{ARCHIVE_BASE}/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{ym}.zip"
        dest = raw_root / "binance_spot_klines_1h" / symbol / f"{symbol}-1h-{ym}.zip"
        yield (url, dest, "binance_vision_spot_monthly_klines", "spot_klines_1h", symbol, ym)


def um_bookdepth_jobs(symbol: str, start: dt.date, raw_root: Path):
    for d in day_range(start, HARD_END):
        url = f"{ARCHIVE_BASE}/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{d}.zip"
        dest = raw_root / "binance_um_bookdepth" / symbol / f"{symbol}-bookDepth-{d}.zip"
        yield (url, dest, "binance_vision_um_daily_bookDepth", "um_bookdepth", symbol, d)


def run_jobs(jobs: List[tuple], workers: int = 8, progress_every: int = 200) -> List[RawFileRecord]:
    out: List[RawFileRecord] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetch_verified, *j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            out.append(f.result())
            if i % progress_every == 0:
                print(f"  {i}/{len(jobs)} done", flush=True)
    return sorted(out, key=lambda r: (r.dataset, r.symbol, r.period))


def write_manifest(records: List[RawFileRecord], path: Path, extra: dict) -> dict:
    summary = {}
    for r in records:
        k = f"{r.dataset}:{r.symbol}"
        s = summary.setdefault(k, {"files": 0, "ok": 0, "missing_404": [], "bad": [], "bytes": 0,
                                   "first_period": None, "last_period": None})
        s["files"] += 1
        s["bytes"] += r.bytes
        if r.status == "OK":
            s["ok"] += 1
            s["first_period"] = s["first_period"] or r.period
            s["last_period"] = r.period
        elif r.status == "MISSING_404":
            s["missing_404"].append(r.period)
        else:
            s["bad"].append({"period": r.period, "status": r.status, "error": r.error})
    manifest = {
        "dataset_version": DATASET_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hard_end_boundary": HARD_END.isoformat(),
        **extra,
        "summary": summary,
        "files": [asdict(r) for r in records],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1))
    return manifest
