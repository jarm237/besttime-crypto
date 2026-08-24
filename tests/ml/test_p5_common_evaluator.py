from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_scraper.ml_engine.common_evaluator import (
    COMMON_EVALUATOR_VERSION,
    ArtifactIdentity,
    CanonicalCandleWindow,
    EvaluationPipeline,
    FixedClock,
    HistoricalEvaluationAdapter,
    InMemoryPersistence,
    LiveEvaluationAdapter,
    MarketEvaluationInput,
    NoOpPersistence,
    ReplayClock,
    canonical_window_from_rows,
    decision_contract_hash,
    evaluate_market,
)
from btc_scraper.ml_engine.evaluation_contracts import (
    EvaluationContractError,
    ReadinessState,
    canonical_entry_readiness_contract,
)
from btc_scraper.ml_engine.pure_scoring import score_signal_pure
from btc_scraper.ml_engine.s3_thresholds import evaluate_s3_threshold
from btc_scraper.trading.risk_sizing_contract import (
    evaluate_risk_gate,
    finalize_position_size,
)


UTC = timezone.utc
EVALUATION_TIME = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ARTIFACT = ArtifactIdentity("fixture", "v1", "artifact-sha", "schema-sha")


def rows(*, count: int = 4, end: datetime = EVALUATION_TIME) -> list[dict]:
    result = []
    for index in range(count):
        timestamp = end - timedelta(minutes=15 * (count - 1 - index))
        close = 100.0 + index
        result.append({
            "timestamp": timestamp.isoformat(),
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0 + index,
            "closed": True,
        })
    return result


def pipeline(
    *,
    signal: str = "BUY",
    probability: float = 0.9,
    expected_return: float = 0.001,
    risk_approved: bool = True,
    raw_size: float = 0.4,
) -> EvaluationPipeline:
    def technical(item):
        tail = item.window.candles[-1]
        return {
            "signal": signal,
            "regime": "TRENDING",
            "close": tail.close,
            "atr": 2.0,
            "above_sma200": signal == "BUY",
            "below_sma200": signal == "SELL",
        }

    def features(item, technical_state):
        values = {
            "close": technical_state["close"],
            "atr": technical_state["atr"],
            "window_hash": item.window.snapshot_hash,
        }
        return {**values, "feature_snapshot_hash": item.window.snapshot_hash}

    def inference(item, features):
        return {
            "prediction": probability,
            "probability": probability,
            "artifact_hash": item.artifact.artifact_hash,
            "feature_schema_hash": item.artifact.feature_schema_hash,
            "feature_snapshot_hash": features["feature_snapshot_hash"],
            "symbol": item.window.symbol.removesuffix("USDT"),
        }

    def score(item, technical_state, inference_result):
        scored = score_signal_pure(
            technical_state,
            {"meta_probability": inference_result["probability"]},
        )
        return scored.to_dict()

    def decision(item, technical_state, inference_result, scoring):
        side = scoring["side"]
        ev_eligible = expected_return >= float(item.context.get("minimum_ev", 0.0005))
        s3 = evaluate_s3_threshold(item.window.symbol, inference_result["probability"])
        candidate = side if ev_eligible and s3.s3_pass else "NEUTRAL"
        gate = evaluate_risk_gate(
            action=candidate,
            risk_approved=risk_approved,
            reason=None if risk_approved else "fixture_risk_reject",
        )
        sizing = finalize_position_size(
            action=candidate,
            risk_result=gate,
            raw_position_size=raw_size,
            kelly_fraction=0.2,
            minimum_size=0.1,
            maximum_size=1.0,
        )
        actionable = candidate in {"BUY", "SELL"} and sizing.final_position_size > 0
        return {
            "ev_eligible": ev_eligible,
            "s3_threshold": s3.s3_threshold,
            "s3_pass": s3.s3_pass,
            "risk_gate": {
                "eligible": gate.eligible,
                "gated": gate.gated,
                "reason": gate.reason,
            },
            "sizing": sizing.to_dict(),
            "final_action": candidate if actionable else "NEUTRAL",
            "take_profit": technical_state["close"] + 4 if actionable else None,
            "stop_loss": technical_state["close"] - 2 if actionable else None,
            "rejection_reason": (
                None if actionable
                else (
                    "EV_REJECTED" if not ev_eligible
                    else "S3_REJECTED" if not s3.s3_pass
                    else gate.reason
                )
            ),
        }

    return EvaluationPipeline(technical, features, inference, score, decision)


def adapters(pipeline_value, *, persistence=None):
    clock = FixedClock(EVALUATION_TIME)
    return (
        LiveEvaluationAdapter(pipeline_value, clock, persistence or NoOpPersistence()),
        HistoricalEvaluationAdapter(pipeline_value, clock, persistence or NoOpPersistence()),
    )


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "BNBUSDT"])
@pytest.mark.parametrize("signal", ["BUY", "SELL", "NEUTRAL"])
def test_live_replay_full_result_parity(symbol, signal):
    live, replay = adapters(pipeline(signal=signal))
    kwargs = dict(
        rows=rows(),
        symbol=symbol,
        timeframe="15m",
        artifact=ARTIFACT,
        context={"minimum_ev": 0.0005},
    )
    live_result = live.evaluate(**kwargs)
    replay_result = replay.evaluate(**kwargs)
    assert live_result == replay_result
    assert live_result.canonical_hash == replay_result.canonical_hash
    assert live_result.section_hashes() == replay_result.section_hashes()


