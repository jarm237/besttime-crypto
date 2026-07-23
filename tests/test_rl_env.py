import os
import shutil
import tempfile
import numpy as np
import pytest
from stable_baselines3 import PPO

from btc_scraper.ml_engine.rl_trading_env import TradeExitEnv, MultiTradeExitEnv


@pytest.fixture
def dummy_trades():
    return [
        {
            "coin": "BTC",
            "entry_time": "2026-01-01 00:00",
            "signal_raw": "BUY",
            "meta_confidence": 0.75,
        },
        {
            "coin": "ETH",
            "entry_time": "2026-01-02 12:00",
            "signal_raw": "SELL",
            "meta_confidence": 0.60,
        }
    ]


def test_trade_exit_env_spaces(dummy_trades):
    env = TradeExitEnv(trades=dummy_trades)
    
    # Verify action and observation space
    assert env.observation_space.shape == (20,)
    assert env.observation_space.dtype == np.float32
    assert env.action_space.n == 6
    
    # Verify mapping of regime
    assert env._map_regime("STRONG_TREND_BULL") == "STRONG_TREND"
    assert env._map_regime("RANGING_ZONE") == "MEAN_REVERSION"
    assert env._map_regime("UNKNOWN_REGIME") == "STRONG_TREND"


def test_trade_exit_env_reset_and_step(dummy_trades):
    env = TradeExitEnv(trades=dummy_trades, config={"max_episode_length": 10})
    
    # Test reset
    obs, info = env.reset(seed=42)
    assert obs.shape == (20,)
    assert isinstance(obs, np.ndarray)
    assert "coin" in info
    assert "direction" in info
    assert info["entry_price"] > 0
    
    # Test step with HOLD action (0)
    next_obs, reward, terminated, truncated, info = env.step(0)
    assert next_obs.shape == (20,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert "current_pnl" in info
    assert "done_reason" in info


def test_trade_exit_env_data_end_observation_shape(dummy_trades):
    env = TradeExitEnv(trades=dummy_trades, config={"max_episode_length": 10})
    env.reset(seed=42)

    env.current_step = len(env.coin_candles[env.coin])
    obs, reward, terminated, truncated, info = env.step(0)

    assert obs.shape == env.observation_space.shape
    assert obs.dtype == np.float32
    assert terminated is True
    assert truncated is False
    assert info["done_reason"] == "DATA_END"


def test_trade_exit_env_exit_reward_is_pure_net_pnl():
    previous_cache = TradeExitEnv._COIN_CANDLES_CACHE
    candles = [
        {
            "time": f"2026-01-01 00:0{i}",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1000.0,
            "rsi": 50.0,
            "macd_hist": 0.0,
            "atr": 1.0,
            "atr_pct": 1.0,
            "adx": 20.0,
            "regime": "STRONG_TREND",
            "fear_greed": 50.0,
        }
        for i in range(5)
    ]
    TradeExitEnv._COIN_CANDLES_CACHE = {"TST": candles}

    try:
        env = TradeExitEnv(
            trades=[{"coin": "TST", "entry_time": candles[0]["time"], "signal_raw": "BUY"}],
            config={
                "max_episode_length": 2,
                "commission_fee": 0.001,
                "slippage_pct": 0.0005,
                "drawdown_penalty": 99.0,
                "sharpe_bonus": 99.0,
            },
        )
        env.reset(seed=42)

        _, reward, terminated, _, info = env.step(4)

        assert terminated is True
        assert info["done_reason"] == "EXIT"
        assert reward == pytest.approx(-0.3)
        assert sum(env.episode_rewards) == pytest.approx(-0.3)
    finally:
        TradeExitEnv._COIN_CANDLES_CACHE = previous_cache


def test_multi_trade_exit_env_cycle(dummy_trades):
    env = MultiTradeExitEnv(trades=dummy_trades, config={"max_episode_length": 5}, trades_per_episode=2)
    obs, info = env.reset()
    
    # Step through until the first trade terminates, it should cycle to the next trade
    terminated = False
    truncated = False
    step_count = 0
    
    while not (terminated or truncated) and step_count < 20:
        # Action 4 is EXIT (should trigger termination of single trade, then cycle or end episode)
        obs, reward, terminated, truncated, info = env.step(4)
        step_count += 1
        
    assert step_count > 0
    assert env.trades_completed == 2
    assert terminated  # Should be terminated after 2 trades


def test_multi_trade_resets_all_trade_local_state(dummy_trades):
    env = MultiTradeExitEnv(trades=dummy_trades, config={"max_episode_length": 5}, trades_per_episode=2)
    env.reset(seed=3)
    env.prev_pnl, env.min_pnl, env.max_pnl = 9.0, -8.0, 10.0
    _, _, terminated, truncated, _ = env.step(4)
    assert not terminated and not truncated
    assert env.prev_pnl == 0.0
    assert env.min_pnl == 0.0
    assert env.max_pnl == 0.0
    assert env.current_drawdown == 0.0
    assert env.last_action is None


def test_time_limit_is_truncated_not_terminated():
    previous_cache = TradeExitEnv._COIN_CANDLES_CACHE
    candles = [{"time": f"t{i}", "close": 100.0, "high": 100.0, "low": 100.0, "atr": 1.0} for i in range(5)]
    TradeExitEnv._COIN_CANDLES_CACHE = {"TST": candles}
    try:
        env = TradeExitEnv([{"coin": "TST", "entry_time": "t0", "signal_raw": "BUY"}], {"max_episode_length": 1})
        env.reset(seed=1)
        _, _, terminated, truncated, info = env.step(0)
        assert terminated is False
        assert truncated is True
        assert info["done_reason"] == "MAX_STEPS"
    finally:
        TradeExitEnv._COIN_CANDLES_CACHE = previous_cache


def test_multi_trade_final_time_limit_stays_truncated():
    previous_cache = TradeExitEnv._COIN_CANDLES_CACHE
    candles = [{"time": f"t{i}", "close": 100.0, "high": 100.0, "low": 100.0, "atr": 1.0} for i in range(5)]
    TradeExitEnv._COIN_CANDLES_CACHE = {"TST": candles}
    try:
        env = MultiTradeExitEnv(
            [{"coin": "TST", "entry_time": "t0", "signal_raw": "BUY"}],
            {"max_episode_length": 1}, trades_per_episode=1,
        )
        env.reset(seed=1)
        _, _, terminated, truncated, _ = env.step(0)
        assert terminated is False
        assert truncated is True
    finally:
        TradeExitEnv._COIN_CANDLES_CACHE = previous_cache


def test_ppo_smoke_train(dummy_trades):
    # Set up environments for training smoke test
    env = MultiTradeExitEnv(
        trades=dummy_trades, 
        config={
            "max_episode_length": 10,
            "reward_scale": 1.0,
            "drawdown_penalty": 0.5,
            "sharpe_bonus": 0.2,
        },
        trades_per_episode=2
    )
    
    try:
        from sb3_contrib import RecurrentPPO
        # Initialize small RecurrentPPO agent
        model = RecurrentPPO(
            "MlpLstmPolicy",
            env,
            learning_rate=3e-4,
            n_steps=64,
            batch_size=32,
            n_epochs=2,
            verbose=0,
        )
        
        # Learn for a few steps
        model.learn(total_timesteps=128)
        
        # Save model to temp folder and load back
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = os.path.join(tmp_dir, "ppo_smoke_model")
            model.save(model_path)
            assert os.path.exists(f"{model_path}.zip")
            
            loaded_model = RecurrentPPO.load(model_path, env=env)
            assert loaded_model is not None
            
            # Predict an action
            obs, info = env.reset()
            action, _ = loaded_model.predict(obs, deterministic=True)
            assert 0 <= int(action) < 6
    finally:
        env.close()
