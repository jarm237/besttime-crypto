import os
import json
import pytest
import numpy as np
from pathlib import Path
from sklearn.datasets import make_classification

import btc_scraper.ml_engine.adaptive_scoring as ads
import btc_scraper.ml_engine.meta_model as mm
from btc_scraper.ml_engine.meta_model import EnsembleMetaModel, compute_calibration_buckets, predict_meta_confidence


@pytest.fixture
def temp_logs_dir(tmp_path):
    # Redirect logs in adaptive_scoring and meta_model to temp path
    original_log = ads.ADAPTIVE_LOG
    original_model = ads.ADAPTIVE_MODEL
    original_model_joblib = ads.ADAPTIVE_MODEL_JOBLIB
    ads.ADAPTIVE_LOG = str(tmp_path / "adaptive_signals.json")
    ads.ADAPTIVE_MODEL = str(tmp_path / "adaptive_model.json")
    ads.ADAPTIVE_MODEL_JOBLIB = str(tmp_path / "adaptive_model.joblib")
    
    original_mm_input = mm.INPUT
    original_mm_model_out = mm.MODEL_OUT
    original_mm_metric_out = mm.METRIC_OUT
    original_mm_feature_imp = mm.FEATURE_IMPORTANCE_OUT
    original_model_cache = mm._MODEL_CACHE
    original_artifact_provenance = mm._MODEL_ARTIFACT_PROVENANCE
    original_artifact_owner = mm._MODEL_ARTIFACT_OWNER_ID
    
    mm.INPUT = tmp_path / "adaptive_signals_v2.json"
    mm.MODEL_OUT = tmp_path / "meta_model.joblib"
    mm.METRIC_OUT = tmp_path / "meta_model.json"
    mm.FEATURE_IMPORTANCE_OUT = tmp_path / "meta_feature_importance.json"
    mm.LOGS = tmp_path
    mm._MODEL_CACHE = None
    mm._MODEL_ARTIFACT_PROVENANCE = None
    mm._MODEL_ARTIFACT_OWNER_ID = None
    
    yield tmp_path
    
    # Restore original paths
    ads.ADAPTIVE_LOG = original_log
    ads.ADAPTIVE_MODEL = original_model
    ads.ADAPTIVE_MODEL_JOBLIB = original_model_joblib
    mm.INPUT = original_mm_input
    mm.MODEL_OUT = original_mm_model_out
    mm.METRIC_OUT = original_mm_metric_out
    mm.FEATURE_IMPORTANCE_OUT = original_mm_feature_imp
    mm.LOGS = original_mm_model_out.parent
    mm._MODEL_CACHE = original_model_cache
    mm._MODEL_ARTIFACT_PROVENANCE = original_artifact_provenance
    mm._MODEL_ARTIFACT_OWNER_ID = original_artifact_owner


def test_calibration_buckets():
    probs = [0.85, 0.75, 0.65, 0.55, 0.35]
    results = ["WIN", "LOSS", "WIN", "LOSS", "LOSS"]
    
    analysis = compute_calibration_buckets(probs, results, min_samples=1)
    
    assert "0.8-1.0" in analysis
    assert "0.0-0.4" in analysis
    assert analysis["0.8-1.0"]["wins"] == 1
    assert analysis["0.8-1.0"]["losses"] == 0
    assert analysis["0.0-0.4"]["wins"] == 0
    assert analysis["0.0-0.4"]["losses"] == 1


def test_adaptive_scoring_log_and_stats(temp_logs_dir):
    # Verify starting empty
    assert len(ads._load_log()) == 0
    
    trade1 = {
        "coin": "BTC",
        "id": "1",
        "entry_price": 60000.0,
        "sell_price": 61200.0,
        "pnl_pct": 2.0,
        "result": "WIN",
        "hold_hours": 2.0,
        "exit_time": "2026-06-28 12:00",
        "signal": "BUY",
        "signal_score": {"score": 85, "regime": "STRONG_TREND_BULL"}
    }
    
    trade2 = {
        "coin": "BTC",
        "id": "2",
        "entry_price": 60000.0,
        "sell_price": 59400.0,
        "pnl_pct": -1.0,
        "result": "LOSS",
        "hold_hours": 3.0,
        "exit_time": "2026-06-28 13:00",
        "signal": "BUY",
        "signal_score": {"score": 82, "regime": "STRONG_TREND_BULL"}
    }
    
    ads.log_trade_outcome(trade1)
    ads.log_trade_outcome(trade2)
    
    log = ads._load_log()
    assert len(log) == 2
    assert log[0]["coin"] == "BTC"
    assert log[0]["result"] == "WIN"
    assert log[0]["traceability_scope"] == "offline_only"
    assert log[0]["runtime_calibration_eligible"] is False
    
    # Check stats computation
    stats = ads.compute_score_stats()
    assert "80" in stats
    assert stats["80"]["count"] == 2
    assert stats["80"]["wins"] == 1
    assert stats["80"]["losses"] == 1
    assert stats["80"]["win_rate"] == 50.0
    
    # Train adaptive model
    train_res = ads.train_adaptive_model(save=True)
    assert train_res is not None
    if train_res.get("model") == "sklearn_random_forest":
        assert os.path.exists(ads.ADAPTIVE_MODEL_JOBLIB)
    else:
        assert os.path.exists(ads.ADAPTIVE_MODEL)
        with open(ads.ADAPTIVE_MODEL) as f:
            saved_model = json.load(f)
            assert "80" in saved_model
            assert saved_model["80"]["win_rate"] == 50.0


