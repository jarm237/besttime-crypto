import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    timeframe: str = "15m"
    coins: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    
    # Cost model
    fee_model: Dict[str, Any] = field(default_factory=lambda: {
        "spot_maker_bps": 10.0,
        "spot_taker_bps": 10.0,
        "futures_maker_bps": 2.0,
        "futures_taker_bps": 5.0,
        "is_futures": True
    })
    
    # Slippage model
    slippage_model: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "mode": "rule_v1",
        "base_slippage_bps": 1.0
    })
    
    # Latency model
    latency_model: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "latency_ms": 250
    })
    
    # Walk forward configuration
    walk_forward: Dict[str, Any] = field(default_factory=lambda: {
        "train_months": 6,
        "test_months": 1,
        "step_months": 1,
        "min_train_samples": 1000,
        "retrain_model": True,
        "reoptimize_threshold": True
    })
    
    # Monte Carlo configuration
    monte_carlo: Dict[str, Any] = field(default_factory=lambda: {
        "n_simulations": 10000,
        "shuffle_trades": True,
        "bootstrap_trades": True,
        "randomize_slippage": True,
        "randomize_latency": True,
        "randomize_spread": True
    })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BacktestConfig":
        # Handle nested updates properly
        config = cls()
        if "initial_capital" in data:
            config.initial_capital = float(data["initial_capital"])
        if "timeframe" in data:
            config.timeframe = str(data["timeframe"])
        if "coins" in data:
            config.coins = list(data["coins"])
        if "fee_model" in data:
            config.fee_model.update(data["fee_model"])
        if "slippage_model" in data:
            config.slippage_model.update(data["slippage_model"])
        if "latency_model" in data:
            config.latency_model.update(data["latency_model"])
        if "walk_forward" in data:
            config.walk_forward.update(data["walk_forward"])
        if "monte_carlo" in data:
            config.monte_carlo.update(data["monte_carlo"])
        return config


# Default institutional approval rules for strategies
APPROVAL_RULES = {
    "min_profit_factor": 1.3,
    "min_sharpe": 1.0,
    "max_drawdown": 0.10,  # 10%
    "min_trades": 100,
    "max_cost_drag_pct_of_gross": 0.35,  # 35%
    "max_probability_of_loss_mc": 0.25,  # 25%
    "max_probability_dd_gt_10pct": 0.20,  # 20%
    "positive_in_at_least_n_regimes": 3,
}


@dataclass
class BacktestResult:
    run_id: str
    timestamp: str
    config: Dict[str, Any]
    metrics: Dict[str, Any]
    trades: List[Dict[str, Any]]
    regime_metrics: Dict[str, Any]
    stress_metrics: Dict[str, Any]
    monte_carlo_metrics: Dict[str, Any]
    attribution: Dict[str, Any]
    approval_status: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
