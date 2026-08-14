"""
Tests for MetaDecisionEngine (btc_scraper/ml_engine/decision_engine.py).

Coverage:
  - _sentiment_support, _regime_support, _volatility_support helpers
  - compute_posterior weighted fusion
  - decide() action classification: BUY, SELL, HOLD, IGNORE, INCREASE, REDUCE
  - decide() when model is missing (graceful error)
  - decide() when model is present (integration with predict_meta_confidence)
  - custom weight configuration
"""
import pytest
import numpy as np

import btc_scraper.ml_engine.meta_model as mm
from btc_scraper.ml_engine.decision_engine import (
    MetaDecisionEngine, DEFAULT_EVIDENCE_WEIGHTS, DecisionAction, apply_final_risk_gate,
)


# ---------------------------------------------------------------------------
# Fixture: isolate model/log paths and reset in-memory model cache
# ---------------------------------------------------------------------------
@pytest.fixture
def clean_engine(tmp_path):
    """Redirect meta_model paths + reset cache for each test."""
    original_model_out = mm.MODEL_OUT
    original_model_cache = mm._MODEL_CACHE
    original_model_error = mm._MODEL_LOAD_ERROR
    original_logs = mm.LOGS

    mm.MODEL_OUT = tmp_path / "meta_model.joblib"
    mm.LOGS = tmp_path
    mm._MODEL_CACHE = None
    mm._MODEL_LOAD_ERROR = None

    yield MetaDecisionEngine()

    mm.MODEL_OUT = original_model_out
    mm.LOGS = original_logs
    mm._MODEL_CACHE = original_model_cache
    mm._MODEL_LOAD_ERROR = original_model_error


@pytest.fixture
def engine_with_model(tmp_path):
    """Provide a MetaDecisionEngine with a real (tiny) model saved to disk."""
    from btc_scraper.ml_engine.meta_model import EnsembleMetaModel, _import_optional_estimators
    from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA_V2
    import joblib

    estimators = _import_optional_estimators()
    if not estimators:
        pytest.skip("No LGBM/CatBoost/XGBoost available.")

    original_model_out = mm.MODEL_OUT
    original_model_cache = mm._MODEL_CACHE
    original_model_error = mm._MODEL_LOAD_ERROR
    original_logs = mm.LOGS

    mm.MODEL_OUT = tmp_path / "meta_model.joblib"
    mm.LOGS = tmp_path
    mm._MODEL_CACHE = None
    mm._MODEL_LOAD_ERROR = None

    n_features = len(FEATURE_SCHEMA_V2)
    X = np.random.rand(40, n_features)
    y = np.array([0, 1] * 20)
    weights = {k: 1.0 for k in estimators}
    model = EnsembleMetaModel(weights=weights, calibration="sigmoid", n_estimators=5, random_state=0)
    model.fit(X, y, cv=2)
    joblib.dump({"model": model, "features": FEATURE_SCHEMA_V2, "version": mm.MODEL_VERSION}, mm.MODEL_OUT)

    engine = MetaDecisionEngine()
    yield engine

    mm.MODEL_OUT = original_model_out
    mm.LOGS = original_logs
    mm._MODEL_CACHE = original_model_cache
    mm._MODEL_LOAD_ERROR = original_model_error


# ---------------------------------------------------------------------------
# Helper support functions
# ---------------------------------------------------------------------------

class TestSentimentSupport:
    def test_buy_high_fg_returns_high(self):
        engine = MetaDecisionEngine()
        score = engine._sentiment_support({"signal": "BUY", "fear_greed": 85})
        assert score > 0.6, f"Expected >0.6, got {score}"

    def test_buy_low_fg_returns_lower(self):
        engine = MetaDecisionEngine()
        score = engine._sentiment_support({"signal": "BUY", "fear_greed": 10})
        assert score < 0.5, f"Expected <0.5, got {score}"

    def test_sell_low_fg_returns_high(self):
        engine = MetaDecisionEngine()
        score = engine._sentiment_support({"signal": "SELL", "fear_greed": 10})
        assert score > 0.5, f"Expected >0.5, got {score}"

    def test_neutral_signal_returns_midpoint(self):
        engine = MetaDecisionEngine()
        score = engine._sentiment_support({"signal": "NEUTRAL", "fear_greed": 50})
        assert score == 0.5

    def test_missing_fg_defaults_to_midpoint(self):
        engine = MetaDecisionEngine()
        score = engine._sentiment_support({"signal": "BUY"})
        # fg defaults to 50, momentum defaults to 0 -> should be around 0.5
        assert 0.3 <= score <= 0.7


