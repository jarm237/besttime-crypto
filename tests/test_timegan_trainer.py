import numpy as np
import torch

from btc_scraper.ml_engine.timegan_trainer import pretrain_autoencoder


def test_pretrain_autoencoder_smoke():
    np.random.seed(0)
    torch.manual_seed(0)
    data = np.random.rand(128, 24, 5).astype(np.float32)
    res = pretrain_autoencoder(data, epochs=3, batch_size=16, lr=1e-3, device="cpu")
    assert isinstance(res, dict)
    losses = res.get("losses")
    assert isinstance(losses, list) and len(losses) == 3
    assert all([float(l) >= 0.0 and np.isfinite(l) for l in losses])
    # Expect some training progress: last loss <= first loss * 1.5 (relaxed)
    assert losses[-1] <= losses[0] * 1.5
