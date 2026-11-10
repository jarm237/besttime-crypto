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
    _utc,
)
from .evaluation_contracts import canonical_entry_readiness_contract


@dataclass(frozen=True)
class ProductionEvaluation:
    result: MarketEvaluationResult
    entry_decision: EntryDecision


from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

TIMEFRAME_SECONDS_MAP = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}


def _infer_candle_closed(item: Mapping[str, Any], eval_dt: datetime, timeframe: str | None = None) -> bool:
    c_flag = item.get("closed")
    if c_flag is None:
        c_flag = item.get("is_closed")
    if c_flag is not None:
        return bool(c_flag)

    close_utc_raw = item.get("close_time_utc") or item.get("close_time")
    if close_utc_raw:
        try:
            return _utc(close_utc_raw) <= eval_dt
        except Exception:
            return False

    open_raw = item.get("open_time_utc") or item.get("time_utc") or item.get("timestamp") or item.get("time")
    if open_raw and timeframe and timeframe in TIMEFRAME_SECONDS_MAP:
        try:
            open_dt = _utc(open_raw)
            duration = TIMEFRAME_SECONDS_MAP[timeframe]
            return (open_dt + timedelta(seconds=duration)) <= eval_dt
        except Exception:
            return False

    return False


def _observation_rows(analysis: Mapping[str, Any], evaluation_time: datetime) -> list[dict]:
    history = analysis.get("history")
    if isinstance(history, list) and history:
        rows = []
        eval_dt = _utc(evaluation_time)
        tf_str = str(analysis.get("timeframe") or "15m")
        for item in history:
            if not isinstance(item, Mapping):
                continue
            timestamp = item.get("time_utc") or item.get("open_time_utc") or item.get("timestamp") or item.get("time")
            if timestamp is None:
                continue

            c_flag = _infer_candle_closed(item, eval_dt, tf_str)
            if not c_flag:
                continue

            close_utc_raw = item.get("close_time_utc")
            if close_utc_raw:
                try:
                    if _utc(close_utc_raw) > eval_dt:
                        continue
                except Exception:
                    pass

            row_dict = {
                "timestamp": timestamp,
                "open": item.get("open", item.get("close", 0.0)),
                "high": item.get("high", item.get("close", 0.0)),
                "low": item.get("low", item.get("close", 0.0)),
                "close": item.get("close", 0.0),
                "volume": item.get("volume", 0.0),
                "closed": True,
            }
            if item.get("open_time"):
                row_dict["open_time"] = item["open_time"]
            if item.get("close_time"):
                row_dict["close_time"] = item["close_time"]
            if item.get("time_utc"):
                row_dict["time_utc"] = item["time_utc"]
            if item.get("open_time_utc") or item.get("time_utc"):
                row_dict["open_time_utc"] = item.get("open_time_utc") or item.get("time_utc")
            if item.get("close_time_utc"):
                row_dict["close_time_utc"] = item["close_time_utc"]
            rows.append(row_dict)
        return rows
    return []


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
    risk_portfolio: Any | None = None,
    **kwargs: Any,
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
        rp = risk_portfolio
        rp_dict = rp.to_dict() if hasattr(rp, "to_dict") else (rp if isinstance(rp, dict) else None)
        entry = trader.build_entry_decision(
            analysis,
            coin,
            risk_decision=rp_dict or analysis.get("risk_decision"),
            portfolio_decision=rp_dict or analysis.get("portfolio_decision"),
            current_balance=current_balance,
            var_cap=var_cap,
            exposure_cap=exposure_cap,
            event_risk=analysis.get("event_risk"),
            evaluation_time=timestamp,
        )
        tp_sl = analysis.get("tp_sl") or {}
        if entry.eligible and entry.sizing is None:
            sizing = trader.compute_position_size(
                entry_price=float(tp_sl.get("entry") or analysis.get("close") or 0.0),
                sl_price=float(tp_sl.get("sl") or 0.0),
                current_balance=current_balance,
                multiplier=float(rp_dict.get("risk_multiplier", 1.0) if rp_dict else sig_score.get("position_size", 1.0)),
                win_prob=float(entry.breakdown.meta_probability if entry.breakdown and entry.breakdown.meta_probability is not None else 0.5),
                rr_ratio=float(tp_sl.get("rr1", 0.0) or 0.0),
                var_cap=var_cap,
                exposure_cap=exposure_cap,
                max_trade_cap=trader.max_trade_usdt,
                min_trade_cap=trader.min_trade_usdt,
                portfolio_weight=float(rp_dict.get("portfolio_weight")) if (rp_dict and rp_dict.get("portfolio_weight") is not None) else None,
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

    readiness_contract = canonical_entry_readiness_contract()

    def readiness(item):
        return readiness_contract.diagnose(item.window.candles, item.evaluation_time)

    pipeline = EvaluationPipeline(technical, features, inference, score, decision, readiness)
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
            "risk_portfolio": risk_portfolio,
        },
    )
    return ProductionEvaluation(result=result, entry_decision=holder["entry"])


def evaluate_live_market(**kwargs: Any) -> ProductionEvaluation:
    """Production live adapter entrypoint."""
    return evaluate_resolved_market(environment="live", **kwargs)


def evaluate_historical_market(**kwargs: Any) -> ProductionEvaluation:
    """Canonical replay entrypoint using the identical production pipeline."""
    return evaluate_resolved_market(environment="historical", **kwargs)