class TestRegimeSupport:
    def test_bull_trend_supports_buy(self):
        engine = MetaDecisionEngine()
        score = engine._regime_support({"signal": "BUY", "regime": "STRONG_TREND_BULL"})
        assert score >= 0.8

    def test_bull_trend_opposes_sell(self):
        engine = MetaDecisionEngine()
        score = engine._regime_support({"signal": "SELL", "regime": "TRENDING_BULL"})
        assert score <= 0.2

    def test_bear_trend_supports_sell(self):
        engine = MetaDecisionEngine()
        score = engine._regime_support({"signal": "SELL", "regime": "TRENDING_BEAR"})
        assert score >= 0.8

    def test_ranging_returns_neutral(self):
        engine = MetaDecisionEngine()
        score = engine._regime_support({"signal": "BUY", "regime": "RANGING"})
        assert score == 0.5

    def test_unknown_regime_returns_neutral(self):
        engine = MetaDecisionEngine()
        score = engine._regime_support({"signal": "BUY", "regime": "UNKNOWN_REGIME"})
        assert score == 0.5


class TestVolatilitySupport:
    def test_panic_high_vol_returns_low(self):
        engine = MetaDecisionEngine()
        score = engine._volatility_support({"atr_percentile": 90})
        assert score <= 0.3

    def test_moderate_vol(self):
        engine = MetaDecisionEngine()
        # atr_percentile=55 falls into >= 40 bucket -> 0.75
        score = engine._volatility_support({"atr_percentile": 55})
        assert score == 0.75

    def test_boundary_vol_60(self):
        engine = MetaDecisionEngine()
        # atr_percentile=65 falls into >= 60 bucket -> 0.5
        score = engine._volatility_support({"atr_percentile": 65})
        assert score == 0.5

    def test_low_vol_returns_high(self):
        engine = MetaDecisionEngine()
        score = engine._volatility_support({"atr_percentile": 20})
        assert score >= 0.85

    def test_high_atr_pct_returns_low(self):
        engine = MetaDecisionEngine()
        score = engine._volatility_support({"atr_pct": 4.0})
        assert score <= 0.3


# ---------------------------------------------------------------------------
# compute_posterior
# ---------------------------------------------------------------------------

class TestComputePosterior:
    def test_all_high_gives_high_posterior(self):
        engine = MetaDecisionEngine()
        p = engine.compute_posterior(0.9, 0.9, 0.9, 0.9)
        assert p >= 0.85

    def test_all_low_gives_low_posterior(self):
        engine = MetaDecisionEngine()
        p = engine.compute_posterior(0.1, 0.1, 0.1, 0.1)
        assert p <= 0.15

    def test_midpoint(self):
        engine = MetaDecisionEngine()
        p = engine.compute_posterior(0.5, 0.5, 0.5, 0.5)
        assert abs(p - 0.5) < 0.01

    def test_custom_weights(self):
        engine = MetaDecisionEngine(weights={"meta": 1.0, "sentiment": 0.0, "regime": 0.0, "volatility": 0.0})
        p = engine.compute_posterior(0.9, 0.1, 0.1, 0.1)
        assert p >= 0.85, "Custom weight should make meta dominate"

    def test_output_clamped_to_01(self):
        engine = MetaDecisionEngine()
        p = engine.compute_posterior(1.5, 1.5, 1.5, 1.5)
        assert 0.0 <= p <= 1.0
        p = engine.compute_posterior(-0.5, -0.5, -0.5, -0.5)
        assert 0.0 <= p <= 1.0


