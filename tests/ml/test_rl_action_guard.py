from btc_scraper.trading.rl_action_guard import guard_rl_action

def test_active_requires_explicit_live_authorization(monkeypatch):
    monkeypatch.delenv("RL_EXIT_ALLOW_LIVE_ACTION", raising=False)
    assert guard_rl_action(4, mode="active").action == 0
    monkeypatch.setenv("RL_EXIT_ALLOW_LIVE_ACTION", "true")
    assert guard_rl_action(4, mode="active", meta_probability=.8).action == 0

def test_invalid_action_is_rejected():
    assert guard_rl_action(99, mode="active").decision == "rejected"