@pytest.mark.parametrize(
    ("probability", "expected_return", "risk_approved", "reason"),
    [
        (0.9, 0.00049, True, "EV_REJECTED"),
        (0.1, 0.001, True, "S3_REJECTED"),
        (0.9, 0.001, False, "fixture_risk_reject"),
    ],
)
def test_rejection_path_parity_and_zero_exposure(
    probability, expected_return, risk_approved, reason
):
    live, replay = adapters(pipeline(
        probability=probability,
        expected_return=expected_return,
        risk_approved=risk_approved,
    ))
    kwargs = dict(
        rows=rows(),
        symbol="BTCUSDT",
        timeframe="15m",
        artifact=ARTIFACT,
        context={"minimum_ev": 0.0005},
    )
    left, right = live.evaluate(**kwargs), replay.evaluate(**kwargs)
    assert left == right
    assert left.final_action == "NEUTRAL"
    assert left.sizing["final_position_size"] == 0
    assert left.rejection_reason == reason


@pytest.mark.parametrize("raw_size", [0.0, 0.1 - 1e-9, 0.1, 0.1 + 1e-9])
def test_sizing_boundaries_have_adapter_parity(raw_size):
    live, replay = adapters(pipeline(raw_size=raw_size))
    kwargs = dict(
        rows=rows(), symbol="ETHUSDT", timeframe="15m",
        artifact=ARTIFACT, context={"minimum_ev": 0.0005},
    )
    assert live.evaluate(**kwargs) == replay.evaluate(**kwargs)


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 8, 21, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 21, 12, 15, tzinfo=UTC),
        datetime(2026, 8, 21, 13, 0, tzinfo=UTC),
        datetime(2026, 8, 22, 0, 0, tzinfo=UTC),
    ],
)
def test_clock_boundaries_are_explicit(timestamp):
    fixture_rows = rows(end=timestamp)
    live = LiveEvaluationAdapter(pipeline(), FixedClock(timestamp))
    replay = HistoricalEvaluationAdapter(pipeline(), ReplayClock())
    kwargs = dict(
        rows=fixture_rows, symbol="BNBUSDT", timeframe="15m",
        artifact=ARTIFACT, context={"minimum_ev": 0.0005},
    )
    assert live.evaluate(**kwargs) == replay.evaluate(**kwargs)


@pytest.mark.parametrize("timeframe", ["15m", "1h", "4h", "1d"])
def test_mtf_windows_normalize_identically(timeframe):
    live_window = canonical_window_from_rows(
        rows(), symbol="BTCUSDT", timeframe=timeframe
    )
    replay_rows = [
        {**item, "time": item.pop("timestamp")}
        for item in [dict(value) for value in rows()]
    ]
    replay_window = canonical_window_from_rows(
        replay_rows, symbol="BTC/USDT", timeframe=timeframe
    )
    assert live_window == replay_window
    assert live_window.snapshot_hash == replay_window.snapshot_hash


def test_future_or_open_candle_fails_closed():
    future = rows()
    future[-1]["timestamp"] = (EVALUATION_TIME + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="lookahead"):
        LiveEvaluationAdapter(pipeline(), FixedClock(EVALUATION_TIME)).evaluate(
            rows=future,
            symbol="BTCUSDT",
            timeframe="15m",
            artifact=ARTIFACT,
        )
    open_rows = rows()
    open_rows[-1]["closed"] = False
    with pytest.raises(ValueError, match="lookahead"):
        HistoricalEvaluationAdapter(pipeline(), FixedClock(EVALUATION_TIME)).evaluate(
            rows=open_rows,
            symbol="BTCUSDT",
            timeframe="15m",
            artifact=ARTIFACT,
        )


def test_candles_must_be_ordered_and_unique():
    unordered = rows()
    unordered[1], unordered[2] = unordered[2], unordered[1]
    with pytest.raises(ValueError, match="ordered"):
        canonical_window_from_rows(unordered, symbol="BTC", timeframe="15m")


def test_common_evaluator_is_deterministic():
    window = canonical_window_from_rows(rows(), symbol="BTC", timeframe="15m")
    item = MarketEvaluationInput(
        window=window,
        evaluation_time=EVALUATION_TIME,
        artifact=ARTIFACT,
        context={"minimum_ev": 0.0005},
    )
    results = [evaluate_market(item, pipeline()) for _ in range(10)]
    assert len({value.canonical_hash for value in results}) == 1


