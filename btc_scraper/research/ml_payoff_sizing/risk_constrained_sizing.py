"""
btc_scraper/research/ml_payoff_sizing/risk_constrained_sizing.py

Position sizing contracts mapping continuous predicted payoff (in bps) into
risk-reducing or asymmetric position scalars.
Strictly calibrated on training-fold distribution quantiles.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping


def compute_risk_reducing_weight(
    pred_bps: float,
    train_quantiles: Mapping[str, float],
    weight_min: float = 0.25,
    weight_max: float = 1.00,
) -> float:
    """
    Primary Sizing Policy: Risk-Reducing Sizing [0.25, 1.00].
    Scales down exposure on low/negative predicted payoff while capping exposure at 1.00.
    """
    p10 = float(train_quantiles.get("p10", -150.0))
    med = float(train_quantiles.get("median", -15.0))

    if med <= p10:
        med = p10 + 50.0

    if pred_bps <= p10:
        return float(weight_min)
    elif pred_bps >= med:
        return float(weight_max)
    else:
        # Linear interpolation between p10 (min weight) and median (max weight)
        ratio = (pred_bps - p10) / (med - p10)
        w = weight_min + ratio * (weight_max - weight_min)
        return float(min(weight_max, max(weight_min, w)))


def compute_asymmetric_expansion_weight(
    pred_bps: float,
    train_quantiles: Mapping[str, float],
    weight_min: float = 0.25,
    weight_max: float = 1.75,
) -> float:
    """
    Optional Diagnostic Sizing Policy: Asymmetric Expansion [0.25, 1.75].
    Scales down on low predicted payoff (<median) and scales up on high predicted payoff (>median).
    """
    p10 = float(train_quantiles.get("p10", -150.0))
    med = float(train_quantiles.get("median", -15.0))
    p90 = float(train_quantiles.get("p90", 250.0))

    if med <= p10:
        med = p10 + 50.0
    if p90 <= med:
        p90 = med + 150.0

    if pred_bps <= med:
        # Scale down between 0.25 and 1.00
        ratio = max(0.0, (pred_bps - p10) / (med - p10))
        w = 0.25 + ratio * (1.00 - 0.25)
        return float(min(1.00, max(0.25, w)))
    else:
        # Scale up between 1.00 and 1.75
        ratio = min(1.0, (pred_bps - med) / (p90 - med))
        w = 1.00 + ratio * (weight_max - 1.00)
        return float(min(weight_max, max(1.00, w)))
