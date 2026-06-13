#!/usr/bin/env python3
"""
Train RL Exit Managers using Stable-Baselines3

Algorithms:
- PPO (Proximal Policy Optimization)
- DQN (Deep Q-Network)
- A2C (Advantage Actor-Critic)

Usage:
    python train_rl_exit_manager.py --algo ppo --train --steps 100000
    python train_rl_exit_manager.py --algo dqn --train --steps 100000
    python train_rl_exit_manager.py --algo a2c --train --steps 100000
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from stable_baselines3 import PPO, DQN, A2C
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnRewardThreshold

from btc_scraper.rl_trading_env import TradeExitEnv, MultiTradeExitEnv


def load_trade_data(csv_path: str = "logs/adaptive_signals.json") -> list[dict]:
    """
    Load historical trade data from adaptive_signals.json.
    
    Args:
        csv_path: Path to signals file
        
    Returns:
        List of trade dicts with indicators
    """
    if not os.path.exists(csv_path):
        print(f"[WARN] File not found: {csv_path}")
        # Generate synthetic trades for testing
        return generate_synthetic_trades(n=100)
    
    try:
        with open(csv_path, "r") as f:
            signals = json.load(f)
        
        trades = []
        for sig_dict in signals:
            trade = {
                "symbol": sig_dict.get("symbol", "BTC"),
                "time": sig_dict.get("time", ""),
                "close": sig_dict.get("close", 100.0),
                "high": sig_dict.get("high", 101.0),
                "low": sig_dict.get("low", 99.0),
                "volume": sig_dict.get("volume", 1000.0),
                "rsi": sig_dict.get("rsi", 50.0),
                "macd_hist": sig_dict.get("macd_hist", 0.0),
                "atr": sig_dict.get("atr", 1.0),
                "adx": sig_dict.get("adx", 20.0),
                "meta_confidence": sig_dict.get("signal_score", {}).get("confidence", 0.5) if isinstance(sig_dict.get("signal_score"), dict) else 0.5,
                "regime": sig_dict.get("regime", "STRONG_TREND"),
                "fear_greed": sig_dict.get("sentiment", {}).get("score", 0.0) * 100 if isinstance(sig_dict.get("sentiment"), dict) else 0.0,
                "volume_ratio": 1.0,  # Can be computed from volume data
                "bbands_width": 2.0,
                "entry_price": sig_dict.get("close", 100.0),
            }
            trades.append(trade)
        
        print(f"[OK] Loaded {len(trades)} trades from {csv_path}")
        return trades
    
    except Exception as e:
        print(f"[ERROR] Failed to load trades: {e}")
        return generate_synthetic_trades(n=100)


def generate_synthetic_trades(n: int = 100) -> list[dict]:
    """
    Generate synthetic trades for testing.
    
    Args:
        n: Number of trades
        
    Returns:
        List of trade dicts
    """
    trades = []
    base_price = 100.0
    
    for i in range(n):
        price = base_price + np.random.randn() * 5
        trades.append({
            "symbol": f"SYN_{i}",
            "time": f"2026-01-{(i % 28) + 1:02d}",
            "close": price,
            "high": price + 1,
            "low": price - 1,
            "volume": 1000 + np.random.randint(-100, 100),
            "rsi": 50 + np.random.randn() * 20,
            "macd_hist": np.random.randn() * 0.01,
            "atr": 1.0 + np.random.rand(),
            "adx": 20 + np.random.randn() * 15,
            "meta_confidence": np.random.rand() * 0.5 + 0.25,
            "regime": np.random.choice(["STRONG_TREND", "WEAK_TREND", "COMPRESSION", "BREAKOUT"]),
            "fear_greed": np.random.randn() * 50,
            "volume_ratio": np.random.rand() * 2 + 0.5,
            "bbands_width": np.random.rand() * 2 + 1.5,
            "entry_price": price,
        })
    
    return trades


def train_agent(
    algorithm: str,
    trades: list[dict],
    total_timesteps: int = 100000,
    learning_rate: float = 3e-4,
    eval_frequency: int = 10000,
    n_eval_episodes: int = 10,
    save_dir: str = "logs/rl_models",
) -> Tuple[str, Dict]:
    """
    Train an RL agent.
    
    Args:
        algorithm: 'ppo', 'dqn', or 'a2c'
        trades: List of trade dicts
        total_timesteps: Total training steps
        learning_rate: Learning rate
        eval_frequency: Eval every N steps
        n_eval_episodes: Number of eval episodes
        save_dir: Where to save models
        
    Returns:
        (model_path, metrics_dict)
    """
    os.makedirs(save_dir, exist_ok=True)
    
    # Create environment
    env = MultiTradeExitEnv(
        trades=trades,
        config={
            "max_episode_length": 50,
            "reward_scale": 1.0,
            "drawdown_penalty": 0.5,
            "sharpe_bonus": 0.2,
        },
        trades_per_episode=5
    )
    
    # Create eval environment
    eval_env = MultiTradeExitEnv(
        trades=trades,
        config={
            "max_episode_length": 50,
            "reward_scale": 1.0,
            "drawdown_penalty": 0.5,
            "sharpe_bonus": 0.2,
        },
        trades_per_episode=5
    )
    
    # Create model
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = os.path.join(save_dir, f"rl_exit_{algorithm}_{timestamp}")
    
    print(f"\n[RL] Training {algorithm.upper()} agent...")
    print(f"  Total timesteps: {total_timesteps:,}")
    print(f"  Learning rate: {learning_rate}")
    print(f"  Saving to: {model_path}")
    
    try:
        if algorithm.lower() == "ppo":
            model = PPO(
                "MlpPolicy",
                env,
                learning_rate=learning_rate,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                verbose=1,
            )
        
        elif algorithm.lower() == "dqn":
            model = DQN(
                "MlpPolicy",
                env,
                learning_rate=learning_rate,
                buffer_size=100000,
                learning_starts=10000,
                target_update_interval=10000,
                verbose=1,
            )
        
        elif algorithm.lower() == "a2c":
            model = A2C(
                "MlpPolicy",
                env,
                learning_rate=learning_rate,
                verbose=1,
            )
        
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        
        # Callbacks
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=save_dir,
            log_path=save_dir,
            eval_freq=eval_frequency,
            n_eval_episodes=n_eval_episodes,
            verbose=1,
        )
        
        # Train
        model.learn(total_timesteps=total_timesteps, callback=eval_callback)
        
        # Save final model
        model.save(model_path)
        print(f"[OK] Model saved to {model_path}")
        
        # Evaluate
        mean_reward, std_reward = evaluate_policy(
            model, eval_env, n_eval_episodes=n_eval_episodes
        )
        
        metrics = {
            "algorithm": algorithm,
            "total_timesteps": total_timesteps,
            "learning_rate": learning_rate,
            "mean_reward": float(mean_reward),
            "std_reward": float(std_reward),
            "timestamp": timestamp,
            "model_path": model_path,
        }
        
        return model_path, metrics
    
    finally:
        env.close()
        eval_env.close()


def compare_agents(
    agent_paths: Dict[str, str],
    trades: list[dict],
    n_episodes: int = 20,
) -> Dict:
    """
    Compare multiple trained agents on the same test set.
    
    Args:
        agent_paths: Dict of {algorithm: model_path}
        trades: Test trades
        n_episodes: Number of evaluation episodes
        
    Returns:
        Comparison results dict
    """
    print("\n[COMPARE] Evaluating agents...")
    
    results = {}
    
    for algo, path in agent_paths.items():
        env = MultiTradeExitEnv(
            trades=trades,
            config={
                "max_episode_length": 50,
                "reward_scale": 1.0,
                "drawdown_penalty": 0.5,
                "sharpe_bonus": 0.2,
            },
            trades_per_episode=5
        )
        
        try:
            # Load model
            if algo.lower() == "ppo":
                model = PPO.load(path, env=env)
            elif algo.lower() == "dqn":
                model = DQN.load(path, env=env)
            elif algo.lower() == "a2c":
                model = A2C.load(path, env=env)
            else:
                continue
            
            # Evaluate
            mean_reward, std_reward = evaluate_policy(
                model, env, n_eval_episodes=n_episodes
            )
            
            results[algo] = {
                "mean_reward": float(mean_reward),
                "std_reward": float(std_reward),
                "model_path": path,
            }
            
            print(f"  {algo.upper():>5}: reward={mean_reward:.4f} ± {std_reward:.4f}")
        
        except Exception as e:
            print(f"  {algo.upper():>5}: [ERROR] {e}")
        
        finally:
            env.close()
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Train RL Exit Managers")
    parser.add_argument("--algo", type=str, default="ppo", choices=["ppo", "dqn", "a2c", "all"],
                        help="Algorithm to train")
    parser.add_argument("--train", action="store_true", help="Train models")
    parser.add_argument("--compare", action="store_true", help="Compare trained models")
    parser.add_argument("--steps", type=int, default=100000, help="Total training steps")
    parser.add_argument("--n-trades", type=int, default=200, help="Number of trades to use")
    
    args = parser.parse_args()
    
    # Load trade data
    trades = load_trade_data()
    if len(trades) < args.n_trades:
        print(f"[WARN] Only {len(trades)} trades available, using all")
    else:
        trades = trades[:args.n_trades]
    
    # Train
    if args.train:
        results_file = "logs/rl_training_results.json"
        results = {}
        
        if args.algo == "all":
            algos = ["ppo", "dqn", "a2c"]
        else:
            algos = [args.algo]
        
        for algo in algos:
            model_path, metrics = train_agent(
                algorithm=algo,
                trades=trades,
                total_timesteps=args.steps,
            )
            results[algo] = metrics
        
        # Save results
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[OK] Training results saved to {results_file}")
    
    # Compare
    if args.compare:
        agent_paths = {
            "ppo": "logs/rl_models/rl_exit_ppo",
            "dqn": "logs/rl_models/rl_exit_dqn",
            "a2c": "logs/rl_models/rl_exit_a2c",
        }
        
        # Filter to existing paths
        agent_paths = {k: v for k, v in agent_paths.items() if os.path.exists(f"{v}.zip")}
        
        if not agent_paths:
            print("[WARN] No trained models found. Run with --train first.")
            return
        
        comparison = compare_agents(agent_paths, trades, n_episodes=20)
        
        # Save comparison
        with open("logs/rl_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2)
        print(f"\n[OK] Comparison saved to logs/rl_comparison.json")


if __name__ == "__main__":
    main()
