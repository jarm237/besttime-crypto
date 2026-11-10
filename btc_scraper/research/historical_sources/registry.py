"""
btc_scraper/research/historical_sources/registry.py
Central registry for historical data adapters and capability tracking.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from btc_scraper.research.historical_sources.contracts import DatasetType


ADAPTER_REGISTRY: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("binance_vision", DatasetType.SPOT_CANDLE.value): {
        "description": "Binance Public Data Vision Spot monthly/daily klines archives with SHA-256 checksums",
        "historical_depth": "2017-08 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("binance_vision", DatasetType.FUTURES_CANDLE.value): {
        "description": "Binance Public Data Vision USD-M Futures klines archives with SHA-256 checksums",
        "historical_depth": "2019-09 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("binance_vision", DatasetType.AGG_TRADE.value): {
        "description": "Binance Public Data Vision Spot & Futures aggTrades tick-level archives",
        "historical_depth": "2017-08 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("binance_vision", DatasetType.FUNDING_RATE.value): {
        "description": "Binance Public Data Vision USD-M monthly funding rate settlement archives",
        "historical_depth": "2019-09 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("binance_vision", DatasetType.FUTURES_METRIC.value): {
        "description": "Binance USD-M 5-minute Open Interest, Long/Short ratios, and Taker Volume metrics",
        "historical_depth": "2021-12 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "CONSERVATIVE_ESTIMATE",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("okx_rest", DatasetType.SPOT_CANDLE.value): {
        "description": "OKX REST historical candles API (paginated, recent months retention)",
        "historical_depth": "Rolling ~3-6 months free",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_LIMITED_HISTORICAL",
    },
    ("okx_rest", DatasetType.FUNDING_RATE.value): {
        "description": "OKX REST historical perpetual swap funding rate settlements",
        "historical_depth": "Rolling ~3-6 months free",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "VERIFIED_PIT",
        "recommended_disposition": "VERIFIED_LIMITED_HISTORICAL",
    },
    ("us_treasury", DatasetType.MACRO_YIELD.value): {
        "description": "U.S. Department of the Treasury official daily par yield curve rates (home.treasury.gov)",
        "historical_depth": "1990 -> 2026-06",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "CONSERVATIVE_ESTIMATE",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("alternative_me", DatasetType.MARKET_SENTIMENT.value): {
        "description": "Alternative.me Crypto Fear & Greed Index daily time series",
        "historical_depth": "2018-02 -> Present",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "CONSERVATIVE_ESTIMATE",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
    ("defi_llama", DatasetType.ONCHAIN_STABLECOIN.value): {
        "description": "DefiLlama historical global pegged stablecoins circulating volume & TVL",
        "historical_depth": "2017-09 -> Present",
        "free_access": True,
        "requires_auth": False,
        "pit_quality": "CONSERVATIVE_ESTIMATE",
        "recommended_disposition": "VERIFIED_FREE_HISTORICAL",
    },
}


def get_adapter_capability(source_id: str, dataset_type: str) -> Optional[Dict[str, Any]]:
    return ADAPTER_REGISTRY.get((source_id, dataset_type))
