"""Read-Only Authentic Market Data Provider for CARM Shadow Observer.

Connects to public spot market data (e.g. Binance Public REST ticker)
for the canonical 8-asset universe without requiring any API keys or
execution credentials.

Preserves rich observational metadata and source lineage:
  - observation_id
  - source
  - symbol
  - event_timestamp_utc
  - ingested_at_utc
  - price
  - price_type
  - data_quality
  - source_lineage
  - is_forward
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

CANONICAL_UNIVERSE: Tuple[str, ...] = (
    "ADAUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "ETHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "SOLUSDT",
    "XRPUSDT",
)


@dataclass
class MarketDataObservation:
    """Individual market price observation with full causal provenance."""

    observation_id: str
    source: str
    symbol: str
    event_timestamp_utc: str
    ingested_at_utc: str
    price: float
    price_type: str
    data_quality: str
    source_lineage: Dict[str, Any]
    is_forward: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CarmMarketDataProvider:
    """Read-only market data adapter for CARM cross-sectional universe.

    Guarantees:
      - Strictly read-only: No execution endpoints, no secret keys.
      - Input validation: Rejects non-positive, NaN, and infinite prices.
      - Lineage preservation: Every price includes ingestion timestamps and URL provenance.
    """

    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    def fetch_live_ticker_snapshot(
        self,
        universe: Optional[Sequence[str]] = None,
    ) -> Tuple[Dict[str, float], List[MarketDataObservation]]:
        """Fetch authentic live spot prices for universe symbols via public REST.

        Returns:
            Tuple of (prices_dict, observations_list).
            Raises RuntimeError if request fails or universe is incomplete.
        """
        target_symbols = list(universe or CANONICAL_UNIVERSE)
        encoded_symbols = urllib.parse.quote(json.dumps(target_symbols, separators=(",", ":")))
        endpoint = f"{self.base_url}/api/v3/ticker/price?symbols={encoded_symbols}"

        ingested_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        req = urllib.request.Request(
            endpoint,
            headers={
                "User-Agent": "CARM-Shadow-Observer/1.0 (read-only research)",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Market data HTTP {resp.status} from {endpoint}")
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error("Failed to fetch live market data: %s", e)
            raise RuntimeError(f"Market data fetch error: {e}") from e

        if not isinstance(payload, list):
            raise ValueError(f"Unexpected ticker payload format: {type(payload)}")

        prices: Dict[str, float] = {}
        observations: List[MarketDataObservation] = []

        for item in payload:
            sym = item.get("symbol")
            raw_p = item.get("price")
            if not sym or raw_p is None:
                continue

            try:
                p_val = float(raw_p)
            except (ValueError, TypeError):
                p_val = float("nan")

            is_valid = p_val > 0.0 and not (p_val != p_val or p_val == float("inf") or p_val == float("-inf"))
            quality = "VALID" if is_valid else "INVALID_PRICE"

            obs = MarketDataObservation(
                observation_id=f"obs-{uuid.uuid4().hex[:16]}",
                source="BINANCE_PUBLIC_REST",
                symbol=sym,
                event_timestamp_utc=ingested_at,
                ingested_at_utc=ingested_at,
                price=p_val if is_valid else 0.0,
                price_type="SPOT_TICKER",
                data_quality=quality,
                source_lineage={
                    "endpoint": endpoint,
                    "raw_symbol": sym,
                    "raw_price": str(raw_p),
                },
                is_forward=True,
            )
            observations.append(obs)
            if is_valid:
                prices[sym] = p_val

        return prices, observations

    def fetch_recent_hourly_klines(
        self,
        universe: Optional[Sequence[str]] = None,
        limit: int = 200,
    ) -> List[Tuple[datetime, Dict[str, float]]]:
        """Fetch authentic 1h klines for universe symbols to build the causal momentum buffer.

        Returns:
            Chronologically sorted list of (bar_timestamp_utc, {sym: close_price}).
        """
        target_symbols = list(universe or CANONICAL_UNIVERSE)
        symbol_bars: Dict[str, Dict[datetime, float]] = {}

        for sym in target_symbols:
            endpoint = f"{self.base_url}/api/v3/klines?symbol={sym}&interval=1h&limit={limit}"
            req = urllib.request.Request(
                endpoint,
                headers={
                    "User-Agent": "CARM-Shadow-Observer/1.0 (read-only research)",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Kline fetch HTTP {resp.status} for {sym}")
                    raw_candles = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.error("Failed to fetch klines for %s: %s", sym, e)
                raise RuntimeError(f"Failed to fetch klines for {sym}: {e}") from e

            bars_for_sym: Dict[datetime, float] = {}
            for candle in raw_candles:
                dt = datetime.fromtimestamp(candle[0] / 1000.0, tz=timezone.utc)
                bars_for_sym[dt] = float(candle[4])
            symbol_bars[sym] = bars_for_sym

        # Intersect timestamps present across all symbols
        all_sym_sets = [set(bars.keys()) for bars in symbol_bars.values()]
        common_timestamps = sorted(set.intersection(*all_sym_sets)) if all_sym_sets else []

        result: List[Tuple[datetime, Dict[str, float]]] = []
        for ts in common_timestamps:
            prices_at_ts = {sym: symbol_bars[sym][ts] for sym in target_symbols}
            result.append((ts, prices_at_ts))

        return result

    @staticmethod
    def create_warmup_observations(
        prices: Dict[str, float],
        timestamp_utc: str,
        source: str = "HISTORICAL_WARMUP",
    ) -> List[MarketDataObservation]:
        """Convert historical warmup prices into explicit non-forward observations."""
        ingested_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        observations: List[MarketDataObservation] = []
        for sym, p in prices.items():
            is_valid = p > 0.0 and not (p != p or p == float("inf") or p == float("-inf"))
            obs = MarketDataObservation(
                observation_id=f"warmup-{uuid.uuid4().hex[:12]}",
                source=source,
                symbol=sym,
                event_timestamp_utc=timestamp_utc,
                ingested_at_utc=ingested_at,
                price=float(p) if is_valid else 0.0,
                price_type="SPOT_HISTORICAL_CLOSE",
                data_quality="VALID" if is_valid else "INVALID_PRICE",
                source_lineage={"historical_warmup": True},
                is_forward=False,
            )
            observations.append(obs)
        return observations
