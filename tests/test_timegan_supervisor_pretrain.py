import numpy as np
import torch

from btc_scraper.ml_engine.timegan_trainer import pretrain_supervisor


def test_supervisor_pretrain_loss_decreases():
    torch.manual_seed(0)
    np.random.seed(0)

    # small synthetic dataset
    data = np.random.rand(256, 24, 5).astype(np.float32)

    out = pretrain_supervisor(data, epochs=6, batch_size=64, lr=1e-3)
    losses = out["losses"]
    assert len(losses) >= 2
    assert losses[-1] <= losses[0], "Supervisor loss did not decrease"
