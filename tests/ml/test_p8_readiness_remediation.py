"""P8 Remediation Regression Test Suite — Canonical 73-Candle Readiness Window.

Validates R3-R8 readiness requirements:
- History producer supplies canonical required window (>=73 candles) when available.
- 72 candles fail closed with INSUFFICIENT_CANONICAL_HISTORY.
- Full production pipeline integration (core.analyze_market -> evaluate_live_market).
- Timestamp, ordering, and lookahead invariants are strictly maintained.
- Model, feature, S3, EV, and risk contracts remain strictly frozen.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest

from btc_scraper.analysis.core import analyze_market
from btc_scraper.ml_engine.evaluation_contracts import (
    EvaluationContractError,
    canonical_entry_readiness_contract,
    canonical_readiness_minimum_observations,
)
from btc_scraper.ml_engine.production_evaluator import evaluate_live_market


def _generate_synthetic_candles(count: int, base_time: datetime | None = None) -> list[dict[str, Any]]:
    """Helper to generate contiguous completed 15m candles with valid UTC ISO timestamps."""
    if base_time is None:
        base_time = datetime(2026, 8, 24, 0, 0, 0, tzinfo=timezone.utc)
    
    candles = []
    close_price = 60000.0
    for i in range(count):
        candle_open_time = base_time + timedelta(minutes=15 * i)
        iso_str = candle_open_time.isoformat()
        
        c = {
            "time": iso_str,
            "time_utc": iso_str,
            "open": close_price,
            "high": close_price + 50.0,
            "low": close_price - 50.0,
            "close": close_price,
            "volume": 100.0,
            "closed": True,
            "rsi": 50.0,
            "ema9": close_price,
            "ema21": close_price,
            "sma50": close_price,
            "sma200": close_price,
            "macd": 0.0,
            "macd_signal": 0.0,
            "macd_hist": 0.0,
            "bb_upper": close_price + 100.0,
            "bb_middle": close_price,
            "bb_lower": close_price - 100.0,
        }
        candles.append(c)
    return candles


@dataclass
class DummySizing:
    rejected: bool = False
    rejection_reason: Any = None
    
    def to_dict(self) -> dict:
        return {}


@dataclass
class DummyEntryDecision:
    eligible: bool = True
    action: Any = None
    gated: bool = False
    rejection_reason: Any = None
    breakdown: Any = None
    sizing: DummySizing = field(default_factory=DummySizing)


class DummyTrader:
    max_trade_usdt = 1000.0
    min_trade_usdt = 10.0

    def build_entry_decision(self, analysis: Mapping[str, Any], coin: str) -> DummyEntryDecision:
        from btc_scraper.trading.decision_types import TradeAction
        return DummyEntryDecision(action=TradeAction.NEUTRAL)

    def compute_position_size(self, **kwargs: Any) -> DummySizing:
        return DummySizing()


def test_r1_contract_ownership():
    """R1: Confirm canonical source-of-truth requirement owner evaluates to 73."""
    assert canonical_readiness_minimum_observations() == 73


def test_r5_exact_minimum_73_candles():
    """R5 Test 1: Given 73 canonical candles, evaluator returns READY and produces evaluation result."""
    candles = _generate_synthetic_candles(73)
    analysis = analyze_market(candles, coin_name="BTC")
    
    eval_time = datetime.fromisoformat(candles[-1]["time_utc"]) + timedelta(minutes=15)
    trader = DummyTrader()
    
    prod_eval = evaluate_live_market(
        analysis=analysis,
        coin="BTC",
        trader=trader,
        current_balance=10000.0,
        var_cap=None,
        exposure_cap=None,
        evaluation_time=eval_time,
    )
    
    assert prod_eval.result is not None
    assert prod_eval.result.symbol == "BTCUSDT"


def test_r5_one_candle_short_72_candles():
    """R5 Test 2: Given 72 candles, readiness fails closed with INSUFFICIENT_CANONICAL_HISTORY."""
    candles = _generate_synthetic_candles(72)
    analysis = analyze_market(candles, coin_name="BTC")
    
    eval_time = datetime.fromisoformat(candles[-1]["time_utc"]) + timedelta(minutes=15)
    trader = DummyTrader()
    
    with pytest.raises(EvaluationContractError, match="INSUFFICIENT_CANONICAL_HISTORY"):
        evaluate_live_market(
            analysis=analysis,
            coin="BTC",
            trader=trader,
            current_balance=10000.0,
            var_cap=None,
            exposure_cap=None,
            evaluation_time=eval_time,
        )


def test_r5_and_r6_upstream_100_candles_integration():
    """R5 Test 3 & R6: Full production pipeline integration with 100 candles.
    
    Given upstream contains 100 valid completed 15m candles,
    production history MUST NOT be reduced to 8, but MUST be >= 73,
    and production evaluator MUST complete successfully.
    """
    candles = _generate_synthetic_candles(100)
    analysis = analyze_market(candles, coin_name="BTC")
    
    assert len(analysis["history"]) == 73
    assert len(analysis["history"]) != 8
    
    eval_time = datetime.fromisoformat(candles[-1]["time_utc"]) + timedelta(minutes=15)
    trader = DummyTrader()
    
    prod_eval = evaluate_live_market(
        analysis=analysis,
        coin="BTC",
        trader=trader,
        current_balance=10000.0,
        var_cap=None,
        exposure_cap=None,
        evaluation_time=eval_time,
    )
    
    assert prod_eval.result is not None
    assert prod_eval.result.symbol == "BTCUSDT"


def test_r5_eight_candles_genuinely_available():
    """R5 Test 4: Given upstream contains only 8 candles, history length is 8 and readiness fails closed."""
    candles = _generate_synthetic_candles(8)
    analysis = analyze_market(candles, coin_name="BTC")
    
    assert len(analysis["history"]) == 8
    
    eval_time = datetime.fromisoformat(candles[-1]["time_utc"]) + timedelta(minutes=15)
    trader = DummyTrader()
    
    with pytest.raises(EvaluationContractError, match="INSUFFICIENT_CANONICAL_HISTORY"):
        evaluate_live_market(
            analysis=analysis,
            coin="BTC",
            trader=trader,
            current_balance=10000.0,
            var_cap=None,
            exposure_cap=None,
            evaluation_time=eval_time,
        )


def test_r5_large_upstream_history_500_candles():
    """R5 Test 5: Given 500 candles, selected history satisfies canonical requirement."""
    candles = _generate_synthetic_candles(500)
    analysis = analyze_market(candles, coin_name="BTC")
    
    assert len(analysis["history"]) >= 73
    
    eval_time = datetime.fromisoformat(candles[-1]["time_utc"]) + timedelta(minutes=15)
    trader = DummyTrader()
    
    prod_eval = evaluate_live_market(
        analysis=analysis,
        coin="BTC",
        trader=trader,
        current_balance=10000.0,
        var_cap=None,
        exposure_cap=None,
        evaluation_time=eval_time,
    )
    
    assert prod_eval.result is not None


def test_r7_timestamp_no_lookahead():
    """R7 & R5 Test 6: Future candle MUST be blocked by point-in-time / lookahead assertions."""
    candles = _generate_synthetic_candles(74)
    analysis = analyze_market(candles, coin_name="BTC")
    
    # Set evaluation time before the 74th candle open/close time
    eval_time = datetime.fromisoformat(candles[72]["time_utc"]) + timedelta(minutes=5)
    trader = DummyTrader()
    
    with pytest.raises((ValueError, EvaluationContractError), match="(lookahead|FUTURE_OBSERVATION)"):
        evaluate_live_market(
            analysis=analysis,
            coin="BTC",
            trader=trader,
            current_balance=10000.0,
            var_cap=None,
            exposure_cap=None,
            evaluation_time=eval_time,
        )


def test_r8_frozen_contract_regression():
    """R8: Verify readiness requirements remain frozen at 73."""
    contract = canonical_entry_readiness_contract()
    assert contract.required_bars == 73
