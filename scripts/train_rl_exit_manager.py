#!/usr/bin/env python3
"""
Train RL Exit Managers using Stable-Baselines3

Algorithms:
- PPO (Proximal Policy Optimization)
- DQN (Deep Q-Network)
- A2C (Advantage Actor-Critic)

Usage:
    python train_rl_exit_manager.py --algo ppo --train --steps 500000
    python train_rl_exit_manager.py --algo dqn --train --steps 500000
    python train_rl_exit_manager.py --algo a2c --train --steps 500000
    python train_rl_exit_manager.py --algo ppo --train --steps 500000 --device cuda
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import glob
import json
import argparse
import pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from stable_baselines3 import DQN, A2C
from sb3_contrib import RecurrentPPO
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.callbacks import EvalCallback, BaseCallback, CallbackList
from stable_baselines3.common.monitor import Monitor

from btc_scraper.ml_engine.rl_trading_env import TradeExitEnv, MultiTradeExitEnv, load_and_prepare_candles
from btc_scraper.ml_engine.timegan import compute_indicators


SYNTHETIC_COIN = "SYN"


class CurriculumCallback(BaseCallback):
    """
    Callback to switch environment curriculum phase from 'easy' to 'full'
    after a specific number of training timesteps.
    """
    def __init__(self, switch_step: int = 150000, verbose: int = 1):
        super().__init__(verbose)
        self.switch_step = switch_step
        self.switched = False
        
    def _on_step(self) -> bool:
        if not self.switched and self.num_timesteps >= self.switch_step:
            self.switched = True
            if self.verbose > 0:
                print(f"\n[Curriculum] Switch step reached ({self.num_timesteps} >= {self.switch_step}).")
                print("[Curriculum] Switching environment to FULL dataset...")
            
            if self.training_env is not None:
                if hasattr(self.training_env, "env_method"):
                    self.training_env.env_method("set_curriculum_phase", "full")
                elif hasattr(self.training_env, "set_curriculum_phase"):
                    self.training_env.set_curriculum_phase("full")
        return True


def load_trade_data(csv_path: str = "logs/adaptive_signals_v2.json") -> list[dict]:
    """
    Load historical trade data from adaptive_signals_v2.json.
    """
    if not os.path.exists(csv_path):
        print(f"[WARN] File not found: {csv_path}")
        fallback_path = "logs/adaptive_signals.json"
        if os.path.exists(fallback_path):
            print(f"[INFO] Falling back to {fallback_path}")
            csv_path = fallback_path
        else:
            return generate_synthetic_trades(n=100)
            
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            signals = json.load(f)
            
        trades = []
        for sig_dict in signals:
            trade = {
                "coin": sig_dict.get("coin", "BTC").upper(),
                "entry_time": sig_dict.get("entry_time", sig_dict.get("time", "")),
                "signal_raw": sig_dict.get("signal_raw", sig_dict.get("signal", "BUY")),
                "meta_confidence": sig_dict.get("meta_confidence", 0.5),
            }
            trades.append(trade)
            
        print(f"[OK] Loaded {len(trades)} trades from {csv_path}")
        return trades
    except Exception as e:
        print(f"[ERROR] Failed to load trades: {e}")
        return generate_synthetic_trades(n=100)


def generate_synthetic_trades(n: int = 100) -> list[dict]:
    """Generate synthetic trades for fallback testing."""
    trades = []
    for i in range(n):
        trades.append({
            "coin": "SYN_BTC",
            "entry_time": "2026-01-01 00:00",
            "signal_raw": "BUY",
            "meta_confidence": 0.5,
        })
    return trades


def load_synthetic_training_data(
    candle_path: str = "data/rl_synthetic_candles.pkl",
    max_sequences: int | None = 5000,
    max_episode_length: int = 50,
    coin: str = SYNTHETIC_COIN,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Load TimeGAN candles and convert them into RL env candles + entry trades.

    The Stage 4/5 generator stores real-scale OHLCV arrays in
    `data/rl_synthetic_candles.pkl`. The training env needs a long candle list
    and trade entry timestamps, so this stitches sequences into one synthetic
    market series and creates evenly spaced BUY entries.
    """
    if not candle_path or not os.path.exists(candle_path):
        return {}, []

    from btc_scraper.ml_engine.governed_artifact_loader import load_trusted_pickle
    data = load_trusted_pickle(candle_path, approved_root=Path(candle_path).resolve().parent)

    sequences = data.get("sequences") if isinstance(data, dict) else data
    sequences = np.asarray(sequences, dtype=np.float32)
    if sequences.ndim != 3 or sequences.shape[2] != 5:
        raise ValueError(f"Expected synthetic sequences shape (N, T, 5), got {sequences.shape}")

    if max_sequences is not None and max_sequences > 0:
        sequences = sequences[:max_sequences]

    if sequences.size == 0:
        return {}, []

    seq_len = int(sequences.shape[1])
    flat = sequences.reshape(-1, 5).astype(np.float32)
    indicators = compute_indicators(flat[np.newaxis, :, :], rsi_period=14, atr_period=14)
    rsi = indicators["rsi_14"][0]
    atr = indicators["atr_14"][0]

    start = pd.Timestamp("2026-01-01 00:00")
    candles: list[dict] = []
    for idx, row in enumerate(flat):
        o, h, l, c, v = map(float, row)
        high = max(h, o, c)
        low = min(l, o, c)
        candles.append({
            "time": (start + pd.Timedelta(minutes=15 * idx)).strftime("%Y-%m-%d %H:%M"),
            "open": o,
            "high": high,
            "low": low,
            "close": c,
            "volume": max(0.0, v),
            "rsi": float(rsi[idx]) if np.isfinite(rsi[idx]) else 50.0,
            "macd_hist": 0.0,
            "atr": float(atr[idx]) if np.isfinite(atr[idx]) else max(1e-8, high - low),
            "atr_pct": (float(atr[idx]) / c * 100.0) if np.isfinite(atr[idx]) and c > 0 else 1.0,
            "adx": 20.0,
            "regime": "SYNTHETIC",
            "fear_greed": 50.0,
            "volume_ratio": 1.0,
            "bb_width_pct": 2.0,
            "is_warmup": 0,
        })

    stride = max(1, min(seq_len, max_episode_length))
    trades = []
    last_entry = max(0, len(candles) - max_episode_length - 1)
    for entry_idx in range(0, last_entry, stride):
        trades.append({
            "coin": coin,
            "entry_time": candles[entry_idx]["time"],
            "signal_raw": "BUY",
            "meta_confidence": 0.5,
            "source": "timegan",
        })

    print(
        f"[OK] Loaded TimeGAN curriculum data: {len(candles):,} candles, "
        f"{len(trades):,} trades from {candle_path}"
    )
    return {coin: candles}, trades


