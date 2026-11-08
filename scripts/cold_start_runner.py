"""
scripts/cold_start_runner.py

Subprocess entry point for offline cold start benchmark.
Injects real NetworkInterceptor BEFORE any application module is imported,
seeds CandleStore with fresh offline candles, silences Telegram notifications,
and writes a structured network audit report upon exit.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 1. Activate NetworkInterceptor Before Any Network Module Is Used ─────────
from scripts.paper_benchmark_support import NetworkInterceptor, make_synthetic_candles, write_network_audit

interceptor = NetworkInterceptor()
interceptor.__enter__()


def _write_network_audit() -> None:
    interceptor.__exit__(None, None, None)
    write_network_audit(interceptor)


atexit.register(_write_network_audit)

# ── 2. Pre-seed CandleStore with Fresh Synthetic Candles ─────────────────────
from btc_scraper.core.candle_store import candle_store
from main import ANALYSIS_SYMBOLS

now_ts = time.time()
for coin in ANALYSIS_SYMBOLS:
    candle_store.seed(coin, "15m", make_synthetic_candles(50000.0, 210, interval="15m", end_time=now_ts))
    candle_store.seed(coin, "1h", make_synthetic_candles(50000.0, 50, interval="1h", end_time=now_ts))
    candle_store.seed(coin, "4h", make_synthetic_candles(50000.0, 50, interval="4h", end_time=now_ts))
    candle_store.seed(coin, "1d", make_synthetic_candles(50000.0, 30, interval="1d", end_time=now_ts))

# ── 3. Patch WS Manager bootstrap_rest & is_healthy in benchmark harness ─────
from btc_scraper.exchanges.binance_ws import BinanceWebSocketManager

async def _noop_bootstrap(self):
    pass

BinanceWebSocketManager.bootstrap_rest = _noop_bootstrap
BinanceWebSocketManager.is_healthy = lambda self: True

# ── 4. Silence Telegram in benchmark harness ─────────────────────────────────
import btc_scraper.telegram_bot
btc_scraper.telegram_bot.send_telegram_message = lambda *args, **kwargs: None
from btc_scraper.trading.auto_trader import AutoTrader
AutoTrader._notify_trade = lambda self, entry: None

# ── 5. Run main.main() ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import main
    # Ensure sys.argv starts with main.py so argparse help/usage messages look standard
    sys.argv[0] = "main.py"
    main.main()

