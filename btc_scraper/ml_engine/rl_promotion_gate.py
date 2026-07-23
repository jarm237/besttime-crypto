"""Fail-closed, multi-criterion promotion gate for RL policies."""
from __future__ import annotations

from typing import Any, Mapping


def evaluate_rl_promotion(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    minimum_seeds: int = 3,
    minimum_regimes: int = 3,
) -> dict[str, Any]:
    checks = {
        "mean_reward_gt_baseline": _gt(candidate, baseline, "mean_reward"),
        "median_reward_gte_baseline": _gte(candidate, baseline, "median_reward"),
        "tail_reward_gte_baseline": _gte(candidate, baseline, "tail_reward_p05"),
        "max_drawdown_lte_baseline": _lte(candidate, baseline, "max_drawdown"),
        "multiple_seed_stability": _segmented_stability(
            candidate.get("seed_metrics"), baseline.get("seed_metrics"), minimum_seeds,
        ),
        "multiple_regime_stability": _segmented_stability(
            candidate.get("regime_metrics"), baseline.get("regime_metrics"), minimum_regimes,
        ),
        "transaction_cost_included": candidate.get("transaction_cost_included") is True,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _values(candidate: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> tuple[float, float] | None:
    try:
        return float(candidate[key]), float(baseline[key])
    except (KeyError, TypeError, ValueError):
        return None


def _gt(candidate: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> bool:
    values = _values(candidate, baseline, key)
    return values is not None and values[0] > values[1]


def _gte(candidate: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> bool:
    values = _values(candidate, baseline, key)
    return values is not None and values[0] >= values[1]


def _lte(candidate: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> bool:
    values = _values(candidate, baseline, key)
    return values is not None and values[0] <= values[1]


def _segmented_stability(candidate: Any, baseline: Any, minimum_segments: int) -> bool:
    if not isinstance(candidate, Mapping) or not isinstance(baseline, Mapping):
        return False
    shared = set(candidate).intersection(baseline)
    if len(shared) < minimum_segments:
        return False
    return all(
        isinstance(candidate[name], Mapping)
        and isinstance(baseline[name], Mapping)
        and _gte(candidate[name], baseline[name], "mean_reward")
        for name in shared
    )
