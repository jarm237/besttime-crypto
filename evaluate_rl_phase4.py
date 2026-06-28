"""
Phase 4: Reinforcement Learning Exit Manager - Evaluation & Backtest

Evaluate trained RL agents on historical data and compare against rule-based exit strategy.
Uses the TradeExitEnv with actual candle price data for meaningful comparison.
"""

import os
import json
import numpy as np
import torch
from pathlib import Path
from datetime import datetime

from stable_baselines3 import PPO, DQN, A2C

from btc_scraper.ml_engine.rl_trading_env import TradeExitEnv, MultiTradeExitEnv
from train_rl_exit_manager import load_trade_data


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_latest_rl_models() -> dict:
    """Find latest trained RL models."""
    rl_dir = Path("logs/rl_models")
    if not rl_dir.exists():
        return {}

    models = {}
    for algo in ["ppo", "dqn", "a2c"]:
        pattern = f"rl_exit_{algo}_*.zip"
        matches = sorted(rl_dir.glob(pattern))
        if matches:
            models[algo] = str(matches[-1])
            print(f"[OK] Found {algo.upper()} model: {matches[-1].name}")

    return models


def make_env(trades: list[dict]) -> MultiTradeExitEnv:
    """Create evaluation environment with full curriculum phase."""
    env = MultiTradeExitEnv(
        trades=trades,
        config={
            "max_episode_length": 50,
            "reward_scale": 1.0,
            "drawdown_penalty": 0.5,
            "sharpe_bonus": 0.2,
            "commission_fee": 0.001,
            "slippage_pct": 0.0005,
        },
        trades_per_episode=5,
    )
    env.set_curriculum_phase("full")
    return env