class TestFinalRiskGate:
    def test_critical_stop_is_immutable(self):
        action, reasons = apply_final_risk_gate("BUY", "CRITICAL", True)
        assert action is DecisionAction.ALLOW_EXIT_ONLY
        assert "critical_context_hard_stop" in reasons

    def test_high_stop_blocks_entry(self):
        action, reasons = apply_final_risk_gate("INCREASE", "HIGH", True)
        assert action is DecisionAction.BLOCK_ENTRY
        assert "high_context_entry_block" in reasons

    def test_neutral_structured_action_cannot_become_trade(self):
        engine = MetaDecisionEngine()
        result = engine.decide({
            "signal": "NEUTRAL (BEARISH)",
            "action": "NEUTRAL",
            "_meta_prediction": {
                "probability": 0.2,
                "expected_return": 0.1,
                "prediction_id": None,
            },
        }, persist_final=False)

        assert result["action"] == "HOLD"
        assert result["terminal_status"] == "HOLD"
        assert result["eligible"] is False

    def test_structured_sell_has_side_adjusted_execution_probability(self):
        engine = MetaDecisionEngine()
        result = engine.decide({
            "signal": "NEUTRAL (BEARISH)",
            "action": "SELL",
            "_meta_prediction": {
                "probability": 0.2,
                "expected_return": 0.1,
                "prediction_id": None,
            },
        }, persist_final=False)

        assert result["action"] == "SELL"
        assert result["terminal_status"] == "TRADE"
        assert result["execution_probability"] == pytest.approx(0.8)

    def test_bearish_support_combines_in_side_space_for_sell(self):
        engine = MetaDecisionEngine()
        result = engine.decide({
            "signal": "STRONG SELL",
            "action": "SELL",
            "fear_greed": 20,
            "sentiment_momentum": -0.8,
            "regime": "bear",
            "atr_pct": 1.0,
            "_meta_prediction": {
                "probability": 0.2,
                "probability_semantics": "P(up)",
                "expected_return": 0.1,
                "prediction_id": None,
            },
        }, persist_final=False)

        assert result["action"] == "SELL"
        assert result["model_probability_up"] == pytest.approx(0.2)
        assert result["meta_probability"] == pytest.approx(0.8)
        assert result["side_probability"] >= 0.65
        assert result["posterior_probability"] <= 0.35
        assert result["decision_contract_version"] == "side-probability-v2"


