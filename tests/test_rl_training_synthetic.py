import pickle

import numpy as np

from btc_scraper.ml_engine.rl_trading_env import MultiTradeExitEnv, TradeExitEnv
from train_rl_exit_manager import (
    SYNTHETIC_COIN,
    _apply_synthetic_curriculum,
    load_synthetic_training_data,
)


def test_load_synthetic_training_data_builds_cache_and_trades(tmp_path):
    sequences = np.zeros((4, 24, 5), dtype=np.float32)
    base = np.linspace(100.0, 110.0, num=96, dtype=np.float32).reshape(4, 24)
    sequences[:, :, 0] = base
    sequences[:, :, 1] = base + 1.0
    sequences[:, :, 2] = base - 1.0
    sequences[:, :, 3] = base + 0.25
    sequences[:, :, 4] = 1000.0

    candle_path = tmp_path / "rl_synthetic_candles.pkl"
    with open(candle_path, "wb") as f:
        pickle.dump({"sequences": sequences}, f)

    cache, trades = load_synthetic_training_data(
        candle_path=str(candle_path),
        max_sequences=4,
        max_episode_length=20,
    )

    assert list(cache.keys()) == [SYNTHETIC_COIN]
    assert len(cache[SYNTHETIC_COIN]) == 96
    assert trades
    assert all(t["coin"] == SYNTHETIC_COIN for t in trades)
    assert all(c["high"] >= max(c["open"], c["close"]) for c in cache[SYNTHETIC_COIN])
    assert all(c["low"] <= min(c["open"], c["close"]) for c in cache[SYNTHETIC_COIN])


def test_apply_synthetic_curriculum_sets_easy_phase(tmp_path):
    sequences = np.zeros((4, 24, 5), dtype=np.float32)
    base = np.linspace(100.0, 120.0, num=96, dtype=np.float32).reshape(4, 24)
    sequences[:, :, 0] = base
    sequences[:, :, 1] = base + 1.0
    sequences[:, :, 2] = base - 1.0
    sequences[:, :, 3] = base + 0.5
    sequences[:, :, 4] = 1000.0

    candle_path = tmp_path / "rl_synthetic_candles.pkl"
    with open(candle_path, "wb") as f:
        pickle.dump({"sequences": sequences}, f)

    cache, trades = load_synthetic_training_data(
        candle_path=str(candle_path),
        max_sequences=4,
        max_episode_length=20,
    )

    previous_cache = TradeExitEnv._COIN_CANDLES_CACHE
    TradeExitEnv._COIN_CANDLES_CACHE = cache
    try:
        env = MultiTradeExitEnv(
            trades=trades,
            config={"max_episode_length": 20},
            trades_per_episode=2,
        )
        _apply_synthetic_curriculum(env)

        assert env.curriculum_phase == "easy"
        assert env.easy_trades
        assert env.active_trades == env.easy_trades
        assert all(t["coin"] == SYNTHETIC_COIN for t in env.easy_trades)
    finally:
        TradeExitEnv._COIN_CANDLES_CACHE = previous_cache
