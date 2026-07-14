import pytest
from btc_scraper.ml_engine.schema_validator import RL_EXIT_OBSERVATION_V2_FEATURES, validate_feature_names

def test_feature_order_is_part_of_schema_contract():
    validate_feature_names(RL_EXIT_OBSERVATION_V2_FEATURES, RL_EXIT_OBSERVATION_V2_FEATURES)
    with pytest.raises(ValueError):
        validate_feature_names(reversed(RL_EXIT_OBSERVATION_V2_FEATURES), RL_EXIT_OBSERVATION_V2_FEATURES)
