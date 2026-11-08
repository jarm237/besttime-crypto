"""Versioned economic-unit helpers for inference and final decisions."""
from __future__ import annotations

import math
import os
from typing import Any, Mapping, Optional


EV_CONTRACT_VERSION = "expected-return-fraction-v1"
EXPECTED_RETURN_UNIT = "fraction"
COST_CONTRACT_VERSION = "cost-contract-v1"
DEFAULT_ROUNDTRIP_COST_BPS = 14.0
DEFAULT_ROUNDTRIP_COST_FRACTION = 0.0014

# ──────────────────────────────────────────────────────────────────────
# Paper Economic Policy Contracts
# ──────────────────────────────────────────────────────────────────────
PAPER_ECONOMIC_POLICY_DEFAULT = "NO_TRADE_SHADOW"
AUTHORIZED_ACTIVE_POLICIES = {"ACTIVE_PAPER", "ACTIVE"}
SHADOW_POLICIES = {"NO_TRADE_SHADOW", "NO_TRADE", "SHADOW"}


def resolve_paper_economic_policy(
    env_override: Optional[str] = None,
    *,
    analysis_info: Optional[Mapping[str, Any]] = None,
) -> str:
    """Canonical resolver for paper trading economic policy.

    Guarantees strict fail-closed behavior:
    - If environment variable PAPER_ECONOMIC_POLICY is unset, empty, or unparseable:
      returns 'NO_TRADE_SHADOW'.
    - 'ACTIVE_PAPER' / 'ACTIVE' is accepted ONLY when explicitly configured.
    - All consumers must call this resolver instead of inspecting os.environ directly.
    """
    raw = env_override if env_override is not None else os.getenv("PAPER_ECONOMIC_POLICY")
    if not raw or not str(raw).strip():
        return PAPER_ECONOMIC_POLICY_DEFAULT

    val = str(raw).strip().upper()
    if val in AUTHORIZED_ACTIVE_POLICIES:
        return val
    if val in SHADOW_POLICIES:
        return val
    # Any unknown policy fail-closed to NO_TRADE_SHADOW
    return PAPER_ECONOMIC_POLICY_DEFAULT


def is_paper_shadow_policy(
    policy: Optional[str] = None,
    *,
    analysis_info: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return True if the resolved policy prohibits order execution and mandates shadow accounting."""
    resolved = resolve_paper_economic_policy(policy, analysis_info=analysis_info)
    return resolved in SHADOW_POLICIES



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


def compute_net_expected_return(
    expected_gross_return: float,
    *,
    roundtrip_cost_fraction: float = DEFAULT_ROUNDTRIP_COST_FRACTION,
) -> dict[str, float]:
    """Compute net expected return after deducting transaction friction (fee + slippage)."""
    gross = _finite(expected_gross_return)
    cost = _finite(roundtrip_cost_fraction)
    net = gross - cost
    return {
        "expected_gross_return": round(gross, 8),
        "expected_cost": round(cost, 8),
        "expected_net_return": round(net, 8),
        "expected_gross_return_bps": round(fraction_to_bps(gross), 4),
        "expected_cost_bps": round(fraction_to_bps(cost), 4),
        "expected_net_return_bps": round(fraction_to_bps(net), 4),
    }
