"""Production composition for the common evaluator contract."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from btc_scraper.trading.decision_types import EntryDecision, TradeAction

from .common_evaluator import (
    ArtifactIdentity,
    EvaluationPipeline,
    FixedClock,
    HistoricalEvaluationAdapter,
    LiveEvaluationAdapter,
    MarketEvaluationResult,
    NoOpPersistence,
)


@dataclass(frozen=True)
class ProductionEvaluation:
    result: MarketEvaluationResult
    entry_decision: EntryDecision


def _observation_rows(analysis: Mapping[str, Any], evaluation_time: datetime) -> list[dict]:
    history = analysis.get("history")
    if isinstance(history, list) and history:
        rows = []
        for item in history:
            if not isinstance(item, Mapping):
                continue
            timestamp = item.get("time") or item.get("timestamp") or item.get("time_utc")
            if timestamp is None:
                continue
            rows.append({
                "timestamp": timestamp,
                "open": item.get("open", item.get("close", 0.0)),
                "high": item.get("high", item.get("close", 0.0)),
                "low": item.get("low", item.get("close", 0.0)),
                "close": item.get("close", 0.0),
                "volume": item.get("volume", 0.0),
                "closed": True,
            })
        if rows:
            return rows
    close = float(analysis.get("close") or 0.0)
    return [{
        "timestamp": evaluation_time.isoformat(),
        "open": float(analysis.get("open") or close),
        "high": float(analysis.get("high") or close),
        "low": float(analysis.get("low") or close),
        "close": close,
        "volume": float(analysis.get("volume") or 0.0),
        "closed": True,
    }]


def evaluate_resolved_market(
    *,
    analysis: dict[str, Any],
    coin: str,
    trader: Any,
    current_balance: float,
    var_cap: float | None,
    exposure_cap: float | None,
    environment: str = "live",
    evaluation_time: datetime | None = None,
) -> ProductionEvaluation:
    """Delegate final eligibility and sizing once to the sealed owners."""
    timestamp = evaluation_time or datetime.now(timezone.utc)
    sig_score = analysis.get("signal_score") or {}
    artifact = ArtifactIdentity(
        model_family=str(analysis.get("model_family") or sig_score.get("model_family") or "unavailable"),
        artifact_version=str(analysis.get("artifact_version") or sig_score.get("artifact_version") or analysis.get("model_version") or "unavailable"),
        artifact_hash=str(analysis.get("artifact_hash") or analysis.get("artifact_sha256") or sig_score.get("artifact_hash") or sig_score.get("artifact_sha256") or "unavailable"),
        feature_schema_hash=str(analysis.get("feature_schema_hash") or sig_score.get("feature_schema_hash") or analysis.get("feature_schema_version") or "unavailable"),
    )
    holder: dict[str, EntryDecision] = {}

    def technical(_item):
        return dict(analysis)

    def features(item, _technical):
        return {
            "feature_snapshot_hash": str(
                analysis.get("feature_hash")
                or sig_score.get("feature_hash")
                or item.window.snapshot_hash
            )
        }

    def inference(_item, feature_state):
        probability = sig_score.get("prediction")
        if probability is None:
            probability = sig_score.get("meta_probability", sig_score.get("meta_confidence", 0.0))
        return {
            "symbol": coin.upper(),
            "prediction": float(probability or 0.0),
            "meta_probability": sig_score.get("meta_probability"),
            "artifact_version": artifact.artifact_version,
            "artifact_hash": artifact.artifact_hash,
            "feature_schema_hash": artifact.feature_schema_hash,
            "model_family": artifact.model_family,
            "feature_snapshot_hash": feature_state["feature_snapshot_hash"],
        }

    def score(_item, _technical, _inference):
        return {
            "raw_score": sig_score.get("raw_score", sig_score.get("score", 50.0)),
            "final_score": sig_score.get("final_score", sig_score.get("score", 50.0)),
            "side": sig_score.get("action", "NEUTRAL"),
            "adjustments": sig_score.get("adjustments", ()),
        }

    def decision(_item, _technical, _inference, _score):
        entry = trader.build_entry_decision(analysis, coin)
        tp_sl = analysis.get("tp_sl") or {}
        if entry.eligible:
            sizing = trader.compute_position_size(
                entry_price=float(tp_sl.get("entry") or analysis.get("close") or 0.0),
                sl_price=float(tp_sl.get("sl") or 0.0),
                current_balance=current_balance,
                multiplier=float(sig_score.get("position_size", 1.0)),
                win_prob=float(entry.breakdown.meta_probability if entry.breakdown and entry.breakdown.meta_probability is not None else 0.5),
                rr_ratio=float(tp_sl.get("rr1", 0.0) or 0.0),
                var_cap=var_cap,
                exposure_cap=exposure_cap,
                max_trade_cap=trader.max_trade_usdt,
                min_trade_cap=trader.min_trade_usdt,
            )
            entry = dataclasses.replace(
                entry,
                eligible=not sizing.rejected,
                rejection_reason=sizing.rejection_reason if sizing.rejected else entry.rejection_reason,
                sizing=sizing,
            )
        holder["entry"] = entry
        return {
            "ev_eligible": bool(entry.eligible),
            "s3_threshold": sig_score.get("s3_threshold"),
            "s3_pass": bool(sig_score.get("s3_pass", False)),
            "risk_gate": {
                "gated": entry.gated,
                "reason": entry.rejection_reason.value if entry.rejection_reason else None,
            },
            "sizing": entry.sizing.to_dict() if entry.sizing else {
                "kelly_fraction": sig_score.get("kelly_fraction"),
                "raw_position_size": 0.0,
                "risk_adjusted_size": 0.0,
                "final_position_size": 0.0,
            },
            "final_action": entry.action.value if entry.eligible and entry.action in {TradeAction.BUY, TradeAction.SELL} else "NEUTRAL",
            "take_profit": float(tp_sl["tp1"]) if entry.eligible and tp_sl.get("tp1") is not None else None,
            "stop_loss": float(tp_sl["sl"]) if entry.eligible and tp_sl.get("sl") is not None else None,
            "rejection_reason": entry.rejection_reason.value if entry.rejection_reason else None,
        }

    pipeline = EvaluationPipeline(technical, features, inference, score, decision)
    adapter_type = HistoricalEvaluationAdapter if str(environment).lower() == "historical" else LiveEvaluationAdapter
    adapter = adapter_type(pipeline, FixedClock(timestamp), NoOpPersistence())
    result = adapter.evaluate(
        rows=_observation_rows(analysis, timestamp),
        symbol=f"{coin.upper()}USDT",
        timeframe=str(analysis.get("timeframe") or "15m"),
        artifact=artifact,
        context={
            "threshold_config_hash": sig_score.get("threshold_contract_sha256"),
            "risk_config_hash": analysis.get("risk_config_hash"),
        },
    )
    return ProductionEvaluation(result=result, entry_decision=holder["entry"])


def evaluate_live_market(**kwargs: Any) -> ProductionEvaluation:
    """Production live adapter entrypoint."""
    return evaluate_resolved_market(environment="live", **kwargs)


def evaluate_historical_market(**kwargs: Any) -> ProductionEvaluation:
    """Canonical replay entrypoint using the identical production pipeline."""
    return evaluate_resolved_market(environment="historical", **kwargs)
