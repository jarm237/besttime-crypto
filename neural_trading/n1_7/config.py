"""N1.7 Configuration, Frozen Thresholds, and Cost Contracts.

Adheres strictly to Phase A instructions:
1. Frozen H-1 Thresholds:
   - entry_basis_ma24_bps >= 75.0
   - entry_yield_ann_pct >= 5.0%
   - exit_basis_ma24_bps <= 15.0
   - max_concurrent_assets = 4
   - max_single_asset_allocation = 25%
   - min_entry_ttm_hours = 72.0

2. Frozen Cost Contract:
   - Base scenario: standard_retail_taker = 39.0 bps round trip.
   - Breakdown:
     * Spot entry fee: 10.0 bps
     * COIN-M entry fee: 5.0 bps
     * Spot exit fee: 10.0 bps
     * COIN-M early exit fee: 5.0 bps
     * COIN-M delivery settlement fee: 5.0 bps
     * Half-spread + impact baseline: 4.5 bps Spot + 4.5 bps COIN-M (measured dynamically from depth, 9.0 bps min baseline)
     Total base round-trip: 10 + 5 + 10 + 5 + 9 = 39.0 bps.

3. Quote Freshness & Integrity:
   - Stale threshold: max quote age = 15.0 seconds.
   - Max inter-venue skew = 10.0 seconds.
   - Non-compliant snapshots flagged as QUOTE_NOT_ELIGIBLE_FOR_EXECUTION_ANALYSIS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT_N1_6 = REPO_ROOT / "data" / "neural_n1_6"
DATA_ROOT_N1_7 = REPO_ROOT / "data" / "neural_n1_7"
RESEARCH_DIR_N1_7 = REPO_ROOT / "research" / "neural_n1_7"

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

TIER1_MMR: Dict[str, float] = {
    "BTCUSD": 0.004,
    "ETHUSD": 0.004,
    "BNBUSD": 0.005,
    "XRPUSD": 0.005,
    "ADAUSD": 0.005,
    "LINKUSD": 0.005,
    "LTCUSD": 0.005,
    "SOLUSD": 0.005,
}

CONTRACT_MULTIPLIERS_USD: Dict[str, float] = {
    "BTCUSD": 100.0,
    "ETHUSD": 10.0,
    "BNBUSD": 10.0,
    "XRPUSD": 10.0,
    "ADAUSD": 10.0,
    "LINKUSD": 10.0,
    "LTCUSD": 10.0,
    "SOLUSD": 10.0,
}


@dataclass(frozen=True)
class FrozenH1ContractN1_7:
    entry_basis_ma24_bps: float = 75.0
    entry_yield_ann_pct: float = 5.0
    exit_basis_ma24_bps: float = 15.0
    min_entry_ttm_hours: float = 72.0
    max_single_weight: float = 0.25
    max_concurrent_assets: int = 4
    # Max acceptable quote latency
    max_quote_age_s: float = 15.0
    max_venue_skew_s: float = 10.0


FROZEN_H1 = FrozenH1ContractN1_7()


@dataclass(frozen=True)
class FrozenStandardRetailTakerCosts:
    """N1.5 frozen baseline: standard_retail_taker = 39.0 bps all-in 4-leg round trip."""
    spot_entry_fee_bps: float = 10.0
    cm_entry_fee_bps: float = 5.0
    spot_exit_fee_bps: float = 10.0
    cm_early_exit_fee_bps: float = 5.0
    cm_delivery_settlement_fee_bps: float = 5.0
    # Minimum baseline half-spread + slippage (4.5 bps per venue, 9.0 bps round trip)
    baseline_spread_slippage_bps: float = 9.0
    all_in_baseline_rt_bps: float = 39.0


class LifecycleState:
    ENTRY_ELIGIBLE = "ENTRY_ELIGIBLE"
    PAIR_ENTRY_SIMULATED = "PAIR_ENTRY_SIMULATED"
    HEDGED_HOLD = "HEDGED_HOLD"
    EXIT_ELIGIBLE = "EXIT_ELIGIBLE"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


COSTS = FrozenStandardRetailTakerCosts()
