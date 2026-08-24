from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from btc_scraper.ml_engine.common_evaluator import (
    ArtifactIdentity,
    EvaluationPipeline,
    FixedClock,
    HistoricalEvaluationAdapter,
    LiveEvaluationAdapter,
    canonical_window_from_rows,
)
from btc_scraper.ml_engine.evaluation_contracts import (
    EvaluationContractError,
    ReadinessState,
    canonical_entry_readiness_contract,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ARTIFACT = ArtifactIdentity("fixture", "v1", "artifact-sha", "schema-sha")


def rows(count: int, *, closed: bool = True) -> list[dict]:
    return [
        {
            "timestamp": (NOW - timedelta(minutes=15 * (count - 1 - index))).isoformat(),
            "open": 100.0 + index,
            "high": 100.5 + index,
            "low": 99.5 + index,
            "close": 100.0 + index,
            "volume": 10.0 + index,
            "closed": closed if index == count - 1 else True,
        }
        for index in range(count)
    ]


def candles(count: int, *, closed: bool = True):
    return canonical_window_from_rows(
        rows(count, closed=closed),
        symbol="BTCUSDT",
        timeframe="15m",
    ).candles


def counted_pipeline(
    calls: dict[str, int],
    *,
    artifact_ok: bool = True,
    schema_ok: bool = True,
) -> EvaluationPipeline:
    def artifact_precondition(_item):
        calls["artifact"] += 1
        if not artifact_ok:
            raise EvaluationContractError("artifact_precondition_failed")

    def schema_precondition(_item):
        calls["schema"] += 1
        if not schema_ok:
            raise EvaluationContractError("schema_precondition_failed")

    def readiness(item):
        calls["readiness"] += 1
        return canonical_entry_readiness_contract().diagnose(
            item.window.candles,
            item.evaluation_time,
        )

    def technical(item):
        calls["technical"] += 1
        return {"regime": "TRENDING", "close": item.window.candles[-1].close}

    def features(item, technical_state):
        calls["features"] += 1
        return {
            "close": technical_state["close"],
            "feature_snapshot_hash": item.window.snapshot_hash,
        }

    def inference(item, features_state):
        calls["inference"] += 1
        return {
            "prediction": 0.9,
            "artifact_hash": item.artifact.artifact_hash,
            "feature_schema_hash": item.artifact.feature_schema_hash,
            "feature_snapshot_hash": features_state["feature_snapshot_hash"],
        }

    def score(_item, _technical, _inference):
        calls["score"] += 1
        return {"raw_score": 80.0, "final_score": 80.0, "side": "BUY", "adjustments": ()}

    def decision(_item, _technical, _inference, _score):
        calls["decision"] += 1
        return {
            "ev_eligible": True,
            "s3_threshold": 0.5,
            "s3_pass": True,
            "risk_gate": {"gated": False},
            "sizing": {"final_position_size": 0.1},
            "final_action": "BUY",
            "take_profit": 110.0,
            "stop_loss": 95.0,
        }

    return EvaluationPipeline(
        technical,
        features,
        inference,
        score,
        decision,
        readiness,
        (artifact_precondition, schema_precondition),
    )


def call_counts() -> dict[str, int]:
    return {
        "artifact": 0,
        "schema": 0,
        "readiness": 0,
        "technical": 0,
        "features": 0,
        "inference": 0,
        "score": 0,
        "decision": 0,
    }


@pytest.mark.parametrize(
    ("artifact_ok", "schema_ok", "count", "expected", "expected_calls"),
    [
        (False, True, 73, "artifact_precondition_failed", {"artifact": 1}),
        (True, False, 73, "schema_precondition_failed", {"artifact": 1, "schema": 1}),
        (
            True,
            True,
            72,
            "readiness_not_ready:WARMING_UP",
            {"artifact": 1, "schema": 1, "readiness": 1},
        ),
    ],
)
def test_p6_g5_contract_precedence_and_no_downstream(
    artifact_ok,
    schema_ok,
    count,
    expected,
    expected_calls,
):
    calls = call_counts()
    adapter = LiveEvaluationAdapter(
        counted_pipeline(calls, artifact_ok=artifact_ok, schema_ok=schema_ok),
        FixedClock(NOW),
    )
    with pytest.raises(EvaluationContractError, match=expected):
        adapter.evaluate(rows=rows(count), symbol="BTCUSDT", timeframe="15m", artifact=ARTIFACT)

    for name, expected_count in expected_calls.items():
        assert calls[name] == expected_count
    assert calls["technical"] == 0
    assert calls["features"] == 0
    assert calls["inference"] == 0
    assert calls["score"] == 0
    assert calls["decision"] == 0


@pytest.mark.parametrize("count", [0, 1, 8, 9, 32, 33, 71, 72])
def test_p6_g5_readiness_matrix_before_effective_minimum(count):
    diagnosis = canonical_entry_readiness_contract().diagnose(rows(count), NOW)
    assert diagnosis.status is ReadinessState.WARMING_UP
    assert diagnosis.required_observations == 73
    assert diagnosis.available_observations == count


@pytest.mark.parametrize("count", [73, 74, 100])
def test_p6_g5_readiness_matrix_at_and_after_effective_minimum(count):
    diagnosis = canonical_entry_readiness_contract().diagnose(candles(count), NOW)
    assert diagnosis.status is ReadinessState.READY
    assert diagnosis.required_observations == 73
    assert diagnosis.available_observations == count


def test_p6_g5_completed_observations_exclude_open_current_candle():
    diagnosis = canonical_entry_readiness_contract().diagnose(candles(73, closed=False), NOW)
    assert diagnosis.status is ReadinessState.INVALID_INPUT
    assert diagnosis.reason_code == "PARTIAL_CANDLE"


def test_p6_g5_first_ready_point_allows_downstream_live_replay_parity():
    live_calls = call_counts()
    replay_calls = call_counts()
    kwargs = dict(rows=rows(73), symbol="BTCUSDT", timeframe="15m", artifact=ARTIFACT)
    live = LiveEvaluationAdapter(counted_pipeline(live_calls), FixedClock(NOW)).evaluate(**kwargs)
    replay = HistoricalEvaluationAdapter(counted_pipeline(replay_calls), FixedClock(NOW)).evaluate(**kwargs)

    assert live == replay
    assert live.canonical_hash == replay.canonical_hash
    assert live.final_action == "BUY"
    for calls in (live_calls, replay_calls):
        assert calls == {
            "artifact": 1,
            "schema": 1,
            "readiness": 1,
            "technical": 1,
            "features": 1,
            "inference": 1,
            "score": 1,
            "decision": 1,
        }


def test_p6_g5_determinism_for_warmup_and_ready_paths():
    warmup = [
        canonical_entry_readiness_contract().diagnose(rows(72), NOW).to_dict()
        for _ in range(5)
    ]
    ready = [
        LiveEvaluationAdapter(counted_pipeline(call_counts()), FixedClock(NOW))
        .evaluate(rows=rows(73), symbol="BTCUSDT", timeframe="15m", artifact=ARTIFACT)
        .canonical_hash
        for _ in range(5)
    ]
    assert len({tuple(item.items()) for item in warmup}) == 1
    assert len(set(ready)) == 1
