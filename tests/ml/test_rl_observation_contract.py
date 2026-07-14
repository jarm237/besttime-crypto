import pytest

from btc_scraper.ml_engine.schema_validator import RLExitObservationV2
from btc_scraper.trading.rl_action_guard import guard_rl_action


def test_rl_observation_requires_twenty_finite_normalized_values():
    RLExitObservationV2(tuple(0.0 for _ in range(20))).validate()
    with pytest.raises(ValueError):
        RLExitObservationV2(tuple(0.0 for _ in range(19))).validate()
    with pytest.raises(ValueError):
        RLExitObservationV2(tuple([0.0] * 19 + [float("nan")])).validate()


def test_shadow_mode_cannot_apply_action():
    outcome = guard_rl_action(4, mode="shadow")
    assert outcome.action == 0 and outcome.decision == "shadowed"
