"""
btc_scraper/execution/execution_config.py
Phase 10 – Execution Intelligence Configuration
"""
from dataclasses import dataclass, field
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class TWAPConfig:
    enabled: bool = True
    slices: int = 5
    interval_seconds: int = 30
    max_duration_seconds: int = 180
    cancel_on_signal_reversal: bool = True


@dataclass
class ExecutionConfig:
    # Master switch
    enabled: bool = True
    dry_run: bool = True

    # Guard thresholds
    max_spread_bps: float = 20.0
    max_slippage_bps: float = 30.0
    min_liquidity_score: float = 0.4
    max_latency_ms: int = 1500
    max_participation_rate: float = 0.02   # max fraction of ADV per order

    # Order behaviour
    default_order_type: str = "LIMIT"       # LIMIT | MARKET | AGGRESSIVE_LIMIT
    emergency_order_type: str = "MARKET"
    limit_order_max_wait_seconds: int = 30

    # Fees / spread (mirrors Phase 9 CostModel defaults)
    futures_taker_bps: float = 5.0
    futures_maker_bps: float = 2.0
    spread_bps_default: float = 2.0

    # TWAP
    twap: TWAPConfig = field(default_factory=TWAPConfig)

    # Paper-to-live approval thresholds
    paper_approval: Dict[str, Any] = field(default_factory=lambda: {
        "min_paper_trades": 50,
        "realized_slippage_within_expected_p75": True,
        "execution_reject_rate_below": 0.20,
        "no_critical_execution_incidents": True,
        "paper_net_pnl_not_worse_than_backtest_by": 0.30,
    })

    @classmethod
    def from_json(cls, path: str) -> "ExecutionConfig":
        """Load config from execution_config.json."""
        cfg_path = Path(path)
        if not cfg_path.exists():
            return cls()
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        ex = raw.get("execution", raw)
        twap_raw = ex.pop("twap", {})
        obj = cls(**{k: v for k, v in ex.items() if k in cls.__dataclass_fields__})
        obj.twap = TWAPConfig(**{k: v for k, v in twap_raw.items() if k in TWAPConfig.__dataclass_fields__})
        return obj

    def to_dict(self) -> Dict[str, Any]:
        import dataclasses
        d = dataclasses.asdict(self)
        return d
