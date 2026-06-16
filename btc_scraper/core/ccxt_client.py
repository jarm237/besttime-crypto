"""
CCXT Client — Abstraction layer cho Binance Testnet (Demo Account).

Hỗ trợ:
  - Binance Spot Testnet (api.testnet.binance.vision)
  - Market orders (khớp ngay)
  - Lấy balance, kiểm tra min order size
  - Fetch order status để verify fill

Sử dụng:
    from btc_scraper.core.ccxt_client import CCXTClient
    client = CCXTClient.from_env()
    balance = await client.get_usdt_balance()
    order = await client.create_market_buy("BTC/USDT", 25.0)
"""
from __future__ import annotations

import os
import time
from typing import Optional, Dict, Any

# ─── BINANCE TESTNET URLS ───────────────────────────────────────────────────
BINANCE_TESTNET_URLS = {
    "api": "https://testnet.binance.vision/api",
    "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
    "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
}


class CCXTClient:
    """
    Thin wrapper quanh ccxt.binance (async) để:
    1. Luôn dùng testnet URL
    2. Cung cấp helper methods đơn giản
    3. Lazy-load ccxt (tránh import error nếu ccxt chưa cài)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        dry_run: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.dry_run = dry_run
        self._exchange = None  # lazy init

    @classmethod
    def from_env(cls) -> "CCXTClient":
        """Tạo client từ biến môi trường."""
        api_key = os.getenv("AUTO_TRADE_BINANCE_API_KEY", "")
        api_secret = os.getenv("AUTO_TRADE_BINANCE_API_SECRET", "")
        testnet = os.getenv("AUTO_TRADE_BINANCE_TESTNET", "true").lower() != "false"
        dry_run = os.getenv("AUTO_TRADE_DRY_RUN", "true").lower() != "false"
        return cls(api_key=api_key, api_secret=api_secret, testnet=testnet, dry_run=dry_run)

    def _get_exchange(self):
        """Lazy-init ccxt.binance exchange async."""
        if self._exchange is not None:
            return self._exchange

        try:
            import ccxt.async_support as ccxt
        except ImportError:
            raise RuntimeError(
                "ccxt chưa được cài. Chạy: pip install ccxt"
            )

        exchange = ccxt.binance({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
                "disableFuturesSandboxWarning": True,  # Bỏ qua lỗi NotSupported của CCXT cho testnet
            },
        })

        if self.testnet:
            exchange.set_sandbox_mode(True)

        self._exchange = exchange
        return exchange

    async def close(self):
        """Đóng kết nối exchange khi không dùng nữa."""
        if self._exchange is not None:
            await self._exchange.close()

    async def ping(self) -> bool:
        """Kiểm tra kết nối tới exchange."""
        try:
            ex = self._get_exchange()
            await ex.fetch_time()
            return True
        except Exception:
            return False

    async def get_usdt_balance(self) -> float:
        """Lấy số dư USDT free trong tài khoản."""
        try:
            ex = self._get_exchange()
            balance = await ex.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0.0))
        except Exception as e:
            raise RuntimeError(f"Không lấy được balance: {e}")

    async def get_symbol_price(self, symbol: str) -> float:
        """Lấy giá hiện tại của symbol (VD: 'BTC/USDT')."""
        try:
            ex = self._get_exchange()
            ticker = await ex.fetch_ticker(symbol)
            return float(ticker["last"] or ticker["close"] or 0.0)
        except Exception as e:
            raise RuntimeError(f"Không lấy được giá {symbol}: {e}")

    async def get_min_order_usdt(self, symbol: str) -> float:
        """Lấy minimum order size tính theo USDT (notional)."""
        try:
            ex = self._get_exchange()
            await ex.load_markets()
            market = ex.market(symbol)
            min_notional = (
                market.get("limits", {})
                .get("cost", {})
                .get("min", 10.0) or 10.0
            )
            return float(min_notional)
        except Exception:
            return 10.0  # safe default

    async def create_market_buy(
        self,
        symbol: str,
        usdt_amount: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Đặt lệnh Market BUY."""
        if self.dry_run:
            price = await self.get_symbol_price(symbol)
            qty = usdt_amount / price if price > 0 else 0
            return {
                "id": f"DRY-{symbol.replace('/', '')}-{int(time.time())}",
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "amount": round(qty, 6),
                "cost": usdt_amount,
                "price": price,
                "status": "dry_run_simulated",
                "timestamp": int(time.time() * 1000),
            }

        ex = self._get_exchange()
        await ex.load_markets()
        market = ex.market(symbol)

        price = await self.get_symbol_price(symbol)
        if price <= 0:
            raise RuntimeError(f"Giá {symbol} không hợp lệ: {price}")
        qty = usdt_amount / price
        qty = ex.amount_to_precision(symbol, qty)

        order = await ex.create_market_buy_order(symbol, float(qty), params=params or {})
        return order

    async def create_market_sell(
        self,
        symbol: str,
        usdt_amount: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Đặt lệnh Market SELL."""
        if self.dry_run:
            price = await self.get_symbol_price(symbol)
            qty = usdt_amount / price if price > 0 else 0
            return {
                "id": f"DRY-{symbol.replace('/', '')}-{int(time.time())}",
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "amount": round(qty, 6),
                "cost": usdt_amount,
                "price": price,
                "status": "dry_run_simulated",
                "timestamp": int(time.time() * 1000),
            }

        ex = self._get_exchange()
        await ex.load_markets()

        price = await self.get_symbol_price(symbol)
        if price <= 0:
            raise RuntimeError(f"Giá {symbol} không hợp lệ: {price}")
        qty = usdt_amount / price
        qty = ex.amount_to_precision(symbol, qty)

        order = await ex.create_market_sell_order(symbol, float(qty), params=params or {})
        return order

    async def fetch_order_status(self, order_id: str, symbol: str) -> str:
        """Lấy trạng thái lệnh."""
        if self.dry_run or str(order_id).startswith("DRY-"):
            return "dry_run_simulated"
        try:
            ex = self._get_exchange()
            order = await ex.fetch_order(order_id, symbol)
            return str(order.get("status", "unknown"))
        except Exception as e:
            return f"error: {e}"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Hủy lệnh."""
        if self.dry_run or str(order_id).startswith("DRY-"):
            return True
        try:
            ex = self._get_exchange()
            await ex.cancel_order(order_id, symbol)
            return True
        except Exception:
            return False

    @property
    def mode(self) -> str:
        return "DRY_RUN" if self.dry_run else ("TESTNET" if self.testnet else "LIVE")
