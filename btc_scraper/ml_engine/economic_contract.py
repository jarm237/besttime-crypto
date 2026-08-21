"""Versioned economic-unit helpers for inference and final decisions."""
from __future__ import annotations

import math


EV_CONTRACT_VERSION = "expected-return-fraction-v1"
EXPECTED_RETURN_UNIT = "fraction"


def _finite(value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("economic value must be finite")
    return normalized


def fraction_to_bps(value: float) -> float:
    """Convert a fractional return to basis points."""
    return _finite(value) * 10_000.0


def bps_to_fraction(value: float) -> float:
    """Convert basis points to the canonical fractional-return unit."""
    return _finite(value) / 10_000.0


def fraction_to_percent_points(value: float) -> float:
    """Convert a fractional return to percentage points for display boundaries."""
    return _finite(value) * 100.0


def percent_points_to_fraction(value: float) -> float:
    """Convert percentage points from TP/SL profiles to a fractional return."""
    return _finite(value) / 100.0
