"""
btc_scraper/research/ml_trade_quality package
"""
from btc_scraper.research.ml_trade_quality.feature_contract import (
    FEATURE_NAMES,
    extract_features_at_bar,
)
from btc_scraper.research.ml_trade_quality.dataset_builder import (
    build_trade_quality_dataset,
)
from btc_scraper.research.ml_trade_quality.purged_walk_forward_trainer import (
    PurgedWalkForwardTrainer,
)
from btc_scraper.research.ml_trade_quality.ml_filtered_strategy import (
    MlFilteredEmaTrendStrategy,
)

__all__ = [
    "FEATURE_NAMES",
    "extract_features_at_bar",
    "build_trade_quality_dataset",
    "PurgedWalkForwardTrainer",
    "MlFilteredEmaTrendStrategy",
]
