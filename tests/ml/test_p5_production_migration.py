from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from btc_scraper.ml_engine.production_evaluator import (
    evaluate_historical_market,
    evaluate_live_market,
)
from btc_scraper.trading.decision_types import (
    DecisionBreakdown,
    DecisionStage,
    EntryDecision,
    FinalDecisionStatus,
    SizingDecision,
    TradeAction,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class OwnerFixture:
    max_trade_usdt = 100.0
    min_trade_usdt = 10.0

    def __init__(self) -> None:
        self.decision_calls = 0
        self.sizing_calls = 0

    def build_entry_decision(self, analysis, coin):
        self.decision_calls += 1
        action = TradeAction(str(analysis["signal_score"]["action"]))
        probability = float(analysis["signal_score"]["meta_probability"])
        eligible = action in {TradeAction.BUY, TradeAction.SELL} and probability >= 0.5
        return EntryDecision(
            eligible=eligible,
            action=action,
            rejection_reason=None,
            final_status=(
                FinalDecisionStatus.ELIGIBLE
                if eligible else FinalDecisionStatus.REJECTED
            ),
            breakdown=DecisionBreakdown(
                decision_stage=DecisionStage.ELIGIBILITY,
                technical_score=int(analysis["signal_score"]["score"]),
                directional_score=int(analysis["signal_score"]["score"]),
                signal_strength=int(analysis["signal_score"]["strength"]),
                signal_action=action,
                meta_probability=probability,
                rr_ratio=float(analysis["tp_sl"]["rr1"]),
                kelly_raw=0.2,
                kelly_applied=0.2,
            ),
            sizing=None,
        )

    def compute_position_size(self, **kwargs):
        self.sizing_calls += 1
        return SizingDecision(
            entry_price=kwargs["entry_price"],
            sl_price=kwargs["sl_price"],
            stop_distance_pct=0.02,
            risk_pct=2.0,
            risk_notional=10.0,
            raw_notional=50.0,
            kelly_adjusted=40.0,
            risk_adjusted_notional=40.0,
            final_notional=40.0,
        )


def analysis(symbol: str, action: str = "BUY", probability: float = 0.9) -> dict:
    score = 90 if action == "BUY" else 10 if action == "SELL" else 50
    return {
        "coin": symbol,
        "symbol": f"{symbol}USDT",
        "timeframe": "15m",
        "signal": action,
        "close": 103.0,
        "regime": "TRENDING",
        "feature_hash": f"features-{symbol}",
        "artifact_hash": f"artifact-{symbol}",
        "artifact_version": "v1",
        "feature_schema_hash": "schema-v1",
        "model_family": "fixture",
        "history": [
            {
                "time": (NOW.replace(minute=15 * index)).isoformat(),
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": 10.0,
            }
            for index in range(4)
        ],
        "signal_score": {
            "action": action,
            "score": score,
            "raw_score": score,
            "final_score": score,
            "strength": abs(score - 50) * 2,
            "meta_probability": probability,
            "prediction": probability,
            "s3_threshold": 0.5,
            "s3_pass": probability >= 0.5,
            "kelly_fraction": 0.2,
            "position_size": 0.8,
            "adjustments": [],
        },
        "tp_sl": {"entry": 103.0, "sl": 101.0, "tp1": 107.0, "rr1": 2.0},
    }


def evaluate_pair(payload: dict):
    live_owner, replay_owner = OwnerFixture(), OwnerFixture()
    kwargs = {
        "analysis": payload,
        "coin": payload["coin"],
        "current_balance": 500.0,
        "var_cap": 100.0,
        "exposure_cap": 100.0,
        "evaluation_time": NOW.replace(minute=45),
    }
    live = evaluate_live_market(trader=live_owner, **kwargs)
    replay = evaluate_historical_market(trader=replay_owner, **kwargs)
    return live, replay, live_owner, replay_owner


def test_real_adapter_entrypoints_have_authoritative_full_parity():
    live, replay, live_owner, replay_owner = evaluate_pair(analysis("BTC"))
    assert live.result == replay.result
    assert live.result.section_hashes() == replay.result.section_hashes()
    assert live.result.final_action == "BUY"
    assert live.result.sizing["final_position_size"] == 40.0
    assert (live_owner.decision_calls, live_owner.sizing_calls) == (1, 1)
    assert (replay_owner.decision_calls, replay_owner.sizing_calls) == (1, 1)


def test_rejection_parity_has_one_decision_and_zero_sizing_pass():
    live, replay, live_owner, replay_owner = evaluate_pair(
        analysis("ETH", probability=0.49)
    )
    assert live.result == replay.result
    assert live.result.final_action == "NEUTRAL"
    assert live.result.sizing["final_position_size"] == 0
    assert (live_owner.decision_calls, live_owner.sizing_calls) == (1, 0)
    assert (replay_owner.decision_calls, replay_owner.sizing_calls) == (1, 0)


def test_cross_symbol_concurrency_isolated():
    payloads = [analysis("BTC"), analysis("ETH", "SELL"), analysis("BNB")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda row: evaluate_pair(row)[0].result, payloads))
    assert [result.symbol for result in results] == [
        "BTCUSDT", "ETHUSDT", "BNBUSDT"
    ]
    assert [result.artifact_hash for result in results] == [
        "artifact-BTC", "artifact-ETH", "artifact-BNB"
    ]
    assert [result.final_action for result in results] == ["BUY", "SELL", "BUY"]


def test_production_composition_delegates_each_owner_once():
    source = Path("btc_scraper/ml_engine/production_evaluator.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    target = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "decision"
    )
    calls = [
        node.func.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert calls.count("build_entry_decision") == 1
    assert calls.count("compute_position_size") == 1


def test_autotrader_process_consumes_live_evaluator_not_decision_owners_directly():
    source = Path("btc_scraper/trading/auto_trader.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    process = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_process_signal"
    )
    called = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(process)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    ]
    assert called.count("evaluate_live_market") == 1
    assert "build_entry_decision" not in called
    assert "compute_position_size" not in called


def test_replay_entrypoint_contains_no_semantic_helpers():
    source = Path("btc_scraper/ml_engine/production_evaluator.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    replay = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_historical_market"
    )
    names = {node.id for node in ast.walk(replay) if isinstance(node, ast.Name)}
    assert names.isdisjoint({
        "score_signal", "evaluate_s3_threshold", "evaluate_risk_gate",
        "finalize_position_size",
    })


def test_legacy_bulk_historical_evaluator_is_quarantined():
    from btc_scraper.analysis import analyze_all_market

    assert analyze_all_market.authoritative_decision is False
    assert analyze_all_market.execution_allowed is False
    assert (
        analyze_all_market.evaluator_classification
        == "NON_CANONICAL_RESEARCH_ONLY"
    )

    production_sources = (
        Path("main.py").read_text(encoding="utf-8")
        + Path("btc_scraper/ml_engine/multi_agent.py").read_text(encoding="utf-8")
        + Path("btc_scraper/trading/auto_trader.py").read_text(encoding="utf-8")
    )
    assert "analyze_all_market(" not in production_sources