def _apply_synthetic_curriculum(env: MultiTradeExitEnv, synthetic_coin: str = SYNTHETIC_COIN) -> None:
    synthetic_coin = synthetic_coin.upper()
    synthetic_trades = [t for t in env.valid_trades if t.get("coin") == synthetic_coin]
    if synthetic_trades:
        env.easy_trades = synthetic_trades
        env.active_trades = env.easy_trades
        env.curriculum_phase = "easy"
        print(f"[RL Env] Synthetic curriculum phase enabled: {len(env.easy_trades)} synthetic trades")


def _get_default_device() -> str:
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def train_agent(
    algorithm: str,
    trades: list[dict],
    total_timesteps: int = 500000,
    learning_rate: float = 3e-4,
    eval_frequency: int = 20000,
    n_eval_episodes: int = 20,
    save_dir: str = "logs/rl_models",
    no_warm_start: bool = False,
    device: str = "auto",
    synthetic_candle_cache: dict[str, list[dict]] | None = None,
    synthetic_trades: list[dict] | None = None,
) -> Tuple[str, Dict]:
    """
    Train an RL agent.
    """
    os.makedirs(save_dir, exist_ok=True)
    
    # Check for previous model (Warm-start)
    latest_model = None
    if not no_warm_start:
        pattern = os.path.join(save_dir, f"rl_exit_{algorithm.lower()}_*.zip")
        models = glob.glob(pattern)
        if models:
            latest_model = max(models, key=os.path.getctime)
            
    max_episode_length = 50
    env_config = {
        "max_episode_length": max_episode_length,
        "reward_scale": 1.0,
        "drawdown_penalty": 0.5,
        "sharpe_bonus": 0.2,
    }

    previous_candle_cache = TradeExitEnv._COIN_CANDLES_CACHE
    using_synthetic = bool(synthetic_candle_cache and synthetic_trades)
    training_trades = list(trades)
    if using_synthetic:
        target_coins = sorted({t.get("coin", "BTC").upper() for t in trades})
        historical_cache = load_and_prepare_candles(
            data_dir="data/historical_18m",
            sentiment_file="logs/sentiment_history.json",
            coins=target_coins,
        )
        TradeExitEnv._COIN_CANDLES_CACHE = {**historical_cache, **synthetic_candle_cache}
        training_trades = list(synthetic_trades or []) + training_trades
        print(
            f"[RL] Training path includes TimeGAN data: "
            f"{len(synthetic_trades or []):,} synthetic trades + {len(trades):,} historical trades"
        )
    
    # Create model path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = os.path.join(save_dir, f"rl_exit_{algorithm}_{timestamp}")
    
    if device == "auto":
        device = _get_default_device()
    elif device == "cuda" and not torch.cuda.is_available():
        print("[WARN] CUDA requested but not available. Falling back to CPU.")
        device = "cpu"
    print(f"\n[RL] Training {algorithm.upper()} agent...")
    print(f"  Total timesteps: {total_timesteps:,}")
    print(f"  Learning rate: {learning_rate}")
    print(f"  Device: {device}")
    print(f"  Saving to: {model_path}")
    
    env = None
    _eval_env_base = None
    try:
        # Create environments after optional synthetic cache injection.
        env = MultiTradeExitEnv(
            trades=training_trades,
            config=env_config,
            trades_per_episode=5
        )
        if using_synthetic:
            _apply_synthetic_curriculum(env)

        _eval_env_base = MultiTradeExitEnv(
            trades=training_trades,
            config=env_config,
            trades_per_episode=5
        )

        # Ensure eval_env starts with full phase for realistic evaluations.
        _eval_env_base.set_curriculum_phase("full")

        # Wrap with Monitor for proper evaluation stats.
        eval_env = Monitor(_eval_env_base)
        from btc_scraper.ml_engine.governed_artifact_loader import load_offline_rl_artifact
        rl_root = Path("logs/rl_models")

        if algorithm.lower() == "ppo":
            if latest_model:
                print(f"[RL] Warm-starting RecurrentPPO from {os.path.basename(latest_model)}...")
                model = load_offline_rl_artifact(
                    latest_model, model_class=RecurrentPPO, approved_root=rl_root,
                    env=env, device=device, custom_objects={"learning_rate": learning_rate},
                )
            else:
                model = RecurrentPPO(
                    "MlpLstmPolicy",
                    env,
                    learning_rate=learning_rate,
                    n_steps=2048,
                    batch_size=64,
                    n_epochs=10,
                    ent_coef=0.02,  # Higher entropy encourages exploration of exit strategies
                    vf_coef=0.5,
                    gamma=0.99,
                    gae_lambda=0.95,
                    verbose=1,
                    device=device,
                )
        
        elif algorithm.lower() == "dqn":
            if latest_model:
                print(f"[RL] Warm-starting DQN from {os.path.basename(latest_model)}...")
                model = load_offline_rl_artifact(latest_model, model_class=DQN, approved_root=rl_root, env=env, device=device, custom_objects={"learning_rate": learning_rate})
            else:
                model = DQN(
                    "MlpPolicy",
                    env,
                    learning_rate=learning_rate,
                    buffer_size=100000,
                    learning_starts=10000,
                    target_update_interval=10000,
                    verbose=1,
                    device=device,
                )
        
        elif algorithm.lower() == "a2c":
            if latest_model:
                print(f"[RL] Warm-starting A2C from {os.path.basename(latest_model)}...")
                model = load_offline_rl_artifact(latest_model, model_class=A2C, approved_root=rl_root, env=env, device=device, custom_objects={"learning_rate": learning_rate})
            else:
                model = A2C(
                    "MlpPolicy",
                    env,
                    learning_rate=learning_rate,
                    verbose=1,
                    device=device,
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
        
        # Switch phase at 30% of total_timesteps
        switch_step = int(total_timesteps * 0.3)
        curriculum_callback = CurriculumCallback(switch_step=switch_step, verbose=1)
        
        callback = CallbackList([eval_callback, curriculum_callback])
        
        # Train
        model.learn(total_timesteps=total_timesteps, callback=callback)
        
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
            "synthetic_curriculum": using_synthetic,
            "synthetic_trades": len(synthetic_trades or []),
        }
        
        return model_path, metrics
        
    finally:
        if env is not None:
            env.close()
        if _eval_env_base is not None:
            _eval_env_base.close()
        if using_synthetic:
            TradeExitEnv._COIN_CANDLES_CACHE = previous_candle_cache


