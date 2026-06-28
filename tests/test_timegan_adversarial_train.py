import numpy as np
import torch

from btc_scraper.ml_engine.timegan_trainer import train_timegan_adversarial


def test_adversarial_train_runs_and_returns_losses():
    torch.manual_seed(0)
    np.random.seed(0)

    data = np.random.rand(256, 24, 5).astype(np.float32)

    out = train_timegan_adversarial(data, epochs=4, batch_size=64, lr=1e-3)
    assert "d_losses" in out and "g_losses" in out
    assert len(out["d_losses"]) == 4
    assert len(out["g_losses"]) == 4
    # losses should be finite
    assert all(np.isfinite(out["d_losses"]))
    assert all(np.isfinite(out["g_losses"]))
