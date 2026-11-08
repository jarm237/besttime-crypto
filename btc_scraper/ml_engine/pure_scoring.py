"""Deterministic, side-aware signal scoring contract.

This module deliberately contains no runtime orchestration, I/O, inference,
risk evaluation, sizing, logging, or persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


SCORING_CONTRACT_VERSION = "pure-scoring/v1"
NEUTRAL_SCORE = 50.0
MINIMUM_SCORE = 0.0
MAXIMUM_SCORE = 100.0


class SignalSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


class AdjustmentEffect(str, Enum):
    STRENGTHEN = "STRENGTHEN"
    WEAKEN = "WEAKEN"


@dataclass(frozen=True)
class ScoreAdjustment:
    reason: str
    effect: AdjustmentEffect
    magnitude: float
    score_before: float
    score_after: float

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["effect"] = self.effect.value
        return result


@dataclass(frozen=True)
class SignalScore:
    raw_score: float
    final_score: float
    side: SignalSide
    adjustments: tuple[ScoreAdjustment, ...]
    contract_version: str = SCORING_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "side": self.side.value,
            "adjustments": [item.to_dict() for item in self.adjustments],
            "contract_version": self.contract_version,
        }


def side_from_signal(signal: Any) -> SignalSide:
    text = str(signal or "").upper()
    if "NEUTRAL" in text or "ERROR" in text:
        return SignalSide.NEUTRAL
    sell_index = min(
        (text.find(token) for token in ("STRONG SELL", "WEAK SELL", "SELL", "BEAR") if token in text),
        default=-1,
    )
    buy_index = min(
        (text.find(token) for token in ("STRONG BUY", "WEAK BUY", "BUY", "BULL") if token in text),
        default=-1,
    )
    if sell_index >= 0 and (buy_index < 0 or sell_index < buy_index):
        return SignalSide.SELL
    if buy_index >= 0:
        return SignalSide.BUY
    return SignalSide.NEUTRAL


def base_score_from_signal(signal: Any) -> float:
    text = str(signal or "").upper()
    side = side_from_signal(text)
    if side is SignalSide.BUY:
        if "STRONG BUY" in text:
            return 90.0
        if "WEAK BUY" in text or ("WEAK" in text and "BUY" in text):
            return 55.0
        return 70.0
    if side is SignalSide.SELL:
        if "STRONG SELL" in text:
            return 10.0
        if "WEAK SELL" in text:
            return 45.0
        return 30.0
    return NEUTRAL_SCORE


def apply_side_adjustment(
    score: float,
    side: SignalSide,
    effect: AdjustmentEffect,
    magnitude: float,
) -> float:
    """Move conviction relative to neutral without an accidental side flip."""
    current = max(MINIMUM_SCORE, min(MAXIMUM_SCORE, float(score)))
    amount = max(0.0, float(magnitude))
    if side is SignalSide.NEUTRAL or amount == 0.0:
        return NEUTRAL_SCORE if side is SignalSide.NEUTRAL else current
    direction = 1.0 if side is SignalSide.BUY else -1.0
    if effect is AdjustmentEffect.STRENGTHEN:
        adjusted = current + direction * amount
    else:
        adjusted = current - direction * amount
        if side is SignalSide.BUY:
            adjusted = max(NEUTRAL_SCORE, adjusted)
        else:
            adjusted = min(NEUTRAL_SCORE, adjusted)
    return max(MINIMUM_SCORE, min(MAXIMUM_SCORE, adjusted))


def score_signal_pure(
    analysis: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> SignalScore:
    """Return a deterministic score from explicit, read-only inputs."""
    explicit_context = context or {}
    signal = analysis.get("signal", explicit_context.get("signal", ""))
    side = side_from_signal(signal)
    raw_score = base_score_from_signal(signal)
    if side is SignalSide.NEUTRAL:
        return SignalScore(raw_score, NEUTRAL_SCORE, side, ())

    score = raw_score
    trace: list[ScoreAdjustment] = []

    def adjust(reason: str, effect: AdjustmentEffect, magnitude: float) -> None:
        nonlocal score
        before = score
        score = apply_side_adjustment(score, side, effect, magnitude)
        if magnitude and score != before:
            trace.append(ScoreAdjustment(reason, effect, float(magnitude), before, score))

    if explicit_context.get("vol_spike") or analysis.get("vol_spike"):
        adjust("VOLUME_SPIKE", AdjustmentEffect.STRENGTHEN, 5.0)

    above_sma200 = bool(explicit_context.get("above_sma200", analysis.get("above_sma200")))
    below_sma200 = bool(explicit_context.get("below_sma200", analysis.get("below_sma200")))
    if above_sma200:
        adjust(
            "ABOVE_SMA200",
            AdjustmentEffect.STRENGTHEN if side is SignalSide.BUY else AdjustmentEffect.WEAKEN,
            5.0,
        )
    if below_sma200:
        adjust(
            "BELOW_SMA200",
            AdjustmentEffect.STRENGTHEN if side is SignalSide.SELL else AdjustmentEffect.WEAKEN,
            5.0,
        )

    if analysis.get("atr_shock") or explicit_context.get("atr_shock"):
        adjust("ATR_SHOCK", AdjustmentEffect.WEAKEN, 10.0)

    sentiment = analysis.get("sentiment") or explicit_context.get("sentiment") or {}
    sentiment_is_stale = (
        str(analysis.get("sentiment_quality_status") or explicit_context.get("sentiment_quality_status") or "").upper() == "STALE_NEUTRALIZED"
        or (isinstance(sentiment, dict) and bool(sentiment.get("stale") or sentiment.get("status") == "stale"))
    )
    if sentiment_is_stale:
        sentiment_score = 0.0
    else:
        try:
            sentiment_value = sentiment.get("normalized_score", sentiment.get("score"))
            sentiment_score = float(sentiment_value) if sentiment_value is not None else None
        except (AttributeError, TypeError, ValueError):
            sentiment_score = None
    try:
        explicit_penalty = abs(float(explicit_context["sentiment_penalty"]))
    except (KeyError, TypeError, ValueError):
        explicit_penalty = 20.0
    if sentiment_score is not None:
        adverse = (
            side is SignalSide.BUY and sentiment_score <= -0.6
        ) or (
            side is SignalSide.SELL and sentiment_score >= 0.6
        )
        if adverse:
            adjust("ADVERSE_SENTIMENT", AdjustmentEffect.WEAKEN, explicit_penalty)

    adaptive_probability = explicit_context.get("adaptive_probability")
    if adaptive_probability is not None:
        try:
            signed_magnitude = (float(adaptive_probability) - 0.5) * 40.0
        except (TypeError, ValueError):
            signed_magnitude = 0.0
        adjust(
            "ADAPTIVE_MODEL",
            AdjustmentEffect.STRENGTHEN if signed_magnitude >= 0 else AdjustmentEffect.WEAKEN,
            abs(round(signed_magnitude)),
        )

    for timeframe, strengthen, weaken in (("1h", 8.0, 15.0), ("4h", 5.0, 10.0), ("1d", 5.0, 5.0)):
        try:
            direction = int(analysis.get(f"tf_{timeframe}_bull", explicit_context.get(f"tf_{timeframe}_bull", 0)) or 0)
        except (TypeError, ValueError):
            direction = 0
        alignment = direction * (1 if side is SignalSide.BUY else -1)
        if alignment > 0:
            adjust(f"MTF_{timeframe.upper()}_ALIGNED", AdjustmentEffect.STRENGTHEN, strengthen)
        elif alignment < 0:
            adjust(f"MTF_{timeframe.upper()}_OPPOSED", AdjustmentEffect.WEAKEN, weaken)

    meta_probability = explicit_context.get("meta_probability")
    meta_reject_threshold = explicit_context.get("meta_reject_threshold")
    try:
        rejected = (
            meta_probability is not None
            and meta_reject_threshold is not None
            and float(meta_reject_threshold) > 0
            and float(meta_probability) < float(meta_reject_threshold)
        )
    except (TypeError, ValueError):
        rejected = False
    if rejected:
        adjust("META_FILTER", AdjustmentEffect.WEAKEN, 20.0)

    final_score = float(round(score))
    final_side = side_from_signal("BUY" if final_score > NEUTRAL_SCORE else "SELL" if final_score < NEUTRAL_SCORE else "NEUTRAL")
    return SignalScore(raw_score, final_score, final_side, tuple(trace))
