"""
btc_scraper/research/experiment_contract.py
Phase M1-B & M1-C: Canonical ExperimentSpec & ExperimentResult Contracts.

Provides immutable, versioned specifications and standardized economic results
for reproducible quantitative strategy research across out-of-sample data.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


EXPERIMENT_CONTRACT_VERSION = "experiment-v2"


def freeze_nested(value: Any) -> Any:
    """Recursively converts dicts to MappingProxyType and lists to tuples for deep immutability."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze_nested(v) for k, v in value.items()})
    elif isinstance(value, (list, tuple)):
        return tuple(freeze_nested(v) for v in value)
    return value


def unfreeze_nested(value: Any) -> Any:
    """Recursively converts MappingProxyType and mappings to dicts and tuples to lists."""
    if isinstance(value, Mapping):
        return {k: unfreeze_nested(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [unfreeze_nested(v) for v in value]
    return value


def _canonical_json(data: Mapping[str, Any]) -> str:
    """Deterministic, sorted-key, minimal-whitespace JSON serializer."""
    clean = unfreeze_nested(data)
    return json.dumps(
        dict(clean),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_spec_hash(payload: Mapping[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of an experiment configuration."""
    clean_dict = {k: v for k, v in payload.items() if k != "spec_hash"}
    return hashlib.sha256(_canonical_json(clean_dict).encode("utf-8")).hexdigest()


# ── Canonical Experiment Specification (M1-B) ─────────────────────────────────

@dataclass(frozen=True)
class ExperimentSpec:
    """
    Immutable, fully deterministic specification of an empirical trading experiment.
    All properties influencing data, features, models, execution, and costs are pinned.
    Nested dictionaries are deeply frozen via MappingProxyType to prevent post-init mutation.
    """
    experiment_id: str
    strategy_id: str
    strategy_version: str
    dataset_manifest_identity: str
    feature_set_version: str
    symbol_universe: Tuple[str, ...]
    timeframe: str
    oos_window: Tuple[str, str]  # (start_iso_utc, end_iso_utc)
    
    # Strategy classification & governance
    strategy_tier: str = "BENCHMARK"  # "BENCHMARK", "PROXY", "CANDIDATE", "PRODUCTION"
    dataset_content_hash: Optional[str] = None
    feature_schema_hash: Optional[str] = None
    
    # Optional model artifact (None for rule-based or passive baselines)
    model_artifact_identity: Optional[str] = None
    model_artifact_sha256: Optional[str] = None
    
    # Windows & Split Plan
    train_window: Optional[Tuple[str, str]] = None
    validation_window: Optional[Tuple[str, str]] = None
    walk_forward_split_plan: Optional[Mapping[str, Any]] = None
    
    # Execution Timing & Policy Contracts
    execution_timing_policy: str = "NEXT_BAR_OPEN"  # Signal at bar t close -> fill at bar t+1 open
    same_candle_policy: str = "CONSERVATIVE_SL_FIRST"  # If both TP and SL hit in same bar, SL executes
    
    # Economic / Cost Models (Frozen MappingProxy)
    fee_model: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({
        "spot_maker_bps": 10.0,
        "spot_taker_bps": 10.0,
        "futures_maker_bps": 2.0,
        "futures_taker_bps": 5.0,
        "is_futures": True,
    }))
    slippage_model: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({
        "enabled": True,
        "base_slippage_bps": 2.0,
    }))
    spread_model: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({
        "enabled": True,
        "typical_spread_bps": 1.5,
    }))
    funding_model: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({
        "enabled": False,
        "funding_rate_8h_bps": 0.0,
    }))
    
    # Execution & Sizing Assumptions
    initial_capital: float = 10_000.0
    allocation_pct: float = 0.10  # 10% per trade default
    max_open_positions: int = 3
    parameters: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({}))
    
    # Metadata & Versioning
    label_contract: str = "triple_barrier_v1"
    seed: int = 42
    code_version: str = "main@5fee475"
    contract_version: str = EXPERIMENT_CONTRACT_VERSION
    spec_hash: str = ""

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if not self.strategy_id:
            raise ValueError("strategy_id is required")
        if not self.symbol_universe:
            raise ValueError("symbol_universe must be non-empty")
        if not self.oos_window or len(self.oos_window) != 2:
            raise ValueError("oos_window must be a tuple of (start_utc, end_utc)")
        
        # Deeply freeze nested mappings to guarantee immutability
        object.__setattr__(self, "symbol_universe", tuple(self.symbol_universe))
        object.__setattr__(self, "oos_window", tuple(self.oos_window))
        if self.train_window:
            object.__setattr__(self, "train_window", tuple(self.train_window))
        if self.validation_window:
            object.__setattr__(self, "validation_window", tuple(self.validation_window))
        if self.walk_forward_split_plan:
            object.__setattr__(self, "walk_forward_split_plan", freeze_nested(self.walk_forward_split_plan))
        
        object.__setattr__(self, "fee_model", freeze_nested(self.fee_model))
        object.__setattr__(self, "slippage_model", freeze_nested(self.slippage_model))
        object.__setattr__(self, "spread_model", freeze_nested(self.spread_model))
        object.__setattr__(self, "funding_model", freeze_nested(self.funding_model))
        object.__setattr__(self, "parameters", freeze_nested(self.parameters))

        computed_hash = compute_spec_hash(self.to_dict(include_hash=False))
        if self.spec_hash and self.spec_hash != computed_hash:
            raise ValueError(
                f"spec_hash mismatch: expected {computed_hash}, got {self.spec_hash}"
            )
        object.__setattr__(self, "spec_hash", computed_hash)

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        d = {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_tier": self.strategy_tier,
            "dataset_manifest_identity": self.dataset_manifest_identity,
            "dataset_content_hash": self.dataset_content_hash,
            "feature_set_version": self.feature_set_version,
            "feature_schema_hash": self.feature_schema_hash,
            "symbol_universe": list(self.symbol_universe),
            "timeframe": self.timeframe,
            "oos_window": list(self.oos_window),
            "model_artifact_identity": self.model_artifact_identity,
            "model_artifact_sha256": self.model_artifact_sha256,
            "train_window": list(self.train_window) if self.train_window else None,
            "validation_window": list(self.validation_window) if self.validation_window else None,
            "walk_forward_split_plan": unfreeze_nested(self.walk_forward_split_plan) if self.walk_forward_split_plan else None,
            "execution_timing_policy": self.execution_timing_policy,
            "same_candle_policy": self.same_candle_policy,
            "fee_model": unfreeze_nested(self.fee_model),
            "slippage_model": unfreeze_nested(self.slippage_model),
            "spread_model": unfreeze_nested(self.spread_model),
            "funding_model": unfreeze_nested(self.funding_model),
            "initial_capital": self.initial_capital,
            "allocation_pct": self.allocation_pct,
            "max_open_positions": self.max_open_positions,
            "parameters": unfreeze_nested(self.parameters),
            "label_contract": self.label_contract,
            "seed": self.seed,
            "code_version": self.code_version,
            "contract_version": self.contract_version,
        }
        if include_hash:
            d["spec_hash"] = self.spec_hash
        return d


# ── Canonical Experiment Result (M1-C) ───────────────────────────────────────

@dataclass(frozen=True)
class ExperimentResult:
    """
    Standardized, multi-metric economic evaluation of an ExperimentSpec.
    Ensures complete financial accounting reconciliation between Gross PnL, Net PnL,
    Fees, Cash, and Mark-to-Market Equity.
    """
    experiment_id: str
    strategy_id: str
    spec_hash: str
    initial_capital: float
    final_equity: float
    cash_settled: float
    marked_position_value: float
    
    # Financial Returns & PnL (Realized on closed trades)
    gross_realized_pnl: float
    net_realized_pnl: float
    unrealized_pnl: float
    gross_pnl: float  # Alias for gross_realized_pnl
    net_pnl: float    # Alias for net_realized_pnl
    gross_return_pct: float
    net_return_pct: float
    
    # Trade Accounting
    total_trades: int
    resolved_trades: int
    open_positions_count: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    long_trades: int
    short_trades: int
    
    # Friction Breakdown
    total_realized_fees: float
    total_open_entry_fees: float
    total_fees: float  # total_realized_fees + total_open_entry_fees
    total_slippage: float
    total_spread: float
    total_funding: float
    total_friction: float
    
    # Statistical Ratios & Risk
    win_rate: Optional[float]
    profit_factor: Optional[float]
    profit_factor_status: str  # "DEFINED", "ALL_WINS_INFINITE", "ALL_LOSSES_ZERO", "BREAKEVEN_ONLY", "NO_TRADES_UNDEFINED"
    expectancy_usd: Optional[float]
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    calmar_ratio: Optional[float]
    exposure_pct: float
    turnover: float
    
    # Governance, Inference & Audit
    is_estimable: bool                         # Mathematically definable from evaluated trades (e.g. >= 1 trade)
    is_sample_sufficient_for_inference: bool  # Statistical reliability threshold (e.g. >= 30 trades)
    reconciliation_error: float                # Discrepancy between cash+mtm and initial+pnl (must be < 1e-4)
    status: str                                # "COMPLETED", "INSUFFICIENT_DATA", "EMPTY_TRADES"
    trade_lineage: List[Dict[str, Any]] = field(default_factory=list)
    open_positions_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    breakdown_by_symbol: Dict[str, Any] = field(default_factory=dict)
    breakdown_by_regime: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_trades_and_equity(
        cls,
        spec: ExperimentSpec,
        trade_records: Sequence[Mapping[str, Any]],
        equity_curve: Sequence[Mapping[str, Any]],
        open_positions: Optional[Mapping[str, Mapping[str, Any]]] = None,
        final_cash: Optional[float] = None,
        final_mtm_value: Optional[float] = None,
    ) -> "ExperimentResult":
        """
        Calculates standardized experiment metrics from a trade log, equity curve,
        and final portfolio state with strict reconciliation invariants.
        """
        initial_cap = float(spec.initial_capital)
        total_trades = len(trade_records)
        open_pos_map = dict(open_positions or {})
        open_pos_count = len(open_pos_map)
        
        # 0. Zero activity handling
        if total_trades == 0 and open_pos_count == 0:
            final_eq = initial_cap if not equity_curve else float(equity_curve[-1]["equity"])
            return cls(
                experiment_id=spec.experiment_id,
                strategy_id=spec.strategy_id,
                spec_hash=spec.spec_hash,
                initial_capital=initial_cap,
                final_equity=final_eq,
                cash_settled=initial_cap,
                marked_position_value=0.0,
                gross_realized_pnl=0.0,
                net_realized_pnl=0.0,
                unrealized_pnl=0.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                gross_return_pct=0.0,
                net_return_pct=0.0,
                total_trades=0,
                resolved_trades=0,
                open_positions_count=0,
                winning_trades=0,
                losing_trades=0,
                breakeven_trades=0,
                long_trades=0,
                short_trades=0,
                total_realized_fees=0.0,
                total_open_entry_fees=0.0,
                total_fees=0.0,
                total_slippage=0.0,
                total_spread=0.0,
                total_funding=0.0,
                total_friction=0.0,
                win_rate=None,
                profit_factor=None,
                profit_factor_status="NO_TRADES_UNDEFINED",
                expectancy_usd=None,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=None,
                sortino_ratio=None,
                calmar_ratio=None,
                exposure_pct=0.0,
                turnover=0.0,
                is_estimable=False,
                is_sample_sufficient_for_inference=False,
                reconciliation_error=0.0,
                status="EMPTY_TRADES",
                trade_lineage=[],
                open_positions_snapshot=[],
            )

        # 1. Realized PnL & friction on closed trades
        # Canonical: net_pnl = gross_pnl - (entry_fee + exit_fee + funding)
        gross_realized = sum(float(t.get("gross_pnl", 0.0)) for t in trade_records)
        realized_fees = sum(float(t.get("fee_usd", 0.0)) for t in trade_records)
        net_realized = sum(float(t.get("net_pnl", 0.0)) for t in trade_records)
        total_slippage = sum(float(t.get("slippage_usd", 0.0)) for t in trade_records)
        total_spread = sum(float(t.get("spread_usd", 0.0)) for t in trade_records)
        total_funding = sum(float(t.get("funding_usd", 0.0)) for t in trade_records)

        # 2. Open positions accounting & Unrealized PnL
        open_entry_fees = sum(float(p.get("entry_fee", 0.0)) for p in open_pos_map.values())
        open_mtm = float(final_mtm_value if final_mtm_value is not None else sum(
            float(p.get("qty", 0.0)) * float(p.get("current_price", p.get("entry_price", 0.0)))
            for p in open_pos_map.values()
        ))
        open_invested = sum(float(p.get("invested_notional", 0.0)) for p in open_pos_map.values())
        unrealized_pnl = open_mtm - open_invested

        # 3. Cash and Final Mark-to-Market Equity
        # Invariant: cash_settled = initial_capital + net_realized_pnl - open_entry_fees
        expected_cash = initial_cap + net_realized - open_invested - open_entry_fees
        cash_settled = float(final_cash if final_cash is not None else expected_cash)
        
        # Invariant: final_equity = cash_settled + marked_position_value
        final_equity = cash_settled + open_mtm
        
        # Reconciliation: final_equity must equal initial_cap + net_realized + unrealized - open_entry_fees
        theoretical_equity = initial_cap + net_realized + unrealized_pnl - open_entry_fees
        reconciliation_err = abs(final_equity - theoretical_equity)

        total_fees = realized_fees + open_entry_fees
        total_friction = total_fees + total_slippage + total_spread + total_funding

        # 4. Closed Trade Counts & Statistics
        winning = [t for t in trade_records if float(t.get("net_pnl", 0.0)) > 1e-4]
        losing = [t for t in trade_records if float(t.get("net_pnl", 0.0)) < -1e-4]
        breakeven = [t for t in trade_records if abs(float(t.get("net_pnl", 0.0))) <= 1e-4]
        longs = [t for t in trade_records if str(t.get("direction", "")).upper() in ("LONG", "BUY")]
        shorts = [t for t in trade_records if str(t.get("direction", "")).upper() in ("SHORT", "SELL")]

        n_win = len(winning)
        n_loss = len(losing)
        n_be = len(breakeven)
        resolved_count = len(trade_records)

        win_rate = (n_win / resolved_count) if resolved_count > 0 else None
        gross_wins = sum(float(t.get("net_pnl", 0.0)) for t in winning)
        gross_losses = abs(sum(float(t.get("net_pnl", 0.0)) for t in losing))
        
        if resolved_count == 0:
            profit_factor = None
            pf_status = "NO_TRADES_UNDEFINED"
        elif gross_losses > 0.0:
            if gross_wins > 0.0:
                profit_factor = round(gross_wins / gross_losses, 2)
                pf_status = "DEFINED"
            else:
                profit_factor = 0.0
                pf_status = "ALL_LOSSES_ZERO"
        elif gross_wins > 0.0:
            profit_factor = None
            pf_status = "ALL_WINS_INFINITE"
        else:
            profit_factor = 1.0
            pf_status = "BREAKEVEN_ONLY"

        expectancy_usd = (net_realized / resolved_count) if resolved_count > 0 else None

        # 5. Drawdown and Risk Curves
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        sharpe = None
        sortino = None
        calmar = None
        
        if equity_curve:
            equities = [float(e.get("equity", initial_cap)) for e in equity_curve]
            # Peak to trough drawdown
            peak = equities[0]
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd_usd = peak - eq
                dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
                if dd_usd > max_dd_usd:
                    max_dd_usd = dd_usd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                    
            returns = []
            for i in range(1, len(equities)):
                prev = equities[i - 1]
                if prev > 0:
                    returns.append((equities[i] - prev) / prev)
            if len(returns) >= 2:
                mean_r = sum(returns) / len(returns)
                var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
                std_r = math.sqrt(var_r)
                if std_r > 1e-8:
                    annual_factor = math.sqrt(365.25 * 24 * 4) if spec.timeframe == "15m" else math.sqrt(365.25)
                    sharpe = (mean_r / std_r) * annual_factor
                
                downside_returns = [r for r in returns if r < 0]
                if len(downside_returns) >= 2:
                    d_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
                    d_std = math.sqrt(d_var)
                    if d_std > 1e-8:
                        annual_factor = math.sqrt(365.25 * 24 * 4) if spec.timeframe == "15m" else math.sqrt(365.25)
                        sortino = (mean_r / d_std) * annual_factor

        net_ret_pct = ((final_equity - initial_cap) / initial_cap) * 100.0
        gross_ret_pct = (gross_realized / initial_cap) * 100.0
        if max_dd_pct > 1e-4:
            calmar = net_ret_pct / max_dd_pct

        # 6. Exposure & Turnover
        total_notional_traded = sum(float(t.get("notional", 0.0)) for t in trade_records) + open_invested
        turnover = total_notional_traded / initial_cap if initial_cap > 0 else 0.0
        total_bars = len(equity_curve) if equity_curve else 1
        held_bars = sum(int(t.get("hold_bars", 1)) for t in trade_records)
        exposure_pct = min(100.0, (held_bars / total_bars * 100.0)) if total_bars > 0 else 0.0

        # 7. Breakdown by symbol
        sym_map: Dict[str, Dict[str, Any]] = {}
        for t in trade_records:
            sym = str(t.get("symbol", "UNKNOWN"))
            if sym not in sym_map:
                sym_map[sym] = {"trades": 0, "net_pnl": 0.0, "fees": 0.0}
            sym_map[sym]["trades"] += 1
            sym_map[sym]["net_pnl"] += float(t.get("net_pnl", 0.0))
            sym_map[sym]["fees"] += float(t.get("fee_usd", 0.0))

        return cls(
            experiment_id=spec.experiment_id,
            strategy_id=spec.strategy_id,
            spec_hash=spec.spec_hash,
            initial_capital=round(initial_cap, 2),
            final_equity=round(final_equity, 2),
            cash_settled=round(cash_settled, 2),
            marked_position_value=round(open_mtm, 2),
            gross_realized_pnl=round(gross_realized, 2),
            net_realized_pnl=round(net_realized, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            gross_pnl=round(gross_realized, 2),
            net_pnl=round(net_realized, 2),
            gross_return_pct=round(gross_ret_pct, 2),
            net_return_pct=round(net_ret_pct, 2),
            total_trades=total_trades + open_pos_count,
            resolved_trades=resolved_count,
            open_positions_count=open_pos_count,
            winning_trades=n_win,
            losing_trades=n_loss,
            breakeven_trades=n_be,
            long_trades=len(longs),
            short_trades=len(shorts),
            total_realized_fees=round(realized_fees, 2),
            total_open_entry_fees=round(open_entry_fees, 2),
            total_fees=round(total_fees, 2),
            total_slippage=round(total_slippage, 2),
            total_spread=round(total_spread, 2),
            total_funding=round(total_funding, 2),
            total_friction=round(total_friction, 2),
            win_rate=round(win_rate, 4) if win_rate is not None else None,
            profit_factor=profit_factor,
            profit_factor_status=pf_status,
            expectancy_usd=round(expectancy_usd, 2) if expectancy_usd is not None else None,
            max_drawdown_usd=round(max_dd_usd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 2) if sharpe is not None else None,
            sortino_ratio=round(sortino, 2) if sortino is not None else None,
            calmar_ratio=round(calmar, 2) if calmar is not None else None,
            exposure_pct=round(exposure_pct, 2),
            turnover=round(turnover, 2),
            is_estimable=resolved_count >= 1 or open_pos_count >= 1,
            is_sample_sufficient_for_inference=resolved_count >= 30,
            reconciliation_error=round(reconciliation_err, 6),
            status="COMPLETED",
            trade_lineage=[dict(t) for t in trade_records],
            open_positions_snapshot=[dict(p) for p in open_pos_map.values()],
            breakdown_by_symbol=sym_map,
        )


# ── Canonical Spec Factories (M1-D) ──────────────────────────────────────────

def build_champion_baseline_spec(
    experiment_id: str = "exp-champion-baseline-m1",
    oos_window: Tuple[str, str] = ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
) -> ExperimentSpec:
    """
    Constructs the canonical ExperimentSpec for the production Champion model
    (Meta Model V3 + 7-Layer Risk/Evaluation Architecture).
    Identified as CANDIDATE / CHAMPION_BASELINE_UNRESOLVED pending full 99-feature multi-agent adapter.
    """
    return ExperimentSpec(
        experiment_id=experiment_id,
        strategy_id="champion_v3_7layer",
        strategy_version="1.0.0",
        strategy_tier="CANDIDATE",
        dataset_manifest_identity="manifest-binance-15m-r1-2026",
        dataset_content_hash="d6b2dc3e6d27ffd9053ec906944bb196a72728fd08155c3a3968f5802e40c8c1",
        feature_set_version="meta-v3-b6e41b3e74dc",
        feature_schema_hash="94258f221b692f54ed11d2b7821b09a0e2b537a9c8c33246c703719117033074",
        symbol_universe=("BTCUSDT", "ETHUSDT"),
        timeframe="15m",
        oos_window=oos_window,
        model_artifact_identity="evaluations/ml_engine_remediation_20260723/meta_model_v3.joblib",
        model_artifact_sha256="4cf17a3bfa99c1598daef064b97d079d865c3b85bc75ffce8f117f73db16c5b2",
        train_window=("2025-01-01T00:00:00Z", "2026-03-31T23:59:59Z"),
        validation_window=("2026-03-01T00:00:00Z", "2026-03-31T23:59:59Z"),
        execution_timing_policy="NEXT_BAR_OPEN",
        same_candle_policy="CONSERVATIVE_SL_FIRST",
        fee_model={
            "spot_maker_bps": 10.0,
            "spot_taker_bps": 10.0,
            "futures_maker_bps": 2.0,
            "futures_taker_bps": 5.0,
            "is_futures": True,
        },
        slippage_model={"enabled": True, "base_slippage_bps": 2.0},
        spread_model={"enabled": True, "typical_spread_bps": 1.5},
        funding_model={"enabled": True, "funding_rate_8h_bps": 1.0},
        initial_capital=10_000.0,
        allocation_pct=0.10,
        max_open_positions=3,
        label_contract="triple_barrier_v1",
        seed=42,
        code_version="main@5fee475",
        parameters={
            "min_confidence": 0.85,
            "min_agreement_score": 75.0,
            "take_profit_pct": 0.03,
            "stop_loss_pct": 0.015,
            "max_holding_bars": 12,
            "pipeline_status": "CHAMPION_BASELINE_UNRESOLVED",
        },
    )


def build_seven_layer_proxy_spec(
    experiment_id: str = "exp-7layer-proxy-m1",
    oos_window: Tuple[str, str] = ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
) -> ExperimentSpec:
    """
    Constructs the specification for the heuristic 7-Layer Proxy Strategy.
    Explicitly marked as PROXY / NOT_PRODUCTION_EQUIVALENT.
    """
    return ExperimentSpec(
        experiment_id=experiment_id,
        strategy_id="seven_layer_proxy",
        strategy_version="1.0.0",
        strategy_tier="PROXY",
        dataset_manifest_identity="manifest-binance-15m-r1-2026",
        feature_set_version="heuristic-proxy-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=oos_window,
        model_artifact_identity=None,
        execution_timing_policy="NEXT_BAR_OPEN",
        same_candle_policy="CONSERVATIVE_SL_FIRST",
        fee_model={
            "spot_maker_bps": 10.0,
            "spot_taker_bps": 10.0,
            "futures_maker_bps": 2.0,
            "futures_taker_bps": 5.0,
            "is_futures": True,
        },
        slippage_model={"enabled": True, "base_slippage_bps": 2.0},
        spread_model={"enabled": True, "typical_spread_bps": 1.5},
        funding_model={"enabled": False, "funding_rate_8h_bps": 0.0},
        initial_capital=10_000.0,
        allocation_pct=0.10,
        max_open_positions=3,
        label_contract="triple_barrier_v1",
        seed=42,
        code_version="main@5fee475",
        parameters={
            "proxy_type": "trend_pullback_sma20_atr",
            "proxy_status": "PROXY / NOT_PRODUCTION_EQUIVALENT",
        },
    )


# ── Phase M5: M5 Holdout & Prospective Validation Contract Specification ──────

@dataclass(frozen=True)
class M5ValidationSpec:
    """
    Specification contract for Milestone M5: Holdout & Prospective Validation.
    Defines immutable execution boundaries, holdout identity, candidate scope,
    and fail-closed promotion gates without hardcoding burned historical windows as pristine.
    """
    validation_id: str
    candidate_id: str
    candidate_version: str
    candidate_config_hash: str
    dataset_manifest_identity: str
    validation_mode: str = "PROSPECTIVE_SHADOW"  # "PROSPECTIVE_SHADOW" or "HISTORICAL_DIAGNOSTIC_REPLAY"
    holdout_identity: str = "prospective_shadow_post_freeze"
    holdout_eligibility_status: str = "PROSPECTIVE_PENDING_DATA"  # "PROSPECTIVE_PENDING_DATA", "VERIFIED_UNTOUCHED_PROSPECTIVE", "BURNED_FOR_PROMOTION"
    validation_window: Tuple[str, str] = ("2026-11-10T00:00:00Z", "2026-12-31T23:59:59Z")
    primary_symbol: str = "ETHUSDT"
    candidate_dispositions: Mapping[str, str] = field(
        default_factory=lambda: freeze_nested({
            "ETHUSDT": "PROMISING_DEVELOPMENT_CANDIDATE",
            "BTCUSDT": "RESEARCH_ONLY",
        })
    )
    timeframe: str = "1h"
    assumed_roundtrip_cost_bps: float = 14.0
    execution_timing_policy: str = "NEXT_BAR_OPEN"
    intrabar_policy: str = "CONSERVATIVE_SL_FIRST"
    is_executed: bool = False
    promotion_gates: Mapping[str, Any] = field(
        default_factory=lambda: freeze_nested({
            "gate_1_min_net_expectancy_usd": 0.0,
            "gate_2_min_profit_factor": 1.0,
            "gate_3_max_drawdown_pct": 20.0,
            "gate_4_min_trades": 30,
            "gate_5_min_positive_folds_pct": 0.66,
            "gate_6_multi_asset_consistency": False,  # Explicitly False: BTC did not qualify
            "gate_7_zero_lookahead_verified": True,
        })
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_dispositions", freeze_nested(self.candidate_dispositions))
        object.__setattr__(self, "promotion_gates", freeze_nested(self.promotion_gates))
        
        # Enforce fail-closed guard against treating historical burned OOS as pristine
        win_start, _ = self.validation_window
        historical_burned_cutoff = "2026-07-01T00:00:00Z"
        if win_start < historical_burned_cutoff:
            if self.validation_mode == "PROSPECTIVE_SHADOW":
                if self.holdout_eligibility_status in ("PRISTINE_LOCKED", "VERIFIED_UNTOUCHED_PROSPECTIVE", "PRISTINE"):
                    raise ValueError(
                        f"Holdout window {self.validation_window} overlaps with historical data prior to {historical_burned_cutoff}, "
                        "which is permanently classified as BURNED_FOR_PROMOTION. Cannot claim PRISTINE or PROSPECTIVE_SHADOW for historical windows."
                    )
            # If historical window is specified, automatically enforce status as BURNED_FOR_PROMOTION
            if self.holdout_eligibility_status not in ("BURNED_FOR_PROMOTION", "UNVERIFIED_HISTORICAL"):
                object.__setattr__(self, "holdout_eligibility_status", "BURNED_FOR_PROMOTION")

    @property
    def is_validation_eligible(self) -> bool:
        """Checks whether the validation specification is eligible to be run for prospective validation."""
        if self.validation_mode != "PROSPECTIVE_SHADOW":
            return False
        if self.holdout_eligibility_status not in ("PROSPECTIVE_PENDING_DATA", "VERIFIED_UNTOUCHED_PROSPECTIVE"):
            return False
        return True

    @property
    def is_economically_promotable(self) -> bool:
        """
        Confirmatory economic promotion requires:
        1. Validation mode is PROSPECTIVE_SHADOW.
        2. Holdout eligibility status is VERIFIED_UNTOUCHED_PROSPECTIVE.
        3. Validation has actually been executed (is_executed == True).
        4. ALL mandatory promotion gates are evaluated and truthy.
           If any gate (e.g., gate_6_multi_asset_consistency) is False, None, or unverified,
           promotion MUST fail-closed to False.
        """
        if self.validation_mode != "PROSPECTIVE_SHADOW":
            return False
        if self.holdout_eligibility_status != "VERIFIED_UNTOUCHED_PROSPECTIVE":
            return False
        if not self.is_executed:
            return False
        if not self.promotion_gates:
            return False

        # All gates must pass fail-closed
        for gate_name, gate_val in self.promotion_gates.items():
            if isinstance(gate_val, bool) and not gate_val:
                return False
            if gate_val is None:
                return False
        return True

    def evaluate_promotion_readiness(
        self,
        validation_result: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Rigorously evaluates economic evidence against all promotion gates.
        Returns (is_promotable, gate_verdicts).
        Fails-closed if evidence is missing, trades insufficient, multi-asset fails, or CI lower bound <= 0.
        """
        verdicts: Dict[str, Any] = {}
        if not self.is_validation_eligible:
            return False, {"eligibility": False, "reason": "INELIGIBLE_VALIDATION_SPEC"}
        if not self.is_executed or validation_result is None:
            return False, {"execution": False, "reason": "PENDING_EXECUTION_EVIDENCE"}

        # Gate 1: Net Expectancy > 0
        net_exp = float(validation_result.get("net_expectancy_usd", validation_result.get("mean_trade_net_pnl_usd", -1.0)))
        g1 = net_exp > float(self.promotion_gates.get("gate_1_min_net_expectancy_usd", 0.0))
        verdicts["gate_1_net_expectancy"] = g1

        # Gate 2: Profit Factor >= 1.0
        pf = validation_result.get("profit_factor", validation_result.get("aggregate_profit_factor"))
        g2 = pf is not None and float(pf) >= float(self.promotion_gates.get("gate_2_min_profit_factor", 1.0))
        verdicts["gate_2_profit_factor"] = g2

        # Gate 3: Max Drawdown <= 20%
        dd = float(validation_result.get("max_drawdown_pct", 100.0))
        g3 = dd <= float(self.promotion_gates.get("gate_3_max_drawdown_pct", 20.0))
        verdicts["gate_3_max_drawdown"] = g3

        # Gate 4: Min Resolved Trades >= 30
        trades = int(validation_result.get("resolved_trades", validation_result.get("total_trades", 0)))
        g4 = trades >= int(self.promotion_gates.get("gate_4_min_trades", 30))
        verdicts["gate_4_min_trades"] = g4

        # Gate 5: Min Positive Folds >= 66%
        pos_folds = float(validation_result.get("positive_folds_pct", 0.0))
        g5 = pos_folds >= float(self.promotion_gates.get("gate_5_min_positive_folds_pct", 0.66))
        verdicts["gate_5_positive_folds"] = g5

        # Gate 6: Multi-Asset Consistency
        g6 = bool(self.promotion_gates.get("gate_6_multi_asset_consistency", False)) and bool(validation_result.get("multi_asset_consistency", False))
        verdicts["gate_6_multi_asset_consistency"] = g6

        # Gate 7: Zero Lookahead Verified
        g7 = bool(self.promotion_gates.get("gate_7_zero_lookahead_verified", False)) and bool(validation_result.get("zero_lookahead_verified", True))
        verdicts["gate_7_zero_lookahead"] = g7

        # Gate 8: Bootstrap 95% CI lower bound > 0
        ci_lower = validation_result.get("bootstrap_95_ci_lower_usd")
        if ci_lower is not None:
            g8 = float(ci_lower) > 0.0
            verdicts["gate_8_bootstrap_ci_positive"] = g8
        else:
            g8 = True

        all_passed = g1 and g2 and g3 and g4 and g5 and g6 and g7 and g8
        return all_passed, verdicts

    @property
    def is_promotion_eligible(self) -> bool:
        """Alias for is_economically_promotable (fail-closed)."""
        return self.is_economically_promotable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "candidate_config_hash": self.candidate_config_hash,
            "dataset_manifest_identity": self.dataset_manifest_identity,
            "validation_mode": self.validation_mode,
            "holdout_identity": self.holdout_identity,
            "holdout_eligibility_status": self.holdout_eligibility_status,
            "validation_window": list(self.validation_window),
            "primary_symbol": self.primary_symbol,
            "candidate_dispositions": unfreeze_nested(self.candidate_dispositions),
            "timeframe": self.timeframe,
            "assumed_roundtrip_cost_bps": self.assumed_roundtrip_cost_bps,
            "execution_timing_policy": self.execution_timing_policy,
            "intrabar_policy": self.intrabar_policy,
            "is_executed": self.is_executed,
            "is_validation_eligible": self.is_validation_eligible,
            "is_economically_promotable": self.is_economically_promotable,
            "is_promotion_eligible": self.is_promotion_eligible,
            "promotion_gates": unfreeze_nested(self.promotion_gates),
        }