class TestSideAgnosticExpectedValueContract:
    def test_buy_eligible_with_positive_ev(self):
        engine = MetaDecisionEngine(min_ev_pct=0.05)
        # P(win) high + TP > SL -> positive EV -> BUY is eligible
        result = engine.decide({
            "signal": "BUY",
            "action": "BUY",
            "_meta_prediction": {
                "probability": 0.8,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
                "prediction_id": "pred-1",
            }
        }, persist_final=False)
        assert result["action"] == "BUY"
        assert result["eligible"] is True

    def test_sell_eligible_with_positive_ev(self):
        engine = MetaDecisionEngine(min_ev_pct=0.05)
        # P(win) high + TP > SL -> positive EV -> SELL is eligible
        result = engine.decide({
            "signal": "SELL",
            "action": "SELL",
            "_meta_prediction": {
                "probability": 0.8,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
                "prediction_id": "pred-2",
            }
        }, persist_final=False)
        assert result["action"] == "SELL"
        assert result["eligible"] is True

    def test_buy_ignored_with_negative_ev(self):
        engine = MetaDecisionEngine(min_ev_pct=0.05)
        # P(win) low -> negative EV -> BUY is ignored
        result = engine.decide({
            "signal": "BUY",
            "action": "BUY",
            "_meta_prediction": {
                "probability": 0.2,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": -0.10,
                "prediction_id": "pred-3",
            }
        }, persist_final=False)
        assert result["action"] == "IGNORE"
        assert result["eligible"] is False

    def test_sell_ignored_with_negative_ev(self):
        engine = MetaDecisionEngine(min_ev_pct=0.05)
        # P(win) low -> negative EV -> SELL is ignored
        result = engine.decide({
            "signal": "SELL",
            "action": "SELL",
            "_meta_prediction": {
                "probability": 0.2,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": -0.10,
                "prediction_id": "pred-4",
            }
        }, persist_final=False)
        assert result["action"] == "IGNORE"
        assert result["eligible"] is False

    def test_symmetric_threshold_gating_behavior(self):
        # Using a custom symmetric threshold of 0.40 and isolating to meta support only
        engine = MetaDecisionEngine(weights={"meta": 1.0}, buy_threshold=0.40, sell_threshold=0.40, min_ev_pct=0.05)
        
        # 1. Meets threshold exactly -> eligible
        res_buy = engine.decide({
            "signal": "BUY",
            "action": "BUY",
            "_meta_prediction": {
                "probability": 0.40,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
            }
        }, persist_final=False)
        assert res_buy["action"] == "BUY"
        
        res_sell = engine.decide({
            "signal": "SELL",
            "action": "SELL",
            "_meta_prediction": {
                "probability": 0.40,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
            }
        }, persist_final=False)
        assert res_sell["action"] == "SELL"

        # 2. Below threshold (0.39) -> HOLD (since EV is positive but probability is insufficient)
        res_buy_hold = engine.decide({
            "signal": "BUY",
            "action": "BUY",
            "_meta_prediction": {
                "probability": 0.39,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
            }
        }, persist_final=False)
        assert res_buy_hold["action"] == "HOLD"
        
        res_sell_hold = engine.decide({
            "signal": "SELL",
            "action": "SELL",
            "_meta_prediction": {
                "probability": 0.39,
                "probability_semantics": "P(win_given_proposed_trade)",
                "expected_return": 0.10,
            }
        }, persist_final=False)
        assert res_sell_hold["action"] == "HOLD"


    def test_unavailable_account_risk_is_persistable_in_final_decision(self):
        engine = MetaDecisionEngine()
        result = engine.decide({
            "signal": "BUY",
            "risk_status": "UNAVAILABLE",
            "risk_blocked": True,
            "risk_failure_reason": "equity_unavailable",
            "_meta_prediction": {
                "probability": 0.9,
                "expected_return": 1.0,
                "prediction_id": "p-risk",
                "signal_id": "s-risk",
            },
        }, persist_final=False)

        assert result["action"] == "BLOCK_ENTRY"
        assert result["risk_status"] == "UNAVAILABLE"
        assert result["risk_failure_reason"] == "equity_unavailable"
        assert "risk_failure=equity_unavailable" in result["reason"]

    def test_apply_context_cannot_overwrite_critical_stop(self):
        engine = MetaDecisionEngine()
        base = {"action": "BUY", "posterior_probability": .9, "expected_return": .2, "reason": "base"}
        result = engine.apply_context(base, {"adjusted_score": .99, "risk_level": "CRITICAL", "stop_processing": True})
        assert result["action"] == "ALLOW_EXIT_ONLY"
        assert result["risk_reason_codes"] == ["critical_context_hard_stop"]

    def test_provider_path_does_not_reinfer(self, monkeypatch):
        engine = MetaDecisionEngine()
        calls = 0
        def decide(_info, **_kwargs):
            nonlocal calls
            calls += 1
            return {"action": "BUY", "posterior_probability": .8, "expected_return": .2, "reason": "base"}
        class Report:
            def to_dict(self):
                return {"adjusted_score": .7, "risk_level": "LOW", "stop_processing": False}
        class Provider:
            name = "test"
            def should_apply_context(self, _state): return True
            def generate_context_report(self, _score, _state): return Report()
        monkeypatch.setattr(engine, "decide", decide)
        engine.decide_with_provider({"signal_id": "sig-1"}, Provider(), object())
        assert calls == 1

    def test_provider_path_persists_one_final_decision(self, monkeypatch, tmp_path):
        from btc_scraper.ml_engine import decision_engine as decision_module
        from btc_scraper.ml_engine import runtime_evidence_store as evidence_module
        store = evidence_module.RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
        store.write_prediction_evidence(
            {"prediction_id": "pred-1", "value": .8},
            {"prediction_id": "pred-1", "features": [1]},
        )
        monkeypatch.setattr(evidence_module, "_STORE", store)
        monkeypatch.setattr(decision_module, "predict_meta_confidence", lambda _info: {
            "probability": .8, "expected_return": .2, "prediction_id": "pred-1",
            "model_version": "v", "artifact_sha256": "sha",
        })
        class Report:
            def to_dict(self): return {"adjusted_score": .9, "risk_level": "LOW", "stop_processing": False}
        class Provider:
            name = "test"
            def should_apply_context(self, _state): return True
            def generate_context_report(self, _score, _state): return Report()
        result = MetaDecisionEngine().decide_with_provider({"signal_id": "sig-1", "signal": "BUY"}, Provider(), object())
        with store._connect() as db:
            rows = db.execute("SELECT prediction_id, payload FROM final_decisions").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == result["prediction_id"] == "pred-1"

    def test_provider_replay_reuses_persisted_final_decision(self, monkeypatch, tmp_path):
        from btc_scraper.ml_engine import runtime_evidence_store as evidence_module

        store = evidence_module.RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
        store.write_prediction_evidence(
            {"prediction_id": "pred-1", "value": .8},
            {"prediction_id": "pred-1", "features": [1]},
        )
        monkeypatch.setattr(evidence_module, "_STORE", store)

        class Report:
            def to_dict(self):
                return {
                    "adjusted_score": .9,
                    "risk_level": "LOW",
                    "stop_processing": False,
                }

        class Provider:
            name = "test"

            def should_apply_context(self, _state):
                return True

            def generate_context_report(self, _score, _state):
                return Report()

        engine = MetaDecisionEngine()
        analysis = {
            "signal_id": "sig-1",
            "signal": "BUY",
            "_meta_prediction": {
                "probability": .8,
                "expected_return": .2,
                "prediction_id": "pred-1",
                "model_version": "v",
                "artifact_sha256": "sha",
            },
        }
        first = engine.decide_with_provider(analysis, Provider(), object())
        replay = engine.decide_with_provider(
            {**analysis, "fear_greed": 5},
            Provider(),
            object(),
        )

        assert replay["decision_id"] == first["decision_id"]
        assert store.count_rows("final_decisions") == 1
        assert store.shadow_evidence_rows()["quarantine"] == []
        assert store.health()["status"] == "healthy"


