from __future__ import annotations

import copy
import json

import pytest

from btc_scraper.ml_engine.pure_scoring import (
    AdjustmentEffect,
    NEUTRAL_SCORE,
    SignalSide,
    apply_side_adjustment,
    score_signal_pure,
)


@pytest.mark.parametrize(
    ("signal", "expected_score", "expected_side"),
    [
        ("STRONG BUY", 90.0, SignalSide.BUY),
        ("WEAK BUY", 55.0, SignalSide.BUY),
        ("BUY", 70.0, SignalSide.BUY),
        ("STRONG SELL", 10.0, SignalSide.SELL),
        ("WEAK SELL", 45.0, SignalSide.SELL),
        ("SELL", 30.0, SignalSide.SELL),
        ("NEUTRAL", 50.0, SignalSide.NEUTRAL),
    ],
)
def test_axis_contract(signal, expected_score, expected_side):
    result = score_signal_pure({"signal": signal})
    assert result.final_score == expected_score
    assert result.side is expected_side


@pytest.mark.parametrize("score", [51.0, 55.0, 70.0, 99.0])
def test_buy_weakening_never_crosses_neutral(score):
    result = apply_side_adjustment(score, SignalSide.BUY, AdjustmentEffect.WEAKEN, 1_000)
    assert result == NEUTRAL_SCORE


@pytest.mark.parametrize("score", [49.0, 45.0, 30.0, 1.0])
def test_sell_weakening_never_crosses_neutral(score):
    result = apply_side_adjustment(score, SignalSide.SELL, AdjustmentEffect.WEAKEN, 1_000)
    assert result == NEUTRAL_SCORE


@pytest.mark.parametrize("magnitude", [1.0, 5.0, 20.0, 100.0])
def test_strengthening_is_mirrored_around_neutral(magnitude):
    buy = apply_side_adjustment(70, SignalSide.BUY, AdjustmentEffect.STRENGTHEN, magnitude)
    sell = apply_side_adjustment(30, SignalSide.SELL, AdjustmentEffect.STRENGTHEN, magnitude)
    assert abs(buy - NEUTRAL_SCORE) == abs(sell - NEUTRAL_SCORE)


@pytest.mark.parametrize("magnitude", [1.0, 5.0, 20.0, 100.0])
def test_weakening_is_mirrored_and_monotonic(magnitude):
    buy = apply_side_adjustment(70, SignalSide.BUY, AdjustmentEffect.WEAKEN, magnitude)
    sell = apply_side_adjustment(30, SignalSide.SELL, AdjustmentEffect.WEAKEN, magnitude)
    assert abs(buy - NEUTRAL_SCORE) == abs(sell - NEUTRAL_SCORE)
    assert abs(buy - NEUTRAL_SCORE) <= 20
    assert abs(sell - NEUTRAL_SCORE) <= 20


def test_side_aware_volume_and_atr_semantics():
    buy_good = score_signal_pure({"signal": "BUY", "vol_spike": True})
    sell_good = score_signal_pure({"signal": "SELL", "vol_spike": True})
    buy_bad = score_signal_pure({"signal": "BUY", "atr_shock": True})
    sell_bad = score_signal_pure({"signal": "SELL", "atr_shock": True})
    assert (buy_good.final_score, sell_good.final_score) == (75.0, 25.0)
    assert (buy_bad.final_score, sell_bad.final_score) == (60.0, 40.0)


def test_adverse_sentiment_cannot_create_opposite_trade():
    buy = score_signal_pure(
        {"signal": "BUY", "sentiment": {"normalized_score": -1}},
        {"sentiment_penalty": 1_000},
    )
    sell = score_signal_pure(
        {"signal": "SELL", "sentiment": {"normalized_score": 1}},
        {"sentiment_penalty": 1_000},
    )
    assert (buy.final_score, buy.side) == (50.0, SignalSide.NEUTRAL)
    assert (sell.final_score, sell.side) == (50.0, SignalSide.NEUTRAL)


def test_neutral_cannot_become_directional_from_context():
    result = score_signal_pure(
        {"signal": "NEUTRAL", "atr_shock": True, "vol_spike": True},
        {"above_sma200": True, "meta_probability": 0.0, "meta_reject_threshold": 1.0},
    )
    assert (result.final_score, result.side, result.adjustments) == (
        50.0,
        SignalSide.NEUTRAL,
        (),
    )


def test_result_is_deterministic_and_byte_equivalent():
    analysis = {"signal": "BUY", "atr_shock": True, "tf_1h_bull": 1}
    context = {"vol_spike": True, "adaptive_probability": 0.7}
    encoded = {
        json.dumps(score_signal_pure(analysis, context).to_dict(), sort_keys=True)
        for _ in range(100)
    }
    assert len(encoded) == 1


def test_inputs_are_not_mutated():
    analysis = {"signal": "SELL", "sentiment": {"score": 0.9}}
    context = {"vol_spike": True, "sentiment_penalty": 40}
    before = copy.deepcopy((analysis, context))
    score_signal_pure(analysis, context)
    assert (analysis, context) == before


def test_ambient_runtime_state_does_not_change_result(monkeypatch):
    analysis = {"signal": "SELL", "atr_shock": True}
    context = {"tf_4h_bull": -1}
    baseline = score_signal_pure(analysis, context)
    monkeypatch.setenv("META_REJECT_THRESHOLD", "0.999")
    monkeypatch.setenv("DISABLE_KELLY", "0")
    assert score_signal_pure(analysis, context) == baseline


def test_adjustment_trace_replays_final_score():
    result = score_signal_pure(
        {"signal": "BUY", "vol_spike": True, "atr_shock": True, "tf_1h_bull": 1}
    )
    score = result.raw_score
    for item in result.adjustments:
        assert item.score_before == score
        score = item.score_after
    assert score == result.final_score


def test_score_signal_orchestrator_invokes_pure_scorer_once(monkeypatch):
    import btc_scraper.ml_engine.signal_score as module

    calls = 0
    real_scorer = module.score_signal_pure

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_scorer(*args, **kwargs)

    monkeypatch.setattr(module, "score_signal_pure", counted)
    monkeypatch.setattr(module, "_get_cached_risk_metrics", lambda: {
        "risk_multiplier": 1.0,
        "blocked": False,
        "status": "HEALTHY",
    })
    result = module.score_signal(
        "BUY",
        {"signal": "BUY", "symbol": "BTCUSDT"},
        {"disable_ml": True},
        meta_prediction={"probability": 0.8},
    )
    assert calls == 1
    assert result["scoring_pass_count"] == 1
    assert result["scoring_contract_version"] == "pure-scoring/v1"


def test_pure_module_has_no_forbidden_runtime_dependencies():
    import inspect
    import btc_scraper.ml_engine.pure_scoring as module

    source = inspect.getsource(module)
    for forbidden in (
        "risk_manager",
        "position_size",
        "order_planner",
        "datetime.now",
        "random.",
        "logger.",
        "open(",
    ):
        assert forbidden not in source
