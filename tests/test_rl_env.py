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
