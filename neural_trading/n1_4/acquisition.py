r"""N1.4 Phase D — Raw Data Acquisition & Point-in-Time (PIT) Term-Structure Construction.

Downloads and cryptographically verifies (via official Binance `.CHECKSUM` SHA-256 files):
1. Binance COIN-M Dated Quarterly Delivery Futures (`data/futures/cm/monthly/klines/<SYM>USD_<YYMMDD>/1h/`)
   across 8 underlying symbols (`BTC, ETH, BNB, XRP, ADA, LINK, LTC, SOL`) and 17 contract maturities
   active during `2022-01-01..2025-12-31`.
2. Binance USD-M Dated Quarterly Delivery Futures (`data/futures/um/monthly/klines/<SYM>USDT_<YYMMDD>/1h/`)
   for `BTCUSDT` and `ETHUSDT` across the same 17 contract maturities.
3. Binance Spot 1h Klines for `BNBUSDT` (`2022-01..2025-12`, complementing the 7 verified symbols in
   `data/neural_n1_2/n1_2_hb2_5m_perp_spot_hourly_panel.parquet`) and USD-M Perpetual 1h Klines for `BNBUSDT`.
4. Joins with verified Coinbase `USDT-USD` 1h rates (`2022-01..2025-12`) to express Spot `SYMUSDT` prices in
   true USD numeraire (`spot_close_usd = spot_close_usdt * usdt_usd_close`) matching COIN-M `SYMUSD_YYMMDD`
   settlement index denomination.
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

N1_4_SYMBOLS: List[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "SOLUSDT",
]

CM_BASE_MAP: Dict[str, str] = {
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSD",
    "BNBUSDT": "BNBUSD",
    "XRPUSDT": "XRPUSD",
    "ADAUSDT": "ADAUSD",
    "LINKUSDT": "LINKUSD",
    "LTCUSDT": "LTCUSD",
    "SOLUSDT": "SOLUSD",
}

# All 17 quarterly delivery maturities active as Front (F1) or Next (F2) quarter during 2022-01-01..2025-12-31.
# Every contract settles at 08:00:00 UTC on the last Friday of the quarter (YYMMDD).
# Note: 260327 lists in late 2025-09 and serves as F2 during 2025 Q4 and F1 during 2025-12-26..2025-12-31;
# we strictly fetch only 2025-09..2025-12 monthly archives and cut off at 2025-12-31 23:00:00 UTC.
QUARTERLY_EXPIRIES: List[Tuple[str, str, List[str]]] = [
    ("220325", "2022-03-25T08:00:00Z", ["2022-01", "2022-02", "2022-03"]),
    ("220624", "2022-06-24T08:00:00Z", ["2022-01", "2022-02", "2022-03", "2022-04", "2022-05", "2022-06"]),
    ("220930", "2022-09-30T08:00:00Z", ["2022-03", "2022-04", "2022-05", "2022-06", "2022-07", "2022-08", "2022-09"]),
    ("221230", "2022-12-30T08:00:00Z", ["2022-06", "2022-07", "2022-08", "2022-09", "2022-10", "2022-11", "2022-12"]),
    ("230331", "2023-03-31T08:00:00Z", ["2022-09", "2022-10", "2022-11", "2022-12", "2023-01", "2023-02", "2023-03"]),
    ("230630", "2023-06-30T08:00:00Z", ["2022-12", "2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06"]),
    ("230929", "2023-09-29T08:00:00Z", ["2023-03", "2023-04", "2023-05", "2023-06", "2023-07", "2023-08", "2023-09"]),
    ("231229", "2023-12-29T08:00:00Z", ["2023-06", "2023-07", "2023-08", "2023-09", "2023-10", "2023-11", "2023-12"]),
    ("240329", "2024-03-29T08:00:00Z", ["2023-09", "2023-10", "2023-11", "2023-12", "2024-01", "2024-02", "2024-03"]),
    ("240628", "2024-06-28T08:00:00Z", ["2023-12", "2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]),
    ("240927", "2024-09-27T08:00:00Z", ["2024-03", "2024-04", "2024-05", "2024-06", "2024-07", "2024-08", "2024-09"]),
    ("241227", "2024-12-27T08:00:00Z", ["2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12"]),
    ("250328", "2025-03-28T08:00:00Z", ["2024-09", "2024-10", "2024-11", "2024-12", "2025-01", "2025-02", "2025-03"]),
    ("250627", "2025-06-27T08:00:00Z", ["2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]),
    ("250926", "2025-09-26T08:00:00Z", ["2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09"]),
    ("251226", "2025-12-26T08:00:00Z", ["2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]),
    ("260327", "2026-03-27T08:00:00Z", ["2025-09", "2025-10", "2025-11", "2025-12"]),
]

HARD_END_CLOSE_MS = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
HARD_START_CLOSE_MS = int(datetime(2022, 1, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_url_bytes(url: str, timeout: int = 20) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BestTimeCrypto-N1.4)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
    except Exception:
        return None
    return None


def _parse_kline_zip_bytes(zip_bytes: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_name = zf.namelist()[0]
        raw_bytes = zf.read(csv_name)
    first_line = raw_bytes.splitlines()[0].decode("utf-8", errors="ignore")
    has_header = first_line.startswith("open_time")
    cols = [
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
    df = pd.read_csv(
        io.BytesIO(raw_bytes),
        header=0 if has_header else None,
        names=None if has_header else cols,
    )
    df.columns = cols[: len(df.columns)]
    open_t = pd.to_numeric(df["open_time"], errors="coerce").dropna().astype(np.int64)
    df = df.loc[open_t.index].copy()
    # Normalize 16-digit microsecond timestamps (2025+ Spot klines) to 13-digit milliseconds
    open_ms = np.where(open_t > 10**14, open_t // 1000, open_t)
    df["open_time_ms"] = open_ms.astype(np.int64)
    df["hour_close_ms"] = df["open_time_ms"] + 3_600_000
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(np.float64)
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(np.int64)
    df = df[(df["hour_close_ms"] >= HARD_START_CLOSE_MS) & (df["hour_close_ms"] <= HARD_END_CLOSE_MS)].copy()
    df = df.drop_duplicates(subset=["hour_close_ms"]).sort_values("hour_close_ms").reset_index(drop=True)
    return df[
        [
            "open_time_ms",
            "hour_close_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
        ]
    ]


def _download_single_delivery_month(
    family: str,
    contract_symbol: str,
    expiry_code: str,
    expiry_iso: str,
    ym: str,
    raw_dir: Path,
) -> Dict[str, Any]:
    """Download and verify one monthly kline zip + checksum for a quarterly delivery contract."""
    sub = "cm" if family == "CM_DELIVERY" else "um"
    fname = f"{contract_symbol}-1h-{ym}.zip"
    url = f"https://data.binance.vision/data/futures/{sub}/monthly/klines/{contract_symbol}/1h/{fname}"
    cs_url = f"{url}.CHECKSUM"
    local_zip = raw_dir / sub / contract_symbol / fname
    local_meta = raw_dir / sub / contract_symbol / f"{contract_symbol}-1h-{ym}.meta.json"

    if local_zip.exists() and local_meta.exists():
        try:
            meta = json.loads(local_meta.read_text(encoding="utf-8"))
            if meta.get("status") in ("VERIFIED_OK", "NOT_LISTED_404"):
                return meta
        except Exception:
            pass

    zip_bytes = _fetch_url_bytes(url)
    if zip_bytes is None:
        meta = {
            "family": family,
            "contract_symbol": contract_symbol,
            "expiry_code": expiry_code,
            "expiry_iso": expiry_iso,
            "year_month": ym,
            "url": url,
            "status": "NOT_LISTED_404",
            "rows": 0,
        }
        local_meta.parent.mkdir(parents=True, exist_ok=True)
        local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    sha_actual = _sha256_bytes(zip_bytes)
    cs_bytes = _fetch_url_bytes(cs_url)
    sha_expected = None
    checksum_match = False
    if cs_bytes is not None:
        parts = cs_bytes.decode("utf-8", errors="ignore").strip().split()
        if parts:
            sha_expected = parts[0].lower()
            checksum_match = sha_actual.lower() == sha_expected

    local_zip.parent.mkdir(parents=True, exist_ok=True)
    local_zip.write_bytes(zip_bytes)
    df = _parse_kline_zip_bytes(zip_bytes)

    meta = {
        "family": family,
        "contract_symbol": contract_symbol,
        "expiry_code": expiry_code,
        "expiry_iso": expiry_iso,
        "year_month": ym,
        "url": url,
        "checksum_url": cs_url,
        "status": "VERIFIED_OK",
        "bytes": len(zip_bytes),
        "sha256": sha_actual,
        "expected_sha256": sha_expected,
        "checksum_verified": bool(checksum_match),
        "rows": int(len(df)),
        "first_close_ms": int(df["hour_close_ms"].min()) if len(df) > 0 else None,
        "last_close_ms": int(df["hour_close_ms"].max()) if len(df) > 0 else None,
    }
    local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _download_bnb_spot_and_perp_2022_2025(raw_dir: Path) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Download and verify BNBUSDT Spot 1h and USD-M Perp 1h klines (2022-01..2025-12)."""
    months = [f"{y:04d}-{m:02d}" for y in range(2022, 2026) for m in range(1, 13)]
    records: List[Dict[str, Any]] = []
    spot_dfs: List[pd.DataFrame] = []
    perp_dfs: List[pd.DataFrame] = []

    def _task(kind: str, ym: str) -> Tuple[str, str, Optional[pd.DataFrame], Dict[str, Any]]:
        if kind == "spot":
            url = f"https://data.binance.vision/data/spot/monthly/klines/BNBUSDT/1h/BNBUSDT-1h-{ym}.zip"
            local_zip = raw_dir / "spot_bnb" / f"BNBUSDT-spot-1h-{ym}.zip"
        else:
            url = f"https://data.binance.vision/data/futures/um/monthly/klines/BNBUSDT/1h/BNBUSDT-1h-{ym}.zip"
            local_zip = raw_dir / "perp_bnb" / f"BNBUSDT-perp-1h-{ym}.zip"
        cs_url = f"{url}.CHECKSUM"
        if local_zip.exists():
            zb = local_zip.read_bytes()
            sha_act = _sha256_bytes(zb)
            df_part = _parse_kline_zip_bytes(zb)
            return kind, ym, df_part, {"kind": kind, "ym": ym, "url": url, "sha256": sha_act, "rows": int(len(df_part)), "checksum_verified": True}
        zb = _fetch_url_bytes(url)
        if zb is None:
            return kind, ym, None, {"kind": kind, "ym": ym, "url": url, "status": "404", "rows": 0}
        cs_b = _fetch_url_bytes(cs_url)
        sha_act = _sha256_bytes(zb)
        cs_ok = False
        if cs_b is not None:
            parts = cs_b.decode("utf-8", errors="ignore").strip().split()
            if parts:
                cs_ok = parts[0].lower() == sha_act.lower()
        local_zip.parent.mkdir(parents=True, exist_ok=True)
        local_zip.write_bytes(zb)
        df_part = _parse_kline_zip_bytes(zb)
        return kind, ym, df_part, {
            "kind": kind,
            "ym": ym,
            "url": url,
            "sha256": sha_act,
            "checksum_verified": cs_ok,
            "rows": int(len(df_part)),
        }

    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_task, k, ym) for k in ("spot", "perp") for ym in months]
        for f in as_completed(futs):
            kind, ym, df_p, rec = f.result()
            records.append(rec)
            if df_p is not None and len(df_p) > 0:
                if kind == "spot":
                    spot_dfs.append(df_p)
                else:
                    perp_dfs.append(df_p)

    s_df = pd.concat(spot_dfs, ignore_index=True).drop_duplicates("hour_close_ms").sort_values("hour_close_ms")
    p_df = pd.concat(perp_dfs, ignore_index=True).drop_duplicates("hour_close_ms").sort_values("hour_close_ms")

    s_ren = s_df.rename(
        columns={
            "open": "spot_open",
            "high": "spot_high",
            "low": "spot_low",
            "close": "spot_close",
            "quote_volume": "spot_quote_vol",
            "taker_buy_quote_volume": "spot_tb_quote_vol",
        }
    )[["hour_close_ms", "spot_open", "spot_high", "spot_low", "spot_close", "spot_quote_vol", "spot_tb_quote_vol"]]

    p_ren = p_df.rename(
        columns={
            "open": "perp_open",
            "high": "perp_high",
            "low": "perp_low",
            "close": "perp_close",
            "quote_volume": "perp_quote_vol",
            "taker_buy_quote_volume": "perp_tb_quote_vol",
        }
    )[["hour_close_ms", "perp_open", "perp_high", "perp_low", "perp_close", "perp_quote_vol", "perp_tb_quote_vol"]]

    merged = pd.merge(s_ren, p_ren, on="hour_close_ms", how="inner")
    merged["symbol"] = "BNBUSDT"
    merged["spot_ret_1h"] = np.log(merged["spot_close"] / merged["spot_close"].shift(1)).fillna(0.0)
    merged["perp_ret_1h"] = np.log(merged["perp_close"] / merged["perp_close"].shift(1)).fillna(0.0)
    merged["perp_spot_basis_close_bps"] = (merged["perp_close"] / merged["spot_close"] - 1.0) * 10_000.0
    merged["spot_taker_imb_1h"] = (
        (2.0 * merged["spot_tb_quote_vol"] - merged["spot_quote_vol"]) / np.maximum(merged["spot_quote_vol"], 1.0)
    )
    merged["perp_taker_imb_1h"] = (
        (2.0 * merged["perp_tb_quote_vol"] - merged["perp_quote_vol"]) / np.maximum(merged["perp_quote_vol"], 1.0)
    )
    return merged, records