def compare_agents(
    agent_paths: Dict[str, str],
    trades: list[dict],
    n_episodes: int = 30,
    device: str = "auto",
) -> Dict:
    """Compare multiple trained agents."""
    print("\n[COMPARE] Evaluating agents...")
    
    results = {}
    if device == "auto":
        device = _get_default_device()
    elif device == "cuda" and not torch.cuda.is_available():
        print("[WARN] CUDA requested for evaluation but not available. Falling back to CPU.")
        device = "cpu"

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
        env.set_curriculum_phase("full")
        
        try:
            from btc_scraper.ml_engine.governed_artifact_loader import load_offline_rl_artifact
            rl_root = Path("logs/rl_models")
            if algo.lower() == "ppo":
                model = load_offline_rl_artifact(path, model_class=RecurrentPPO, approved_root=rl_root, env=env, device=device)
            elif algo.lower() == "dqn":
                model = load_offline_rl_artifact(path, model_class=DQN, approved_root=rl_root, env=env, device=device)
            elif algo.lower() == "a2c":
                model = load_offline_rl_artifact(path, model_class=A2C, approved_root=rl_root, env=env, device=device)
            else:
                continue
                
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
    parser.add_argument("--steps", type=int, default=500000, help="Total training steps")
    parser.add_argument("--n-trades", type=int, default=20000, help="Number of trades to use")
    parser.add_argument("--no-warm-start", action="store_true", help="Train from scratch")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"],
                        help="Device for model training/evaluation")
    parser.add_argument("--synthetic-candles", type=str, default="data/rl_synthetic_candles.pkl",
                        help="TimeGAN candle pickle used for synthetic curriculum")
    parser.add_argument("--synthetic-sequences", type=int, default=5000,
                        help="Max TimeGAN sequences to load for curriculum; use 0 for all")
    parser.add_argument("--no-synthetic-curriculum", action="store_true",
                        help="Disable automatic TimeGAN curriculum even if rl_synthetic_candles.pkl exists")
    
    args = parser.parse_args()
    
    # Load trade data
    trades = load_trade_data()
    if len(trades) < args.n_trades:
        print(f"[WARN] Only {len(trades)} trades available, using all")
    else:
        trades = trades[:args.n_trades]

    # Train
    if args.train:
        synthetic_cache = {}
        synthetic_trades = []
        if not args.no_synthetic_curriculum:
            max_sequences = None if args.synthetic_sequences == 0 else args.synthetic_sequences
            synthetic_cache, synthetic_trades = load_synthetic_training_data(
                candle_path=args.synthetic_candles,
                max_sequences=max_sequences,
                max_episode_length=50,
            )
            if not synthetic_trades:
                print(f"[INFO] No TimeGAN curriculum data loaded from {args.synthetic_candles}; using historical path only.")

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
                no_warm_start=args.no_warm_start,
                device=args.device,
                synthetic_candle_cache=synthetic_cache,
                synthetic_trades=synthetic_trades,
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
            
        comparison = compare_agents(agent_paths, trades, n_episodes=30, device=args.device)
        
        with open("logs/rl_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2)
        print(f"\n[OK] Comparison saved to logs/rl_comparison.json")


if __name__ == "__main__":
    main()
