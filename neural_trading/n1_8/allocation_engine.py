"""N1.8 Allocation and Margin Engine: Risk Aggregation, Collateral Feasibility & Execution Semantics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neural_trading.n1_8.config import (
    CONTRACT_MULTIPLIERS_USD,
    COSTS,
    FROZEN_H1,
    PORTFOLIO_CONFIG,
    TIER1_MMR,
)


@dataclass
class ContractPosition:
    contract_symbol: str
    underlying_asset: str
    contracts_short: int
    contract_size_usd: float
    entry_notional_usd: float
    entry_spot_price: float
    entry_futures_price: float
    allocated_coin_collateral: float
    entry_timestamp_ms: int
    status: str  # HEDGED_HOLD, RISK_ACTION_REQUIRED, etc.
    disposition_note: str = ""


@dataclass
class UnderlyingRiskBucket:
    underlying_asset: str
    max_capital_usd: float
    aggregate_position_notional_usd: float = 0.0
    aggregate_collateral_coin: float = 0.0
    aggregate_committed_capital_usd: float = 0.0
    active_contracts: List[ContractPosition] = field(default_factory=list)
    defect_detected: bool = False
    defect_note: str = ""

    @property
    def capital_utilization_pct(self) -> float:
        return (self.aggregate_committed_capital_usd / max(self.max_capital_usd, 1.0)) * 100.0

    @property
    def remaining_capital_usd(self) -> float:
        return max(0.0, self.max_capital_usd - self.aggregate_committed_capital_usd)


class AccountUnderlyingAllocationLedger:
    """Account-level allocation ledger enforcing portfolio-level limits strictly aggregated by underlying asset."""

    def __init__(self, portfolio_capital_usd: float = PORTFOLIO_CONFIG.portfolio_capital_usd) -> None:
        self.portfolio_capital_usd = portfolio_capital_usd
        self.max_per_underlying_usd = portfolio_capital_usd * PORTFOLIO_CONFIG.max_single_asset_weight
        self.underlyings: Dict[str, UnderlyingRiskBucket] = {}
        self.rejection_log: List[Dict[str, Any]] = []

    def get_or_create_bucket(self, underlying: str) -> UnderlyingRiskBucket:
        if underlying not in self.underlyings:
            self.underlyings[underlying] = UnderlyingRiskBucket(
                underlying_asset=underlying,
                max_capital_usd=self.max_per_underlying_usd,
            )
        return self.underlyings[underlying]

    def allocate_position(
        self,
        contract_symbol: str,
        contracts: int,
        contract_size_usd: float,
        spot_price: float,
        fut_price: float,
        timestamp_ms: int,
        allow_over_allocation_recording: bool = False,
    ) -> Tuple[bool, Optional[ContractPosition], str]:
        """Allocates a new contract position. If it violates underlying-level risk, records defect or rejects."""
        # Derive underlying (e.g. BNBUSD_261225 -> BNB)
        underlying = contract_symbol.split("USD")[0]
        bucket = self.get_or_create_bucket(underlying)

        notional_usd = contracts * contract_size_usd
        required_coin = notional_usd / spot_price
        new_total_capital = bucket.aggregate_committed_capital_usd + notional_usd

        if new_total_capital > bucket.max_capital_usd + 1e-6:
            reason = (
                f"EXCEEDS_AGGREGATE_UNDERLYING_CAP: Underlying {underlying} already has "
                f"${bucket.aggregate_committed_capital_usd:.2f} committed; adding ${notional_usd:.2f} "
                f"would reach ${new_total_capital:.2f}, exceeding ${bucket.max_capital_usd:.2f} cap."
            )
            if allow_over_allocation_recording:
                # Create position but mark with defect
                bucket.defect_detected = True
                bucket.defect_note = reason
                pos = ContractPosition(
                    contract_symbol=contract_symbol,
                    underlying_asset=underlying,
                    contracts_short=contracts,
                    contract_size_usd=contract_size_usd,
                    entry_notional_usd=notional_usd,
                    entry_spot_price=spot_price,
                    entry_futures_price=fut_price,
                    allocated_coin_collateral=required_coin,
                    entry_timestamp_ms=timestamp_ms,
                    status="RISK_ACTION_REQUIRED",
                    disposition_note=reason,
                )
                bucket.active_contracts.append(pos)
                bucket.aggregate_position_notional_usd += notional_usd
                bucket.aggregate_collateral_coin += required_coin
                bucket.aggregate_committed_capital_usd += notional_usd
                self.rejection_log.append({
                    "contract_symbol": contract_symbol,
                    "underlying": underlying,
                    "notional_usd": notional_usd,
                    "disposition": "DEFECT_RECORDED_OVER_ALLOCATION",
                    "reason": reason,
                })
                return False, pos, reason
            else:
                self.rejection_log.append({
                    "contract_symbol": contract_symbol,
                    "underlying": underlying,
                    "notional_usd": notional_usd,
                    "disposition": "REJECTED_RISK_LIMIT",
                    "reason": reason,
                })
                return False, None, reason

        # Valid allocation
        pos = ContractPosition(
            contract_symbol=contract_symbol,
            underlying_asset=underlying,
            contracts_short=contracts,
            contract_size_usd=contract_size_usd,
            entry_notional_usd=notional_usd,
            entry_spot_price=spot_price,
            entry_futures_price=fut_price,
            allocated_coin_collateral=required_coin,
            entry_timestamp_ms=timestamp_ms,
            status="HEDGED_HOLD",
            disposition_note="ALLOCATED_WITHIN_RISK_CAP",
        )
        bucket.active_contracts.append(pos)
        bucket.aggregate_position_notional_usd += notional_usd
        bucket.aggregate_collateral_coin += required_coin
        bucket.aggregate_committed_capital_usd += notional_usd
        return True, pos, "SUCCESS"

    def to_dict(self) -> Dict[str, Any]:
        total_committed = sum(b.aggregate_committed_capital_usd for b in self.underlyings.values())
        return {
            "portfolio_capital_usd": self.portfolio_capital_usd,
            "max_per_underlying_cap_usd": self.max_per_underlying_usd,
            "total_portfolio_committed_capital_usd": round(total_committed, 2),
            "portfolio_utilization_pct": round((total_committed / self.portfolio_capital_usd) * 100.0, 2),
            "underlying_buckets": {
                u: {
                    "underlying_asset": b.underlying_asset,
                    "max_capital_usd": b.max_capital_usd,
                    "aggregate_position_notional_usd": round(b.aggregate_position_notional_usd, 2),
                    "aggregate_collateral_coin": round(b.aggregate_collateral_coin, 6),
                    "aggregate_committed_capital_usd": round(b.aggregate_committed_capital_usd, 2),
                    "capital_utilization_pct": round(b.capital_utilization_pct, 2),
                    "active_contracts_count": len(b.active_contracts),
                    "defect_detected": b.defect_detected,
                    "defect_note": b.defect_note,
                    "contracts": [
                        {
                            "contract_symbol": c.contract_symbol,
                            "contracts_short": c.contracts_short,
                            "entry_notional_usd": c.entry_notional_usd,
                            "allocated_coin_collateral": round(c.allocated_coin_collateral, 6),
                            "status": c.status,
                            "disposition_note": c.disposition_note,
                        }
                        for c in b.active_contracts
                    ],
                }
                for u, b in self.underlyings.items()
            },
            "rejection_log": self.rejection_log,
        }


class AccountMarginLedger:
    """Cross Margin account ledger tracking collateral, requirements, and margin ratio per underlying coin."""

    def __init__(self) -> None:
        self.wallets: Dict[str, Dict[str, Any]] = {}

    def update_coin_wallet(
        self,
        coin: str,
        wallet_balance_coin: float,
        active_positions: List[Dict[str, Any]],
        current_spot_prices: Dict[str, float],
        current_futures_prices: Dict[str, float],
    ) -> Dict[str, Any]:
        """Calculates exact Binance cross-margin account metrics for an underlying coin wallet."""
        total_inverse_upnl_coin = 0.0
        total_maint_margin_coin = 0.0
        total_initial_margin_coin = 0.0
        total_notional_usd = 0.0

        mmr_rate = TIER1_MMR.get(coin, 0.005)
        imr_rate = 0.05  # 20x max initial margin requirement (or 1.0 for 1x)

        for pos in active_positions:
            sym = pos["contract_symbol"]
            notional = pos["entry_notional_usd"]
            entry_fut = pos["entry_futures_price"]
            cur_fut = current_futures_prices.get(sym, entry_fut)

            if cur_fut > 0 and entry_fut > 0:
                # Inverse futures PnL in coin = notional * (1/F_cur - 1/F_entry)
                inv_pnl = notional * (1.0 / cur_fut - 1.0 / entry_fut)
                total_inverse_upnl_coin += inv_pnl

                # Maintenance and Initial Margin in coin
                maint_coin = (notional * mmr_rate) / cur_fut
                init_coin = (notional * imr_rate) / cur_fut
                total_maint_margin_coin += maint_coin
                total_initial_margin_coin += init_coin
                total_notional_usd += notional

        margin_balance_coin = wallet_balance_coin + total_inverse_upnl_coin
        spot_px = current_spot_prices.get(coin, 1.0)
        margin_balance_usd = margin_balance_coin * spot_px

        # Dynamic Margin Ratio = Maintenance Margin / Margin Balance
        margin_ratio = (
            (total_maint_margin_coin / margin_balance_coin)
            if margin_balance_coin > 1e-12
            else (999.0 if total_maint_margin_coin > 0 else 0.0)
        )
        available_margin_coin = max(0.0, margin_balance_coin - total_initial_margin_coin)

        wallet_status = {
            "coin": coin,
            "wallet_balance_coin": round(wallet_balance_coin, 6),
            "unrealized_inverse_pnl_coin": round(total_inverse_upnl_coin, 6),
            "margin_balance_coin": round(margin_balance_coin, 6),
            "margin_balance_usd": round(margin_balance_usd, 2),
            "initial_margin_requirement_coin": round(total_initial_margin_coin, 6),
            "maintenance_margin_requirement_coin": round(total_maint_margin_coin, 6),
            "margin_ratio": round(margin_ratio, 6),
            "margin_ratio_pct": round(margin_ratio * 100.0, 4),
            "available_margin_coin": round(available_margin_coin, 6),
            "contract_tier": "Tier 1",
            "tier_mmr_rate": mmr_rate,
            "liquidation_risk_note": "NON_ZERO: Liquidation occurs if margin_ratio reaches 100.0% (extreme basis blowouts or exchange haircuts).",
        }
        self.wallets[coin] = wallet_status
        return wallet_status


class IndependentLegExecutionSimulator:
    """Evaluates the three execution scenarios under true physical exchange sequencing and collateral constraints."""

    @staticmethod
    def simulate_spot_first(
        target_notional_usd: float,
        spot_ask_vwap: float,
        spot_avail_usd: float,
        cm_bid_vwap: float,
        cm_avail_usd: float,
        contract_size_usd: float,
        transfer_latency_s: float = 0.86,
    ) -> Dict[str, Any]:
        # Account starts with USDT cash
        initial_account_delta_usd = 0.0
        # Leg 1: Spot order fills
        spot_filled_usd = min(target_notional_usd, spot_avail_usd)
        intermediate_account_delta_usd = spot_filled_usd  # Long coin price exposure!

        # Coin transfer to COIN-M margin wallet
        # Leg 2: Futures short order fills
        cm_filled_usd = min(spot_filled_usd, cm_avail_usd)
        contracts = int(math.floor(cm_filled_usd / contract_size_usd))
        actual_cm_notional = contracts * contract_size_usd

        final_account_delta_usd = spot_filled_usd - actual_cm_notional
        max_unhedged_delta_usd = intermediate_account_delta_usd

        spot_fee = spot_filled_usd * (COSTS.spot_entry_fee_bps / 10_000.0)
        cm_fee = actual_cm_notional * (COSTS.cm_entry_fee_bps / 10_000.0)

        failure_reason = None
        if spot_filled_usd > actual_cm_notional + 100.0:
            failure_reason = "FUTURES_BOOK_THIN_PARTIAL_HEDGE_UNFILLED"

        return {
            "scenario": "scenario_1_spot_fills_first",
            "initial_account_delta": initial_account_delta_usd,
            "first_leg_fill": f"SPOT_BUY_${spot_filled_usd:.2f}",
            "intermediate_account_delta": round(intermediate_account_delta_usd, 2),
            "second_leg_fill": f"COINM_SHORT_${actual_cm_notional:.2f}",
            "final_account_delta": round(final_account_delta_usd, 2),
            "maximum_unhedged_delta": round(max_unhedged_delta_usd, 2),
            "required_margin": round(spot_filled_usd, 2),
            "required_prefunding": "USDT_CASH_ONLY",
            "execution_cost": round(spot_fee + cm_fee, 4),
            "quote_staleness": round(transfer_latency_s, 2),
            "failure_reason": failure_reason,
            "status": "HEDGE_COMPLETE" if failure_reason is None else "LEGGING_EXPOSURE_RISK",
        }

    @staticmethod
    def simulate_coinm_first(
        target_notional_usd: float,
        spot_ask_vwap: float,
        spot_avail_usd: float,
        cm_bid_vwap: float,
        cm_avail_usd: float,
        contract_size_usd: float,
        has_prefunded_collateral: bool = False,
    ) -> Dict[str, Any]:
        if not has_prefunded_collateral:
            # Physical rule: COIN-M cannot short without coin collateral in margin wallet!
            return {
                "scenario": "scenario_2_coinm_fills_first_unfunded",
                "initial_account_delta": 0.0,
                "first_leg_fill": "NONE",
                "intermediate_account_delta": 0.0,
                "second_leg_fill": "NONE",
                "final_account_delta": 0.0,
                "maximum_unhedged_delta": 0.0,
                "required_margin": 0.0,
                "required_prefunding": "INSUFFICIENT_COIN_COLLATERAL",
                "execution_cost": 0.0,
                "quote_staleness": 0.0,
                "failure_reason": "COINM_FIRST_BLOCKED_INSUFFICIENT_COLLATERAL",
                "status": "BLOCKED_BY_EXCHANGE_MARGIN_RULE",
            }

        # If prefunded, the account holds coin collateral beforehand
        initial_account_delta_usd = target_notional_usd  # Holding coin beforehand = +Delta!
        contracts = int(math.floor(min(target_notional_usd, cm_avail_usd) / contract_size_usd))
        cm_filled_usd = contracts * contract_size_usd

        # After short fills, net delta drops
        intermediate_account_delta_usd = initial_account_delta_usd - cm_filled_usd

        # Leg 2: Rebalance spot if needed
        spot_rebalance_usd = intermediate_account_delta_usd
        final_account_delta_usd = 0.0
        max_unhedged_delta_usd = initial_account_delta_usd  # Long exposure existed while prefunded!

        spot_fee = spot_rebalance_usd * (COSTS.spot_entry_fee_bps / 10_000.0)
        cm_fee = cm_filled_usd * (COSTS.cm_entry_fee_bps / 10_000.0)

        return {
            "scenario": "scenario_2_coinm_fills_first_prefunded",
            "initial_account_delta": round(initial_account_delta_usd, 2),
            "first_leg_fill": f"COINM_SHORT_${cm_filled_usd:.2f}",
            "intermediate_account_delta": round(intermediate_account_delta_usd, 2),
            "second_leg_fill": f"SPOT_REBALANCE_${spot_rebalance_usd:.2f}",
            "final_account_delta": round(final_account_delta_usd, 2),
            "maximum_unhedged_delta": round(max_unhedged_delta_usd, 2),
            "required_margin": round(cm_filled_usd, 2),
            "required_prefunding": f"100%_COIN_COLLATERAL_${target_notional_usd:.2f}",
            "execution_cost": round(spot_fee + cm_fee, 4),
            "quote_staleness": 0.5,
            "failure_reason": None,
            "status": "HEDGE_COMPLETE_PREFUNDED",
        }

    @staticmethod
    def simulate_matched_virtual_capacity(
        target_notional_usd: float,
        spot_ask_vwap: float,
        spot_avail_usd: float,
        cm_bid_vwap: float,
        cm_avail_usd: float,
        contract_size_usd: float,
    ) -> Dict[str, Any]:
        matched_usd = min(target_notional_usd, spot_avail_usd, cm_avail_usd)
        contracts = int(math.floor(matched_usd / contract_size_usd))
        matched_exec_usd = contracts * contract_size_usd

        spot_fee = matched_exec_usd * (COSTS.spot_entry_fee_bps / 10_000.0)
        cm_fee = matched_exec_usd * (COSTS.cm_entry_fee_bps / 10_000.0)

        return {
            "scenario": "scenario_3_matched_virtual_capacity",
            "initial_account_delta": 0.0,
            "first_leg_fill": f"VIRTUAL_SPOT_${matched_exec_usd:.2f}",
            "intermediate_account_delta": 0.0,
            "second_leg_fill": f"VIRTUAL_COINM_${matched_exec_usd:.2f}",
            "final_account_delta": 0.0,
            "maximum_unhedged_delta": 0.0,
            "required_margin": round(matched_exec_usd, 2),
            "required_prefunding": "SYNCHRONIZED_MATCHING_ASSUMPTION",
            "execution_cost": round(spot_fee + cm_fee, 4),
            "quote_staleness": 0.2,
            "failure_reason": None,
            "status": "BOOK_DEPTH_PAIRABLE",  # NOT TWO_LEG_EXECUTION_CONFIRMED!
        }
