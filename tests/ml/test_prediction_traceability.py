import json

from btc_scraper.ml_engine.prediction_logger import append_prediction


def test_prediction_envelope_contains_required_traceability_fields(tmp_path):
    entry = append_prediction(model_name="meta_model", model_version="v1", artifact_sha256="abc",
                              feature_schema_version="schema", raw_prediction=.7, calibrated_prediction=.7,
                              features=[1, 2], decision_context="entry", log_dir=tmp_path)
    assert entry["prediction_id"] and entry["feature_hash"] and entry["artifact_sha256"] == "abc"
    row = json.loads(next(tmp_path.glob("predictions_*.jsonl")).read_text(encoding="utf-8"))
    assert row["model_version"] == "v1"
