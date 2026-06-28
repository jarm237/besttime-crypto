import numpy as np
import torch
import os
from btc_scraper.ml_engine.rl_trading_env import TradeExitEnv, synthetic_sequences_to_candles
from btc_scraper.ml_engine.timegan import OHLCVScaler


def test_rl_env_runs_with_synthetic_on_gpu_if_available(tmp_path):
    # create synthetic sequence long enough for episodes
    rng = np.random.RandomState(1)
    seq_len = 200
    synth = rng.rand(1, seq_len, 5).astype('float32')

    scaler = OHLCVScaler()
    scaler.fit(synth)
    scaled = scaler.transform(synth)

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    tensor = torch.from_numpy(scaled)
    if device == 'cuda':
        tensor = tensor.to('cuda')

    candles = synthetic_sequences_to_candles(tensor, scaler, coin='SYN', start_time='2026-06-01 00:00', device=device)
    assert len(candles) == seq_len

    # Inject into TradeExitEnv cache
    TradeExitEnv._COIN_CANDLES_CACHE = {'SYN': candles}

    trades = [{'coin': 'SYN', 'entry_time': candles[0]['time'], 'signal_raw': 'BUY'}]
    env = TradeExitEnv(trades, config={'max_episode_length': 50})
    obs, info = env.reset()
    assert obs.shape[0] == 20
    # step through a few actions
    for _ in range(5):
        obs, reward, terminated, truncated, info = env.step(0)
        if terminated:
            break
    # cleanup cache
    TradeExitEnv._COIN_CANDLES_CACHE = None
