"""P7 Attempt #4 — R6 Remediation Preflight & Verification Tests.

Verifies transitive symbol compatibility, composed prediction path, and dynamic routing
for all 9 authorized symbols.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from btc_scraper.core.config import get_analysis_universe
from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator
from btc_scraper.ml_engine.inference_router import InferenceRouter
from btc_scraper.ml_engine.meta_model import predict_meta_confidence

AUTHORIZED_SYMBOLS = ("BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC")


@pytest.fixture(scope="module")
def router():
    registry_path = ROOT / "model_coverage_mc6_inference_registry.json"
    assert registry_path.exists()
    return InferenceRouter(registry_path, ROOT)


# ── T1  Router resolves all 9 authorized symbols ──────────────────────────────
def test_r6_t1_router_resolves_all_authorized(router):
    for sym in AUTHORIZED_SYMBOLS:
        route = router.resolve(sym)
        assert route.symbol == sym
        assert route.route_type in {"LEGACY", "MC5_QUALIFIED"}


# ── T2  Direct prediction preflight for all 9 symbols ─────────────────────────
def test_r6_t2_prediction_preflight(monkeypatch):
    # Disable database writes during prediction audit log
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "false")
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")

    coord = get_inference_coordinator()

    for sym in AUTHORIZED_SYMBOLS:
        analysis = {
            "coin": sym,
            "symbol": f"{sym}USDT",
            "timeframe": "15m",
            "signal": "BUY",
            "cycle_id": "preflight-test",
            "observed_at": "2026-08-25T14:59:00+07:00",
            "close": 100.0,
            "fear_greed": 50,
            "return_8": 0.01,
            "return_32": 0.02,
            "return_72": 0.03,
            "abs_move_72": 0.04,
        }
        res = coord.predict_once(
            analysis,
            symbol=sym,
            timeframe="15m",
            decision_context="entry",
            caller_context="agent_orchestrator",
        )
        assert res.symbol == sym
        assert 0.0 <= res.prediction <= 1.0
        assert 0.0 <= res.probability <= 1.0


# ── T3  Invariant check: MC5 routes do NOT traverse legacy classifier ─────────
def test_r6_t3_mc5_invariant_check(monkeypatch):
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "false")
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")

    # Monkeypatch model_predict_proba of meta_model to record calls
    import btc_scraper.ml_engine.meta_model as mm
    calls = []
    original_predict = mm.model_predict_proba

    def mock_predict(*args, **kwargs):
        calls.append(args)
        return original_predict(*args, **kwargs)

    monkeypatch.setattr(mm, "model_predict_proba", mock_predict)

    coord = get_inference_coordinator()

    # Predict for a qualified symbol (e.g. DOGE)
    analysis = {
        "coin": "DOGE",
        "symbol": "DOGEUSDT",
        "timeframe": "15m",
        "signal": "BUY",
        "cycle_id": "invariant-test",
        "observed_at": "2026-08-25T14:59:00+07:00",
        "close": 0.15,
        "fear_greed": 50,
        "return_8": 0.01,
        "return_32": 0.02,
        "return_72": 0.03,
        "abs_move_72": 0.04,
    }
    res = coord.predict_once(
        analysis,
        symbol="DOGE",
        timeframe="15m",
        decision_context="entry",
        caller_context="agent_orchestrator",
    )
    assert res.symbol == "DOGE"

    # For MC5_QUALIFIED symbols, mm.model_predict_proba (the legacy meta-model predict method)
    # MUST NOT be called!
    assert len(calls) == 0
