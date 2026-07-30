"""
RL Trading Environment for Exit Management (Phase 4)

Gymnasium-based environment for learning optimal exit strategies.
State: market indicators + position state
Actions: HOLD, PARTIAL_CLOSE_50, MOVE_SL_TO_BREAKEVEN, TAKE_PROFIT, EXIT
Reward: step-to-step delta of net PnL after commission and slippage
"""

import os
from pathlib import Path
import csv
import glob
import json
import math
import pickle
from datetime import datetime
import numpy as np
from btc_scraper.regime.contract import model_regime_bucket
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Tuple, Any, List

from btc_scraper.analysis.core import analyze_market, calculate_tp_sl
from btc_scraper.ml_engine.timegan import postprocess_synthetic_sequences
from btc_scraper.ml_engine.timegan import OHLCVScaler
from datetime import timedelta
from btc_scraper.core.config import FRESH_TRAINING_DATA_DIR

RL_ENVIRONMENT_VERSION = "trade-exit-env-v2-no-cross-trade-state"
RL_OBSERVATION_SCHEMA_VERSION = "rl-exit-observation-v1-20f"
RL_REWARD_SCHEMA_VERSION = "rl-exit-reward-v2-net-pnl-delta-costed"


def load_sentiment_history(sentiment_file: str = "logs/sentiment_history.json") -> dict:
    """Load historical sentiment Fear & Greed values by date."""
    if not os.path.exists(sentiment_file):
        return {}
    try:
        with open(sentiment_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        sentiment_by_date = {}
        for k, v in raw.items():
            date_key = k[:10]  # "YYYY-MM-DD"
            if date_key not in sentiment_by_date:
                sentiment_by_date[date_key] = {
                    "score": float(v.get("score", 0.0)),
                    "raw_value": int(v.get("raw_value", 50)),
                    "label": str(v.get("label", "Neutral")),
                }
        return sentiment_by_date
    except Exception as e:
        print(f"[RL Environment] Error loading sentiment history: {e}")
        return {}


def load_and_prepare_candles(
    data_dir: str | None = None,
    sentiment_file: str = "logs/sentiment_history.json",
    coins: List[str] = None,
    cache_file: str = "data/rl_candle_cache.pkl",
) -> dict:
    """
    Load all 15m candle CSVs for target coins, run analyze_market ONCE per coin
    to populate indicators, and cache results.
    
    Uses a disk-level pickle cache so indicators are only computed once across
    all training runs. Delete data/rl_candle_cache.pkl to force recompute.
    """
    # ── Check disk cache first ──────────────────────────────────────────────
    if cache_file and os.path.exists(cache_file):
        try:
            print(f"[RL Environment] Loading indicator cache from {cache_file}...")
            from .governed_artifact_loader import load_trusted_pickle
            cached = load_trusted_pickle(cache_file)
            # Filter to requested coins if specified
            if coins:
                target = set(c.upper() for c in coins)
                cached = {k: v for k, v in cached.items() if k in target}
            if cached:
                print(f"[RL Environment] Cache hit: {list(cached.keys())} ({sum(len(v) for v in cached.values()):,} total candles)")
                return cached
        except Exception as e:
            print(f"[RL Environment] Cache load failed ({e}), recomputing...")

    sentiment_by_date = load_sentiment_history(sentiment_file)
    sorted_dates = sorted(sentiment_by_date.keys())
    
    # Target coins set
    target_coins = set(c.upper() for c in coins) if coins else None
    
    # Resolve data_dir default to fresh training data dir
    if not data_dir:
        if FRESH_TRAINING_DATA_DIR.is_absolute():
            data_dir = str(FRESH_TRAINING_DATA_DIR)
        else:
            data_dir = str(Path(__file__).resolve().parents[2] / FRESH_TRAINING_DATA_DIR)

    # Find matching CSV files
    csv_pattern = os.path.join(data_dir, "*_15m.csv")
    csv_files = glob.glob(csv_pattern)
    
    coin_files = {}
    for f in csv_files:
        parts = os.path.basename(f).split("_")
        if len(parts) >= 3:
            coin = parts[-2].upper()
            if target_coins and coin not in target_coins:
                continue
            if coin not in coin_files:
                coin_files[coin] = []
            coin_files[coin].append(f)
            
    coin_candles = {}
    
    # Temporarily mock sentiment module inside analyze_market to avoid DB/network issues
    import btc_scraper.core.sentiment as _sent_mod
    import btc_scraper.analysis.core as _analysis_core
    
    orig_get_sentiment = _sent_mod.get_market_sentiment
    orig_get_trend = _sent_mod.get_sentiment_trend
    orig_save_sentiment = _sent_mod._save_sentiment_to_history
    
    # Mock date context variable
    mock_date_ctx = "2026-01-01"
    
    def mock_get_market_sentiment():
        if mock_date_ctx in sentiment_by_date:
            return sentiment_by_date[mock_date_ctx]
        import bisect
        idx = bisect.bisect_right(sorted_dates, mock_date_ctx) - 1
        if idx >= 0:
            return sentiment_by_date[sorted_dates[idx]]
        return {"score": 0.0, "raw_value": 50, "label": "Neutral"}
        
    def mock_get_sentiment_trend(current_sentiment=None):
        return {
            "trend": "STABLE",
            "momentum": 0.0,
            "recovery_signal": False,
            "risk_signal": False,
        }
        
    _sent_mod.get_market_sentiment = mock_get_market_sentiment
    _sent_mod.get_sentiment_trend = mock_get_sentiment_trend
    _sent_mod._save_sentiment_to_history = lambda *a, **k: None
    
    _analysis_core.get_market_sentiment = mock_get_market_sentiment
    _analysis_core.get_sentiment_trend = mock_get_sentiment_trend
    _analysis_core._save_sentiment_to_history = lambda *a, **k: None
    
    try:
        for coin, files in coin_files.items():
            print(f"[RL Environment] Loading and calculating indicators for {coin}...")
            combined = []
            for path in files:
                with open(path, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        dt = datetime.strptime(row["time"], "%Y-%m-%d %H:%M")
                        combined.append({
                            "time": row["time"],
                            "time_dt": dt,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row["volume"]),
                            "is_warmup": int(row.get("is_warmup", 0)),
                        })
            
            if not combined:
                continue
                
            # Dedup and sort
            seen = set()
            dedup = []
            for c in combined:
                if c["time"] not in seen:
                    seen.add(c["time"])
                    dedup.append(c)
            dedup.sort(key=lambda x: x["time_dt"])
            
            # Run analyze_market in one pass
            if len(dedup) >= 220:
                mock_date_ctx = dedup[-1]["time"][:10]
                try:
                    analyze_market(dedup)
                except Exception as e:
                    print(f"[RL Environment] Warning: analyze_market failed on {coin}: {e}")
                    
                # Fill fear_greed based on actual historical dates
                for c in dedup:
                    c_date = c["time"][:10]
                    sent = sentiment_by_date.get(c_date, {"raw_value": 50})
                    c["fear_greed"] = float(sent.get("raw_value", 50))
                    # Remove non-serialisable datetime object before caching
                    c.pop("time_dt", None)
                    
                coin_candles[coin] = dedup
                print(f"[RL Environment] Successfully processed {len(dedup)} candles for {coin}.")
    finally:
        # Restore original sentiment functions
        _sent_mod.get_market_sentiment = orig_get_sentiment
        _sent_mod.get_sentiment_trend = orig_get_trend
        _sent_mod._save_sentiment_to_history = orig_save_sentiment
        _analysis_core.get_market_sentiment = orig_get_sentiment
        _analysis_core.get_sentiment_trend = orig_get_trend
        _analysis_core._save_sentiment_to_history = orig_save_sentiment
    
    # ── Save to disk cache ──────────────────────────────────────────────────
    if coin_candles and cache_file:
        try:
            os.makedirs(os.path.dirname(cache_file) if os.path.dirname(cache_file) else ".", exist_ok=True)
            with open(cache_file, "wb") as f:
                pickle.dump(coin_candles, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[RL Environment] Indicator cache saved to {cache_file} ({os.path.getsize(cache_file)/1024/1024:.1f} MB)")
        except Exception as e:
            print(f"[RL Environment] Warning: could not save cache: {e}")
        
    return coin_candles


def synthetic_sequences_to_candles(
    sequences,
    scaler: OHLCVScaler,
    coin: str = "SYN",
    start_time: str = "2026-01-01 00:00",
    freq_minutes: int = 15,
    device: str = "cpu",
    indicator_params: dict | None = None,
) -> List[dict]:
    """Convert synthetic OHLCV sequences into a list of candle dicts suitable for the RL env.

    Accepts either a NumPy array (N, T, 5) or a torch.Tensor (on CPU or CUDA). Uses
    `postprocess_synthetic_sequences` to inverse-transform using the provided `scaler`.

    Returns a list of dicts with keys matching `load_and_prepare_candles` output.
    """
    # Postprocess back to real scale (handles GPU tensors)
    real = postprocess_synthetic_sequences(sequences, scaler, device=device)

    # Use the first sequence if multiple provided
    if real.ndim == 3 and real.shape[0] >= 1:
        seq = real[0]
    else:
        raise ValueError("Expected sequences shape (N, T, 5)")

    # Build time series
    t0 = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
    candles = []
    for i in range(seq.shape[0]):
        o, h, l, c, v = map(float, seq[i])
        ts = (t0 + timedelta(minutes=i * freq_minutes)).strftime("%Y-%m-%d %H:%M")
        candles.append({
            "time": ts,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            # minimal indicator placeholders (can be expanded later)
            "rsi": None,
            "macd_hist": 0.0,
            "atr": None,
            "adx": 20.0,
            "regime": "SYNTHETIC",
            "is_warmup": 0,
        })
    # compute proper indicators from full sequence
    from btc_scraper.ml_engine.timegan import compute_indicators

    params = indicator_params or {}
    sma_windows = params.get("sma_windows", (3, 5))
    rsi_period = params.get("rsi_period", 14)
    atr_period = params.get("atr_period", 14)
    ema_spans = params.get("ema_spans", [])
    compute_obv_flag = params.get("obv", True)

    seq_batch = seq[np.newaxis, :, :]
    indicators = compute_indicators(seq_batch, sma_windows=sma_windows, rsi_period=rsi_period, atr_period=atr_period)
    # optional EMA and OBV
    if ema_spans:
        from btc_scraper.ml_engine.timegan import compute_ema
        for span in ema_spans:
            indicators[f"ema_{span}"] = compute_ema(seq_batch, span=span)[0]
    if compute_obv_flag:
        from btc_scraper.ml_engine.timegan import compute_obv
        indicators["obv"] = compute_obv(seq_batch)[0]
    rsi = indicators.get("rsi_14")[0]
    atr = indicators.get("atr_14")[0]
    for i in range(len(candles)):
        candles[i]["rsi"] = float(rsi[i]) if not np.isnan(rsi[i]) else 50.0
        candles[i]["atr"] = float(atr[i]) if not np.isnan(atr[i]) else max(1.0, abs(candles[i]["high"] - candles[i]["low"]))
        # optional EMAs/OBV attached for downstream usage
        for span in ema_spans:
            key = f"ema_{span}"
            candles[i][key] = float(indicators.get(key)[i]) if key in indicators else None
        if compute_obv_flag:
            candles[i]["obv"] = float(indicators.get("obv")[i]) if "obv" in indicators else 0.0

    return candles


class TradeExitEnv(gym.Env):
    """
    Gymnasium environment for trading exit management with real price progression.
    
    State Space (18 features):
    - rsi (0-100) normalized to (-1, 1)
    - macd_hist (-inf, inf) normalized to (-1, 1)
    - atr (0, inf) normalized to (0, 1)
    - adx (0-100) normalized to (0, 1)
    - meta_confidence (0-1)
    - regime (0-7) one-hot encoded to 8 features
    - pnl_pct (-100, 100) normalized to (-1, 1)
    - hold_time (0-max_episode_length) normalized to (0, 1)
    - fear_greed (-100, 100) normalized to (-1, 1)
    - volume_ratio (0, 10) normalized to (0, 1)
    - bbands_width (0, 10) normalized to (0, 1)
    Total: 10 + 8 regime features = 18 features
    
    Action Space (6 discrete actions):
    0: HOLD
    1: PARTIAL_CLOSE_50
    2: MOVE_SL_TO_BREAKEVEN
    3: TAKE_PROFIT
    4: EXIT
    5: TRAILING_SL_ATR
    """
    
    metadata = {"render_modes": ["human"]}
    
    # Class-level cache to avoid loading CSVs twice when train/eval envs are created
    _COIN_CANDLES_CACHE = None
    
    def __init__(self, trades: list[dict], config: dict = None):
        super().__init__()
        
        self.trades = trades
        self.config = config or {}
        
        # Environment parameters
        self.max_episode_length = self.config.get("max_episode_length", 50)
        self.reward_scale = self.config.get("reward_scale", 1.0)
        # Legacy config keys kept for backward compatibility. Reward is now
        # pure net PnL delta, so these values are intentionally not applied.
        self.drawdown_penalty = self.config.get("drawdown_penalty", 0.5)
        self.sharpe_bonus = self.config.get("sharpe_bonus", 0.2)
        self.commission_fee = self.config.get("commission_fee", 0.001)  # Default: 0.1% fee per side (entry + exit)
        self.slippage_pct = self.config.get("slippage_pct", 0.0005)      # Default: 0.05% slippage per side (entry + exit)
        # Decision interval: number of environment steps per agent decision (1 = every candle)
        # To use 1-hour decisions on 15m data, set decision_interval=4
        self.decision_interval = int(self.config.get("decision_interval", 1))
        
        # State space: 20 continuous features
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(20,), dtype=np.float32
        )
        
        # Action space: 6 discrete actions
        self.action_space = spaces.Discrete(6)
        
        # Load and cache candles
        if TradeExitEnv._COIN_CANDLES_CACHE is None:
            target_coins = list(set(t.get("coin", "BTC").upper() for t in trades))
            TradeExitEnv._COIN_CANDLES_CACHE = load_and_prepare_candles(
                data_dir=None,
                sentiment_file="logs/sentiment_history.json",
                coins=target_coins
            )
            
        self.coin_candles = TradeExitEnv._COIN_CANDLES_CACHE
        
        # Build time-to-index lookup maps for O(1) matching
        candle_time_maps = {}
        for coin, candles in self.coin_candles.items():
            candle_time_maps[coin] = {c["time"]: idx for idx, c in enumerate(candles)}

        # Find candle index for each entry signal
        self.valid_trades = []
        for t in trades:
            coin = t.get("coin", "BTC").upper()
            entry_time = t.get("entry_time")
            if coin in self.coin_candles and entry_time:
                time_map = candle_time_maps.get(coin, {})
                found_idx = time_map.get(entry_time)
                if found_idx is not None:
                    # Only simulate if we have enough future candles
                    if len(self.coin_candles[coin]) - found_idx > self.max_episode_length:
                        trade_copy = dict(t)
                        trade_copy["coin"] = coin
                        trade_copy["candle_idx"] = found_idx
                        self.valid_trades.append(trade_copy)
                        
        if not self.valid_trades:
            print("[WARN] No trades matched with historical candles. Falling back to dummy mode.")
            # Dummy fallback if no candles matched
            self.valid_trades = [{"coin": "BTC", "candle_idx": 0, "signal_raw": "BUY"}]
            self.coin_candles = {"BTC": [{"time": "2026-01-01 00:00", "close": 100.0, "high": 101.0, "low": 99.0, "volume": 100.0, "rsi": 50.0, "macd_hist": 0.0, "atr": 1.0, "adx": 20.0, "regime": "STRONG_TREND"} for _ in range(200)]}
            
        print(f"[RL Environment] Successfully matched {len(self.valid_trades)} / {len(trades)} trades with candles.")
        
        # Pre-classify trades for Curriculum Learning
        self.easy_trades = []
        self.hard_trades = []
        easy_regimes = {"STRONG_TREND_BULL", "STRONG_TREND_BEAR", "STRONG_TREND", "BREAKOUT"}
        for t in self.valid_trades:
            coin = t["coin"]
            idx = t["candle_idx"]
            candle = self.coin_candles[coin][idx]
            regime = candle.get("regime", "STRONG_TREND")
            if regime in easy_regimes:
                self.easy_trades.append(t)
            else:
                self.hard_trades.append(t)
                
        if not self.easy_trades:
            self.easy_trades = self.valid_trades
            
        self.curriculum_phase = "easy"
        self.active_trades = self.easy_trades
        self.trailing_sl_active = False
        
        # Episode state
        self.current_step = 0
        self.current_trade_idx = 0
        self.entry_price = 0.0
        self.sl = 0.0
        self.tp = 0.0
        self.direction = "LONG"
        self.max_pnl = 0.0
        self.episode_rewards = []
        self.episode_done_reason = ""
        self.prev_pnl = 0.0
        self.min_pnl = 0.0
        self.current_drawdown = 0.0
        self.holding_steps = 0
        self.last_action = None
        self.trade_done = False
        self.trade_rewards = []
        
        # Regime names for internal tracking
        self.regime_names = [
            "STRONG_TREND", "WEAK_TREND", "COMPRESSION",
            "BREAKOUT", "MEAN_REVERSION", "PANIC_SELL",
            "LOW_LIQUIDITY", "PUMP_RISK"
        ]
        
    def set_curriculum_phase(self, phase: str):
        self.curriculum_phase = phase
        if phase == "easy":
            self.active_trades = self.easy_trades
        else:
            self.active_trades = self.valid_trades
        print(f"[RL Env] Curriculum phase set to '{phase}'. Active trades: {len(self.active_trades)}")

    def _reset_trade_state(self, trade: dict) -> dict:
        """Initialize every trade-local field from one canonical boundary."""
        self.trade = trade
        self.coin = trade["coin"]
        self.entry_candle_idx = trade["candle_idx"]
        entry_candle = self.coin_candles[self.coin][self.entry_candle_idx]
        self.entry_price = float(entry_candle["close"])
        self.current_step = 0
        self.prev_pnl = 0.0
        self.max_pnl = 0.0
        self.min_pnl = 0.0
        self.current_drawdown = 0.0
        self.holding_steps = 0
        self.last_action = None
        self.trade_done = False
        self.trade_rewards = []
        self.trailing_sl_active = False
        sig = str(trade.get("signal_raw", "BUY")).upper()
        self.direction = "SHORT" if "SELL" in sig or "SHORT" in sig else "LONG"
        tp_sl = calculate_tp_sl(
            close=entry_candle["close"], signal=trade.get("signal_raw", "BUY"),
            atr=entry_candle.get("atr", 1.0), support=entry_candle.get("support", 0.0),
            resistance=entry_candle.get("resistance", 0.0), bb_upper=entry_candle.get("bb_upper", 0.0),
            bb_middle=entry_candle.get("bb_middle", 0.0), bb_lower=entry_candle.get("bb_lower", 0.0),
            regime=entry_candle.get("regime"),
        )
        self.sl, self.tp = tp_sl["sl"], tp_sl["tp1"]
        return entry_candle
        
    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        """Reset environment to initial state."""
        super().reset(seed=seed)
        
        self.episode_rewards = []
        self.episode_done_reason = ""
        
        # Select trade
        self.current_trade_idx = self.np_random.integers(0, len(self.active_trades))
        entry_candle = self._reset_trade_state(self.active_trades[self.current_trade_idx])
        
        obs = self._get_observation(entry_candle, 0)
        info = {
            "coin": self.coin,
            "direction": self.direction,
            "entry_time": entry_candle["time"],
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp": self.tp,
        }
        
        return obs, info
        
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """Execute one time step."""
        self.last_action = int(action)
        # Index in preloaded candles
        idx = self.entry_candle_idx + self.current_step
        
        # Safety check if we exceed data range
        if idx >= len(self.coin_candles[self.coin]):
            terminated = True
            reward = 0.0
            truncated = False
            dummy_obs = np.zeros(self.observation_space.shape, dtype=np.float32)
            info = {
                "current_pnl": 0.0,
                "max_pnl": self.max_pnl,
                "done_reason": "DATA_END",
                "step": self.current_step,
            }
            return dummy_obs, reward, terminated, truncated, info
            
        candle = self.coin_candles[self.coin][idx]
        
        # Update trailing SL if active
        became_risk_free = False
        if self.trailing_sl_active:
            old_sl = self.sl
            atr = float(candle.get("atr", 1.0))
            if self.direction == "LONG":
                candidate_sl = candle["close"] - 1.5 * atr
                self.sl = max(self.sl, candidate_sl)
                if old_sl <= self.entry_price and self.sl > self.entry_price:
                    became_risk_free = True
            else:
                candidate_sl = candle["close"] + 1.5 * atr
                self.sl = min(self.sl, candidate_sl)
                if old_sl >= self.entry_price and self.sl < self.entry_price:
                    became_risk_free = True
        
        # Calculate current PnL
        # Calculate current PnL
        if self.direction == "LONG":
            current_pnl = ((candle["close"] - self.entry_price) / self.entry_price) * 100
        else:
            current_pnl = ((self.entry_price - candle["close"]) / self.entry_price) * 100
            
        self.max_pnl = max(self.max_pnl, current_pnl)
        self.min_pnl = min(self.min_pnl, current_pnl)
        self.current_drawdown = self.max_pnl - current_pnl
        
        # Dense reward shaping: use the step-to-step difference in Net PnL (percentage).
        # Total reward accumulated over the episode will equal final realized Net PnL.
        reward = 0.0
        terminated = False
        done_reason = ""

        # 1. Check if TP or SL was hit at this candle
        hit_sl = False
        hit_tp = False

        if self.direction == "LONG":
            if candle["low"] <= self.sl:
                hit_sl = True
            if candle["high"] >= self.tp:
                hit_tp = True
        else:
            if candle["high"] >= self.sl:
                hit_sl = True
            if candle["low"] <= self.tp:
                hit_tp = True

        # Helper to compute total round-trip cost percentage (in same units as current_pnl)
        def _round_trip_cost_pct(factor: float = 1.0) -> float:
            return (2 * self.commission_fee + 2 * self.slippage_pct) * 100 * float(factor)

        if hit_sl or hit_tp:
            # Realized PnL at SL/TP
            if hit_sl:
                if self.direction == "LONG":
                    realized_pnl = ((self.sl - self.entry_price) / self.entry_price) * 100
                    done_reason = "SL_HIT"
                else:
                    realized_pnl = ((self.entry_price - self.sl) / self.entry_price) * 100
                    done_reason = "SL_HIT"
            else:
                if self.direction == "LONG":
                    realized_pnl = ((self.tp - self.entry_price) / self.entry_price) * 100
                    done_reason = "TP_HIT"
                else:
                    realized_pnl = ((self.entry_price - self.tp) / self.entry_price) * 100
                    done_reason = "TP_HIT"

            net_pnl = realized_pnl - _round_trip_cost_pct()
            reward = (net_pnl - self.prev_pnl) * self.reward_scale
            self.prev_pnl = net_pnl
            terminated = True

        # Determine whether agent action should be applied this step according to decision interval
        action_allowed = (self.current_step % max(1, self.decision_interval) == 0)

        # 2. Process Agent actions if not force-terminated
        if not terminated:
            # If action isn't allowed this step, treat as HOLD
            if not action_allowed:
                action = 0

            if action == 0:  # HOLD
                reward = (current_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = current_pnl

            elif action == 1:  # PARTIAL_CLOSE_50
                partial_realized = current_pnl * 0.5
                net_pnl = partial_realized - _round_trip_cost_pct(0.5)
                reward = (net_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = net_pnl
                terminated = True
                done_reason = "PARTIAL_CLOSE_50"

            elif action == 2:  # MOVE_SL_TO_BREAKEVEN
                self.sl = self.entry_price
                reward = (current_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = current_pnl

            elif action == 3:  # TAKE_PROFIT
                # Immediate exit at current price
                net_pnl = current_pnl - _round_trip_cost_pct()
                reward = (net_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = net_pnl
                terminated = True
                done_reason = "TAKE_PROFIT"

            elif action == 4:  # EXIT
                net_pnl = current_pnl - _round_trip_cost_pct()
                reward = (net_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = net_pnl
                terminated = True
                done_reason = "EXIT"

            elif action == 5:  # TRAILING_SL_ATR
                self.trailing_sl_active = True
                atr = float(candle.get("atr", 1.0))
                if self.direction == "LONG":
                    candidate_sl = candle["close"] - 1.5 * atr
                    self.sl = max(self.sl, candidate_sl)
                else:
                    candidate_sl = candle["close"] + 1.5 * atr
                    self.sl = min(self.sl, candidate_sl)

                reward = (current_pnl - self.prev_pnl) * self.reward_scale
                self.prev_pnl = current_pnl

        # Advance step and record reward
        self.current_step += 1
        self.holding_steps = self.current_step
        self.episode_rewards.append(reward)
        self.trade_rewards.append(reward)

        # Check max episode length
        truncated = self.current_step >= self.max_episode_length and not terminated
        if truncated:
            done_reason = "MAX_STEPS"
            net_pnl = current_pnl - _round_trip_cost_pct()
            reward = (net_pnl - self.prev_pnl) * self.reward_scale
            self.prev_pnl = net_pnl
            self.episode_rewards[-1] = reward
            self.trade_rewards[-1] = reward
        self.trade_done = terminated or truncated

            
        # Fetch next candle observation
        next_idx = min(idx + 1, len(self.coin_candles[self.coin]) - 1)
        next_candle = self.coin_candles[self.coin][next_idx]
        next_obs = self._get_observation(next_candle, self.current_step)
        
        info = {
            "current_pnl": current_pnl,
            "max_pnl": self.max_pnl,
            "done_reason": done_reason,
            "step": self.current_step,
            "sl": self.sl,
            "tp": self.tp,
        }
        
        return next_obs, reward, terminated, truncated, info

        
    def _get_observation(self, candle: dict, step: int) -> np.ndarray:
        """Compute normalized observation vector (20 features)."""
        obs = np.zeros(20, dtype=np.float32)
        
        # Feature 0: RSI (0-100 -> -1 to 1)
        rsi = float(candle.get("rsi", 50.0))
        obs[0] = (rsi - 50) / 50.0
        
        # Feature 1: MACD Hist (tanh normalized)
        macd_hist = float(candle.get("macd_hist", 0.0))
        obs[1] = np.tanh(macd_hist)
        
        # Feature 2: ATR % (0, inf -> 0, 1)
        atr_pct = float(candle.get("atr_pct", 2.0))
        obs[2] = np.tanh(atr_pct / 2.0)
        
        # Feature 3: ADX (0-100 -> 0, 1)
        adx = float(candle.get("adx", 20.0))
        obs[3] = adx / 100.0
        
        # Feature 4: Entry Confidence (0-1)
        meta_conf = self.trade.get("meta_confidence", 0.5)
        if meta_conf is None or isinstance(meta_conf, str):
            ss = self.trade.get("signal_score")
            if isinstance(ss, dict):
                meta_conf = ss.get("meta_confidence", 0.5)
            else:
                meta_conf = 0.5
        obs[4] = float(meta_conf)
        
        # Features 5-12: Regime one-hot
        regime = str(candle.get("regime", "STRONG_TREND"))
        mapped = self._map_regime(regime)
        regime_idx = self.regime_names.index(mapped) if mapped in self.regime_names else 0
        obs[5 + regime_idx] = 1.0
        
        # Feature 13: PnL % (-100, 100 -> -1, 1)
        if self.direction == "LONG":
            current_pnl = ((candle["close"] - self.entry_price) / self.entry_price) * 100
        else:
            current_pnl = ((self.entry_price - candle["close"]) / self.entry_price) * 100
        obs[13] = np.tanh(current_pnl / 5.0)
        
        # Feature 14: Hold time (0, max -> 0, 1)
        hold_time = min(step, self.max_episode_length)
        obs[14] = hold_time / self.max_episode_length
        
        # Feature 15: Fear & Greed (-1 to 1)
        fear_greed = float(candle.get("fear_greed", 50.0))
        obs[15] = (fear_greed - 50) / 50.0
        
        # Feature 16: Volume Ratio (0, 10 -> 0, 1)
        vol_ratio = float(candle.get("volume_ratio", 1.0))
        obs[16] = np.tanh(vol_ratio / 5.0)
        
        # Feature 17: BB Width % (0, 10 -> 0, 1)
        bb_width_pct = float(candle.get("bb_width_pct", 2.0))
        obs[17] = np.tanh((bb_width_pct - 2.0) / 2.0)
        
        # Feature 18: Max drawdown since entry (min_pnl)
        obs[18] = np.tanh(self.min_pnl / 5.0)
        
        # Feature 19: Average market correlation
        from btc_scraper.analysis.correlation import correlation_engine, SECTOR_MAP
        target = self.coin.upper()
        corrs = []
        for other_coin in SECTOR_MAP.keys():
            if other_coin != target:
                corr_val = correlation_engine.get_correlation(target, other_coin)
                corrs.append(corr_val)
        obs[19] = float(np.mean(corrs)) if corrs else 0.5
        
        return obs
        
    def _map_regime(self, raw_regime: str) -> str:
        return model_regime_bucket(raw_regime)
        
    def render(self, mode="human"):
        pass


class MultiTradeExitEnv(TradeExitEnv):
    """
    Extended environment that cycles through multiple trades per episode
    for better learning efficiency.
    """
    
    def __init__(self, trades: list[dict], config: dict = None, trades_per_episode: int = 5):
        super().__init__(trades, config)
        self.trades_per_episode = trades_per_episode
        self.trades_completed = 0
        
    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        obs, info = super().reset(seed=seed, options=options)
        self.trades_completed = 0
        return obs, info
        
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        obs, reward, terminated, truncated, info = super().step(action)
        
        if terminated or truncated:
            self.trades_completed += 1
            
            if self.trades_completed < self.trades_per_episode:
                # Pick a random trade
                self.current_trade_idx = self.np_random.integers(0, len(self.active_trades))
                entry_candle = self._reset_trade_state(self.active_trades[self.current_trade_idx])
                
                obs = self._get_observation(entry_candle, 0)
                terminated = False  # Don't terminate yet
                truncated = False
            else:
                info["total_trades"] = self.trades_completed
                info["episode_reward"] = np.sum(self.episode_rewards)
                
        return obs, reward, terminated, truncated, info
