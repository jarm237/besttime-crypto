"""Frozen contracts and recorder configuration for N1.6.

The H-1 entry/exit thresholds are copied verbatim from the frozen N1.5 simulator
(`neural_trading/n1_5/coinm_simulator.py::simulate_h1_coinm_reality_check`). They must not be
changed in response to forward quotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data" / "neural_n1_6"
RAW_DIR = DATA_ROOT / "raw"
CONTROL_DIR = DATA_ROOT / "control"
STATE_DIR = DATA_ROOT / "state"
MANIFEST_DIR = DATA_ROOT / "manifests"
RESEARCH_DIR = REPO_ROOT / "research" / "neural_n1_6"

SPOT_BASE = "https://api.binance.com"
DAPI_BASE = "https://dapi.binance.com"
COINBASE_USDT_USD = "https://api.exchange.coinbase.com/products/USDT-USD"
KRAKEN_TICKER = "https://api.kraken.com/0/public/Ticker?pair=USDTZUSD"

# COIN-M pair -> Binance Spot symbol (same 8-asset universe as N1.4/N1.5)
PAIR_TO_SPOT: Dict[str, str] = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "BNBUSD": "BNBUSDT",
    "XRPUSD": "XRPUSDT",
    "ADAUSD": "ADAUSDT",
    "LINKUSD": "LINKUSDT",
    "LTCUSD": "LTCUSDT",
    "SOLUSD": "SOLUSDT",
}

# Documented COIN-M Tier-1 maintenance margin rates used by N1.5 (leverage brackets endpoint
# `/dapi/v2/leverageBracket` is SIGNED, so it cannot be refreshed from public endpoints).
TIER1_MMR: Dict[str, float] = {"BTCUSD": 0.004, "ETHUSD": 0.004}
TIER1_MMR_DEFAULT = 0.005
TIER1_MAX_NOTIONAL_USD: Dict[str, float] = {"BTCUSD": 250_000.0, "ETHUSD": 250_000.0}
TIER1_MAX_NOTIONAL_DEFAULT = 100_000.0


@dataclass(frozen=True)
class FrozenH1Contract:
    """Verbatim frozen N1.5 H-1 rule set (do not modify)."""

    entry_basis_ma24_bps: float = 75.0
    entry_yield_ma24_ann_pct: float = 5.0
    entry_min_hourly_basis_bps: float = 50.0
    min_entry_ttm_hours: float = 72.0
    exit_basis_ma24_bps: float = 15.0
    exit_hourly_basis_bps: float = 5.0
    ma_window_hours: int = 24
    ma_min_periods: int = 6
    max_single_weight: float = 0.25
    max_concurrent_assets: int = 4
    # N1.5 EXECUTABLE mode additionally required next-open basis >= 40 bps before entering
    executable_open_basis_floor_bps: float = 40.0


FROZEN_H1 = FrozenH1Contract()


@dataclass(frozen=True)
class FeeModel:
    """N1.5 `standard_retail_taker` exchange fees (VIP-0, no COIN-M BNB discount). Spreads/impact are
    NOT assumed here: in N1.6 they are measured from observed order books."""

    spot_taker_bps: float = 10.0
    cm_taker_bps: float = 5.0
    cm_delivery_bps: float = 5.0


FEES = FeeModel()


@dataclass
class RecorderConfig:
    book_interval_s: float = 10.0
    slow_interval_s: float = 60.0
    universe_refresh_s: float = 600.0
    depth_limit: int = 20
    http_timeout_s: float = 8.0
    stale_after_s: float = 30.0
    max_workers: int = 12
    signal_delay_after_hour_s: float = 90.0
    pairs: Tuple[str, ...] = field(default_factory=lambda: tuple(PAIR_TO_SPOT.keys()))


def tier1_mmr(pair: str) -> float:
    return TIER1_MMR.get(pair, TIER1_MMR_DEFAULT)


def tier1_max_notional(pair: str) -> float:
    return TIER1_MAX_NOTIONAL_USD.get(pair, TIER1_MAX_NOTIONAL_DEFAULT)
