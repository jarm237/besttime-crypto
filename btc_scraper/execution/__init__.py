"""
btc_scraper/execution/__init__.py
Phase 10 – Execution Intelligence Package | Phase 1 Remediation
"""
from .execution_config import ExecutionConfig, TWAPConfig
from .fill_tracker import FillTracker, ExecutionRecord, FillEvent, OrderStatus
from .liquidity_analyzer import LiquidityAnalyzer, LiquiditySnapshot
from .slippage_predictor import SlippagePredictor, SlippagePredictorV1, SlippagePredictorV2
from .order_type_selector import OrderTypeSelector, OrderDecision, OrderType, Urgency, TimeInForce
from .smart_orders import SmartOrderFactory, MarketOrderSpec, LimitOrderSpec, AggressiveLimitSpec, TWAPOrderSpec
from .twap import TWAPExecutor, TWAPPlan, ChildOrderSlice
from .execution_planner import ExecutionPlanner, ExecutionPlan
from .execution_risk_monitor import ExecutionRiskMonitor, GuardDecision, GuardAction
from .post_trade_analyzer import PostTradeAnalyzer, ExecutionCostBreakdown
from .exchange_adapter import (
    WriteExchangeAdapter, ReadOnlyExchangeAdapter,
    make_write_adapter_from_env, make_readonly_adapter_from_env,
)
from .execution_engine import ExecutionEngine

__all__ = [
    "ExecutionConfig", "TWAPConfig",
    "FillTracker", "ExecutionRecord", "FillEvent", "OrderStatus",
    "LiquidityAnalyzer", "LiquiditySnapshot",
    "SlippagePredictor", "SlippagePredictorV1", "SlippagePredictorV2",
    "OrderTypeSelector", "OrderDecision", "OrderType", "Urgency", "TimeInForce",
    "SmartOrderFactory", "MarketOrderSpec", "LimitOrderSpec", "AggressiveLimitSpec", "TWAPOrderSpec",
    "TWAPExecutor", "TWAPPlan", "ChildOrderSlice",
    "ExecutionPlanner", "ExecutionPlan",
    "ExecutionRiskMonitor", "GuardDecision", "GuardAction",
    "PostTradeAnalyzer", "ExecutionCostBreakdown",
    "WriteExchangeAdapter", "ReadOnlyExchangeAdapter",
    "make_write_adapter_from_env", "make_readonly_adapter_from_env",
    "ExecutionEngine",
]
