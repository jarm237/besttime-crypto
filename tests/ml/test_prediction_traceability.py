import json

from btc_scraper.ml_engine.meta_model import _resolve_prediction_symbol
from btc_scraper.ml_engine.prediction_logger import append_prediction


def test_meta_model_prediction_symbol_fallbacks_are_contract_safe():
    assert _resolve_prediction_symbol({"coin": "btc"}) == "BTC"
    assert _resolve_prediction_symbol({"symbol": "ETH/USDT"}) == "ETH"
    assert _resolve_prediction_symbol({"ticker": "xrpUSDT"}) == "XRP"
    assert _resolve_prediction_symbol({}) == "UNKNOWN"


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
