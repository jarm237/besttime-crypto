"""
btc_scraper/research/ml_payoff_sizing package
"""
from btc_scraper.research.ml_payoff_sizing.payoff_dataset import build_payoff_dataset
from btc_scraper.research.ml_payoff_sizing.payoff_regressors import (
    PurgedWalkForwardPayoffTrainer,
)
from btc_scraper.research.ml_payoff_sizing.risk_constrained_sizing import (
    compute_asymmetric_expansion_weight,
    compute_risk_reducing_weight,
)
from btc_scraper.research.ml_payoff_sizing.payoff_sizing_strategy import (
    PayoffSizedEmaTrendStrategy,
)

__all__ = [
    "build_payoff_dataset",
    "PurgedWalkForwardPayoffTrainer",
    "compute_risk_reducing_weight",
    "compute_asymmetric_expansion_weight",
    "PayoffSizedEmaTrendStrategy",
]
