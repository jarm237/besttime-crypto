from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.economic_contract import (
    EV_CONTRACT_VERSION,
    EXPECTED_RETURN_UNIT,
    bps_to_fraction,
    fraction_to_bps,
)
from btc_scraper.ml_engine.meta_model import _compute_expected_value_metrics
from btc_scraper.ml_engine.s3_thresholds import (
    S3_THRESHOLD_CONTRACT_VERSION,
    evaluate_s3_threshold,
    load_s3_threshold_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _decision(
    *,
    symbol: str = "BTCUSDT",
    action: str = "BUY",
    probability: float = 0.9,
    expected_return: float = 0.001,
) -> dict:
    return MetaDecisionEngine(weights={"meta": 1.0}).decide(
        {
            "coin": symbol.removesuffix("USDT"),
            "symbol": symbol,
            "signal": action,
            "action": action,
            "_meta_prediction": {
                "probability": probability,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": expected_return,
                "expected_return_unit": EXPECTED_RETURN_UNIT,
                "ev_contract_version": EV_CONTRACT_VERSION,
                "prediction_id": None,
            },
        },
        persist_final=False,
    )


def test_ev_conversion_helpers_define_fraction_contract() -> None:
    assert EV_CONTRACT_VERSION == "expected-return-fraction-v1"
    assert EXPECTED_RETURN_UNIT == "fraction"
    assert bps_to_fraction(4.99) == pytest.approx(0.000499)
    assert bps_to_fraction(5.00) == pytest.approx(0.000500)
    assert bps_to_fraction(5.01) == pytest.approx(0.000501)
    assert fraction_to_bps(0.01) == pytest.approx(100.0)


def test_meta_model_expected_value_is_emitted_as_fraction() -> None:
    metrics = _compute_expected_value_metrics(
        0.5863507385296476,
        {
            "action": "BUY",
            "tp_sl": {
                "entry": 100.0,
                "sl": 99.7,
                "tp1": 100.5,
                "tp2": 101.0,
            },
        },
    )

    assert metrics["expected_return"] == pytest.approx(0.00257033)
    assert metrics["expected_return_bps"] == pytest.approx(25.7033)
    assert metrics["expected_return_unit"] == EXPECTED_RETURN_UNIT
    assert metrics["ev_contract_version"] == EV_CONTRACT_VERSION
    assert metrics["tp1_pct"] == pytest.approx(0.5)
    assert metrics["tp2_pct"] == pytest.approx(1.0)
    assert metrics["sl_pct"] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("bps", "expected_action", "eligible"),
    [
        (4.99, "IGNORE", False),
        (5.00, "BUY", True),
        (5.01, "BUY", True),
    ],
)
def test_ev_boundary_is_exact_at_five_bps(
    bps: float,
    expected_action: str,
    eligible: bool,
) -> None:
    decision = _decision(expected_return=bps_to_fraction(bps))

    assert decision["action"] == expected_action
    assert decision["eligible"] is eligible
    assert decision["expected_return_unit"] == EXPECTED_RETURN_UNIT
    assert decision["ev_contract_version"] == EV_CONTRACT_VERSION


def test_side_agnostic_positive_ev_allows_buy_and_sell() -> None:
    buy = _decision(action="BUY", expected_return=0.001)
    sell = _decision(action="SELL", expected_return=0.001)
    negative = _decision(action="BUY", expected_return=-0.001)

    assert buy["action"] == "BUY"
    assert sell["action"] == "SELL"
    assert negative["action"] == "IGNORE"


def test_s3_contract_matches_frozen_research_thresholds() -> None:
    contract = load_s3_threshold_contract()
    research = json.loads(
        (
            REPO_ROOT
            / "research/historical_market_replay_v5/v5_filter_model/model.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["threshold_contract_version"] == S3_THRESHOLD_CONTRACT_VERSION
    assert contract["missing_policy"] == "FAIL_CLOSED"
    assert contract["probability_semantics"] == "P(win_given_proposed_trade)"
    assert contract["comparison"] == ">="
    assert contract["thresholds"] == {
        symbol: payload["s3_threshold"] for symbol, payload in research.items()
    }


@pytest.mark.parametrize("symbol", ["BTC", "ETH", "BNB"])
def test_s3_below_exact_and_above_boundaries(symbol: str) -> None:
    threshold = load_s3_threshold_contract()["thresholds"][symbol]
    below = _decision(symbol=f"{symbol}USDT", probability=threshold - 1e-12)
    exact = _decision(symbol=f"{symbol}USDT", probability=threshold)
    above = _decision(symbol=f"{symbol}USDT", probability=threshold + 1e-12)

    assert below["action"] == "IGNORE"
    assert below["s3_pass"] is False
    assert exact["action"] == "BUY"
    assert exact["s3_pass"] is True
    assert above["action"] == "BUY"
    assert above["s3_pass"] is True
    for decision in (below, exact, above):
        assert decision["symbol"] == symbol
        assert decision["s3_threshold"] == pytest.approx(threshold)
        assert decision["threshold_contract_version"] == S3_THRESHOLD_CONTRACT_VERSION


def test_s3_unknown_symbol_fails_closed_without_global_fallback(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_TRADE_META_THRESHOLD", "0")
    monkeypatch.setenv("META_REJECT_THRESHOLD", "0")

    gate = evaluate_s3_threshold("DOGEUSDT", 0.999)
    decision = _decision(symbol="DOGEUSDT", probability=0.999)

    assert gate.s3_threshold is None
    assert gate.s3_pass is False
    assert gate.error == "s3_threshold_unresolved:DOGE"
    assert decision["action"] == "IGNORE"
    assert decision["s3_pass"] is False
    assert decision["s3_threshold"] is None
    assert decision["s3_threshold_error"] == "s3_threshold_unresolved:DOGE"


def test_context_adjustment_cannot_bypass_failed_s3() -> None:
    threshold = load_s3_threshold_contract()["thresholds"]["ETH"]
    analysis = {"coin": "ETH", "symbol": "ETHUSDT", "signal": "BUY", "action": "BUY"}
    base = _decision(symbol="ETHUSDT", probability=threshold - 0.01)

    adjusted = MetaDecisionEngine(weights={"meta": 1.0}).apply_context(
        base,
        {"adjusted_score": 0.999, "risk_level": "LOW", "stop_processing": False},
        analysis_info=analysis,
    )

    assert base["action"] == "IGNORE"
    assert adjusted["action"] == "IGNORE"
    assert adjusted["s3_pass"] is False


def test_replay_adapter_uses_shared_s3_resolver(monkeypatch) -> None:
    from scripts import hmr_v5_d2_parity_replay as replay

    calls: list[tuple[str, float]] = []

    def reject(symbol: str, probability: float):
        calls.append((symbol, probability))
        return SimpleNamespace(s3_pass=False)

    monkeypatch.setattr(replay, "evaluate_s3_threshold", reject)
    engine = replay.RuntimeInferenceEngine(
        REPO_ROOT / "research/historical_market_replay_v5/v5_filter_model"
    )
    probability, decision = engine.predict_score_and_decision(
        "BTC", [0.004, 0.008, 0.012, 0.012]
    )

    assert calls == [("BTC", probability)]
    assert decision is False