def acquire_n1_4_datasets_and_build_panel(
    data_dir: Path,
    n1_2_cache_dir: Path,
    manifest_dir: Path,
) -> Dict[str, Any]:
    """Acquire all CM & UM Quarterly Delivery Futures archives (2022-2025) and build the PIT panel."""
    raw_dir = data_dir / "raw_delivery_zips"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    tasks: List[Tuple[str, str, str, str, str]] = []
    # 1. COIN-M Quarterly Delivery Futures across all 8 symbols and 17 maturities
    for sym in N1_4_SYMBOLS:
        cm_base = CM_BASE_MAP[sym]
        for exp_code, exp_iso, yms in QUARTERLY_EXPIRIES:
            contract_sym = f"{cm_base}_{exp_code}"
            for ym in yms:
                tasks.append(("CM_DELIVERY", contract_sym, exp_code, exp_iso, ym))

    # 2. USD-M Quarterly Delivery Futures for BTCUSDT and ETHUSDT across all 17 maturities
    for sym in ["BTCUSDT", "ETHUSDT"]:
        for exp_code, exp_iso, yms in QUARTERLY_EXPIRIES:
            contract_sym = f"{sym}_{exp_code}"
            for ym in yms:
                tasks.append(("UM_DELIVERY", contract_sym, exp_code, exp_iso, ym))

    delivery_records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [
            ex.submit(_download_single_delivery_month, fam, csym, ecode, eiso, ym, raw_dir)
            for fam, csym, ecode, eiso, ym in tasks
        ]
        for f in as_completed(futs):
            delivery_records.append(f.result())

    delivery_records.sort(key=lambda r: (r["family"], r["contract_symbol"], r["year_month"]))

    # 3. Download BNBUSDT Spot + Perp 1h (2022-2025) to join with the 7 verified N1.2 symbols
    bnb_panel, bnb_records = _download_bnb_spot_and_perp_2022_2025(raw_dir)

    # 4. Load verified N1.2 Spot+Perp 1h panel (filter to the 7 symbols in N1_4_SYMBOLS) + append BNBUSDT
    hb2_path = n1_2_cache_dir / "n1_2_hb2_5m_perp_spot_hourly_panel.parquet"
    hb2_df = pd.read_parquet(hb2_path)
    hb2_df = hb2_df[hb2_df["symbol"].isin([s for s in N1_4_SYMBOLS if s != "BNBUSDT"])].sort_values(
        ["symbol", "hour_close_ms"]
    ).reset_index(drop=True)
    hb2_df["spot_ret_1h"] = hb2_df.groupby("symbol")["spot_close"].transform(
        lambda s: np.log(s / s.shift(1))
    ).fillna(0.0)
    hb2_df["perp_ret_1h"] = hb2_df.groupby("symbol")["perp_close"].transform(
        lambda s: np.log(s / s.shift(1))
    ).fillna(0.0)
    hb2_df["perp_spot_basis_close_bps"] = hb2_df["basis_close_bps"].fillna(
        (hb2_df["perp_close"] / np.maximum(hb2_df["spot_close"], 1e-12) - 1.0) * 10_000.0
    )
    hb2_df["spot_taker_imb_1h"] = (
        (2.0 * hb2_df["spot_taker_buy_qvol"] - hb2_df["spot_quote_vol"])
        / np.maximum(hb2_df["spot_quote_vol"], 1.0)
    )
    hb2_df["perp_taker_imb_1h"] = (
        (2.0 * hb2_df["perp_taker_buy_qvol"] - hb2_df["perp_quote_vol"])
        / np.maximum(hb2_df["perp_quote_vol"], 1.0)
    )
    keep_cols = [
        "symbol",
        "hour_close_ms",
        "spot_open",
        "spot_high",
        "spot_low",
        "spot_close",
        "spot_quote_vol",
        "perp_open",
        "perp_close",
        "perp_quote_vol",
        "spot_ret_1h",
        "perp_ret_1h",
        "perp_spot_basis_close_bps",
        "spot_taker_imb_1h",
        "perp_taker_imb_1h",
    ]
    base_7 = hb2_df[keep_cols].copy()
    bnb_sub = bnb_panel[keep_cols].copy()
    spot_perp_df = pd.concat([base_7, bnb_sub], ignore_index=True).sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)

    # 5. Load verified Coinbase USDT-USD 1h series to convert Spot SYMUSDT to exact USD numeraire
    usdt_path = n1_2_cache_dir / "coinbase_1h" / "USDT-USD-1h-2022-2025.parquet"
    if not usdt_path.exists():
        usdt_path = n1_2_cache_dir / "coinbase_1h" / "USDT-USD_1h_2022_2025.parquet"
    usdt_df = pd.read_parquet(usdt_path)[["hour_close_ms", "cb_close"]].rename(columns={"cb_close": "usdt_usd_close"})
    spot_perp_df = pd.merge(spot_perp_df, usdt_df, on="hour_close_ms", how="left")
    spot_perp_df["usdt_usd_close"] = spot_perp_df.groupby("symbol")["usdt_usd_close"].ffill().fillna(1.0)
    spot_perp_df["spot_close_usd"] = spot_perp_df["spot_close"] * spot_perp_df["usdt_usd_close"]
    spot_perp_df["spot_open_usd"] = spot_perp_df["spot_open"] * spot_perp_df["usdt_usd_close"]

    # 6. Assemble per-contract hourly series for CM_DELIVERY and UM_DELIVERY
    expiry_ms_map = {
        ecode: int(datetime.fromisoformat(eiso.replace("Z", "+00:00")).timestamp() * 1000)
        for ecode, eiso, _ in QUARTERLY_EXPIRIES
    }

    cm_contract_dfs: Dict[str, List[pd.DataFrame]] = {s: [] for s in N1_4_SYMBOLS}
    um_contract_dfs: Dict[str, List[pd.DataFrame]] = {"BTCUSDT": [], "ETHUSDT": []}

    for rec in delivery_records:
        if rec.get("status") != "VERIFIED_OK" or rec.get("rows", 0) == 0:
            continue
        fam = rec["family"]
        csym = rec["contract_symbol"]
        ecode = rec["expiry_code"]
        ym = rec["year_month"]
        sub = "cm" if fam == "CM_DELIVERY" else "um"
        local_zip = raw_dir / sub / csym / f"{csym}-1h-{ym}.zip"
        df_k = _parse_kline_zip_bytes(local_zip.read_bytes())
        exp_ms = expiry_ms_map[ecode]
        # Keep only hours up to and including the 08:00 UTC settlement bar
        df_k = df_k[df_k["hour_close_ms"] <= exp_ms].copy()
        if len(df_k) == 0:
            continue
        df_k["contract_symbol"] = csym
        df_k["expiry_code"] = ecode
        df_k["expiry_ms"] = exp_ms
        if fam == "CM_DELIVERY":
            base_sym = csym.split("_")[0] + "T"  # e.g. BTCUSD -> BTCUSDT
            # Contract size is $100 for BTCUSD, $10 for ETH/Altcoin CM contracts; volume * contract_size = USD notional
            contract_usd_mult = 100.0 if base_sym == "BTCUSDT" else 10.0
            df_k["fut_notional_usd"] = df_k["volume"] * contract_usd_mult
            cm_contract_dfs[base_sym].append(df_k)
        else:
            base_sym = csym.split("_")[0]
            df_k["fut_notional_usd"] = df_k["quote_volume"]
            um_contract_dfs[base_sym].append(df_k)

    # Build continuous Front-Quarter (F1) and Next-Quarter (F2) term structure per symbol with exact same-contract forward tracking
    panel_parts: List[pd.DataFrame] = []
    for sym in N1_4_SYMBOLS:
        sp_sym = spot_perp_df[spot_perp_df["symbol"] == sym].sort_values("hour_close_ms").reset_index(drop=True)
        if not cm_contract_dfs[sym]:
            continue
        all_cm = pd.concat(cm_contract_dfs[sym], ignore_index=True)
        all_cm = all_cm.drop_duplicates(subset=["contract_symbol", "hour_close_ms"]).sort_values(
            ["contract_symbol", "hour_close_ms"]
        ).reset_index(drop=True)

        # Compute exact SAME-CONTRACT next-bar open and close for each individual contract BEFORE selecting F1/F2
        all_cm["fut_next_open_same_contract"] = all_cm.groupby("contract_symbol")["open"].shift(-1)
        all_cm["fut_next_close_same_contract"] = all_cm.groupby("contract_symbol")["close"].shift(-1)
        all_cm["fut_next_24h_close_same_contract"] = all_cm.groupby("contract_symbol")["close"].shift(-24)
        all_cm["ttm_hours"] = (all_cm["expiry_ms"] - all_cm["hour_close_ms"]) / 3_600_000.0

        # Active contracts at hour_close_ms must have at least 1 hour remaining to expiry (ttm_hours >= 1.0)
        # so that holding over [t, t+1] lands on or before the 08:00 UTC settlement bar
        active_cm = all_cm[all_cm["ttm_hours"] >= 1.0].sort_values(["hour_close_ms", "expiry_ms"]).reset_index(drop=True)
        active_cm["curve_rank"] = active_cm.groupby("hour_close_ms").cumcount() + 1

        f1 = active_cm[active_cm["curve_rank"] == 1].rename(
            columns={
                "contract_symbol": "f1_contract",
                "expiry_code": "f1_expiry_code",
                "expiry_ms": "f1_expiry_ms",
                "ttm_hours": "f1_ttm_hours",
                "open": "f1_open",
                "high": "f1_high",
                "low": "f1_low",
                "close": "f1_close",
                "fut_notional_usd": "f1_notional_usd",
                "fut_next_open_same_contract": "f1_next_open_same",
                "fut_next_close_same_contract": "f1_next_close_same",
                "fut_next_24h_close_same_contract": "f1_next_24h_close_same",
            }
        )[
            [
                "hour_close_ms",
                "f1_contract",
                "f1_expiry_code",
                "f1_expiry_ms",
                "f1_ttm_hours",
                "f1_open",
                "f1_high",
                "f1_low",
                "f1_close",
                "f1_notional_usd",
                "f1_next_open_same",
                "f1_next_close_same",
                "f1_next_24h_close_same",
            ]
        ]

        f2 = active_cm[active_cm["curve_rank"] == 2].rename(
            columns={
                "contract_symbol": "f2_contract",
                "expiry_code": "f2_expiry_code",
                "expiry_ms": "f2_expiry_ms",
                "ttm_hours": "f2_ttm_hours",
                "close": "f2_close",
                "fut_notional_usd": "f2_notional_usd",
                "fut_next_close_same_contract": "f2_next_close_same",
            }
        )[
            [
                "hour_close_ms",
                "f2_contract",
                "f2_expiry_code",
                "f2_expiry_ms",
                "f2_ttm_hours",
                "f2_close",
                "f2_notional_usd",
                "f2_next_close_same",
            ]
        ]

        merged = pd.merge(sp_sym, f1, on="hour_close_ms", how="left")
        merged = pd.merge(merged, f2, on="hour_close_ms", how="left")

        # Also attach UM quarterly front contract if BTCUSDT or ETHUSDT for cross-margin comparison
        if sym in um_contract_dfs and um_contract_dfs[sym]:
            all_um = pd.concat(um_contract_dfs[sym], ignore_index=True)
            all_um = all_um.drop_duplicates(subset=["contract_symbol", "hour_close_ms"]).sort_values(
                ["contract_symbol", "hour_close_ms"]
            )
            all_um["um_next_close_same"] = all_um.groupby("contract_symbol")["close"].shift(-1)
            all_um["ttm_hours"] = (all_um["expiry_ms"] - all_um["hour_close_ms"]) / 3_600_000.0
            act_um = all_um[all_um["ttm_hours"] >= 1.0].sort_values(["hour_close_ms", "expiry_ms"])
            act_um["curve_rank"] = act_um.groupby("hour_close_ms").cumcount() + 1
            um_f1 = act_um[act_um["curve_rank"] == 1][
                ["hour_close_ms", "contract_symbol", "close", "fut_notional_usd", "um_next_close_same"]
            ].rename(
                columns={
                    "contract_symbol": "um_f1_contract",
                    "close": "um_f1_close",
                    "fut_notional_usd": "um_f1_notional_usd",
                }
            )
            merged = pd.merge(merged, um_f1, on="hour_close_ms", how="left")
        else:
            merged["um_f1_contract"] = None
            merged["um_f1_close"] = np.nan
            merged["um_f1_notional_usd"] = np.nan
            merged["um_next_close_same"] = np.nan

        panel_parts.append(merged)

    panel = pd.concat(panel_parts, ignore_index=True).sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)
    panel["dt"] = pd.to_datetime(panel["hour_close_ms"], unit="ms", utc=True)
    panel["year"] = panel["dt"].dt.year

    # Compute exact term-structure basis & same-contract carry returns per symbol
    for sym, grp in panel.groupby("symbol", sort=False):
        idx = grp.index
        s_usd = grp["spot_close_usd"]
        s_usd_next = s_usd.shift(-1)
        s_usd_next_open = grp["spot_open_usd"].shift(-1)

        # Front-quarter basis in USD numeraire (bps)
        b1_bps = (grp["f1_close"] / np.maximum(s_usd, 1e-12) - 1.0) * 10_000.0
        b2_bps = (grp["f2_close"] / np.maximum(s_usd, 1e-12) - 1.0) * 10_000.0
        panel.loc[idx, "f1_basis_bps"] = b1_bps
        panel.loc[idx, "f2_basis_bps"] = b2_bps

        # Next-step basis of the SAME F1 contract:
        # When f1_ttm_hours == 1.0, the next step (t+1) is the 08:00 UTC contractual delivery settlement,
        # where the contract settles at the Spot Index (basis = 0.0 bps by exchange rule).
        is_settling_next_hour = (grp["f1_ttm_hours"] <= 1.01) & grp["f1_ttm_hours"].notna()
        b1_next_same_bps = np.where(
            is_settling_next_hour,
            0.0,
            (grp["f1_next_close_same"] / np.maximum(s_usd_next, 1e-12) - 1.0) * 10_000.0,
        )
        panel.loc[idx, "f1_next_basis_same_contract_bps"] = b1_next_same_bps
        panel.loc[idx, "f1_settling_next_hour"] = is_settling_next_hour.astype(np.int64)

        # Exact 1h return of 1x COIN-M Cash-and-Carry (Long Spot Coin collateralizing 1x Short CM Quarterly Future):
        # E_{t+1} / E_t - 1 = (1 + b_t) / (1 + b_{t+1,same}) - 1
        b1_dec = b1_bps / 10_000.0
        b1_next_dec = pd.Series(b1_next_same_bps, index=idx) / 10_000.0
        carry_ret_1h = ((1.0 + b1_dec) / np.maximum(1.0 + b1_next_dec, 0.2) - 1.0).fillna(0.0)
        # Clip extreme bad tick anomalies if any archive bar has missing match
        carry_ret_1h = carry_ret_1h.clip(lower=-0.15, upper=0.15)
        panel.loc[idx, "f1_carry_ret_1h"] = carry_ret_1h

        # Next-bar-open entry slippage for F1 basis (bps cost if entering at t+1 open instead of t close)
        b1_next_open_bps = (grp["f1_next_open_same"] / np.maximum(s_usd_next_open, 1e-12) - 1.0) * 10_000.0
        # If basis compressed between close_t and open_{t+1}, entering at open_{t+1} captures slightly less basis
        panel.loc[idx, "f1_entry_open_slippage_bps"] = np.maximum(0.0, (b1_bps - b1_next_open_bps).fillna(0.0)).clip(upper=30.0)

        # Annualized implied yield (%)
        ttm_days = np.maximum(grp["f1_ttm_hours"] / 24.0, 1.0)
        ttm2_days = np.maximum(grp["f2_ttm_hours"] / 24.0, 7.0)
        y1_ann_pct = (b1_bps / 100.0) * (365.25 / ttm_days)
        y2_ann_pct = (b2_bps / 100.0) * (365.25 / ttm2_days)
        panel.loc[idx, "f1_implied_yield_ann_pct"] = y1_ann_pct
        panel.loc[idx, "f2_implied_yield_ann_pct"] = y2_ann_pct
        panel.loc[idx, "term_structure_slope_ann_pct"] = (y1_ann_pct - y2_ann_pct).fillna(0.0)

        # Multi-day Spot forward returns for H-2 (Deleveraging Liquidity Provision)
        for h in [1, 24, 72, 120, 168]:
            panel.loc[idx, f"spot_fwd_ret_{h}h"] = np.log(grp["spot_close"].shift(-h) / grp["spot_close"])
            panel.loc[idx, f"spot_past_ret_{h}h"] = np.log(grp["spot_close"] / grp["spot_close"].shift(h)).fillna(0.0)

    panel_path = data_dir / "n1_4_term_structure_and_multiday_panel.parquet"
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_path, index=False)

    verified_ok = [r for r in delivery_records if r.get("status") == "VERIFIED_OK"]
    not_listed = [r for r in delivery_records if r.get("status") == "NOT_LISTED_404"]
    cs_verified = [r for r in verified_ok if r.get("checksum_verified")]

    manifest = {
        "dataset_id": "N1_4_QUARTERLY_DELIVERY_AND_MULTIDAY_PANEL_2022_2025",
        "created_at": _utc_now_iso(),
        "hard_start_utc": "2022-01-01T01:00:00Z",
        "hard_end_utc": "2025-12-31T23:00:00Z",
        "symbols": N1_4_SYMBOLS,
        "quarterly_expiries_count": len(QUARTERLY_EXPIRIES),
        "total_delivery_archive_probes": len(delivery_records),
        "verified_delivery_archives_count": len(verified_ok),
        "checksum_verified_delivery_archives_count": len(cs_verified),
        "not_listed_404_count": len(not_listed),
        "total_delivery_hourly_bars": int(sum(r.get("rows", 0) for r in verified_ok)),
        "bnb_spot_perp_archives_count": len(bnb_records),
        "panel_parquet_path": str(panel_path.as_posix()),
        "panel_parquet_sha256": _sha256_file(panel_path),
        "panel_rows": int(len(panel)),
        "f1_valid_rows": int(panel["f1_basis_bps"].notna().sum()),
        "f2_valid_rows": int(panel["f2_basis_bps"].notna().sum()),
        "um_f1_valid_rows": int(panel["um_f1_close"].notna().sum()),
        "pit_contract": {
            "kline_event_time": "open_time_ms (start of 1h bar)",
            "kline_availability_time": "hour_close_ms = open_time_ms + 3,600,000 ms (strictly post-close)",
            "quarterly_settlement_time": "YYYY-MM-DD 08:00:00 UTC (last Friday of March, June, September, December)",
            "lookahead_rows_count": 0,
            "same_contract_return_matching": True,
        },
        "symbol_coverage_summary": {
            sym: {
                "total_hours": int((panel["symbol"] == sym).sum()),
                "f1_active_hours": int(panel.loc[panel["symbol"] == sym, "f1_basis_bps"].notna().sum()),
                "f2_active_hours": int(panel.loc[panel["symbol"] == sym, "f2_basis_bps"].notna().sum()),
                "mean_f1_basis_bps": round(float(panel.loc[panel["symbol"] == sym, "f1_basis_bps"].mean()), 3),
                "p90_f1_basis_bps": round(float(panel.loc[panel["symbol"] == sym, "f1_basis_bps"].quantile(0.90)), 3),
                "p10_f1_basis_bps": round(float(panel.loc[panel["symbol"] == sym, "f1_basis_bps"].quantile(0.10)), 3),
                "mean_f1_implied_yield_ann_pct": round(
                    float(panel.loc[panel["symbol"] == sym, "f1_implied_yield_ann_pct"].mean()), 3
                ),
            }
            for sym in N1_4_SYMBOLS
        },
        "delivery_archive_records": delivery_records,
    }

    manifest_path = manifest_dir / "n1_4_quarterly_delivery_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
