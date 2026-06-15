"""
RL Trading Environment for Exit Management (Phase 4)

Gymnasium-based environment for learning optimal exit strategies.
State: market indicators + position state
Actions: HOLD, PARTIAL_CLOSE_50, MOVE_SL_TO_BREAKEVEN, TAKE_PROFIT, EXIT
Reward: PnL - drawdown_penalty + sharpe_bonus
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Dict, Tuple, Any


class TradeExitEnv(gym.Env):
    """
    Gymnasium environment for trading exit management.
    
    State Space (10 features):
    - rsi (0-100) normalized to (-1, 1)
    - macd_hist (-inf, inf) normalized to (-1, 1)
    - atr (0, inf) normalized to (0, 1)
    - adx (0-100) normalized to (0, 1)
    - meta_confidence (0-1)
    - regime (0-7) one-hot encoded to 8 features
    - pnl_pct (-100, 100) normalized to (-1, 1)
    - hold_time (0-500 bars) normalized to (0, 1)
    - fear_greed (-100, 100) normalized to (-1, 1)
    - volume_ratio (0, 10) normalized to (0, 1)
    Total: 10 + 8 regime features = 18 features
    
    Action Space (5 discrete actions):
    0: HOLD
    1: PARTIAL_CLOSE_50
    2: MOVE_SL_TO_BREAKEVEN
    3: TAKE_PROFIT
    4: EXIT
    
    Reward:
    - Base: PnL
    - Penalty: -drawdown if underwater
    - Bonus: +sharpe if exit at peak
    """
    
    metadata = {"render_modes": ["human"]}
    
    def __init__(self, trades: list[dict], config: dict = None):
        """
        Initialize environment.
        
        Args:
            trades: List of trade dicts with OHLCV + indicators
            config: Config dict with reward params, episode length, etc.
        """
        super().__init__()
        
        self.trades = trades
        self.config = config or {}
        
        # Environment parameters
        self.max_episode_length = self.config.get("max_episode_length", 100)
        self.reward_scale = self.config.get("reward_scale", 1.0)
        self.drawdown_penalty = self.config.get("drawdown_penalty", 0.5)
        self.sharpe_bonus = self.config.get("sharpe_bonus", 0.2)
        
        # State space: 18 continuous features
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(18,), dtype=np.float32
        )
        
        # Action space: 5 discrete actions
        self.action_space = spaces.Discrete(5)
        
        # Episode state
        self.current_step = 0
        self.current_trade_idx = 0
        self.entry_price = 0.0
        self.entry_pnl = 0.0
        self.max_pnl = 0.0
        self.episode_rewards = []
        self.episode_done_reason = ""
        
        # Regime names for internal tracking
        self.regime_names = [
            "STRONG_TREND", "WEAK_TREND", "COMPRESSION",
            "BREAKOUT", "MEAN_REVERSION", "PANIC_SELL",
            "LOW_LIQUIDITY", "PUMP_RISK"
        ]
    
    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        """Reset environment to initial state."""
        super().reset(seed=seed)
        
        self.current_step = 0
        self.current_trade_idx = self.np_random.integers(0, len(self.trades))
        self.episode_rewards = []
        self.episode_done_reason = ""
        
        # Get initial trade
        trade = self.trades[self.current_trade_idx]
        self.entry_price = trade.get("entry_price", trade.get("close", 100.0))
        self.entry_pnl = 0.0
        self.max_pnl = 0.0
        
        obs = self._get_observation(trade, 0)
        info = {}
        
        return obs, info
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute one step.
        
        Args:
            action: Action index (0-4)
            
        Returns:
            (observation, reward, terminated, truncated, info)
        """
        trade = self.trades[self.current_trade_idx]
        current_price = trade.get("close", 100.0)
        
        # Compute PnL
        current_pnl = ((current_price - self.entry_price) / self.entry_price) * 100
        self.max_pnl = max(self.max_pnl, current_pnl)
        
        reward = 0.0
        terminated = False
        done_reason = ""
        
        # Action-based logic
        if action == 0:  # HOLD
            reward = 0.01  # Small reward for staying in
        
        elif action == 1:  # PARTIAL_CLOSE_50
            # Realize 50% at current price
            partial_pnl = current_pnl * 0.5
            reward = partial_pnl * self.reward_scale
            terminated = True
            done_reason = "PARTIAL_CLOSE_50"
        
        elif action == 2:  # MOVE_SL_TO_BREAKEVEN
            # Safe move but locks profit
            if current_pnl > 0:
                reward = 0.05  # Small bonus for locking gains
            else:
                reward = -0.02  # Penalty for moving SL when losing
        
        elif action == 3:  # TAKE_PROFIT
            # Fully exit at current price
            final_pnl = current_pnl
            reward = final_pnl * self.reward_scale
            
            # Bonus if exiting near peak
            if final_pnl > self.max_pnl * 0.9:  # Within 10% of peak
                reward += self.sharpe_bonus
            
            terminated = True
            done_reason = "TAKE_PROFIT"
        
        elif action == 4:  # EXIT
            # Emergency exit
            final_pnl = current_pnl
            reward = final_pnl * self.reward_scale
            
            # Penalty for exiting underwater
            if final_pnl < 0:
                reward -= self.drawdown_penalty
            
            terminated = True
            done_reason = "EXIT"
        
        self.current_step += 1
        self.episode_rewards.append(reward)
        
        # Truncate if max episode length reached
        truncated = self.current_step >= self.max_episode_length
        if truncated:
            done_reason = "MAX_STEPS"
        
        # Get next observation
        next_obs = self._get_observation(trade, self.current_step)
        
        info = {
            "current_pnl": current_pnl,
            "max_pnl": self.max_pnl,
            "done_reason": done_reason,
            "step": self.current_step,
        }
        
        return next_obs, reward, terminated, truncated, info
    
    def _get_observation(self, trade: dict, step: int) -> np.ndarray:
        """
        Compute observation vector (18 features).
        
        Args:
            trade: Trade dict with indicators
            step: Current step in episode
            
        Returns:
            Normalized observation array (18,)
        """
        obs = np.zeros(18, dtype=np.float32)
        
        # Feature 0: RSI (0-100 -> -1 to 1)
        rsi = float(trade.get("rsi", 50.0))
        obs[0] = (rsi - 50) / 50.0
        
        # Feature 1: MACD Hist (normalize by bounds)
        macd_hist = float(trade.get("macd_hist", 0.0))
        obs[1] = np.tanh(macd_hist / 0.01)  # Normalize with reasonable bound
        
        # Feature 2: ATR (0, inf -> 0, 1)
        atr = float(trade.get("atr", 1.0))
        close = float(trade.get("close", 100.0))
        atr_pct = (atr / close) * 100 if close > 0 else 0.0
        obs[2] = np.tanh(atr_pct / 2.0)  # Typical ATR is 1-3% of price
        
        # Feature 3: ADX (0-100 -> 0, 1)
        adx = float(trade.get("adx", 20.0))
        obs[3] = adx / 100.0
        
        # Feature 4: Meta Confidence (0-1)
        meta_conf = trade.get("meta_confidence", 0.5)
        if isinstance(meta_conf, str):
            meta_conf = 0.5  # Default if string value
        obs[4] = float(meta_conf)
        
        # Features 5-12: Regime one-hot (8 values)
        regime = str(trade.get("regime", "STRONG_TREND"))
        regime_idx = self.regime_names.index(regime) if regime in self.regime_names else 0
        obs[5 + regime_idx] = 1.0
        
        # Feature 13: PnL % (-100, 100 -> -1, 1)
        current_price = float(trade.get("close", 100.0))
        current_pnl = ((current_price - self.entry_price) / self.entry_price) * 100 if self.entry_price > 0 else 0.0
        obs[13] = np.tanh(current_pnl / 50.0)
        
        # Feature 14: Hold time (bars, 0-500 -> 0, 1)
        hold_time = min(step, self.max_episode_length)
        obs[14] = hold_time / self.max_episode_length
        
        # Feature 15: Fear & Greed (-100, 100 -> -1, 1)
        fear_greed = float(trade.get("fear_greed", 0.0))
        obs[15] = fear_greed / 100.0
        
        # Feature 16: Volume Ratio (0, 10 -> 0, 1)
        vol_ratio = float(trade.get("volume_ratio", 1.0))
        obs[16] = np.tanh(vol_ratio / 5.0)
        
        # Feature 17: Spare/composite feature
        bbands_width = float(trade.get("bbands_width", 2.0))
        obs[17] = np.tanh((bbands_width - 2.0) / 2.0)
        
        return obs
    
    def render(self, mode="human"):
        """Render environment state."""
        if self.current_trade_idx < len(self.trades):
            trade = self.trades[self.current_trade_idx]
            print(f"Step: {self.current_step}, Trade: {trade.get('symbol', '?')}, "
                  f"Close: {trade.get('close', '?'):.2f}, Rewards: {np.sum(self.episode_rewards):.4f}")


