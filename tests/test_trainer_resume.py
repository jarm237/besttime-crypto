import os
import glob
import numpy as np
import torch

from btc_scraper.ml_engine.timegan_trainer import pretrain_autoencoder


def test_pretrain_autoencoder_resume(tmp_path):
    # small random dataset
    data = np.random.RandomState(0).rand(64, 24, 5).astype("float32")

    ck_base = tmp_path / "ae_test.pt"

    # run initial training for 2 epochs and save checkpoints each epoch
    out1 = pretrain_autoencoder(data, epochs=2, batch_size=16, save_path=str(ck_base), checkpoint_interval=1)
    assert "losses" in out1 and len(out1["losses"]) == 2

    # find the saved checkpoint file for epoch 1
    matches = list(tmp_path.glob("*autoencoder*"))
    assert matches, f"no checkpoint files found in {tmp_path}"
    ckpt = str(matches[0])

    # load checkpoint to get recorded epoch
    ck = torch.load(ckpt, map_location="cpu")
    start_epoch = int(ck.get("epoch", 0))

    # resume training: target epochs > start_epoch
    target_epochs = start_epoch + 2
    out2 = pretrain_autoencoder(data, epochs=target_epochs, batch_size=16, resume_from=ckpt)

    # out2 losses should contain (target_epochs - start_epoch) entries
    assert "losses" in out2
    assert len(out2["losses"]) == (target_epochs - start_epoch)