# ──────────────────────────────────────────────────────────────────────────────
# RL Agent Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _get_default_device() -> str:
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def evaluate_rl_agent(
    algo: str,
    model_path: str,
    trades: list[dict],
    n_episodes: int = 50,
    device: str = "auto",
) -> dict:
    """Evaluate a single RL agent over n_episodes and collect per-episode metrics."""
    if device == "auto":
        device = _get_default_device()
    elif device == "cuda" and not torch.cuda.is_available():
        print("[WARN] CUDA requested but not available. Falling back to CPU.")
        device = "cpu"

    print(f"\n[EVAL] Evaluating {algo.upper()} agent ({n_episodes} episodes) on device={device}...")

    env = make_env(trades)

    try:
        if algo.lower() == "ppo":
            model = PPO.load(model_path, env=env, device=device)
        elif algo.lower() == "dqn":
            model = DQN.load(model_path, env=env, device=device)
        elif algo.lower() == "a2c":
            model = A2C.load(model_path, env=env, device=device)
        else:
            raise ValueError(f"Unknown algorithm: {algo}")
    except Exception as e:
        print(f"  [ERROR] Could not load {algo}: {e}")
        env.close()
        return {}

    episode_rewards = []
    episode_pnls = []
    action_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    action_names = {0: "HOLD", 1: "PARTIAL_CLOSE_50", 2: "MOVE_SL_BE", 3: "TAKE_PROFIT", 4: "EXIT", 5: "TRAILING_SL_ATR"}
    done_reasons = {}

    for ep in range(n_episodes):
        obs, _ = env.reset()
        terminated = False
        ep_reward = 0.0
        ep_pnl = 0.0

        while not terminated:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            ep_reward += reward
            action_counts[int(action)] += 1
            ep_pnl = info.get("current_pnl", ep_pnl)
            reason = info.get("done_reason", "")
            if reason:
                done_reasons[reason] = done_reasons.get(reason, 0) + 1
            if truncated:
                terminated = True

        episode_rewards.append(ep_reward)
        episode_pnls.append(ep_pnl)

    env.close()

    mean_reward = float(np.mean(episode_rewards))
    std_reward = float(np.std(episode_rewards))
    mean_pnl = float(np.mean(episode_pnls))

    print(f"  Mean Reward : {mean_reward:.4f} ± {std_reward:.4f}")
    print(f"  Mean PnL    : {mean_pnl:.4f}%")
    print(f"  Action dist : {', '.join(f'{action_names[k]}={v}' for k, v in action_counts.items())}")
    print(f"  Done reasons: {done_reasons}")

    return {
        "mean_reward": mean_reward,
        "std_reward": std_reward,
        "mean_pnl": mean_pnl,
        "action_distribution": {action_names[k]: v for k, v in action_counts.items()},
        "done_reasons": done_reasons,
        "n_episodes": n_episodes,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Rule-Based Baseline Evaluation (using TradeExitEnv)
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_rule_based(trades: list[dict], n_episodes: int = 50) -> dict:
    """
    Evaluate a simple rule-based exit strategy using the same TradeExitEnv:
    - HOLD (action=0) until TP or SL is hit (or max steps).
    This is the most honest baseline — just hold and let TP/SL rules decide.
    """
    print(f"\n[EVAL] Evaluating Rule-Based (Hold-until-TP/SL) strategy ({n_episodes} episodes)...")

    env = make_env(trades)

    episode_rewards = []
    episode_pnls = []
    done_reasons = {}

    for ep in range(n_episodes):
        obs, _ = env.reset()
        terminated = False
        ep_reward = 0.0
        ep_pnl = 0.0

        while not terminated:
            action = 0  # Always HOLD
            obs, reward, terminated, truncated, info = env.step(action)
            ep_reward += reward
            ep_pnl = info.get("current_pnl", ep_pnl)
            reason = info.get("done_reason", "")
            if reason:
                done_reasons[reason] = done_reasons.get(reason, 0) + 1
            if truncated:
                terminated = True

        episode_rewards.append(ep_reward)
        episode_pnls.append(ep_pnl)

    env.close()

    mean_reward = float(np.mean(episode_rewards))
    std_reward = float(np.std(episode_rewards))
    mean_pnl = float(np.mean(episode_pnls))
    total = sum(done_reasons.values())
    win_rate = done_reasons.get("TP_HIT", 0) / total if total > 0 else 0.0

    print(f"  Mean Reward : {mean_reward:.4f} ± {std_reward:.4f}")
    print(f"  Mean PnL    : {mean_pnl:.4f}%")
    print(f"  Win Rate (TP hit): {win_rate:.1%}")
    print(f"  Done reasons: {done_reasons}")

    return {
        "mean_reward": mean_reward,
        "std_reward": std_reward,
        "mean_pnl": mean_pnl,
        "win_rate": win_rate,
        "done_reasons": done_reasons,
        "n_episodes": n_episodes,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Report Generation
# ──────────────────────────────────────────────────────────────────────────────

def generate_phase_4_report(n_episodes: int = 50):
    """Generate comprehensive Phase 4 RL evaluation report."""

    print("\n" + "=" * 70)
    print("PHASE 4: RL EXIT MANAGER — EVALUATION REPORT")
    print("=" * 70)

    # Load trade data
    trades = load_trade_data()
    print(f"[OK] Loaded {len(trades)} trade signals for evaluation.")

    report = {
        "phase": 4,
        "title": "Reinforcement Learning Exit Manager — Phase 2 Optimized",
        "date": datetime.now().isoformat(),
        "n_eval_episodes": n_episodes,
        "environment": {
            "state_space": 18,
            "action_space": 6,
            "actions": ["HOLD", "PARTIAL_CLOSE_50", "MOVE_SL_TO_BREAKEVEN", "TAKE_PROFIT", "EXIT", "TRAILING_SL_ATR"],
            "episode_length": 50,
            "data_source": "data/historical_18m/ (real price candles)",
            "curriculum": "Easy → Full (Curriculum Learning)",
        },
        "training_results": {},
        "rl_agents": {},
        "rule_based": {},
        "comparison_summary": {},
    }

    # Load previous training results if available
    results_file = "logs/rl_training_results.json"
    if os.path.exists(results_file):
        with open(results_file) as f:
            report["training_results"] = json.load(f)

    # Rule-based baseline
    report["rule_based"] = evaluate_rule_based(trades, n_episodes=n_episodes)

    # RL agents
    models = load_latest_rl_models()
    if not models:
        print("\n[WARN] No trained RL models found in logs/rl_models/.")
        print("[WARN] Run training first: python train_rl_exit_manager.py --algo ppo --train --steps 500000")
    else:
        # Share candle cache — only load once
        TradeExitEnv._COIN_CANDLES_CACHE = None
        for algo, path in models.items():
            result = evaluate_rl_agent(algo, path, trades, n_episodes=n_episodes, device="auto")
            if result:
                report["rl_agents"][algo] = result

    # Comparison summary
    rb = report["rule_based"]
    best_algo = None
    best_reward = rb["mean_reward"]
    for algo, data in report["rl_agents"].items():
        if data["mean_reward"] > best_reward:
            best_reward = data["mean_reward"]
            best_algo = algo

    report["comparison_summary"] = {
        "best_agent": best_algo or "rule_based",
        "rule_based_mean_reward": rb["mean_reward"],
        "rule_based_win_rate": rb.get("win_rate", 0.0),
        "rl_improvements": {
            algo: {
                "delta_reward": data["mean_reward"] - rb["mean_reward"],
                "mean_reward": data["mean_reward"],
            }
            for algo, data in report["rl_agents"].items()
        },
    }

    # Save report
    os.makedirs("logs", exist_ok=True)
    report_file = "logs/phase_4_rl_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n[OK] Phase 4 report saved to {report_file}")
    return report


def print_phase_4_summary():
    """Print Phase 4 summary from saved report or generate fresh."""
    print("\n" + "=" * 70)
    print("PHASE 4: REINFORCEMENT LEARNING EXIT MANAGER - SUMMARY")
    print("=" * 70)

    print("\n[OK] Phase 2 Optimizations Applied:")
    print("  - Environment uses real historical 15m candle data from data/historical_18m/")
    print("  - indicators pre-computed via analyze_market() for all coins")
    print("  - TP/SL hit detection using candle high/low (realistic simulation)")
    print("  - Curriculum Learning: easy (STRONG_TREND) -> full dataset")
    print("  - PPO: ent_coef=0.01 for better exploration")
    print("  - MultiTradeExitEnv: 5 trades per episode for efficiency")

    print("\n[OK] State Space (18 features):")
    print("  RSI, MACD_hist, ATR%, ADX, meta_confidence")
    print("  regime (8 one-hot), PnL%, hold_time, fear_greed")
    print("  volume_ratio, bb_width_pct")

    print("\n[OK] Action Space (6 discrete):")
    print("  0=HOLD, 1=PARTIAL_CLOSE_50, 2=MOVE_SL_TO_BREAKEVEN, 3=TAKE_PROFIT, 4=EXIT, 5=TRAILING_SL_ATR")

    print("\n[OK] Training Results:")
    if os.path.exists("logs/rl_training_results.json"):
        with open("logs/rl_training_results.json") as f:
            results = json.load(f)
        for algo, metrics in results.items():
            print(f"  {algo.upper():>5}: mean_reward={metrics['mean_reward']:.4f} +/- {metrics['std_reward']:.4f}")
    else:
        print("  [INFO] No training results found. Run --train first.")

    print("\n[OK] Next Steps:")
    print("  - Integrate best RL agent into live trading system (main.py)")
    print("  - A/B test RL exit vs rule-based on real forward trades")
    print("  - Fine-tune reward function based on portfolio Sharpe ratio")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate RL Exit Managers - Phase 4")
    parser.add_argument("--episodes", type=int, default=50, help="Number of evaluation episodes")
    parser.add_argument("--summary-only", action="store_true", help="Only print summary, don't run full eval")
    args = parser.parse_args()

    if args.summary_only:
        print_phase_4_summary()
    else:
        report = generate_phase_4_report(n_episodes=args.episodes)
        print_phase_4_summary()