def test_warming_up_short_circuits_before_any_semantic_stage():
    calls = {"technical": 0, "features": 0, "inference": 0, "score": 0, "decision": 0}

    def readiness(item):
        return canonical_entry_readiness_contract().diagnose(
            item.window.candles,
            item.evaluation_time,
        )

    def counted(name):
        def inner(*_args):
            calls[name] += 1
            return {}
        return inner

    gated = EvaluationPipeline(
        counted("technical"),
        counted("features"),
        counted("inference"),
        counted("score"),
        counted("decision"),
        readiness,
    )
    with pytest.raises(EvaluationContractError, match="WARMING_UP"):
        LiveEvaluationAdapter(gated, FixedClock(EVALUATION_TIME)).evaluate(
            rows=rows(count=72),
            symbol="BTCUSDT",
            timeframe="15m",
            artifact=ARTIFACT,
        )
    assert calls == {"technical": 0, "features": 0, "inference": 0, "score": 0, "decision": 0}


def test_readiness_gate_has_live_replay_parity_at_boundary():
    gated = EvaluationPipeline(
        pipeline().technical,
        pipeline().features,
        pipeline().inference,
        pipeline().score,
        pipeline().decision,
        lambda item: canonical_entry_readiness_contract().diagnose(
            item.window.candles,
            item.evaluation_time,
        ),
    )
    live, replay = adapters(gated)
    kwargs = dict(
        rows=rows(count=73),
        symbol="BTCUSDT",
        timeframe="15m",
        artifact=ARTIFACT,
        context={"minimum_ev": 0.0005},
    )
    assert live.evaluate(**kwargs) == replay.evaluate(**kwargs)

    short = {**kwargs, "rows": rows(count=72)}
    for adapter in adapters(gated):
        with pytest.raises(EvaluationContractError, match=ReadinessState.WARMING_UP.value):
            adapter.evaluate(**short)


def test_persistence_is_outside_and_cannot_change_result():
    memory = InMemoryPersistence()
    live_memory = LiveEvaluationAdapter(pipeline(), FixedClock(EVALUATION_TIME), memory)
    live_noop = LiveEvaluationAdapter(pipeline(), FixedClock(EVALUATION_TIME))
    kwargs = dict(
        rows=rows(), symbol="BTCUSDT", timeframe="15m",
        artifact=ARTIFACT, context={"minimum_ev": 0.0005},
    )
    expected = live_noop.evaluate(**kwargs)
    actual = live_memory.evaluate(**kwargs)
    assert actual == expected
    assert memory.results == [actual]


def test_artifact_and_schema_identity_fail_closed():
    base = pipeline()

    def bad_inference(item, features):
        return {
            "prediction": 0.9,
            "probability": 0.9,
            "artifact_hash": "wrong",
            "feature_schema_hash": item.artifact.feature_schema_hash,
        }

    bad = EvaluationPipeline(
        base.technical, base.features, bad_inference, base.score, base.decision
    )
    with pytest.raises(ValueError, match="artifact identity"):
        LiveEvaluationAdapter(bad, FixedClock(EVALUATION_TIME)).evaluate(
            rows=rows(), symbol="BTCUSDT", timeframe="15m", artifact=ARTIFACT
        )


def test_nonactionable_positive_size_is_rejected_by_composition_boundary():
    base = pipeline()

    def invalid_decision(item, technical, inference, scoring):
        return {
            "final_action": "NEUTRAL",
            "risk_gate": {"gated": False},
            "sizing": {"final_position_size": 0.1},
        }

    invalid = EvaluationPipeline(
        base.technical, base.features, base.inference, base.score, invalid_decision
    )
    with pytest.raises(ValueError, match="non-actionable"):
        LiveEvaluationAdapter(invalid, FixedClock(EVALUATION_TIME)).evaluate(
            rows=rows(), symbol="BTCUSDT", timeframe="15m", artifact=ARTIFACT
        )


def test_decision_contract_hash_is_stable_and_config_sensitive():
    assert decision_contract_hash({}) == decision_contract_hash({})
    assert decision_contract_hash({"risk_config_hash": "a"}) != decision_contract_hash(
        {"risk_config_hash": "b"}
    )


def test_evaluator_contains_no_io_clock_persistence_or_execution_calls():
    source_path = Path("btc_scraper/ml_engine/common_evaluator.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    evaluator = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_market"
    )
    forbidden = {
        "open", "sleep", "now", "time", "persist", "place_order",
        "submit_live", "create_fill", "mutate_ledger",
    }
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(evaluator)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert called.isdisjoint(forbidden)


def test_adapter_methods_contain_no_semantic_contract_calls():
    source = Path("btc_scraper/ml_engine/common_evaluator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    adapter = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MarketEvaluationAdapter"
    )
    forbidden = {
        "score_signal_pure", "evaluate_s3_threshold", "evaluate_risk_gate",
        "finalize_position_size",
    }
    names = {node.id for node in ast.walk(adapter) if isinstance(node, ast.Name)}
    assert names.isdisjoint(forbidden)


def test_contract_version_is_exposed():
    live, _ = adapters(pipeline())
    result = live.evaluate(
        rows=rows(), symbol="BTCUSDT", timeframe="15m",
        artifact=ARTIFACT, context={"minimum_ev": 0.0005},
    )
    assert result.evaluator_contract_version == COMMON_EVALUATOR_VERSION
    assert len(result.decision_contract_hash) == 64
