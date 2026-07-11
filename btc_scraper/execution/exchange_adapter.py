"""
btc_scraper/execution/exchange_adapter.py
Phase 1 — Task 1.2: ExchangeAdapter

Isolated write/read adapter for the exchange layer.
RULES:
  - Only ExecutionEngine may hold a WriteAdapter instance.
  - All other modules must use ReadOnlyAdapter (read-only queries).
  - Direct CCXTClient write calls outside ExecutionEngine are FORBIDDEN.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ── Base interface ─────────────────────────────────────────────────────────────

class BaseExchangeAdapter(ABC):
    """Abstract interface shared by read-only and write adapters."""

    @abstractmethod
    async def get_symbol_price(self, symbol: str) -> float:
        ...

    @abstractmethod
    async def get_usdt_balance(self) -> float:
        ...

    @abstractmethod
    async def ping(self) -> bool:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ── Read-Only Adapter ──────────────────────────────────────────────────────────

class ReadOnlyExchangeAdapter(BaseExchangeAdapter):
    """
    Safe adapter for modules that only need market data / balance reads.
    Write methods raise PermissionError to prevent accidental direct orders.
    """

    def __init__(self, ccxt_client=None):
        self._client = ccxt_client

    async def get_symbol_price(self, symbol: str) -> float:
        if self._client is None:
            return 0.0
        return await self._client.get_symbol_price(symbol)

    async def get_usdt_balance(self) -> float:
        if self._client is None:
            return 0.0
        return await self._client.get_usdt_balance()

    async def ping(self) -> bool:
        if self._client is None:
            return False
        return await self._client.ping()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    # ── Write guard ─────────────────────────────────────────────────────────

    async def create_market_buy(self, *args, **kwargs):
        raise PermissionError(
            "Direct exchange writes are forbidden. Use ExecutionEngine.submit_live() instead."
        )

    async def create_market_sell(self, *args, **kwargs):
        raise PermissionError(
            "Direct exchange writes are forbidden. Use ExecutionEngine.submit_live() instead."
        )


# ── Write Adapter (ExecutionEngine only) ──────────────────────────────────────

class WriteExchangeAdapter(BaseExchangeAdapter):
    """
    Full read+write adapter — ONLY injected into ExecutionEngine.
    Never pass this object to any other module.
    """

    def __init__(self, ccxt_client=None):
        self._client = ccxt_client

    async def get_symbol_price(self, symbol: str) -> float:
        if self._client is None:
            return 0.0
        return await self._client.get_symbol_price(symbol)

    async def get_usdt_balance(self) -> float:
        if self._client is None:
            return 0.0
        return await self._client.get_usdt_balance()

    async def ping(self) -> bool:
        if self._client is None:
            return False
        return await self._client.ping()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ── Write methods ────────────────────────────────────────────────────────

    async def create_market_buy(
        self,
        symbol: str,
        usdt_amount: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Place a market buy order through the exchange."""
        if self._client is None:
            return self._dry_run_fill(symbol, "buy", usdt_amount)
        logger.info(f"[ExchangeAdapter] MARKET BUY {symbol} ${usdt_amount:.2f}")
        return await self._client.create_market_buy(symbol, usdt_amount, params)

    async def create_market_sell(
        self,
        symbol: str,
        usdt_amount: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Place a market sell order through the exchange."""
        if self._client is None:
            return self._dry_run_fill(symbol, "sell", usdt_amount)
        logger.info(f"[ExchangeAdapter] MARKET SELL {symbol} ${usdt_amount:.2f}")
        return await self._client.create_market_sell(symbol, usdt_amount, params)

    async def fetch_order_status(self, order_id: str, symbol: str) -> str:
        if self._client is None:
            return "dry_run_simulated"
        return await self._client.fetch_order_status(order_id, symbol)

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        if self._client is None:
            return True
        return await self._client.cancel_order(order_id, symbol)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _dry_run_fill(symbol: str, side: str, usdt_amount: float) -> Dict[str, Any]:
        """Synthetic fill for paper/backtest when no exchange client is available."""
        return {
            "id": f"DRY-{symbol.replace('/', '')}-{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "type": "market",
            "amount": 0.0,
            "cost": usdt_amount,
            "price": 0.0,
            "status": "dry_run_simulated",
            "timestamp": int(time.time() * 1000),
        }


# ── Factory ────────────────────────────────────────────────────────────────────

def make_write_adapter_from_env() -> WriteExchangeAdapter:
    """
    Build a WriteExchangeAdapter using CCXTClient.from_env().
    Call only from ExecutionEngine.
    """
    try:
        from btc_scraper.core.ccxt_client import CCXTClient
        client = CCXTClient.from_env()
        return WriteExchangeAdapter(client)
    except Exception as exc:
        logger.warning(f"[ExchangeAdapter] Could not init CCXTClient: {exc} — using dry-run adapter")
        return WriteExchangeAdapter(None)


def make_readonly_adapter_from_env() -> ReadOnlyExchangeAdapter:
    """
    Build a ReadOnlyExchangeAdapter using CCXTClient.from_env().
    Safe to pass to any module needing market data.
    """
    try:
        from btc_scraper.core.ccxt_client import CCXTClient
        client = CCXTClient.from_env()
        return ReadOnlyExchangeAdapter(client)
    except Exception as exc:
        logger.warning(f"[ExchangeAdapter] Could not init read-only adapter: {exc}")
        return ReadOnlyExchangeAdapter(None)