class MultiTradeExitEnv(TradeExitEnv):
    """
    Extended environment that cycles through multiple trades per episode
    for better learning efficiency.
    """
    
    def __init__(self, trades: list[dict], config: dict = None, trades_per_episode: int = 5):
        """
        Initialize multi-trade environment.
        
        Args:
            trades: List of trade dicts
            config: Config dict
            trades_per_episode: Number of trades per episode
        """
        super().__init__(trades, config)
        self.trades_per_episode = trades_per_episode
        self.trades_completed = 0
    
    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        """Reset for next batch of trades."""
        super().reset(seed=seed, options=options)
        self.trades_completed = 0
        return self._get_observation(self.trades[self.current_trade_idx], 0), {}
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute step and auto-cycle trades when terminated.
        """
        obs, reward, terminated, truncated, info = super().step(action)
        
        # Auto-cycle to next trade if terminated
        if terminated:
            self.trades_completed += 1
            
            # Move to next trade or signal episode end
            if self.trades_completed < self.trades_per_episode:
                self.current_trade_idx = (self.current_trade_idx + 1) % len(self.trades)
                self.current_step = 0
                self.entry_price = self.trades[self.current_trade_idx].get("entry_price", 
                                                                             self.trades[self.current_trade_idx].get("close", 100.0))
                self.max_pnl = 0.0
                obs = self._get_observation(self.trades[self.current_trade_idx], 0)
                terminated = False  # Don't terminate yet
            else:
                terminated = True  # Episode done
                info["total_trades"] = self.trades_completed
                info["episode_reward"] = np.sum(self.episode_rewards)
        
        return obs, reward, terminated, truncated, info
