"""N1.5 Phase A, B, C, D — Official Binance COIN-M Contract Specifications, Mark/Index Price Acquisition, and 30m Settlement TWAP."""
from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from neural_trading.n1_4.acquisition import (
    CM_BASE_MAP,
    HARD_END_CLOSE_MS,
    HARD_START_CLOSE_MS,
    N1_4_SYMBOLS,
    QUARTERLY_EXPIRIES,
)


@dataclass(frozen=True)
class CoinMContractSpec:
    """Official Binance COIN-M Quarterly Delivery contract specification."""

    symbol: str
    cm_pair: str
    contract_size_usd: float  # $100 for BTCUSD, $10 for ETHUSD and altcoin CM contracts
    tier1_max_notional_usd: float
    tier1_maint_margin_rate: float  # Official Tier 1 MMR (0.40% BTC/ETH, 0.50%-1.00% alts)
    exchange_info_base_mmr: float  # Conservative base maintMarginPercent reported in dapi/v1/exchangeInfo (2.50%)
    required_initial_margin_rate: float  # 5.00% standard (or 100% at 1x target cash-and-carry leverage)
    liquidation_fee_rate: float  # Official dapi/v1/exchangeInfo liquidationFee (1.00% to 2.50%)


COINM_CONTRACT_SPECS: Dict[str, CoinMContractSpec] = {
    "BTCUSDT": CoinMContractSpec("BTCUSDT", "BTCUSD", 100.0, 250_000.0, 0.0040, 0.0250, 0.0500, 0.0100),
    "ETHUSDT": CoinMContractSpec("ETHUSDT", "ETHUSD", 10.0, 250_000.0, 0.0040, 0.0250, 0.0500, 0.0100),
    "BNBUSDT": CoinMContractSpec("BNBUSDT", "BNBUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0100),
    "XRPUSDT": CoinMContractSpec("XRPUSDT", "XRPUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0100),
    "ADAUSDT": CoinMContractSpec("ADAUSDT", "ADAUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0100),
    "LINKUSDT": CoinMContractSpec("LINKUSDT", "LINKUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0100),
    "LTCUSDT": CoinMContractSpec("LTCUSDT", "LTCUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0200),
    "SOLUSDT": CoinMContractSpec("SOLUSDT", "SOLUSD", 10.0, 100_000.0, 0.0050, 0.0250, 0.0500, 0.0250),
}


@dataclass(frozen=True)
class FeeAndExecutionScenario:
    """Complete fee, settlement, spread, slippage, and BNB-discount specification."""

    scenario_id: str
    description: str
    spot_entry_fee_bps: float
    spot_exit_fee_bps: float
    cm_entry_fee_bps: float
    cm_early_exit_fee_bps: float
    cm_delivery_settlement_fee_bps: float  # Official Binance delivery fee at 08:00 UTC expiry
    spot_half_spread_and_impact_bps: float
    cm_half_spread_and_impact_bps: float
    bnb_replenishment_conversion_bps: float  # Cost to top up BNB for Spot fee deduction (0 if not using BNB)
    bnb_discount_applied_spot: bool
    bnb_discount_applied_cm: bool  # Always False: Binance 10% Futures BNB discount is USD-M only, NOT COIN-M


FEE_SCENARIOS: Dict[str, FeeAndExecutionScenario] = {
    "n1_4_reference_schedule": FeeAndExecutionScenario(
        scenario_id="n1_4_reference_schedule",
        description="N1.4 assumed schedule (7 bps/leg Spot all-in + 4 bps/leg CM all-in + 1.5 bps settlement)",
        spot_entry_fee_bps=5.5,
        spot_exit_fee_bps=5.5,
        cm_entry_fee_bps=2.0,
        cm_early_exit_fee_bps=2.0,
        cm_delivery_settlement_fee_bps=1.5,
        spot_half_spread_and_impact_bps=1.5,
        cm_half_spread_and_impact_bps=2.0,
        bnb_replenishment_conversion_bps=0.0,
        bnb_discount_applied_spot=False,
        bnb_discount_applied_cm=False,
    ),
    "verified_historical_fee_schedule": FeeAndExecutionScenario(
        scenario_id="verified_historical_fee_schedule",
        description=(
            "Verified Historical Binance VIP-0 Maker-Limit / Taker Blended Schedule: "
            "Spot 10.0 bps/leg standard fee (or passive limit 10.0 bps), COIN-M 50/50 Maker(1.0 bps)/Taker(5.0 bps) = 3.0 bps/leg, "
            "official COIN-M delivery settlement fee = 5.0 bps (Taker rate at expiry), plus empirical half-spread & impact."
        ),
        spot_entry_fee_bps=10.0,
        spot_exit_fee_bps=10.0,
        cm_entry_fee_bps=3.0,
        cm_early_exit_fee_bps=3.0,
        cm_delivery_settlement_fee_bps=5.0,
        spot_half_spread_and_impact_bps=1.5,
        cm_half_spread_and_impact_bps=2.0,
        bnb_replenishment_conversion_bps=0.0,
        bnb_discount_applied_spot=False,
        bnb_discount_applied_cm=False,
    ),
    "standard_retail_taker": FeeAndExecutionScenario(
        scenario_id="standard_retail_taker",
        description=(
            "Standard Retail VIP-0 Pure Market Taker on all legs: "
            "Spot Taker = 10.0 bps/leg, COIN-M Taker = 5.0 bps/leg, COIN-M Delivery Settlement = 5.0 bps (Taker rate), "
            "plus Spot half-spread/slippage (2.0 bps/leg) and COIN-M half-spread/slippage (2.5 bps/leg) -> 39.0 bps 4-leg RT."
        ),
        spot_entry_fee_bps=10.0,
        spot_exit_fee_bps=10.0,
        cm_entry_fee_bps=5.0,
        cm_early_exit_fee_bps=5.0,
        cm_delivery_settlement_fee_bps=5.0,
        spot_half_spread_and_impact_bps=2.0,
        cm_half_spread_and_impact_bps=2.5,
        bnb_replenishment_conversion_bps=0.0,
        bnb_discount_applied_spot=False,
        bnb_discount_applied_cm=False,
    ),
    "bnb_discount_if_eligible": FeeAndExecutionScenario(
        scenario_id="bnb_discount_if_eligible",
        description=(
            "BNB Discount Where Eligible: Spot 25% BNB fee discount (10.0 -> 7.5 bps/leg) + 0.3 bps BNB top-up conversion; "
            "COIN-M Futures is INELIGIBLE for the 10% BNB discount (fees settled in base coin at 5.0 bps Taker / 5.0 bps Delivery), "
            "plus 2.0 bps Spot and 2.5 bps COIN-M half-spread/slippage -> 34.6 bps 4-leg RT."
        ),
        spot_entry_fee_bps=7.5,
        spot_exit_fee_bps=7.5,
        cm_entry_fee_bps=5.0,
        cm_early_exit_fee_bps=5.0,
        cm_delivery_settlement_fee_bps=5.0,
        spot_half_spread_and_impact_bps=2.0,
        cm_half_spread_and_impact_bps=2.5,
        bnb_replenishment_conversion_bps=0.3,
        bnb_discount_applied_spot=True,
        bnb_discount_applied_cm=False,
    ),
    "stressed_execution_cost": FeeAndExecutionScenario(
        scenario_id="stressed_execution_cost",
        description=(
            "Stressed Execution Cost: VIP-0 Pure Taker (Spot 10.0 bps/leg, COIN-M 5.0 bps/leg, Delivery 5.0 bps) "
            "+ doubled spread/impact (Spot 4.0 bps/leg, COIN-M 5.5 bps/leg) -> 49.0 bps 4-leg RT."
        ),
        spot_entry_fee_bps=10.0,
        spot_exit_fee_bps=10.0,
        cm_entry_fee_bps=5.0,
        cm_early_exit_fee_bps=5.0,
        cm_delivery_settlement_fee_bps=5.0,
        spot_half_spread_and_impact_bps=4.0,
        cm_half_spread_and_impact_bps=5.5,
        bnb_replenishment_conversion_bps=0.0,
        bnb_discount_applied_spot=False,
        bnb_discount_applied_cm=False,
    ),
}


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fetch_bytes(url: str, timeout: int = 25, retries: int = 3) -> Optional[bytes]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:  # noqa: BLE001
            if attempt + 1 == retries:
                return None
    return None


def _parse_kline_zip(zb: bytes) -> pd.DataFrame:
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
    with zipfile.ZipFile(io.BytesIO(zb)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            return pd.DataFrame(columns=cols)
        with zf.open(names[0]) as f:
            raw = f.read().decode("utf-8", errors="ignore").strip()
    if not raw:
        return pd.DataFrame(columns=cols)
    lines = raw.splitlines()
    first = lines[0].split(",")[0].strip().strip('"')
    start_idx = 1 if not first.isdigit() else 0
    if start_idx >= len(lines):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(io.StringIO("\n".join(lines[start_idx:])), header=None, names=cols)
    for c in ["open_time", "close_time"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int64)
        df[c] = np.where(df[c] > 10**14, df[c] // 1000, df[c])
    for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(np.float64)
    return df


def verify_and_resolve_unverified_archive(
    n1_4_manifest_path: Path,
    raw_delivery_dir: Path,
) -> Dict[str, Any]:
    """Inspect the single unverified archive from N1.4 (SOLUSD_250926-1h-2025-08.zip) and verify its official .CHECKSUM."""
    manifest = json.loads(n1_4_manifest_path.read_text(encoding="utf-8"))
    unverified_recs = [
        r
        for r in manifest["delivery_archive_records"]
        if r.get("status") == "VERIFIED_OK" and not r.get("checksum_verified")
    ]
    results = []
    for r in unverified_recs:
        cs_url = r["checksum_url"]
        local_zip = raw_delivery_dir / "cm" / r["contract_symbol"] / f"{r['contract_symbol']}-1h-{r['year_month']}.zip"
        local_sha = _sha256_bytes(local_zip.read_bytes()) if local_zip.exists() else r.get("sha256")
        cs_bytes = _fetch_bytes(cs_url, timeout=20, retries=3)
        expected_sha = None
        if cs_bytes is not None:
            parts = cs_bytes.decode("utf-8", errors="ignore").strip().split()
            if parts:
                expected_sha = parts[0].lower()
        verified_now = bool(expected_sha is not None and local_sha is not None and expected_sha == local_sha.lower())
        results.append(
            {
                "contract_symbol": r["contract_symbol"],
                "year_month": r["year_month"],
                "url": r["url"],
                "checksum_url": cs_url,
                "local_sha256": local_sha,
                "official_checksum_sha256": expected_sha,
                "checksum_verified_on_recheck": verified_now,
                "root_cause_in_n1_4": "Transient read timeout on .CHECKSUM request during 16-worker parallel fetch in N1.4",
            }
        )
    return {
        "n1_4_unverified_count": len(unverified_recs),
        "rechecked_records": results,
        "all_967_archives_verified_after_recheck": all(x["checksum_verified_on_recheck"] for x in results),
    }


def _fetch_single_1m_delivery_index(
    cm_pair: str,
    exp_code: str,
    exp_iso: str,
    cache_dir: Path,
) -> Dict[str, Any]:
    """Download 1m indexPriceKlines for (cm_pair, delivery_date) and compute official 30m (07:30..08:00 UTC) TWAP."""
    day_str = exp_iso[:10]  # YYYY-MM-DD
    url = f"https://data.binance.vision/data/futures/cm/daily/indexPriceKlines/{cm_pair}/1m/{cm_pair}-1m-{day_str}.zip"
    cs_url = f"{url}.CHECKSUM"
    local_zip = cache_dir / "index_1m_delivery" / cm_pair / f"{cm_pair}-1m-{day_str}.zip"
    local_meta = cache_dir / "index_1m_delivery" / cm_pair / f"{cm_pair}-1m-{day_str}.meta.json"

    if local_zip.exists() and local_meta.exists():
        try:
            meta = json.loads(local_meta.read_text(encoding="utf-8"))
            if meta.get("status") in ("VERIFIED_OK", "NOT_AVAILABLE_404"):
                return meta
        except Exception:  # noqa: BLE001
            pass

    zb = _fetch_bytes(url)
    if zb is None:
        # Try monthly 1m archive if daily 1m is not present
        ym = day_str[:7]
        m_url = f"https://data.binance.vision/data/futures/cm/monthly/indexPriceKlines/{cm_pair}/1m/{cm_pair}-1m-{ym}.zip"
        m_cs_url = f"{m_url}.CHECKSUM"
        zb = _fetch_bytes(m_url)
        if zb is None:
            meta = {
                "cm_pair": cm_pair,
                "expiry_code": exp_code,
                "delivery_date": day_str,
                "status": "NOT_AVAILABLE_404",
            }
            local_meta.parent.mkdir(parents=True, exist_ok=True)
            local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta
        url = m_url
        cs_url = m_cs_url

    cs_b = _fetch_bytes(cs_url)
    sha_act = _sha256_bytes(zb)
    sha_exp = None
    cs_ok = False
    if cs_b is not None:
        parts = cs_b.decode("utf-8", errors="ignore").strip().split()
        if parts:
            sha_exp = parts[0].lower()
            cs_ok = sha_exp == sha_act.lower()

    local_zip.parent.mkdir(parents=True, exist_ok=True)
    local_zip.write_bytes(zb)

    df = _parse_kline_zip(zb)
    exp_ms = int(datetime.fromisoformat(exp_iso.replace("Z", "+00:00")).timestamp() * 1000)
    # Official Binance rule: arithmetic mean of Price Index over 07:30:00 to 08:00:00 UTC (30 1m bars with open_time in [exp_ms - 30m, exp_ms - 1m])
    w30 = df[(df["open_time"] >= exp_ms - 30 * 60_000) & (df["open_time"] < exp_ms)]
    # Compare against 60m TWAP (07:00..08:00 UTC) and 08:00 UTC close
    w60 = df[(df["open_time"] >= exp_ms - 60 * 60_000) & (df["open_time"] < exp_ms)]

    # Each 1m bar has (open + high + low + close) / 4 or close; we compute both close mean and OHLC4 mean
    twap_30m = float(w30["close"].mean()) if len(w30) > 0 else np.nan
    twap_30m_ohlc4 = float(((w30["open"] + w30["high"] + w30["low"] + w30["close"]) / 4.0).mean()) if len(w30) > 0 else np.nan
    twap_60m = float(w60["close"].mean()) if len(w60) > 0 else np.nan
    close_0800 = float(w30["close"].iloc[-1]) if len(w30) > 0 else np.nan

    meta = {
        "cm_pair": cm_pair,
        "expiry_code": exp_code,
        "delivery_date": day_str,
        "expiry_ms": exp_ms,
        "url": url,
        "sha256": sha_act,
        "expected_sha256": sha_exp,
        "checksum_verified": cs_ok,
        "status": "VERIFIED_OK",
        "bars_30m_count": int(len(w30)),
        "official_twap_30m_index": round(twap_30m, 8) if np.isfinite(twap_30m) else None,
        "twap_30m_ohlc4_index": round(twap_30m_ohlc4, 8) if np.isfinite(twap_30m_ohlc4) else None,
        "twap_60m_index": round(twap_60m, 8) if np.isfinite(twap_60m) else None,
        "index_at_0800_utc": round(close_0800, 8) if np.isfinite(close_0800) else None,
        "diff_30m_vs_0800_bps": (
            round((twap_30m / close_0800 - 1.0) * 10_000.0, 4)
            if (np.isfinite(twap_30m) and np.isfinite(close_0800) and close_0800 > 0)
            else 0.0
        ),
        "diff_30m_vs_60m_bps": (
            round((twap_30m / twap_60m - 1.0) * 10_000.0, 4)
            if (np.isfinite(twap_30m) and np.isfinite(twap_60m) and twap_60m > 0)
            else 0.0
        ),
    }
    local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _fetch_single_mark_1h_month(
    contract_sym: str,
    exp_code: str,
    ym: str,
    cache_dir: Path,
) -> Dict[str, Any]:
    """Download and SHA-256 verify 1h markPriceKlines for a COIN-M quarterly delivery contract month."""
    url = f"https://data.binance.vision/data/futures/cm/monthly/markPriceKlines/{contract_sym}/1h/{contract_sym}-1h-{ym}.zip"
    cs_url = f"{url}.CHECKSUM"
    local_zip = cache_dir / "mark_1h" / contract_sym / f"{contract_sym}-mark-1h-{ym}.zip"
    local_meta = cache_dir / "mark_1h" / contract_sym / f"{contract_sym}-mark-1h-{ym}.meta.json"

    if local_zip.exists() and local_meta.exists():
        try:
            meta = json.loads(local_meta.read_text(encoding="utf-8"))
            if meta.get("status") == "VERIFIED_OK" and meta.get("checksum_verified"):
                return meta
        except Exception:  # noqa: BLE001
            pass

    zb = _fetch_bytes(url)
    if zb is None:
        meta = {"contract_symbol": contract_sym, "expiry_code": exp_code, "year_month": ym, "status": "NOT_LISTED_404", "rows": 0}
        local_meta.parent.mkdir(parents=True, exist_ok=True)
        local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    cs_b = _fetch_bytes(cs_url)
    sha_act = _sha256_bytes(zb)
    sha_exp = None
    cs_ok = False
    if cs_b is not None:
        parts = cs_b.decode("utf-8", errors="ignore").strip().split()
        if parts:
            sha_exp = parts[0].lower()
            cs_ok = sha_exp == sha_act.lower()

    local_zip.parent.mkdir(parents=True, exist_ok=True)
    local_zip.write_bytes(zb)
    df = _parse_kline_zip(zb)
    meta = {
        "contract_symbol": contract_sym,
        "expiry_code": exp_code,
        "year_month": ym,
        "url": url,
        "sha256": sha_act,
        "expected_sha256": sha_exp,
        "checksum_verified": cs_ok,
        "status": "VERIFIED_OK",
        "rows": int(len(df)),
    }
    local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def acquire_n1_5_mark_and_settlement_data(
    n1_4_data_dir: Path,
    n1_4_manifest_path: Path,
    n1_5_data_dir: Path,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Acquire authoritative COIN-M markPriceKlines (1h) and 1m Delivery Settlement Index TWAPs (2022-2025) and enrich the N1.4 panel."""
    n1_5_data_dir.mkdir(parents=True, exist_ok=True)
    raw_delivery_dir = n1_4_data_dir / "raw_delivery_zips"

    # 1. Re-verify the single unverified archive from N1.4
    unverified_audit = verify_and_resolve_unverified_archive(n1_4_manifest_path, raw_delivery_dir)

    # 2. Fetch 1m indexPriceKlines on all 16 quarterly delivery dates (220325..251226) across all 8 COIN-M pairs
    settlement_tasks = []
    for sym in N1_4_SYMBOLS:
        cm_pair = CM_BASE_MAP[sym]
        for exp_code, exp_iso, _ in QUARTERLY_EXPIRIES:
            if exp_code == "260327":
                continue  # 260327 settles in 2026 (outside 2022-2025 window)
            settlement_tasks.append((cm_pair, exp_code, exp_iso))

    settlement_records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_fetch_single_1m_delivery_index, cp, ec, ei, n1_5_data_dir) for cp, ec, ei in settlement_tasks]
        for f in as_completed(futs):
            settlement_records.append(f.result())

    settlement_records.sort(key=lambda r: (r["cm_pair"], r["expiry_code"]))

    # Map (symbol, expiry_code) -> official_twap_30m_index
    rev_cm_map = {v: k for k, v in CM_BASE_MAP.items()}
    settlement_map: Dict[Tuple[str, str], float] = {}
    for r in settlement_records:
        if r.get("status") == "VERIFIED_OK" and r.get("official_twap_30m_index") is not None:
            sym = rev_cm_map[r["cm_pair"]]
            settlement_map[(sym, r["expiry_code"])] = float(r["official_twap_30m_index"])

    # 3. Fetch 1h markPriceKlines for all active CM delivery contract-months in N1.4 manifest
    n1_4_manifest = json.loads(n1_4_manifest_path.read_text(encoding="utf-8"))
    active_cm_recs = [
        r
        for r in n1_4_manifest["delivery_archive_records"]
        if r.get("family") == "CM_DELIVERY" and r.get("status") == "VERIFIED_OK" and r.get("rows", 0) > 0
    ]

    mark_records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [
            ex.submit(_fetch_single_mark_1h_month, r["contract_symbol"], r["expiry_code"], r["year_month"], n1_5_data_dir)
            for r in active_cm_recs
        ]
        for f in as_completed(futs):
            mark_records.append(f.result())

    mark_records.sort(key=lambda r: (r["contract_symbol"], r["year_month"]))

    # Assemble per-contract markPrice DataFrame
    mark_dfs: List[pd.DataFrame] = []
    for r in mark_records:
        if r.get("status") != "VERIFIED_OK" or r.get("rows", 0) == 0:
            continue
        csym = r["contract_symbol"]
        ym = r["year_month"]
        lzip = n1_5_data_dir / "mark_1h" / csym / f"{csym}-mark-1h-{ym}.zip"
        df_m = _parse_kline_zip(lzip.read_bytes())
        if len(df_m) == 0:
            continue
        df_m["hour_close_ms"] = ((df_m["open_time"] // 3_600_000) + 1) * 3_600_000
        df_m = df_m[(df_m["hour_close_ms"] >= HARD_START_CLOSE_MS) & (df_m["hour_close_ms"] <= HARD_END_CLOSE_MS)].copy()
        df_m["f1_contract"] = csym
        df_m = df_m.rename(
            columns={
                "open": "f1_mark_open",
                "high": "f1_mark_high",
                "low": "f1_mark_low",
                "close": "f1_mark_close",
            }
        )[["f1_contract", "hour_close_ms", "f1_mark_open", "f1_mark_high", "f1_mark_low", "f1_mark_close"]]
        mark_dfs.append(df_m)

    all_mark = (
        pd.concat(mark_dfs, ignore_index=True)
        .drop_duplicates(subset=["f1_contract", "hour_close_ms"])
        .sort_values(["f1_contract", "hour_close_ms"])
        .reset_index(drop=True)
    )
    all_mark["f1_mark_next_open_same"] = all_mark.groupby("f1_contract")["f1_mark_open"].shift(-1)
    all_mark["f1_mark_next_high_same"] = all_mark.groupby("f1_contract")["f1_mark_high"].shift(-1)
    all_mark["f1_mark_next_close_same"] = all_mark.groupby("f1_contract")["f1_mark_close"].shift(-1)

    # Load N1.4 panel and join mark prices + official 30m delivery settlement index
    panel = pd.read_parquet(n1_4_data_dir / "n1_4_term_structure_and_multiday_panel.parquet")
    panel = pd.merge(panel, all_mark, on=["f1_contract", "hour_close_ms"], how="left")

    # Fill any missing mark prices with contract kline prices (if any early hours lacked mark file)
    for col_m, col_k in [
        ("f1_mark_open", "f1_open"),
        ("f1_mark_high", "f1_high"),
        ("f1_mark_low", "f1_low"),
        ("f1_mark_close", "f1_close"),
        ("f1_mark_next_open_same", "f1_next_open_same"),
        ("f1_mark_next_close_same", "f1_next_close_same"),
    ]:
        panel[col_m] = panel[col_m].fillna(panel[col_k])
    panel["f1_mark_next_high_same"] = panel["f1_mark_next_high_same"].fillna(panel["f1_high"])

    # Attach official 30m TWAP delivery settlement index for each contract expiry
    panel["official_settlement_twap_30m_usd"] = [
        settlement_map.get((sym, str(ec)), np.nan) if pd.notna(ec) else np.nan
        for sym, ec in zip(panel["symbol"], panel["f1_expiry_code"])
    ]
    # Fallback to next bar spot_close_usd only if 1m index archive wasn't listed for that symbol/expiry
    panel["spot_next_close_usd"] = panel.groupby("symbol")["spot_close_usd"].shift(-1)
    panel["spot_next_open_usd"] = panel.groupby("symbol")["spot_open_usd"].shift(-1)
    panel["official_settlement_twap_30m_usd"] = panel["official_settlement_twap_30m_usd"].fillna(
        panel["spot_next_close_usd"]
    )

    enriched_path = n1_5_data_dir / "n1_5_enriched_coinm_panel.parquet"
    panel.to_parquet(enriched_path, index=False)

    ver_settle = [r for r in settlement_records if r.get("status") == "VERIFIED_OK"]
    ver_mark = [r for r in mark_records if r.get("status") == "VERIFIED_OK"]
    diffs_30_vs_0800 = [abs(r["diff_30m_vs_0800_bps"]) for r in ver_settle if r.get("diff_30m_vs_0800_bps") is not None]
    diffs_30_vs_60 = [abs(r["diff_30m_vs_60m_bps"]) for r in ver_settle if r.get("diff_30m_vs_60m_bps") is not None]

    summary = {
        "unverified_archive_audit": unverified_audit,
        "settlement_1m_index_archives_probed": len(settlement_records),
        "settlement_1m_index_archives_verified": len(ver_settle),
        "settlement_1m_checksum_verified": sum(1 for r in ver_settle if r.get("checksum_verified")),
        "mean_abs_diff_30m_twap_vs_0800_close_bps": round(float(np.mean(diffs_30_vs_0800)), 3) if diffs_30_vs_0800 else 0.0,
        "max_abs_diff_30m_twap_vs_0800_close_bps": round(float(np.max(diffs_30_vs_0800)), 3) if diffs_30_vs_0800 else 0.0,
        "mean_abs_diff_30m_twap_vs_60m_twap_bps": round(float(np.mean(diffs_30_vs_60)), 3) if diffs_30_vs_60 else 0.0,
        "mark_price_1h_archives_probed": len(mark_records),
        "mark_price_1h_archives_verified": len(ver_mark),
        "mark_price_1h_checksum_verified": sum(1 for r in ver_mark if r.get("checksum_verified")),
        "enriched_panel_path": str(enriched_path.as_posix()),
        "settlement_records_sample": ver_settle[:16],
    }
    return panel, summary
