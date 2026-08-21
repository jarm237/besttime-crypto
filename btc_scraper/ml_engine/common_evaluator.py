"""Canonical live/replay market-evaluation boundary.

Adapters own acquisition, clock selection, and persistence.  Every semantic
stage is supplied once through :class:`EvaluationPipeline` and is invoked in
the same order for live and replay inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from .economic_contract import EV_CONTRACT_VERSION
from .inference_contract import INFERENCE_CONTRACT_VERSION
from .pure_scoring import SCORING_CONTRACT_VERSION
from .s3_thresholds import S3_THRESHOLD_CONTRACT_VERSION
from btc_scraper.trading.risk_sizing_contract import RISK_SIZING_CONTRACT_VERSION


COMMON_EVALUATOR_VERSION = "common-evaluator/v1"
DECISION_CONTRACT_VERSION = "decision-composition/v1"


def _utc(value: datetime | str | int | float) -> datetime:
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        resolved = datetime.fromtimestamp(numeric, tz=timezone.utc)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        resolved = datetime.fromisoformat(text)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _finite(value: Any, field_name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _freeze(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalCandle:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time", _utc(self.open_time))
        object.__setattr__(self, "close_time", _utc(self.close_time))
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.close_time < self.open_time:
            raise ValueError("candle close_time precedes open_time")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC envelope")
        if self.volume < 0:
            raise ValueError("candle volume must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["open_time"] = self.open_time.isoformat()
        payload["close_time"] = self.close_time.isoformat()
        return payload


@dataclass(frozen=True)
class CanonicalCandleWindow:
    symbol: str
    timeframe: str
    candles: tuple[CanonicalCandle, ...]

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper().replace("/", "").replace("-", "")
        if not symbol:
            raise ValueError("symbol is required")
        if not self.timeframe or not self.candles:
            raise ValueError("timeframe and at least one candle are required")
        object.__setattr__(self, "symbol", symbol)
        prior: datetime | None = None
        for candle in self.candles:
            if prior is not None and candle.open_time <= prior:
                raise ValueError("candles must be strictly ordered and unique")
            prior = candle.open_time

    @property
    def end_time(self) -> datetime:
        return self.candles[-1].close_time

    @property
    def snapshot_hash(self) -> str:
        return _sha256(self.to_dict())

    def assert_point_in_time(self, evaluation_time: datetime) -> None:
        resolved = _utc(evaluation_time)
        if any(not item.closed or item.close_time > resolved for item in self.candles):
            raise ValueError("canonical_window_lookahead")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candles": [item.to_dict() for item in self.candles],
        }


def canonical_window_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    default_interval_seconds: int | None = None,
) -> CanonicalCandleWindow:
    """Normalize exchange rows or replay rows without environment-specific rules."""
    normalized: list[CanonicalCandle] = []
    for row in rows:
        open_raw = row.get("open_time", row.get("time", row.get("timestamp")))
        close_raw = row.get("close_time", row.get("close_timestamp"))
        if open_raw is None:
            raise ValueError("candle open time is required")
        open_time = _utc(open_raw)
        if close_raw is None:
            if default_interval_seconds is None:
                # Existing datasets commonly label rows by their closed-bar time.
                close_time = open_time
            else:
                close_time = datetime.fromtimestamp(
                    open_time.timestamp() + default_interval_seconds,
                    tz=timezone.utc,
                )
        else:
            close_time = _utc(close_raw)
        normalized.append(CanonicalCandle(
            open_time=open_time,
            close_time=close_time,
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row.get("volume", 0.0),
            closed=bool(row.get("closed", row.get("is_closed", True))),
        ))
    return CanonicalCandleWindow(symbol=symbol, timeframe=timeframe, candles=tuple(normalized))


@dataclass(frozen=True)
class ArtifactIdentity:
    model_family: str
    artifact_version: str
    artifact_hash: str
    feature_schema_hash: str


@dataclass(frozen=True)
class MarketEvaluationInput:
    window: CanonicalCandleWindow
    evaluation_time: datetime
    artifact: ArtifactIdentity
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_time", _utc(self.evaluation_time))
        object.__setattr__(self, "context", _freeze(self.context))
        self.window.assert_point_in_time(self.evaluation_time)


@dataclass(frozen=True)
class MarketEvaluationResult:
    symbol: str
    evaluation_time: str
    technical_state: Mapping[str, Any]
    regime: str
    feature_snapshot_hash: str
    prediction: float
    inference: Mapping[str, Any]
    raw_score: float
    final_score: float
    score_side: str
    score_adjustments: tuple[Mapping[str, Any], ...]
    ev_eligible: bool
    s3_threshold: float | None
    s3_pass: bool
    risk_gate: Mapping[str, Any]
    sizing: Mapping[str, Any]
    final_action: str
    take_profit: float | None
    stop_loss: float | None
    rejection_reason: str | None
    artifact_hash: str
    feature_schema_hash: str
    decision_contract_hash: str
    evaluator_contract_version: str = COMMON_EVALUATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "evaluation_time": self.evaluation_time,
            "technical_state": dict(self.technical_state),
            "regime": self.regime,
            "feature_snapshot_hash": self.feature_snapshot_hash,
            "prediction": self.prediction,
            "inference": dict(self.inference),
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "score_side": self.score_side,
            "score_adjustments": [dict(item) for item in self.score_adjustments],
            "ev_eligible": self.ev_eligible,
            "s3_threshold": self.s3_threshold,
            "s3_pass": self.s3_pass,
            "risk_gate": dict(self.risk_gate),
            "sizing": dict(self.sizing),
            "final_action": self.final_action,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "rejection_reason": self.rejection_reason,
            "artifact_hash": self.artifact_hash,
            "feature_schema_hash": self.feature_schema_hash,
            "decision_contract_hash": self.decision_contract_hash,
            "evaluator_contract_version": self.evaluator_contract_version,
        }

    @property
    def canonical_hash(self) -> str:
        return _sha256(self.to_dict())

    def section_hashes(self) -> dict[str, str]:
        return {
            "signal_hash": _sha256({
                "technical_state": dict(self.technical_state),
                "regime": self.regime,
                "feature_snapshot_hash": self.feature_snapshot_hash,
            }),
            "inference_hash": _sha256(dict(self.inference)),
            "score_hash": _sha256({
                "raw_score": self.raw_score,
                "final_score": self.final_score,
                "side": self.score_side,
                "adjustments": [dict(item) for item in self.score_adjustments],
            }),
            "decision_hash": _sha256({
                "ev_eligible": self.ev_eligible,
                "s3_threshold": self.s3_threshold,
                "s3_pass": self.s3_pass,
                "risk_gate": dict(self.risk_gate),
                "sizing": dict(self.sizing),
                "final_action": self.final_action,
                "take_profit": self.take_profit,
                "stop_loss": self.stop_loss,
                "rejection_reason": self.rejection_reason,
                "decision_contract_hash": self.decision_contract_hash,
            }),
        }


TechnicalEvaluator = Callable[[MarketEvaluationInput], Mapping[str, Any]]
FeatureEvaluator = Callable[[MarketEvaluationInput, Mapping[str, Any]], Mapping[str, Any]]
InferenceEvaluator = Callable[[MarketEvaluationInput, Mapping[str, Any]], Mapping[str, Any]]
ScoreEvaluator = Callable[[MarketEvaluationInput, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
DecisionEvaluator = Callable[
    [MarketEvaluationInput, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class EvaluationPipeline:
    technical: TechnicalEvaluator
    features: FeatureEvaluator
    inference: InferenceEvaluator
    score: ScoreEvaluator
    decision: DecisionEvaluator


def decision_contract_hash(context: Mapping[str, Any] | None = None) -> str:
    relevant = dict(context or {})
    contract = {
        "composition": DECISION_CONTRACT_VERSION,
        "ev": EV_CONTRACT_VERSION,
        "s3": S3_THRESHOLD_CONTRACT_VERSION,
        "inference": INFERENCE_CONTRACT_VERSION,
        "scoring": SCORING_CONTRACT_VERSION,
        "risk_sizing": RISK_SIZING_CONTRACT_VERSION,
        "threshold_config_hash": relevant.get("threshold_config_hash"),
        "risk_config_hash": relevant.get("risk_config_hash"),
    }
    return _sha256(contract)


def evaluate_market(
    evaluation_input: MarketEvaluationInput,
    pipeline: EvaluationPipeline,
) -> MarketEvaluationResult:
    """Execute every decision stage exactly once from explicit input."""
    technical = dict(pipeline.technical(evaluation_input))
    features = dict(pipeline.features(evaluation_input, technical))
    inference = dict(pipeline.inference(evaluation_input, features))
    scoring = dict(pipeline.score(evaluation_input, technical, inference))
    decision = dict(pipeline.decision(evaluation_input, technical, inference, scoring))

    feature_hash = str(features.get("feature_snapshot_hash") or _sha256(features))
    artifact_hash = str(inference.get("artifact_hash") or evaluation_input.artifact.artifact_hash)
    schema_hash = str(
        inference.get("feature_schema_hash")
        or evaluation_input.artifact.feature_schema_hash
    )
    if artifact_hash != evaluation_input.artifact.artifact_hash:
        raise ValueError("inference artifact identity mismatch")
    if schema_hash != evaluation_input.artifact.feature_schema_hash:
        raise ValueError("inference feature schema identity mismatch")

    action = str(decision.get("final_action", "NEUTRAL")).upper()
    sizing = dict(decision.get("sizing") or {})
    final_size = float(sizing.get("final_position_size", 0.0) or 0.0)
    if action not in {"BUY", "SELL"} and final_size != 0.0:
        raise ValueError("non-actionable decision exposes positive size")
    risk_gate = dict(decision.get("risk_gate") or {})
    if bool(risk_gate.get("gated")) and final_size != 0.0:
        raise ValueError("gated decision exposes positive size")

    adjustments = tuple(dict(item) for item in scoring.get("adjustments", ()))
    return MarketEvaluationResult(
        symbol=evaluation_input.window.symbol,
        evaluation_time=evaluation_input.evaluation_time.isoformat(),
        technical_state=_freeze(technical),
        regime=str(technical.get("regime", "UNKNOWN")),
        feature_snapshot_hash=feature_hash,
        prediction=_finite(inference.get("prediction", 0.0), "prediction"),
        inference=_freeze(inference),
        raw_score=_finite(scoring.get("raw_score", scoring.get("score", 50.0)), "raw_score"),
        final_score=_finite(scoring.get("final_score", scoring.get("score", 50.0)), "final_score"),
        score_side=str(scoring.get("side", action)),
        score_adjustments=adjustments,
        ev_eligible=bool(decision.get("ev_eligible", False)),
        s3_threshold=(
            _finite(decision["s3_threshold"], "s3_threshold")
            if decision.get("s3_threshold") is not None else None
        ),
        s3_pass=bool(decision.get("s3_pass", False)),
        risk_gate=_freeze(risk_gate),
        sizing=_freeze(sizing),
        final_action=action,
        take_profit=(
            _finite(decision["take_profit"], "take_profit")
            if decision.get("take_profit") is not None else None
        ),
        stop_loss=(
            _finite(decision["stop_loss"], "stop_loss")
            if decision.get("stop_loss") is not None else None
        ),
        rejection_reason=decision.get("rejection_reason"),
        artifact_hash=artifact_hash,
        feature_schema_hash=schema_hash,
        decision_contract_hash=decision_contract_hash(evaluation_input.context),
    )


class EvaluationClock(Protocol):
    def resolve(self, window: CanonicalCandleWindow) -> datetime: ...


@dataclass(frozen=True)
class FixedClock:
    timestamp: datetime

    def resolve(self, window: CanonicalCandleWindow) -> datetime:
        return _utc(self.timestamp)


class ReplayClock:
    def resolve(self, window: CanonicalCandleWindow) -> datetime:
        return window.end_time


class LiveClock:
    def __init__(self, now: Callable[[], datetime] | None = None):
        self._now = now or (lambda: datetime.now(timezone.utc))

    def resolve(self, window: CanonicalCandleWindow) -> datetime:
        return _utc(self._now())


class EvaluationPersistence(Protocol):
    def persist(self, result: MarketEvaluationResult) -> None: ...


class NoOpPersistence:
    def persist(self, result: MarketEvaluationResult) -> None:
        return None


class InMemoryPersistence:
    def __init__(self) -> None:
        self.results: list[MarketEvaluationResult] = []

    def persist(self, result: MarketEvaluationResult) -> None:
        self.results.append(result)


@dataclass
class MarketEvaluationAdapter:
    pipeline: EvaluationPipeline
    clock: EvaluationClock
    persistence: EvaluationPersistence = field(default_factory=NoOpPersistence)

    def evaluate(
        self,
        *,
        rows: Iterable[Mapping[str, Any]],
        symbol: str,
        timeframe: str,
        artifact: ArtifactIdentity,
        context: Mapping[str, Any] | None = None,
        default_interval_seconds: int | None = None,
    ) -> MarketEvaluationResult:
        window = canonical_window_from_rows(
            rows,
            symbol=symbol,
            timeframe=timeframe,
            default_interval_seconds=default_interval_seconds,
        )
        item = MarketEvaluationInput(
            window=window,
            evaluation_time=self.clock.resolve(window),
            artifact=artifact,
            context=context or {},
        )
        result = evaluate_market(item, self.pipeline)
        self.persistence.persist(result)
        return result


class LiveEvaluationAdapter(MarketEvaluationAdapter):
    """Live-only acquisition/clock/persistence shell."""


class HistoricalEvaluationAdapter(MarketEvaluationAdapter):
    """Replay-only acquisition/clock/persistence shell."""
