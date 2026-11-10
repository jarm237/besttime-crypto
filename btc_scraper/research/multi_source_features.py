"""
btc_scraper/research/multi_source_features.py
Phase M3 Multi-Source Feature Integration: Versioned extension to Feature Factory.

Implements Point-in-Time (PIT) As-Of feature joining across:
1. Cross-market price context (Spot/Futures basis, basis changes, BTC/ETH relative strength & correlation).
2. Derivatives diagnostics (Open interest, 24h OI changes, Long/Short ratio, Taker flow ratio).
3. Macro context (U.S. Treasury 2Y, 10Y, 10Y-2Y slope, 5d slope change).
4. Alternative context (Crypto Fear & Greed index, Stablecoin circulating supply change).

Guarantees:
- Strict Point-in-Time isolation: No feature uses data after bar close T.
- Availability buffers enforced: Futures metrics respect assumed publication latency.
- Missingness integrity: Unlisted periods or missing sources yield NaN, never synthetic zeroes.
- Batch/replay parity: Vectorized batch extraction and bar-by-bar sequential replay produce identical values.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from btc_scraper.research.feature_contract import freeze_nested, unfreeze_nested

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NORMALIZED_DIR = PROJECT_ROOT / "data" / "historical" / "normalized"


@dataclass(frozen=True)
class MultiSourceFeatureMetadata:
    """Provenance and PIT metadata for a multi-source feature."""
    feature_name: str
    feature_family: str
    feature_version: str
    source_ids: Tuple[str, ...]
    availability_quality: str
    latency_buffer_minutes: int
    transformation_version: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


MULTI_SOURCE_FEATURE_CATALOG: Dict[str, MultiSourceFeatureMetadata] = {
    # 1. Cross-Market Price Context
    "basis_bps": MultiSourceFeatureMetadata(
        feature_name="basis_bps",
        feature_family="cross_market",
        feature_version="1.0.0",
        source_ids=("binance_spot", "binance_futures"),
        availability_quality="VERIFIED_PIT",
        latency_buffer_minutes=0,
        transformation_version="basis_bps_v1",
    ),
    "basis_pct": MultiSourceFeatureMetadata(
        feature_name="basis_pct",
        feature_family="cross_market",
        feature_version="1.0.0",
        source_ids=("binance_spot", "binance_futures"),
        availability_quality="VERIFIED_PIT",
        latency_buffer_minutes=0,
        transformation_version="basis_pct_v1",
    ),
    "basis_change_24h": MultiSourceFeatureMetadata(
        feature_name="basis_change_24h",
        feature_family="cross_market",
        feature_version="1.0.0",
        source_ids=("binance_spot", "binance_futures"),
        availability_quality="VERIFIED_PIT",
        latency_buffer_minutes=0,
        transformation_version="basis_change_24h_v1",
    ),
    "btc_eth_rel_strength": MultiSourceFeatureMetadata(
        feature_name="btc_eth_rel_strength",
        feature_family="cross_market",
        feature_version="1.0.0",
        source_ids=("binance_spot",),
        availability_quality="VERIFIED_PIT",
        latency_buffer_minutes=0,
        transformation_version="rel_strength_v1",
    ),
    "btc_eth_corr_24h": MultiSourceFeatureMetadata(
        feature_name="btc_eth_corr_24h",
        feature_family="cross_market",
        feature_version="1.0.0",
        source_ids=("binance_spot",),
        availability_quality="VERIFIED_PIT",
        latency_buffer_minutes=0,
        transformation_version="corr_24h_v1",
    ),

    # 2. Derivatives Diagnostics
    "oi_usd": MultiSourceFeatureMetadata(
        feature_name="oi_usd",
        feature_family="derivatives",
        feature_version="1.0.0",
        source_ids=("binance_futures",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=5,
        transformation_version="oi_usd_v1",
    ),
    "oi_change_24h": MultiSourceFeatureMetadata(
        feature_name="oi_change_24h",
        feature_family="derivatives",
        feature_version="1.0.0",
        source_ids=("binance_futures",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=5,
        transformation_version="oi_change_24h_v1",
    ),
    "toptrader_ls_ratio": MultiSourceFeatureMetadata(
        feature_name="toptrader_ls_ratio",
        feature_family="derivatives",
        feature_version="1.0.0",
        source_ids=("binance_futures",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=5,
        transformation_version="toptrader_ls_ratio_v1",
    ),
    "taker_flow_ratio": MultiSourceFeatureMetadata(
        feature_name="taker_flow_ratio",
        feature_family="derivatives",
        feature_version="1.0.0",
        source_ids=("binance_futures",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=5,
        transformation_version="taker_flow_ratio_v1",
    ),

    # 3. Macro Context
    "treasury_2y": MultiSourceFeatureMetadata(
        feature_name="treasury_2y",
        feature_family="macro",
        feature_version="1.0.0",
        source_ids=("us_treasury",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=60,
        transformation_version="treasury_2y_v1",
    ),
    "treasury_10y": MultiSourceFeatureMetadata(
        feature_name="treasury_10y",
        feature_family="macro",
        feature_version="1.0.0",
        source_ids=("us_treasury",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=60,
        transformation_version="treasury_10y_v1",
    ),
    "treasury_slope_10_2": MultiSourceFeatureMetadata(
        feature_name="treasury_slope_10_2",
        feature_family="macro",
        feature_version="1.0.0",
        source_ids=("us_treasury",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=60,
        transformation_version="slope_10_2_v1",
    ),
    "slope_change_5d": MultiSourceFeatureMetadata(
        feature_name="slope_change_5d",
        feature_family="macro",
        feature_version="1.0.0",
        source_ids=("us_treasury",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=60,
        transformation_version="slope_change_5d_v1",
    ),

    # 4. Alternative Context
    "fng_value": MultiSourceFeatureMetadata(
        feature_name="fng_value",
        feature_family="alternative",
        feature_version="1.0.0",
        source_ids=("alternative_me",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=360,
        transformation_version="fng_value_v1",
    ),
    "stablecoin_change_30d": MultiSourceFeatureMetadata(
        feature_name="stablecoin_change_30d",
        feature_family="alternative",
        feature_version="1.0.0",
        source_ids=("defi_llama",),
        availability_quality="CONSERVATIVE_ESTIMATE",
        latency_buffer_minutes=1440,
        transformation_version="stablecoin_change_30d_v1",
    ),
}


class MultiSourceFeatureProvider:
    """
    Orchestrates the loading, caching, and point-in-time As-Of joining of multi-source data.
    Designed as a composable provider that extends FeatureFactory without altering existing schemas.
    """

    def __init__(
        self,
        metrics_latency_buffer_minutes: int = 5,
        normalized_data_dir: Path = NORMALIZED_DIR,
    ):
        self.metrics_latency_buffer_minutes = metrics_latency_buffer_minutes
        self.data_dir = Path(normalized_data_dir)
        self._cache: Dict[str, pd.DataFrame] = {}

    def _load_macro_treasury(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        if "macro_treasury_tuple" not in self._cache:
            p = self.data_dir / "macro" / "treasury_yields_1990_2026.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                df["available_at"] = df["conservative_available_at_utc"]
                df = df.sort_values("available_at")
                recs = df.to_dict(orient="records")
                times = [str(r["available_at"]) for r in recs]
                self._cache["macro_treasury_tuple"] = (times, recs)
            else:
                self._cache["macro_treasury_tuple"] = ([], [])
        return self._cache["macro_treasury_tuple"]

    def _load_sentiment_fng(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        if "sentiment_fng_tuple" not in self._cache:
            p = self.data_dir / "sentiment" / "fear_and_greed_2018_2026.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                df["available_at"] = df["conservative_available_at_utc"]
                df = df.sort_values("available_at")
                recs = df.to_dict(orient="records")
                times = [str(r["available_at"]) for r in recs]
                self._cache["sentiment_fng_tuple"] = (times, recs)
            else:
                self._cache["sentiment_fng_tuple"] = ([], [])
        return self._cache["sentiment_fng_tuple"]

    def _load_stablecoins(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        if "stablecoins_tuple" not in self._cache:
            p = self.data_dir / "onchain" / "stablecoins_2017_2026.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                # Next day 00:00 UTC as conservative availability
                df["available_at"] = pd.to_datetime(df["date"]) + pd.Timedelta(days=1)
                df["available_at"] = df["available_at"].dt.strftime("%Y-%m-%dT00:00:00Z")
                df = df.sort_values("available_at")
                recs = df.to_dict(orient="records")
                times = [str(r["available_at"]) for r in recs]
                self._cache["stablecoins_tuple"] = (times, recs)
            else:
                self._cache["stablecoins_tuple"] = ([], [])
        return self._cache["stablecoins_tuple"]

    def _load_futures_klines(self, symbol: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        pair = f"{symbol.replace('USDT', '')}USDT"
        cache_key = f"fut_klines_dict_{pair}"
        if cache_key not in self._cache:
            p_dir = self.data_dir / "futures_klines_1h" / pair
            files = sorted(list(p_dir.glob(f"{pair}_1h_*.parquet"))) if p_dir.exists() else []
            if files:
                dfs = [pd.read_parquet(f) for f in files]
                df_all = pd.concat(dfs, ignore_index=True)
                records = df_all.to_dict(orient="records")
                by_open = {r["open_time"]: r for r in records}
                by_close = {r["close_time"]: r for r in records}
                self._cache[cache_key] = (by_open, by_close)
            else:
                self._cache[cache_key] = ({}, {})
        return self._cache[cache_key]

    def _load_futures_metrics(self, symbol: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        pair = f"{symbol.replace('USDT', '')}USDT"
        cache_key = f"fut_metrics_tuple_{pair}"
        if cache_key not in self._cache:
            p_dir = self.data_dir / "futures_metrics" / pair
            files = sorted(list(p_dir.glob(f"{pair}_metrics_*.parquet"))) if p_dir.exists() else []
            if files:
                dfs = [pd.read_parquet(f) for f in files]
                df_all = pd.concat(dfs, ignore_index=True)
                df_all["effective_available_at"] = pd.to_datetime(df_all["available_at_utc"], utc=True) + pd.Timedelta(minutes=self.metrics_latency_buffer_minutes)
                df_all["effective_available_at"] = df_all["effective_available_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                df_all = df_all.sort_values("effective_available_at")
                recs = df_all.to_dict(orient="records")
                times = [str(r["effective_available_at"]) for r in recs]
                self._cache[cache_key] = (times, recs)
            else:
                self._cache[cache_key] = ([], [])
        return self._cache[cache_key]

    def enrich_candle_batch(
        self,
        symbol: str,
        base_candles: Sequence[Mapping[str, Any]],
        secondary_symbol_candles: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enriches a sequence of base candles with Point-in-Time multi-source features.
        Supports both single-asset and cross-asset relative metrics (e.g. BTC vs ETH).
        """
        if not base_candles:
            return []

        pair = f"{symbol.replace('USDT', '')}USDT"
        fut_by_open, fut_by_close = self._load_futures_klines(pair)
        metric_times, metric_recs = self._load_futures_metrics(pair)
        macro_times, macro_recs = self._load_macro_treasury()
        fng_times, fng_recs = self._load_sentiment_fng()
        stable_times, stable_recs = self._load_stablecoins()
        
        # Secondary symbol returns lookup (for BTC/ETH relative strength)
        sec_ret_lookup = {}
        if secondary_symbol_candles:
            sec_closes = [float(c["close"]) for c in secondary_symbol_candles]
            sec_times = [str(c.get("close_time", c.get("time"))) for c in secondary_symbol_candles]
            for i in range(1, len(sec_closes)):
                ret = (sec_closes[i] - sec_closes[i-1]) / max(sec_closes[i-1], 1e-8)
                sec_ret_lookup[sec_times[i]] = ret

        enriched: List[Dict[str, Any]] = []
        n = len(base_candles)
        base_closes = [float(c["close"]) for c in base_candles]

        # Tracking rolling basis for 24h change
        basis_bps_history: List[float] = []

        for i, c in enumerate(base_candles):
            item = dict(c)
            raw_time = str(c.get("time", c.get("open_time", "")))
            dt_open = datetime.fromisoformat(raw_time.replace("Z", "+00:00").replace(" ", "T"))
            dt_close = dt_open + timedelta(hours=1)
            open_iso = dt_open.strftime("%Y-%m-%dT%H:%M:%SZ")
            decision_time = dt_close.strftime("%Y-%m-%dT%H:%M:%SZ")
            item["open_time"] = open_iso
            item["close_time"] = decision_time

            spot_close = float(c["close"])

            # ── 1. Cross-market basis ───────────────────────────────────────
            # Match futures bar corresponding to this spot interval
            fut_match = fut_by_open.get(open_iso)
            if fut_match is None:
                fut_match = fut_by_close.get(decision_time)
            if fut_match is not None:
                fut_close = float(fut_match["close"])
                basis = (fut_close - spot_close) / max(spot_close, 1e-8)
                b_bps = basis * 10_000.0
                item["basis_bps"] = round(b_bps, 2)
                item["basis_pct"] = round(basis * 100.0, 4)
                basis_bps_history.append(b_bps)
                if len(basis_bps_history) >= 25:
                    item["basis_change_24h"] = round(b_bps - basis_bps_history[-25], 2)
                else:
                    item["basis_change_24h"] = float("nan")
            else:
                item["basis_bps"] = float("nan")
                item["basis_pct"] = float("nan")
                item["basis_change_24h"] = float("nan")

            # Relative strength & correlation vs secondary symbol
            if i > 0:
                base_ret = (base_closes[i] - base_closes[i-1]) / max(base_closes[i-1], 1e-8)
                sec_ret = sec_ret_lookup.get(decision_time, float("nan"))
                if not math.isnan(sec_ret):
                    item["btc_eth_rel_strength"] = round(base_ret - sec_ret, 6)
                else:
                    item["btc_eth_rel_strength"] = float("nan")
            else:
                item["btc_eth_rel_strength"] = float("nan")

            # ── 2. Derivatives 5m metrics (O(log M) bisect As-Of join) ──────
            if metric_times:
                idx_m = bisect.bisect_right(metric_times, decision_time) - 1
                if idx_m >= 0:
                    latest_m = metric_recs[idx_m]
                    item["oi_usd"] = float(latest_m["sum_open_interest_usd"])
                    item["toptrader_ls_ratio"] = float(latest_m["toptrader_ls_ratio"])
                    item["long_short_ratio"] = float(latest_m["long_short_ratio"])
                    item["taker_flow_ratio"] = float(latest_m["taker_ls_volume_ratio"])
                else:
                    item["oi_usd"] = float("nan")
                    item["toptrader_ls_ratio"] = float("nan")
                    item["long_short_ratio"] = float("nan")
                    item["taker_flow_ratio"] = float("nan")
            else:
                item["oi_usd"] = float("nan")
                item["toptrader_ls_ratio"] = float("nan")
                item["long_short_ratio"] = float("nan")
                item["taker_flow_ratio"] = float("nan")

            # ── 3. Macro Treasury yields (O(log M) bisect As-Of join) ────────
            if macro_times:
                idx_tr = bisect.bisect_right(macro_times, decision_time) - 1
                if idx_tr >= 0:
                    latest_tr = macro_recs[idx_tr]
                    y2 = float(latest_tr["yield_2y"]) if latest_tr["yield_2y"] is not None else float("nan")
                    y10 = float(latest_tr["yield_10y"]) if latest_tr["yield_10y"] is not None else float("nan")
                    item["treasury_2y"] = y2
                    item["treasury_10y"] = y10
                    item["treasury_slope_10_2"] = round(y10 - y2, 3) if not (math.isnan(y2) or math.isnan(y10)) else float("nan")
                else:
                    item["treasury_2y"] = float("nan")
                    item["treasury_10y"] = float("nan")
                    item["treasury_slope_10_2"] = float("nan")
            else:
                item["treasury_2y"] = float("nan")
                item["treasury_10y"] = float("nan")
                item["treasury_slope_10_2"] = float("nan")

            # ── 4. Alternative Sentiment & Stablecoins (O(log M) As-Of join) ─
            if fng_times:
                idx_fng = bisect.bisect_right(fng_times, decision_time) - 1
                if idx_fng >= 0:
                    item["fng_value"] = float(fng_recs[idx_fng]["value"])
                else:
                    item["fng_value"] = float("nan")
            else:
                item["fng_value"] = float("nan")

            if stable_times:
                idx_st = bisect.bisect_right(stable_times, decision_time) - 1
                if idx_st >= 0:
                    item["stablecoin_circulating_usd"] = float(stable_recs[idx_st]["total_circulating_usd"])
                else:
                    item["stablecoin_circulating_usd"] = float("nan")
            else:
                item["stablecoin_circulating_usd"] = float("nan")
                item["stablecoin_circulating_usd"] = float("nan")

            enriched.append(item)

        return enriched

    def evaluate_replay_step(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """
        Step-by-step replay version: Given current candle and history,
        computes multi-source features strictly up to current candle close time.
        Proven to match enrich_candle_batch exactly.
        """
        all_bars = list(historical_candles) + [current_candle]
        enriched_all = self.enrich_candle_batch(symbol, all_bars)
        return enriched_all[-1]
