from btc_scraper.ml_engine.rl_promotion_gate import evaluate_rl_promotion


def _metrics(reward: float) -> dict:
    return {
        "mean_reward": reward,
        "median_reward": reward,
        "tail_reward_p05": reward - 1,
        "max_drawdown": 1.0,
        "evaluation_seeds": [11, 22, 33],
        "regimes_evaluated": ["TREND", "RANGE", "PANIC"],
        "seed_metrics": {str(seed): {"mean_reward": reward} for seed in (11, 22, 33)},
        "regime_metrics": {regime: {"mean_reward": reward} for regime in ("TREND", "RANGE", "PANIC")},
        "transaction_cost_included": True,
    }


def test_rl_gate_requires_all_risk_and_stability_criteria():
    baseline = _metrics(1.0)
    candidate = _metrics(1.1)
    assert evaluate_rl_promotion(candidate, baseline)["passed"] is True
    candidate["max_drawdown"] = 1.1
    result = evaluate_rl_promotion(candidate, baseline)
    assert result["passed"] is False
    assert "max_drawdown_lte_baseline" in result["failed_checks"]


def test_rl_gate_fails_closed_when_evidence_is_missing():
    result = evaluate_rl_promotion({"mean_reward": 2.0}, {"mean_reward": 1.0})
    assert result["passed"] is False
    assert "multiple_seed_stability" in result["failed_checks"]
