import json

import pytest

from btc_scraper.ml_engine.inference_contract import (
    InferenceContractError,
    normalize_inference_symbol,
)
from btc_scraper.ml_engine.prediction_logger import append_prediction


def test_meta_model_prediction_symbol_fallbacks_are_contract_safe():
    assert normalize_inference_symbol("btc") == "BTC"
    assert normalize_inference_symbol("ETH/USDT") == "ETH"
    with pytest.raises(InferenceContractError, match="unsupported"):
        normalize_inference_symbol("NOTACOIN")
    with pytest.raises(InferenceContractError, match="must_be_string"):
        normalize_inference_symbol(None)


def test_prediction_envelope_contains_required_traceability_fields(tmp_path):
    entry = append_prediction(model_name="meta_model", model_version="v1", artifact_sha256="abc",
                              feature_schema_version="schema", raw_prediction=.7, calibrated_prediction=.7,
                              features=[1, 2], decision_context="entry", symbol="BTC",
                              timeframe="15m", side="BUY", signal_id="sig-trace-1",
                              caller_context="traceability_test", log_dir=tmp_path)
    assert entry["prediction_id"] and entry["feature_hash"] and entry["artifact_sha256"] == "abc"
    assert entry["feature_snapshot_id"]
    assert entry["symbol"] == "BTC"
    assert entry["timeframe"] == "15m"
    assert entry["side"] == "BUY"
    assert entry["valid_until"]
    assert entry["signal_id"] == "sig-trace-1"
    assert entry["deployment_id"]
    assert entry["caller_context"] == "traceability_test"
    row = json.loads(next(tmp_path.glob("predictions_*.jsonl")).read_text(encoding="utf-8"))
    assert row["model_version"] == "v1"