# ---------------------------------------------------------------------------
# decide() without model
# ---------------------------------------------------------------------------

class TestDecideNoModel:
    def test_returns_neutral_when_no_model(self, clean_engine):
        result = clean_engine.decide({"coin": "BTC", "signal": "BUY"})
        assert result["action"] == "NEUTRAL"
        assert result["posterior_probability"] is None
        assert result["meta_probability"] is None
        assert "error" in result

    def test_result_is_dict(self, clean_engine):
        result = clean_engine.decide({"coin": "ETH", "signal": "SELL"})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# decide() with model — action classification
# ---------------------------------------------------------------------------

class TestDecideWithModel:
    def test_returns_dict_with_required_keys(self, engine_with_model):
        required = {
            "action", "posterior_probability", "meta_probability",
            "sentiment_support", "regime_support", "volatility_support",
            "expected_return", "expected_drawdown", "expected_hold_time",
            "prob_tp1", "prob_tp2", "prob_sl", "meta_ev", "reason",
        }
        result = engine_with_model.decide({
            "coin": "BTC", "signal": "BUY", "action": "BUY",
            "rsi": 55.0, "macd_hist": 0.01, "atr_pct": 1.2,
            "fear_greed": 60, "regime": "TRENDING_BULL",
        })
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    def test_action_is_valid_enum(self, engine_with_model):
        valid_actions = {"BUY", "SELL", "HOLD", "IGNORE", "INCREASE", "REDUCE", "NEUTRAL"}
        result = engine_with_model.decide({
            "coin": "BTC", "signal": "BUY", "action": "BUY",
            "rsi": 60.0, "atr_pct": 1.0, "fear_greed": 70,
        })
        assert result["action"] in valid_actions

    def test_posterior_in_range_01(self, engine_with_model):
        result = engine_with_model.decide({
            "coin": "ETH", "signal": "BUY", "action": "BUY",
            "rsi": 55.0, "atr_pct": 1.5,
        })
        p = result["posterior_probability"]
        assert p is not None
        assert 0.0 <= p <= 1.0

    def test_reason_string_contains_components(self, engine_with_model):
        result = engine_with_model.decide({"coin": "SOL", "signal": "BUY", "action": "BUY"})
        reason = result.get("reason", "")
        assert "meta_prob=" in reason
        assert "posterior=" in reason
        assert "ev=" in reason

    def test_ignore_when_ev_too_small(self, monkeypatch, tmp_path):
        """Force action=IGNORE by injecting prob=0.5 with symmetric TP/SL (+0.01% / -0.01%).
        EV = 0.5*tp1_pct - 0.5*sl_pct ~ 0 -> abs(EV) < min_ev_pct(0.05) -> IGNORE."""
        from btc_scraper.ml_engine import meta_model as _mm
        from btc_scraper.ml_engine import decision_engine as _de

        original_cache = _mm._MODEL_CACHE
        _mm._MODEL_CACHE = None

        # Inject a stub that bypasses model loading and returns prob=0.5 + EV computation
        def _stub(info):
            from btc_scraper.ml_engine.meta_model import _compute_expected_value_metrics
            return {"probability": 0.5, **_compute_expected_value_metrics(0.5, info)}

        monkeypatch.setattr(_de, "predict_meta_confidence", _stub)

        engine = MetaDecisionEngine(min_ev_pct=0.05)
        # Use field names that _extract_tp_sl_profile actually reads: entry, sl, tp1
        result = engine.decide({
            "coin": "BTC",
            "signal": "BUY",
            "action": "BUY",
            "entry": 100.0,
            "tp1": 100.01,   # +0.01%
            "sl":  99.99,    # -0.01%
        })

        _mm._MODEL_CACHE = original_cache

        assert result["action"] == "IGNORE", (
            f"Expected IGNORE for near-zero EV, got {result['action']} "
            f"(expected_return={result.get('expected_return')})"
        )
