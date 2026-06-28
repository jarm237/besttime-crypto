import os
import numpy as np
import torch

from btc_scraper.ml_engine.timegan_trainer import run_stage3_pipeline


def test_stage3_pipeline_runs_and_saves(tmp_path):
    torch.manual_seed(0)
    np.random.seed(0)

    data = np.random.rand(128, 16, 5).astype(np.float32)
    out = run_stage3_pipeline(data, ae_epochs=2, sup_epochs=2, adv_epochs=2, batch_size=32, checkpoint_dir=str(tmp_path), verbose=False)

    assert "autoencoder" in out and "supervisor" in out and "adversarial" in out
    ck = out["checkpoints"]
    # checkpoint files exist
    assert os.path.exists(ck["autoencoder"]) and os.path.exists(ck["supervisor"]) and os.path.exists(ck["adversarial"]) 
    # losses present
    assert len(out["autoencoder"]["losses"]) == 2
    assert len(out["supervisor"]["losses"]) == 2
    assert len(out["adversarial"]["d_losses"]) == 2
