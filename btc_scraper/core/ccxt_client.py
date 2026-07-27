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

        try:
            order = await ex.create_market_buy_order(symbol, float(qty), params=params or {})
            return order
        except Exception as e:
            if "-2015" in str(e) or "Invalid API-key" in str(e):
                raise RuntimeError(f"Lỗi API Key: Vui lòng kiểm tra lại. Nếu dùng Testnet, bạn phải tạo Key tại testnet.binancefuture.com (Futures Testnet), không dùng key Spot! Chi tiết: {e}")
            raise RuntimeError(f"Lỗi đặt lệnh: {e}")

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

        try:
            order = await ex.create_market_sell_order(symbol, float(qty), params=params or {})
            return order
        except Exception as e:
            if "-2015" in str(e) or "Invalid API-key" in str(e):
                raise RuntimeError(f"Lỗi API Key: Vui lòng kiểm tra lại. Nếu dùng Testnet, bạn phải tạo Key tại testnet.binancefuture.com (Futures Testnet), không dùng key Spot! Chi tiết: {e}")
            raise RuntimeError(f"Lỗi đặt lệnh: {e}")

    async def create_limit_buy(
        self,
        symbol: str,
        usdt_amount: float,
        limit_price: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Place a LIMIT BUY order."""
        if limit_price <= 0:
            raise ValueError("limit_price must be greater than zero")
        qty = usdt_amount / limit_price
        if self.dry_run:
            return {
                "id": f"DRY-LIMIT-{symbol.replace('/', '')}-{int(time.time())}",
                "symbol": symbol,
                "side": "buy",
                "type": "limit",
                "amount": round(qty, 6),
                "cost": usdt_amount,
                "price": limit_price,
                "status": "dry_run_simulated",
                "timestamp": int(time.time() * 1000),
            }

        ex = self._get_exchange()
        await ex.load_markets()
        precise_qty = ex.amount_to_precision(symbol, qty)
        precise_price = ex.price_to_precision(symbol, limit_price)
        try:
            return await ex.create_limit_buy_order(
                symbol, float(precise_qty), float(precise_price), params=params or {}
            )
        except Exception as e:
            if "-2015" in str(e) or "Invalid API-key" in str(e):
                raise RuntimeError(f"Lỗi API Key: Vui lòng kiểm tra lại. Chi tiết: {e}")
            raise RuntimeError(f"Lỗi đặt lệnh limit buy: {e}")

    async def create_limit_sell(
        self,
        symbol: str,
        usdt_amount: float,
        limit_price: float,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Place a LIMIT SELL order."""
        if limit_price <= 0:
            raise ValueError("limit_price must be greater than zero")
        qty = usdt_amount / limit_price
        if self.dry_run:
            return {
                "id": f"DRY-LIMIT-{symbol.replace('/', '')}-{int(time.time())}",
                "symbol": symbol,
                "side": "sell",
                "type": "limit",
                "amount": round(qty, 6),
                "cost": usdt_amount,
                "price": limit_price,
                "status": "dry_run_simulated",
                "timestamp": int(time.time() * 1000),
            }

        ex = self._get_exchange()
        await ex.load_markets()
        precise_qty = ex.amount_to_precision(symbol, qty)
        precise_price = ex.price_to_precision(symbol, limit_price)
        try:
            return await ex.create_limit_sell_order(
                symbol, float(precise_qty), float(precise_price), params=params or {}
            )
        except Exception as e:
            if "-2015" in str(e) or "Invalid API-key" in str(e):
                raise RuntimeError(f"Lỗi API Key: Vui lòng kiểm tra lại. Chi tiết: {e}")
            raise RuntimeError(f"Lỗi đặt lệnh limit sell: {e}")

    async def get_open_position_qty(self, symbol: str) -> float:
        """Return the signed base-asset quantity open for a futures symbol."""
        if self.dry_run:
            return 0.0
        try:
            ex = self._get_exchange()
            positions = await ex.fetch_positions([symbol])
            for position in positions:
                if position.get("symbol") != symbol:
                    continue
                info = position.get("info") or {}
                # Binance futures' positionAmt is the authoritative signed qty.
                raw_qty = info.get("positionAmt", position.get("contracts", 0.0))
                qty = float(raw_qty or 0.0)
                if qty:
                    return qty
            return 0.0
        except Exception as e:
            raise RuntimeError(f"Could not fetch position for {symbol}: {e}")

    async def close_position_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Dict[str, Any]:
        """Close an exact quantity at market with Binance reduceOnly enabled."""
        if quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        normalized_side = side.lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError(f"invalid close side: {side}")
        if self.dry_run:
            price = await self.get_symbol_price(symbol)
            return {
                "id": f"DRY-CLOSE-{symbol.replace('/', '')}-{int(time.time())}",
                "symbol": symbol,
                "side": normalized_side,
                "type": "market",
                "amount": quantity,
                "cost": quantity * price,
                "price": price,
                "status": "dry_run_simulated",
                "timestamp": int(time.time() * 1000),
            }

        ex = self._get_exchange()
        await ex.load_markets()
        precise_qty = float(ex.amount_to_precision(symbol, quantity))
        if precise_qty <= 0:
            raise ValueError(f"invalid quantity after precision for {symbol}")
        try:
            return await ex.create_order(
                symbol, "market", normalized_side, precise_qty,
                params={"reduceOnly": True},
            )
        except Exception as e:
            raise RuntimeError(f"Could not close position: {e}")

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