def test_ensemble_meta_model():
    from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA_V2
    n_features = len(FEATURE_SCHEMA_V2)
    
    # Generate simple synthetic dataset matching features length
    X, y = make_classification(
        n_samples=40,
        n_features=n_features,
        n_informative=10,
        n_redundant=2,
        random_state=42
    )
    
    # Force class 0 and 1
    y[0] = 0
    y[1] = 1
    
    # Determine which base models are available
    estimators = mm._import_optional_estimators()
    if not estimators:
        pytest.skip("No LGBM, CatBoost, or XGBoost available for testing EnsembleMetaModel.")
        
    # Pick weights representing available estimators
    weights = {k: 1.0 for k in estimators.keys()}
    
    # Test Init
    model = EnsembleMetaModel(weights=weights, n_estimators=10, random_state=42)
    
    # Test Fit
    model.fit(X, y, cv=2)
    assert len(model.models_) > 0
    
    # Test Predict Proba
    probs = model.predict_proba(X[:5])
    assert probs.shape == (5, 2)
    assert np.allclose(np.sum(probs, axis=1), 1.0)
    
    # Test Predict
    preds = model.predict(X[:5])
    assert len(preds) == 5
    assert all(p in [0, 1] for p in preds)


def test_xgboost_gpu_device_string():
    params0 = mm._get_backend_kwargs("xgboost", use_gpu=True, device_id=0)
    assert params0["tree_method"] == "hist"
    assert params0["device"] == "gpu"

    params1 = mm._get_backend_kwargs("xgboost", use_gpu=True, device_id=1)
    assert params1["tree_method"] == "hist"
    assert params1["device"] == "gpu:1"


def test_predict_meta_confidence(temp_logs_dir):
    # Test predict when model is missing
    res_no_model = predict_meta_confidence(
        {"coin": "BTC", "action": "BUY"},
        symbol="BTC",
    )
    assert "error" in res_no_model
    assert res_no_model["probability"] is None
    
    # Train and save a small calibrated model to temp folder to test loading
    from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA_V2
    n_features = len(FEATURE_SCHEMA_V2)
    
    estimators = mm._import_optional_estimators()
    if not estimators:
        pytest.skip("No LGBM, CatBoost, or XGBoost available to save test meta model.")
        
    X = np.random.rand(30, n_features)
    y = np.random.randint(0, 2, size=30)
    y[0] = 0
    y[1] = 1
    
    weights = {k: 1.0 for k in estimators.keys()}
    model = EnsembleMetaModel(weights=weights, calibration="sigmoid", n_estimators=5, random_state=42)
    model.fit(X, y, cv=2)
    
    import joblib
    # Save dummy model structure
    joblib.dump({"model": model, "features": FEATURE_SCHEMA_V2, "version": mm.MODEL_VERSION}, mm.MODEL_OUT)
    
    # Test prediction with mock data
    mock_analysis_info = {
        "coin": "BTC",
        "action": "BUY",
        "rsi": 55.0,
        "macd_hist": 0.01,
        "atr_pct": 1.5,
        "volume_ratio": 1.2,
        "fear_greed": 60,
        "bb_width_pct": 2.5,
        "adx": 25.0,
        "mtf_alignment": 1,
        "regime": "STRONG_TREND_BULL"
    }
    
    res = predict_meta_confidence(mock_analysis_info, symbol="BTC")
    assert "probability" in res
    assert isinstance(res["probability"], float)
    assert 0.0 <= res["probability"] <= 1.0
    assert "expected_return" in res
    assert "prob_tp1" in res
    assert "prob_sl" in res
    assert res["expected_return_bps"] == pytest.approx(
        res["expected_return"] * 10_000,
        abs=0.0001,
    )
    assert res["expected_return_unit"] == "fraction"
    assert res["ev_contract_version"] == "expected-return-fraction-v1"


def test_meta_decision_engine():
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine

    engine = MetaDecisionEngine()
    decision = engine.decide({
        "signal": "BUY",
        "fear_greed": 70,
        "sentiment_momentum": 0.3,
        "regime": "TRENDING_BULL",
        "atr_pct": 1.2,
        "tp_sl": {"entry": 100.0, "sl": 98.0, "tp1": 102.0, "tp2": 104.0},
    })

    assert isinstance(decision, dict)
    assert decision["action"] in {"BUY", "HOLD", "IGNORE", "INCREASE", "REDUCE", "SELL", "NEUTRAL"}
    assert decision["posterior_probability"] is None or (0.0 <= decision["posterior_probability"] <= 1.0)
