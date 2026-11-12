"""Configuration and parameters for N1.8 COIN-M Forward Lifecycle Correctness & Natural Economic Accumulation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

DATA_ROOT_N1_6 = Path("data/neural_n1_6")
DATA_ROOT_N1_7 = Path("data/neural_n1_7")
DATA_ROOT_N1_8 = Path("data/neural_n1_8")

RESEARCH_DIR_N1_7 = Path("research/neural_n1_7")
RESEARCH_DIR_N1_8 = Path("research/neural_n1_8")


@dataclass(frozen=True)
class PortfolioRiskConfig:
    portfolio_capital_usd: float = 20_000.0
    max_single_asset_weight: float = 0.25  # 25% max per underlying asset ($5,000 max)
    max_concurrent_assets: int = 4
    leverage_multiplier: float = 1.0  # 1x floor fully-collateralized carry


@dataclass(frozen=True)
class FrozenH1Parameters:
    entry_basis_ma24_bps: float = 75.0
    entry_yield_ann_pct: float = 5.0
    exit_basis_ma24_bps: float = 15.0
    min_entry_ttm_hours: float = 72.0
    max_venue_skew_s: float = 2.0
    max_quote_age_s: float = 5.0


@dataclass(frozen=True)
class CostSchedule:
    # Round-trip standard retail taker schedule = 39.0 bps total
    spot_entry_fee_bps: float = 10.0
    cm_entry_fee_bps: float = 5.0
    spot_exit_fee_bps: float = 10.0
    cm_delivery_settlement_fee_bps: float = 5.0
    baseline_spread_slippage_bps: float = 9.0

    @property
    def total_roundtrip_bps(self) -> float:
        return (
            self.spot_entry_fee_bps
            + self.cm_entry_fee_bps
            + self.spot_exit_fee_bps
            + self.cm_delivery_settlement_fee_bps
            + self.baseline_spread_slippage_bps
        )


CONTRACT_MULTIPLIERS_USD: Dict[str, float] = {
    "BTCUSD": 100.0,
    "ETHUSD": 10.0,
    "BNBUSD": 10.0,
    "SOLUSD": 10.0,
    "XRPUSD": 10.0,
    "ADAUSD": 10.0,
    "LTCUSD": 10.0,
    "LINKUSD": 10.0,
}

# Binance Tier 1 Maintenance Margin Rates (MMR)
TIER1_MMR: Dict[str, float] = {
    "BTC": 0.0040,  # 0.40%
    "ETH": 0.0050,  # 0.50%
    "BNB": 0.0050,  # 0.50%
    "SOL": 0.0065,  # 0.65%
    "XRP": 0.0065,  # 0.65%
    "ADA": 0.0065,  # 0.65%
    "LTC": 0.0065,  # 0.65%
    "LINK": 0.0065,  # 0.65%
}

PAIR_TO_SPOT: Dict[str, str] = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT",
    "XRPUSD": "XRPUSDT",
    "ADAUSD": "ADAUSDT",
    "LTCUSD": "LTCUSDT",
    "LINKUSD": "LINKUSDT",
}

PORTFOLIO_CONFIG = PortfolioRiskConfig()
FROZEN_H1 = FrozenH1Parameters()
COSTS = CostSchedule()
