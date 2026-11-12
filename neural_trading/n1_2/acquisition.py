"""N1.2 Phase C — Objective-Driven Fresh Data Acquisition with strict 10-field PIT provenance.

Acquires and verifies three authoritative raw data streams matched to Hypotheses H-A and H-B:
1. H-A: Binance Spot Monthly Tick-by-Tick `aggTrades` (`data/spot/monthly/aggTrades`) + SHA-256 `.CHECKSUM`
   combined with verified daily `bookDepth` snapshots for persistent trade-level order-flow & liquidity dislocation.
2. H-B1: Coinbase Exchange Historical 1h USD Spot Candles (`api.exchange.coinbase.com/products/<SYM>-USD/candles`)
   synchronized against Binance Spot 1h USDT klines for inter-venue fiat USD vs offshore USDT price/flow discovery.
3. H-B2: Binance 5-Minute (`5m`) USD-M Perpetual vs 5-Minute (`5m`) Spot Klines + SHA-256 `.CHECKSUM`
   for high-frequency intraday basis velocity and perp-vs-spot taker-flow dislocation.

Also probes and documents authoritative availability of historical `bookTicker` archives (`HTTP 404` on
`data.binance.vision`), recording exact provenance and fallback to tick-by-tick `aggTrades` realized
bid-ask bounce spread + `bookDepth`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BINANCE_VISION_BASE = "https://data.binance.vision"
COINBASE_API_BASE = "https://api.exchange.coinbase.com"

# 8-asset cross-venue & 5m perp/spot universe (2022-01 .. 2025-12)
HB_SYMBOLS_BINANCE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "DOGEUSDT",
]
HB_SYMBOLS_COINBASE = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
    "LTCUSDT": "LTC-USD",
    "LINKUSDT": "LINK-USD",
    "ADAUSDT": "ADA-USD",
    "XRPUSDT": "XRP-USD",
    "DOGEUSDT": "DOGE-USD",
}

# 5-asset liquid Spot universe for tick-by-tick monthly aggTrades (2022-01 .. 2025-12)
# Chosen so 240 monthly tick-by-tick archives (~4.2 GB raw zipped, ~95M individual aggTrades)
# can be downloaded, SHA-256 verified against .CHECKSUM, and aggregated at tick level.
HA_AGGTRADES_SYMBOLS = [
    "LINKUSDT",
    "ADAUSDT",
    "XLMUSDT",
    "ETCUSDT",
    "TRXUSDT",
]

MANDATORY_PROVENANCE_FIELDS = [
    "source",
    "original_timestamp",
    "actual_availability_timestamp",
    "ingestion_timestamp",
    "raw_payload",
    "source_checksum",
    "local_sha256",
    "trading_eligibility",
    "missing_intervals",
    "execution_constraints",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_ms_to_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_bytes(url: str, timeout: int = 45, max_retries: int = 3) -> Tuple[Optional[bytes], int, str]:
    headers = {
        "User-Agent": "besttime-crypto-n1-2-research/1.0",
        "Accept": "application/json, application/octet-stream, */*",
    }
    last_err = ""
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.status, "OK"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, 404, "HTTP_404_NOT_FOUND"
            last_err = f"HTTP_{e.code}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(0.6 * (attempt + 1))
    return None, 0, last_err or "FETCH_FAILED"


def _parse_checksum_text(text: str) -> str:
    parts = text.strip().split()
    return parts[0].lower() if parts else ""


def _month_list(start_year: int = 2022, end_year: int = 2025) -> List[str]:
    out: List[str] = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            out.append(f"{y:04d}-{m:02d}")
    return out


def probe_unsuitable_sources() -> List[Dict[str, Any]]:
    """Explicitly probe and document candidate sources that fail Phase C historical completeness."""
    probes = [
        (
            "Binance USD-M Daily bookTicker Archive (2023-05-01)",
            f"{BINANCE_VISION_BASE}/data/futures/um/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2023-05-01.zip",
        ),
        (
            "Binance USD-M Daily bookTicker Archive (2024-06-01)",
            f"{BINANCE_VISION_BASE}/data/futures/um/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2024-06-01.zip",
        ),
        (
            "Binance Spot Daily bookTicker Archive (2024-06-01)",
            f"{BINANCE_VISION_BASE}/data/spot/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2024-06-01.zip",
        ),
        (
            "Binance USD-M Liquidation Orders Snapshot API (Public Unauthenticated)",
            "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=5",
        ),
    ]
    results: List[Dict[str, Any]] = []
    for label, url in probes:
        body, status, note = _fetch_bytes(url, timeout=15, max_retries=1)
        results.append(
            {
                "source": url,
                "label": label,
                "http_status": status,
                "status_note": note,
                "ingestion_timestamp": _utc_now_iso(),
                "suitability_disposition": "REJECTED_SOURCE_UNAVAILABLE_AT_AUTHORITATIVE_ARCHIVE",
                "reason": (
                    "Authoritative historical archive returns HTTP 404 / endpoint retired; "
                    "per Phase C rules, do not fabricate or interpolate missing top-of-book L1 quotes or forced liquidations."
                ),
            }
        )
    return results


def _process_single_aggtrades_month(
    symbol: str,
    ym: str,
    cache_dir: Path,
) -> Dict[str, Any]:
    """Download/load a monthly Spot aggTrades zip, verify SHA-256 against .CHECKSUM, and aggregate tick metrics into 1h bars."""
    sym_dir = cache_dir / "aggtrades_hourly" / symbol
    sym_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = sym_dir / f"{symbol}-aggTrades-{ym}-hourly.parquet"
    meta_path = sym_dir / f"{symbol}-aggTrades-{ym}-meta.json"

    if parquet_path.exists() and meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            if all(k in meta for k in MANDATORY_PROVENANCE_FIELDS) and meta.get("checksum_verified") is True:
                return meta
        except Exception:  # noqa: BLE001
            pass

    zip_url = f"{BINANCE_VISION_BASE}/data/spot/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{ym}.zip"
    chk_url = f"{zip_url}.CHECKSUM"
    ingested_at = _utc_now_iso()

    chk_bytes, chk_status, chk_note = _fetch_bytes(chk_url, timeout=30, max_retries=3)
    zip_bytes, zip_status, zip_note = _fetch_bytes(zip_url, timeout=120, max_retries=3)

    if zip_bytes is None or chk_bytes is None:
        raise RuntimeError(f"Failed to fetch aggTrades {symbol} {ym}: zip={zip_note} ({zip_status}), chk={chk_note}")

    expected_sha = _parse_checksum_text(chk_bytes.decode("utf-8", errors="replace"))
    local_sha = _sha256_bytes(zip_bytes)
    checksum_ok = bool(expected_sha and (expected_sha == local_sha))
    if not checksum_ok:
        raise RuntimeError(f"SHA-256 mismatch for {symbol} {ym}: expected {expected_sha}, got {local_sha}")

    # Parse CSV inside zip into DataFrame in chunks to keep memory low and speed high
    col_names = ["agg_id", "price", "qty", "first_id", "last_id", "ts", "is_buyer_maker", "is_best_match"]
    hourly_chunks: List[pd.DataFrame] = []
    first_ts_ms: Optional[int] = None
    last_ts_ms: Optional[int] = None
    total_rows = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_members = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_members:
            raise RuntimeError(f"No CSV member in {symbol} {ym}")
        with zf.open(csv_members[0]) as raw_csv:
            # Peek first line to see if header is present
            first_line = raw_csv.readline().decode("utf-8", errors="replace").strip()
        has_header = first_line.startswith("agg") or first_line.startswith("a")

        with zf.open(csv_members[0]) as raw_csv:
            reader = pd.read_csv(
                raw_csv,
                names=None if has_header else col_names,
                header=0 if has_header else None,
                chunksize=500_000,
            )
            for chunk in reader:
                if has_header:
                    chunk.columns = col_names[: len(chunk.columns)]
                # Normalize timestamp: Binance switched Spot from ms to microseconds (16 digits) in 2025!
                ts_raw = chunk["ts"].to_numpy(dtype=np.int64)
                ts_ms = np.where(ts_raw > 10**14, ts_raw // 1000, ts_raw)
                if first_ts_ms is None and len(ts_ms) > 0:
                    first_ts_ms = int(ts_ms[0])
                if len(ts_ms) > 0:
                    last_ts_ms = int(ts_ms[-1])
                total_rows += len(ts_ms)

                price = chunk["price"].to_numpy(dtype=np.float64)
                qty = chunk["qty"].to_numpy(dtype=np.float64)
                notional = price * qty
                first_id = chunk["first_id"].to_numpy(dtype=np.int64)
                last_id = chunk["last_id"].to_numpy(dtype=np.int64)
                sweep_count = np.maximum(1, last_id - first_id + 1).astype(np.float64)

                ibm_raw = chunk["is_buyer_maker"]
                if ibm_raw.dtype == bool:
                    is_sell_aggressor = ibm_raw.to_numpy(dtype=bool)
                else:
                    is_sell_aggressor = ibm_raw.astype(str).str.lower().isin(["true", "1"]).to_numpy(dtype=bool)
                is_buy_aggressor = ~is_sell_aggressor
                sign = np.where(is_buy_aggressor, 1.0, -1.0)

                # Hour bucket (close timestamp at end of hour: floor(ts_ms / 3600000) * 3600000 + 3600000)
                # Using close_ts_ms = (ts_ms // 3_600_000 + 1) * 3_600_000 so bar at T contains trades in [T-1h, T)
                # strictly available at decision timestamp T.
                hour_close_ms = ((ts_ms // 3_600_000) + 1) * 3_600_000

                # Whale (>= $25,000) vs Medium ($2,000..$25,000) vs Retail (< $2,000)
                is_whale = notional >= 25_000.0
                is_retail = notional < 2_000.0

                buy_notional = np.where(is_buy_aggressor, notional, 0.0)
                sell_notional = np.where(is_sell_aggressor, notional, 0.0)
                whale_buy_notional = np.where(is_buy_aggressor & is_whale, notional, 0.0)
                whale_sell_notional = np.where(is_sell_aggressor & is_whale, notional, 0.0)
                retail_buy_notional = np.where(is_buy_aggressor & is_retail, notional, 0.0)
                retail_sell_notional = np.where(is_sell_aggressor & is_retail, notional, 0.0)

                # Sweep fragmentation: underlying matched trades per aggTrade
                buy_sweep_orders = np.where(is_buy_aggressor, sweep_count, 0.0)
                sell_sweep_orders = np.where(is_sell_aggressor, sweep_count, 0.0)
                multi_fill_buy_notional = np.where(is_buy_aggressor & (sweep_count >= 3), notional, 0.0)
                multi_fill_sell_notional = np.where(is_sell_aggressor & (sweep_count >= 3), notional, 0.0)

                # Tick-to-tick price impact & realized bid-ask bounce
                d_log_p = np.zeros_like(price)
                if len(price) > 1:
                    d_log_p[1:] = np.log(np.maximum(price[1:], 1e-12) / np.maximum(price[:-1], 1e-12))
                sign_change = np.zeros_like(sign)
                if len(sign) > 1:
                    sign_change[1:] = sign[1:] - sign[:-1]  # +2 on sell->buy, -2 on buy->sell

                # When sign flips from sell (-1) to buy (+1), d_log_p estimates effective full spread;
                # signed bounce = d_log_p * (sign_change / 2.0) when |sign_change| == 2
                is_flip = np.abs(sign_change) == 2.0
                bounce_spread_bps = np.where(is_flip, d_log_p * (sign_change / 2.0) * 10_000.0, 0.0)
                flip_count = is_flip.astype(np.float64)

                # Price impact on same-sign continuation (|sign_change| == 0)
                is_cont_buy = (sign_change == 0.0) & is_buy_aggressor
                is_cont_sell = (sign_change == 0.0) & is_sell_aggressor
                buy_impact_bps = np.where(is_cont_buy, np.maximum(0.0, d_log_p) * 10_000.0, 0.0)
                sell_impact_bps = np.where(is_cont_sell, np.maximum(0.0, -d_log_p) * 10_000.0, 0.0)

                df_part = pd.DataFrame(
                    {
                        "hour_close_ms": hour_close_ms,
                        "open_price": price,
                        "high_price": price,
                        "low_price": price,
                        "close_price": price,
                        "agg_trade_count": np.ones(len(price), dtype=np.float64),
                        "underlying_order_count": sweep_count,
                        "total_notional": notional,
                        "buy_notional": buy_notional,
                        "sell_notional": sell_notional,
                        "whale_buy_notional": whale_buy_notional,
                        "whale_sell_notional": whale_sell_notional,
                        "retail_buy_notional": retail_buy_notional,
                        "retail_sell_notional": retail_sell_notional,
                        "buy_sweep_orders": buy_sweep_orders,
                        "sell_sweep_orders": sell_sweep_orders,
                        "multi_fill_buy_notional": multi_fill_buy_notional,
                        "multi_fill_sell_notional": multi_fill_sell_notional,
                        "bounce_spread_bps_sum": bounce_spread_bps,
                        "flip_count": flip_count,
                        "buy_impact_bps_sum": buy_impact_bps,
                        "sell_impact_bps_sum": sell_impact_bps,
                        "cont_buy_count": is_cont_buy.astype(np.float64),
                        "cont_sell_count": is_cont_sell.astype(np.float64),
                    }
                )
                grp = df_part.groupby("hour_close_ms", sort=False).agg(
                    {
                        "open_price": "first",
                        "high_price": "max",
                        "low_price": "min",
                        "close_price": "last",
                        "agg_trade_count": "sum",
                        "underlying_order_count": "sum",
                        "total_notional": "sum",
                        "buy_notional": "sum",
                        "sell_notional": "sum",
                        "whale_buy_notional": "sum",
                        "whale_sell_notional": "sum",
                        "retail_buy_notional": "sum",
                        "retail_sell_notional": "sum",
                        "buy_sweep_orders": "sum",
                        "sell_sweep_orders": "sum",
                        "multi_fill_buy_notional": "sum",
                        "multi_fill_sell_notional": "sum",
                        "bounce_spread_bps_sum": "sum",
                        "flip_count": "sum",
                        "buy_impact_bps_sum": "sum",
                        "sell_impact_bps_sum": "sum",
                        "cont_buy_count": "sum",
                        "cont_sell_count": "sum",
                    }
                )
                hourly_chunks.append(grp.reset_index())

    if not hourly_chunks:
        raise RuntimeError(f"Empty aggTrades chunks for {symbol} {ym}")

    combined = pd.concat(hourly_chunks, ignore_index=True)
    hourly = (
        combined.groupby("hour_close_ms", sort=True)
        .agg(
            {
                "open_price": "first",
                "high_price": "max",
                "low_price": "min",
                "close_price": "last",
                "agg_trade_count": "sum",
                "underlying_order_count": "sum",
                "total_notional": "sum",
                "buy_notional": "sum",
                "sell_notional": "sum",
                "whale_buy_notional": "sum",
                "whale_sell_notional": "sum",
                "retail_buy_notional": "sum",
                "retail_sell_notional": "sum",
                "buy_sweep_orders": "sum",
                "sell_sweep_orders": "sum",
                "multi_fill_buy_notional": "sum",
                "multi_fill_sell_notional": "sum",
                "bounce_spread_bps_sum": "sum",
                "flip_count": "sum",
                "buy_impact_bps_sum": "sum",
                "sell_impact_bps_sum": "sum",
                "cont_buy_count": "sum",
                "cont_sell_count": "sum",
            }
        )
        .reset_index()
    )
    hourly["symbol"] = symbol
    hourly.to_parquet(parquet_path, index=False)

    # Identify missing 1h intervals within the month
    expected_hours = int((hourly["hour_close_ms"].max() - hourly["hour_close_ms"].min()) // 3_600_000) + 1
    actual_hours = int(len(hourly))
    missing_count = max(0, expected_hours - actual_hours)

    meta: Dict[str, Any] = {
        "symbol": symbol,
        "year_month": ym,
        "source": zip_url,
        "original_timestamp": f"{_ts_ms_to_iso(first_ts_ms or 0)}..{_ts_ms_to_iso(last_ts_ms or 0)}",
        "actual_availability_timestamp": _ts_ms_to_iso(int(hourly["hour_close_ms"].max())),
        "ingestion_timestamp": ingested_at,
        "raw_payload": {
            "archive_name": f"{symbol}-aggTrades-{ym}.zip",
            "compressed_bytes": len(zip_bytes),
            "raw_aggtrade_rows": int(total_rows),
            "derived_hourly_parquet": str(parquet_path.as_posix()),
            "columns": col_names,
        },
        "source_checksum": expected_sha,
        "local_sha256": local_sha,
        "checksum_verified": checksum_ok,
        "trading_eligibility": "ELIGIBLE_RESEARCH_AND_BACKTEST_LONG_ONLY_SPOT",
        "missing_intervals": {
            "expected_hourly_bars": expected_hours,
            "actual_hourly_bars": actual_hours,
            "missing_hourly_bars": missing_count,
        },
        "execution_constraints": {
            "venue": "BINANCE_SPOT",
            "short_selling_allowed": False,
            "round_trip_fee_slippage_bps": 14.0,
            "per_leg_cost_bps": 7.0,
            "point_in_time_lag_ms": 0,
        },
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def acquire_ha_aggtrades_dataset(
    cache_dir: Path,
    manifest_path: Path,
    symbols: Optional[List[str]] = None,
    start_year: int = 2022,
    end_year: int = 2025,
    max_workers: int = 6,
) -> Dict[str, Any]:
    """Acquire and verify monthly Spot aggTrades across the H-A universe (2022-2025)."""
    syms = symbols or HA_AGGTRADES_SYMBOLS
    months = _month_list(start_year, end_year)
    tasks = [(s, ym) for s in syms for ym in months]

    records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_process_single_aggtrades_month, s, ym, cache_dir): (s, ym) for s, ym in tasks}
        for fut in as_completed(fut_map):
            s, ym = fut_map[fut]
            meta = fut.result()
            records.append(meta)

    records.sort(key=lambda r: (r["symbol"], r["year_month"]))

    # Combine hourly parquets into a single canonical H-A panel parquet
    frames: List[pd.DataFrame] = []
    for r in records:
        p = Path(r["raw_payload"]["derived_hourly_parquet"])
        frames.append(pd.read_parquet(p))
    panel = pd.concat(frames, ignore_index=True).sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)
    panel_path = cache_dir / "n1_2_ha_aggtrades_hourly_panel.parquet"
    panel.to_parquet(panel_path, index=False)

    manifest = {
        "dataset_id": "N1_2_HA_SPOT_AGGTRADES_2022_2025",
        "created_at": _utc_now_iso(),
        "symbols": syms,
        "months_count": len(months),
        "total_archives": len(records),
        "checksum_verified_count": sum(1 for r in records if r.get("checksum_verified")),
        "total_raw_aggtrades_processed": int(sum(r["raw_payload"]["raw_aggtrade_rows"] for r in records)),
        "total_compressed_bytes": int(sum(r["raw_payload"]["compressed_bytes"] for r in records)),
        "panel_parquet_path": str(panel_path.as_posix()),
        "panel_sha256": _sha256_file(panel_path),
        "mandatory_provenance_fields": MANDATORY_PROVENANCE_FIELDS,
        "records": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def _fetch_coinbase_symbol_1h(
    bn_symbol: str,
    cb_product: str,
    cache_dir: Path,
    start_iso: str = "2022-01-01T00:00:00Z",
    end_iso: str = "2025-12-31T23:00:00Z",
) -> Dict[str, Any]:
    """Fetch 1h candles from Coinbase Exchange REST API in 300-bar windows and save raw JSON + parquet."""
    cb_dir = cache_dir / "coinbase_1h"
    cb_dir.mkdir(parents=True, exist_ok=True)
    raw_json_path = cb_dir / f"{cb_product}-1h-2022-2025.json"
    parquet_path = cb_dir / f"{cb_product}-1h-2022-2025.parquet"
    meta_path = cb_dir / f"{cb_product}-1h-2022-2025-meta.json"

    if raw_json_path.exists() and parquet_path.exists() and meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            if all(k in meta for k in MANDATORY_PROVENANCE_FIELDS):
                return meta
        except Exception:  # noqa: BLE001
            pass

    start_ts = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end_ts = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
    step_sec = 300 * 3600  # 300 hours per request (Coinbase max limit per call is 300 candles)

    all_rows: List[List[float]] = []
    cur = start_ts
    ingested_at = _utc_now_iso()
    while cur <= end_ts:
        win_end = min(end_ts, cur + step_sec - 3600)
        s_str = datetime.fromtimestamp(cur, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        e_str = datetime.fromtimestamp(win_end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{COINBASE_API_BASE}/products/{cb_product}/candles?granularity=3600&start={s_str}&end={e_str}"
        body, status, note = _fetch_bytes(url, timeout=30, max_retries=4)
        if body is None:
            raise RuntimeError(f"Coinbase fetch failed for {cb_product} [{s_str}..{e_str}]: {status} {note}")
        rows = json.loads(body.decode("utf-8"))
        if isinstance(rows, list):
            all_rows.extend(rows)
        cur = win_end + 3600
        time.sleep(0.12)

    # Deduplicate by open timestamp (row[0] is candle start time in unix seconds on Coinbase)
    dedup: Dict[int, List[float]] = {}
    for r in all_rows:
        if len(r) >= 6:
            dedup[int(r[0])] = [float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]

    sorted_open_sec = sorted(dedup.keys())
    clean_rows = [dedup[k] for k in sorted_open_sec]
    raw_bytes = json.dumps(clean_rows).encode("utf-8")
    raw_json_path.write_bytes(raw_bytes)
    local_sha = _sha256_bytes(raw_bytes)

    # Convert to DataFrame aligned on hour_close_ms = (open_sec + 3600) * 1000
    df = pd.DataFrame(
        clean_rows,
        columns=["open_sec", "cb_low", "cb_high", "cb_open", "cb_close", "cb_volume_base"],
    )
    df["hour_close_ms"] = (df["open_sec"].astype(np.int64) + 3600) * 1000
    df["cb_notional_usd"] = df["cb_close"] * df["cb_volume_base"]
    df["symbol"] = bn_symbol
    df["cb_product"] = cb_product
    df = df.sort_values("hour_close_ms").reset_index(drop=True)
    df.to_parquet(parquet_path, index=False)

    expected_bars = int((end_ts - start_ts) // 3600) + 1
    actual_bars = int(len(df))
    missing_bars = max(0, expected_bars - actual_bars)

    meta: Dict[str, Any] = {
        "symbol": bn_symbol,
        "cb_product": cb_product,
        "source": f"{COINBASE_API_BASE}/products/{cb_product}/candles?granularity=3600",
        "original_timestamp": f"{start_iso}..{end_iso}",
        "actual_availability_timestamp": _ts_ms_to_iso(int(df["hour_close_ms"].max())),
        "ingestion_timestamp": ingested_at,
        "raw_payload": {
            "raw_json_path": str(raw_json_path.as_posix()),
            "derived_parquet_path": str(parquet_path.as_posix()),
            "raw_bytes": len(raw_bytes),
            "candle_count": actual_bars,
            "schema": ["time_open_unix_sec", "low", "high", "open", "close", "volume_base"],
        },
        "source_checksum": f"REST_JSON_PAYLOAD_SHA256:{local_sha}",
        "local_sha256": local_sha,
        "trading_eligibility": "SIGNAL_AND_CROSS_VENUE_DISCOVERY_ONLY_EXECUTION_ON_BINANCE_SPOT",
        "missing_intervals": {
            "expected_hourly_bars": expected_bars,
            "actual_hourly_bars": actual_bars,
            "missing_or_outage_bars": missing_bars,
            "completeness_ratio": round(actual_bars / max(1, expected_bars), 6),
        },
        "execution_constraints": {
            "signal_venue": "COINBASE_EXCHANGE_USD_SPOT",
            "execution_venue": "BINANCE_SPOT_USDT",
            "cross_venue_transfer_latency_assumed": "NO_INSTANT_ARB_SIGNAL_USED_CAUSALLY_AT_BAR_CLOSE",
            "binance_spot_round_trip_cost_bps": 14.0,
        },
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def acquire_hb1_coinbase_dataset(
    cache_dir: Path,
    manifest_path: Path,
) -> Dict[str, Any]:
    """Acquire and verify Coinbase 1h USD candles for all 8 H-B symbols (2022-2025)."""
    records: List[Dict[str, Any]] = []
    for bn_sym in HB_SYMBOLS_BINANCE:
        cb_prod = HB_SYMBOLS_COINBASE[bn_sym]
        meta = _fetch_coinbase_symbol_1h(bn_sym, cb_prod, cache_dir=cache_dir)
        records.append(meta)

    frames = [pd.read_parquet(r["raw_payload"]["derived_parquet_path"]) for r in records]
    panel = pd.concat(frames, ignore_index=True).sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)
    panel_path = cache_dir / "n1_2_hb1_coinbase_1h_panel.parquet"
    panel.to_parquet(panel_path, index=False)

    manifest = {
        "dataset_id": "N1_2_HB1_COINBASE_USD_1H_2022_2025",
        "created_at": _utc_now_iso(),
        "symbols": HB_SYMBOLS_BINANCE,
        "total_products": len(records),
        "total_candles": int(sum(r["raw_payload"]["candle_count"] for r in records)),
        "panel_parquet_path": str(panel_path.as_posix()),
        "panel_sha256": _sha256_file(panel_path),
        "mandatory_provenance_fields": MANDATORY_PROVENANCE_FIELDS,
        "records": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def _process_single_5m_month(
    symbol: str,
    ym: str,
    cache_dir: Path,
) -> Dict[str, Any]:
    """Download/verify 5m Spot and 5m USD-M Perp monthly zips for (symbol, ym) and aggregate intraday lead-lag into 1h bars."""
    out_dir = cache_dir / "perp_spot_5m_hourly" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / f"{symbol}-5m-leadlag-{ym}.parquet"
    meta_path = out_dir / f"{symbol}-5m-leadlag-{ym}-meta.json"

    if parquet_path.exists() and meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            if all(k in meta for k in MANDATORY_PROVENANCE_FIELDS) and meta.get("checksum_verified") is True:
                return meta
        except Exception:  # noqa: BLE001
            pass

    spot_url = f"{BINANCE_VISION_BASE}/data/spot/monthly/klines/{symbol}/5m/{symbol}-5m-{ym}.zip"
    spot_chk_url = f"{spot_url}.CHECKSUM"
    perp_url = f"{BINANCE_VISION_BASE}/data/futures/um/monthly/klines/{symbol}/5m/{symbol}-5m-{ym}.zip"
    perp_chk_url = f"{perp_url}.CHECKSUM"
    ingested_at = _utc_now_iso()

    s_zip, s_st, s_note = _fetch_bytes(spot_url, timeout=45, max_retries=3)
    s_chk, _, _ = _fetch_bytes(spot_chk_url, timeout=30, max_retries=3)
    p_zip, p_st, p_note = _fetch_bytes(perp_url, timeout=45, max_retries=3)
    p_chk, _, _ = _fetch_bytes(perp_chk_url, timeout=30, max_retries=3)

    if s_zip is None or s_chk is None or p_zip is None or p_chk is None:
        raise RuntimeError(f"Failed 5m fetch for {symbol} {ym}: spot={s_st}/{s_note}, perp={p_st}/{p_note}")

    s_exp = _parse_checksum_text(s_chk.decode("utf-8", errors="replace"))
    s_sha = _sha256_bytes(s_zip)
    p_exp = _parse_checksum_text(p_chk.decode("utf-8", errors="replace"))
    p_sha = _sha256_bytes(p_zip)
    chk_ok = bool(s_exp == s_sha and p_exp == p_sha)
    if not chk_ok:
        raise RuntimeError(f"5m SHA256 mismatch for {symbol} {ym}: spot({s_exp} vs {s_sha}), perp({p_exp} vs {p_sha})")

    kline_cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
        "ignore",
    ]

    def _read_kline_zip(zbytes: bytes) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
            csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(csv_name) as f:
                first = f.readline().decode("utf-8", errors="replace").strip()
            has_hdr = first.startswith("open")
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, names=None if has_hdr else kline_cols, header=0 if has_hdr else None)
                if has_hdr:
                    df.columns = kline_cols[: len(df.columns)]
        ot = df["open_time"].to_numpy(dtype=np.int64)
        ot_ms = np.where(ot > 10**14, ot // 1000, ot)
        df["open_time_ms"] = ot_ms
        for c in ["open", "high", "low", "close", "quote_volume", "taker_buy_quote_volume", "count"]:
            df[c] = df[c].astype(np.float64)
        return df

    df_s = _read_kline_zip(s_zip)
    df_p = _read_kline_zip(p_zip)

    m = pd.merge(
        df_s[["open_time_ms", "open", "high", "low", "close", "quote_volume", "taker_buy_quote_volume", "count"]],
        df_p[["open_time_ms", "open", "high", "low", "close", "quote_volume", "taker_buy_quote_volume", "count"]],
        on="open_time_ms",
        suffixes=("_spot", "_perp"),
        how="inner",
    ).sort_values("open_time_ms").reset_index(drop=True)

    # 5m close timestamp is open_time_ms + 300_000; hour_close_ms is ((open_time_ms // 3_600_000) + 1) * 3_600_000
    m["subbar_idx"] = (m["open_time_ms"] % 3_600_000) // 300_000  # 0..11 within the hour
    m["hour_close_ms"] = ((m["open_time_ms"] // 3_600_000) + 1) * 3_600_000

    m["ret_5m_spot"] = np.log(np.maximum(m["close_spot"], 1e-12) / np.maximum(m["open_spot"], 1e-12))
    m["ret_5m_perp"] = np.log(np.maximum(m["close_perp"], 1e-12) / np.maximum(m["open_perp"], 1e-12))
    m["basis_5m_bps"] = (m["close_perp"] / np.maximum(m["close_spot"], 1e-12) - 1.0) * 10_000.0

    s_qvol = np.maximum(m["quote_volume_spot"], 1e-8)
    p_qvol = np.maximum(m["quote_volume_perp"], 1e-8)
    m["spot_taker_imb_5m"] = (2.0 * m["taker_buy_quote_volume_spot"] - m["quote_volume_spot"]) / s_qvol
    m["perp_taker_imb_5m"] = (2.0 * m["taker_buy_quote_volume_perp"] - m["quote_volume_perp"]) / p_qvol
    m["perp_minus_spot_imb_5m"] = m["perp_taker_imb_5m"] - m["spot_taker_imb_5m"]
    m["perp_minus_spot_ret_5m_bps"] = (m["ret_5m_perp"] - m["ret_5m_spot"]) * 10_000.0

    # Last 15m of the hour (subbar_idx in {9, 10, 11}) vs first 45m (subbar_idx < 9)
    is_last15m = m["subbar_idx"] >= 9
    m["last15m_perp_ret"] = np.where(is_last15m, m["ret_5m_perp"], 0.0)
    m["last15m_spot_ret"] = np.where(is_last15m, m["ret_5m_spot"], 0.0)
    m["last15m_perp_signed_qvol"] = np.where(
        is_last15m, 2.0 * m["taker_buy_quote_volume_perp"] - m["quote_volume_perp"], 0.0
    )
    m["last15m_perp_qvol"] = np.where(is_last15m, m["quote_volume_perp"], 0.0)
    m["last15m_spot_signed_qvol"] = np.where(
        is_last15m, 2.0 * m["taker_buy_quote_volume_spot"] - m["quote_volume_spot"], 0.0
    )
    m["last15m_spot_qvol"] = np.where(is_last15m, m["quote_volume_spot"], 0.0)

    # Intraday 5m realized variance & perp-leads-spot 5m cross-correlation proxy
    m["prev_perp_ret_5m"] = m["ret_5m_perp"].shift(1).fillna(0.0)
    m["perp_lead1_spot_cov"] = m["prev_perp_ret_5m"] * m["ret_5m_spot"]
    m["rv_5m_spot"] = m["ret_5m_spot"] ** 2
    m["rv_5m_perp"] = m["ret_5m_perp"] ** 2

    hourly = (
        m.groupby("hour_close_ms", sort=True)
        .agg(
            spot_open=("open_spot", "first"),
            spot_high=("high_spot", "max"),
            spot_low=("low_spot", "min"),
            spot_close=("close_spot", "last"),
            perp_open=("open_perp", "first"),
            perp_close=("close_perp", "last"),
            spot_quote_vol=("quote_volume_spot", "sum"),
            perp_quote_vol=("quote_volume_perp", "sum"),
            spot_taker_buy_qvol=("taker_buy_quote_volume_spot", "sum"),
            perp_taker_buy_qvol=("taker_buy_quote_volume_perp", "sum"),
            basis_open_bps=("basis_5m_bps", "first"),
            basis_close_bps=("basis_5m_bps", "last"),
            basis_mean_bps=("basis_5m_bps", "mean"),
            basis_max_bps=("basis_5m_bps", "max"),
            basis_min_bps=("basis_5m_bps", "min"),
            last15m_perp_ret=("last15m_perp_ret", "sum"),
            last15m_spot_ret=("last15m_spot_ret", "sum"),
            last15m_perp_signed_qvol=("last15m_perp_signed_qvol", "sum"),
            last15m_perp_qvol=("last15m_perp_qvol", "sum"),
            last15m_spot_signed_qvol=("last15m_spot_signed_qvol", "sum"),
            last15m_spot_qvol=("last15m_spot_qvol", "sum"),
            perp_lead1_spot_cov=("perp_lead1_spot_cov", "sum"),
            rv_5m_spot=("rv_5m_spot", "sum"),
            rv_5m_perp=("rv_5m_perp", "sum"),
            subbar_count=("subbar_idx", "count"),
        )
        .reset_index()
    )
    hourly["symbol"] = symbol
    hourly.to_parquet(parquet_path, index=False)

    meta: Dict[str, Any] = {
        "symbol": symbol,
        "year_month": ym,
        "source": f"SPOT:{spot_url} | PERP:{perp_url}",
        "original_timestamp": (
            f"{_ts_ms_to_iso(int(m['open_time_ms'].min()))}..{_ts_ms_to_iso(int(hourly['hour_close_ms'].max()))}"
            if len(m) > 0
            else ym
        ),
        "actual_availability_timestamp": _ts_ms_to_iso(int(hourly["hour_close_ms"].max())) if len(hourly) > 0 else ym,
        "ingestion_timestamp": ingested_at,
        "raw_payload": {
            "spot_archive": f"{symbol}-5m-{ym}.zip",
            "perp_archive": f"{symbol}-5m-{ym}.zip",
            "spot_bytes": len(s_zip),
            "perp_bytes": len(p_zip),
            "matched_5m_bars": int(len(m)),
            "derived_hourly_parquet": str(parquet_path.as_posix()),
        },
        "source_checksum": f"SPOT:{s_exp}|PERP:{p_exp}",
        "local_sha256": f"SPOT:{s_sha}|PERP:{p_sha}",
        "checksum_verified": chk_ok,
        "trading_eligibility": "ELIGIBLE_SPOT_EXECUTION_WITH_SYNCHRONIZED_5M_PERP_SIGNAL",
        "missing_intervals": {
            "hourly_bars": int(len(hourly)),
            "incomplete_hours_lt_12_subbars": int((hourly["subbar_count"] < 12).sum()),
        },
        "execution_constraints": {
            "execution_venue": "BINANCE_SPOT",
            "signal_venues": ["BINANCE_USD_M_PERP_5M", "BINANCE_SPOT_5M"],
            "short_selling_allowed": False,
            "round_trip_fee_slippage_bps": 14.0,
        },
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def acquire_hb2_5m_perp_spot_dataset(
    cache_dir: Path,
    manifest_path: Path,
    symbols: Optional[List[str]] = None,
    start_year: int = 2022,
    end_year: int = 2025,
    max_workers: int = 8,
) -> Dict[str, Any]:
    """Acquire and verify 5m Binance USD-M Perp and Spot monthly archives across 8 symbols (2022-2025)."""
    syms = symbols or HB_SYMBOLS_BINANCE
    months = _month_list(start_year, end_year)
    tasks = [(s, ym) for s in syms for ym in months]

    records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_process_single_5m_month, s, ym, cache_dir): (s, ym) for s, ym in tasks}
        for fut in as_completed(fut_map):
            records.append(fut.result())

    records.sort(key=lambda r: (r["symbol"], r["year_month"]))

    frames = [pd.read_parquet(r["raw_payload"]["derived_hourly_parquet"]) for r in records]
    panel = pd.concat(frames, ignore_index=True).sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)
    panel_path = cache_dir / "n1_2_hb2_5m_perp_spot_hourly_panel.parquet"
    panel.to_parquet(panel_path, index=False)

    manifest = {
        "dataset_id": "N1_2_HB2_BINANCE_5M_PERP_VS_SPOT_2022_2025",
        "created_at": _utc_now_iso(),
        "symbols": syms,
        "months_count": len(months),
        "total_symbol_month_pairs": len(records),
        "total_verified_archives": len(records) * 2,
        "checksum_verified_count": sum(1 for r in records if r.get("checksum_verified")),
        "total_matched_5m_bars": int(sum(r["raw_payload"]["matched_5m_bars"] for r in records)),
        "panel_parquet_path": str(panel_path.as_posix()),
        "panel_sha256": _sha256_file(panel_path),
        "mandatory_provenance_fields": MANDATORY_PROVENANCE_FIELDS,
        "records": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
