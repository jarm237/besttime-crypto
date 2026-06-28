"""Simple trainer utilities for TimeGAN Stage 3.1 (Autoencoder pre-training).

Provides `pretrain_autoencoder` which trains `Embedder`+`Recovery` on OHLCV sequences
to minimize reconstruction MSE. Designed for small smoke runs and integration tests.
"""
from typing import Dict, List, Optional
import os
import math

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from btc_scraper.ml_engine.timegan import AltcoinSequenceDataset, OHLCVScaler
from btc_scraper.ml_engine.timegan_model import Embedder, Recovery
from btc_scraper.ml_engine.timegan_model import Generator, Discriminator
from btc_scraper.ml_engine.timegan_model import Supervisor

import time
import logging

logger = logging.getLogger("timegan")


def _make_checkpoint_path(base: str, prefix: str, epoch: int) -> str:
    if os.path.isdir(base):
        return os.path.join(base, f"{prefix}_epoch{epoch}.pt")
    root, ext = os.path.splitext(base)
    if ext:
        return f"{root}_{prefix}_epoch{epoch}{ext}"
    return f"{base}_{prefix}_epoch{epoch}.pt"


def pretrain_autoencoder(
    sequences: np.ndarray,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: Optional[str] = None,
    save_path: Optional[str] = None,
    resume_from: Optional[str] = None,
    checkpoint_interval: int = 0,
    verbose: bool = False,
) -> Dict[str, List[float]]:
    """Pretrain Embedder+Recovery as an autoencoder.

    Returns a dict containing 'losses' list and optionally saves checkpoint.
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if not isinstance(sequences, np.ndarray):
        sequences = np.asarray(sequences, dtype=np.float32)

    dataset = AltcoinSequenceDataset(sequences)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    emb = Embedder(input_size=5, hidden_dim=64, latent_dim=32).to(device)
    rec = Recovery(latent_dim=32, hidden_dim=64, output_size=5).to(device)

    params = list(emb.parameters()) + list(rec.parameters())
    opt = torch.optim.Adam(params, lr=lr)
    loss_fn = nn.MSELoss()

    losses: List[float] = []

    # resume support: if resume_from provided and exists, load model + optimizer state
    start_epoch = 0
    if resume_from and os.path.exists(resume_from):
        ck = torch.load(resume_from, map_location=device)
        emb.load_state_dict(ck.get("embedder_state", {}))
        rec.load_state_dict(ck.get("recovery_state", {}))
        if "opt_state" in ck:
            try:
                opt.load_state_dict(ck["opt_state"])
            except Exception:
                # optimizer state may be incompatible across PyTorch versions/devices
                logger.warning("Could not load optimizer state from %s", resume_from)
        start_epoch = int(ck.get("epoch", 0))

    for epoch in range(start_epoch, epochs):
        emb.train(); rec.train()
        epoch_loss = 0.0
        n = 0
        for batch in dataloader:
            x = batch.to(device)
            opt.zero_grad()
            h = emb(x)
            x_rec = rec(h)
            loss = loss_fn(x_rec, x)
            loss.backward()
            opt.step()
            epoch_loss += float(loss.item()) * x.size(0)
            n += x.size(0)

        avg = epoch_loss / max(1, n)
        losses.append(avg)

        if verbose:
            logger.info("AE epoch %d loss=%.6f", epoch + 1, avg)

        if save_path and checkpoint_interval and (epoch + 1) % checkpoint_interval == 0:
            path = _make_checkpoint_path(save_path, "autoencoder", epoch + 1)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            torch.save({
                "embedder_state": emb.state_dict(),
                "recovery_state": rec.state_dict(),
                "opt_state": opt.state_dict(),
                "epoch": epoch + 1,
            }, path)

    if save_path and not checkpoint_interval:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({
            "embedder_state": emb.state_dict(),
            "recovery_state": rec.state_dict(),
            "opt_state": opt.state_dict(),
        }, save_path)

    return {"losses": losses}


def pretrain_supervisor(
    sequences: np.ndarray,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: Optional[str] = None,
    emb_state_dict: Optional[dict] = None,
    save_path: Optional[str] = None,
    resume_from: Optional[str] = None,
    checkpoint_interval: int = 0,
    verbose: bool = False,
) -> Dict[str, List[float]]:
    """Supervised pretraining for the `Supervisor` network.

    Trains the Supervisor to predict the next latent step: Supervisor(h)[:, :-1, :] ~ h[:, 1:, :].
    If `emb_state_dict` is provided, the `Embedder` weights are loaded and frozen.
    Returns a dict containing 'losses'.
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if not isinstance(sequences, np.ndarray):
        sequences = np.asarray(sequences, dtype=np.float32)

    dataset = AltcoinSequenceDataset(sequences)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    emb = Embedder(input_size=5, hidden_dim=64, latent_dim=32).to(device)
    if emb_state_dict is not None:
        emb.load_state_dict(emb_state_dict)
    # freeze embedder during supervisor pretrain
    for p in emb.parameters():
        p.requires_grad = False

    sup = Supervisor(latent_dim=32, hidden_dim=64).to(device)
    opt = torch.optim.Adam(sup.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    losses: List[float] = []

    # resume support
    start_epoch = 0
    if resume_from and os.path.exists(resume_from):
        ck = torch.load(resume_from, map_location=device)
        sup.load_state_dict(ck.get("supervisor_state", {}))
        if "opt_state" in ck:
            try:
                opt.load_state_dict(ck["opt_state"])
            except Exception:
                logger.warning("Could not load supervisor optimizer state from %s", resume_from)
        start_epoch = int(ck.get("epoch", 0))

    for epoch in range(start_epoch, epochs):
        sup.train(); emb.eval()
        epoch_loss = 0.0
        n = 0
        for batch in dataloader:
            x = batch.to(device)
            with torch.no_grad():
                h = emb(x)

            opt.zero_grad()
            h_hat = sup(h)
            # predict next-step: compare h_hat[:, :-1, :] with h[:, 1:, :]
            pred = h_hat[:, :-1, :]
            target = h[:, 1:, :]
            loss = loss_fn(pred, target)
            loss.backward()
            opt.step()

            epoch_loss += float(loss.item()) * x.size(0)
            n += x.size(0)

        avg = epoch_loss / max(1, n)
        losses.append(avg)

        if verbose:
            logger.info("Supervisor epoch %d loss=%.6f", epoch + 1, avg)

        if save_path and checkpoint_interval and (epoch + 1) % checkpoint_interval == 0:
            path = _make_checkpoint_path(save_path, "supervisor", epoch + 1)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            torch.save({
                "supervisor_state": sup.state_dict(),
                "opt_state": opt.state_dict(),
                "epoch": epoch + 1,
            }, path)

    if save_path and not checkpoint_interval:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({"supervisor_state": sup.state_dict(), "opt_state": opt.state_dict()}, save_path)

    return {"losses": losses}


def train_timegan_adversarial(
    sequences: np.ndarray,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-4,
    device: Optional[str] = None,
    emb_state_dict: Optional[dict] = None,
    rec_state_dict: Optional[dict] = None,
    sup_state_dict: Optional[dict] = None,
    save_path: Optional[str] = None,
    resume_from: Optional[str] = None,
    checkpoint_interval: int = 0,
    verbose: bool = False,
) -> Dict[str, List[float]]:
    """Simplified adversarial training for TimeGAN components.

    Trains Generator+Supervisor to fool Discriminator while optionally using
    pretrained Embedder/Recovery/Supervisor weights. Designed for smoke tests.
    Returns dict with 'd_losses' and 'g_losses'.
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if not isinstance(sequences, np.ndarray):
        sequences = np.asarray(sequences, dtype=np.float32)

    dataset = AltcoinSequenceDataset(sequences)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    emb = Embedder(input_size=5, hidden_dim=64, latent_dim=32).to(device)
    rec = Recovery(latent_dim=32, hidden_dim=64, output_size=5).to(device)
    sup = Supervisor(latent_dim=32, hidden_dim=64).to(device)
    gen = Generator(noise_dim=32, hidden_dim=64, latent_dim=32).to(device)
    disc = Discriminator(latent_dim=32, hidden_dim=64).to(device)

    if emb_state_dict is not None:
        emb.load_state_dict(emb_state_dict)
    if rec_state_dict is not None:
        rec.load_state_dict(rec_state_dict)
    if sup_state_dict is not None:
        sup.load_state_dict(sup_state_dict)

    # Freeze embedder/recovery for adversarial training (assume pretrained)
    for p in emb.parameters():
        p.requires_grad = False
    for p in rec.parameters():
        p.requires_grad = False

    opt_d = torch.optim.Adam(disc.parameters(), lr=lr)
    opt_g = torch.optim.Adam(list(gen.parameters()) + list(sup.parameters()), lr=lr)

    bce = nn.BCELoss()
    mse = nn.MSELoss()

    d_losses: List[float] = []
    g_losses: List[float] = []

    # resume support
    start_epoch = 0
    if resume_from and os.path.exists(resume_from):
        ck = torch.load(resume_from, map_location=device)
        gen.load_state_dict(ck.get("generator_state", {}))
        sup.load_state_dict(ck.get("supervisor_state", {}))
        disc.load_state_dict(ck.get("discriminator_state", {}))
        if "opt_d_state" in ck:
            try:
                opt_d.load_state_dict(ck["opt_d_state"])
            except Exception:
                logger.warning("Could not load discriminator optimizer state from %s", resume_from)
        if "opt_g_state" in ck:
            try:
                opt_g.load_state_dict(ck["opt_g_state"])
            except Exception:
                logger.warning("Could not load generator optimizer state from %s", resume_from)
        start_epoch = int(ck.get("epoch", 0))

    for epoch in range(start_epoch, epochs):
        epoch_d = 0.0
        epoch_g = 0.0
        n = 0
        for batch in dataloader:
            x = batch.to(device)
            with torch.no_grad():
                h_real = emb(x)  # (B, T, latent)

            B, T, _ = h_real.shape

            # --- Train Discriminator ---
            disc.train()
            gen.train(); sup.train()
            opt_d.zero_grad()

            # real labels = 1
            real_labels = torch.ones(B, T, 1, device=device)
            fake_labels = torch.zeros(B, T, 1, device=device)

            d_real = disc(h_real)
            # sample noise and produce fake latent
            z = torch.randn(B, T, 32, device=device)
            e_fake = gen(z)
            s_fake = sup(e_fake)

            d_fake = disc(s_fake.detach())

            loss_d_real = bce(d_real, real_labels)
            loss_d_fake = bce(d_fake, fake_labels)
            loss_d = (loss_d_real + loss_d_fake) * 0.5
            loss_d.backward()
            opt_d.step()

            # --- Train Generator + Supervisor ---
            opt_g.zero_grad()
            # adversarial: want discriminator to predict 1 for fake
            d_fake_for_g = disc(s_fake)
            loss_g_adv = bce(d_fake_for_g, real_labels)
            # supervised: match next-step latent dynamics
            loss_sup = mse(s_fake[:, :-1, :], e_fake[:, 1:, :])
            loss_g = loss_g_adv + 0.1 * loss_sup
            loss_g.backward()
            opt_g.step()

            epoch_d += float(loss_d.item()) * B
            epoch_g += float(loss_g.item()) * B
            n += B

        d_losses.append(epoch_d / max(1, n))
        g_losses.append(epoch_g / max(1, n))

        if verbose:
            logger.info("Adv epoch %d d_loss=%.6f g_loss=%.6f", epoch + 1, d_losses[-1], g_losses[-1])

        if save_path and checkpoint_interval and (epoch + 1) % checkpoint_interval == 0:
            path = _make_checkpoint_path(save_path, "adv", epoch + 1)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            torch.save({
                "generator_state": gen.state_dict(),
                "supervisor_state": sup.state_dict(),
                "discriminator_state": disc.state_dict(),
                "opt_d_state": opt_d.state_dict(),
                "opt_g_state": opt_g.state_dict(),
                "epoch": epoch + 1,
            }, path)

    if save_path and not checkpoint_interval:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({
            "generator_state": gen.state_dict(),
            "supervisor_state": sup.state_dict(),
            "discriminator_state": disc.state_dict(),
            "opt_d_state": opt_d.state_dict(),
            "opt_g_state": opt_g.state_dict(),
        }, save_path)

    return {"d_losses": d_losses, "g_losses": g_losses}


def run_stage3_pipeline(
    sequences: np.ndarray,
    ae_epochs: int = 5,
    sup_epochs: int = 5,
    adv_epochs: int = 5,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: Optional[str] = None,
    checkpoint_dir: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, object]:
    """Run Stage 3 pipeline end-to-end:
    1) autoencoder pretrain
    2) supervisor supervised pretrain
    3) adversarial training

    Saves intermediate checkpoints to `checkpoint_dir` if provided.
    Returns a dict with losses and checkpoint paths.
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if not isinstance(sequences, np.ndarray):
        sequences = np.asarray(sequences, dtype=np.float32)

    if checkpoint_dir:
        os.makedirs(checkpoint_dir, exist_ok=True)

    ae_ck = os.path.join(checkpoint_dir or ".", "autoencoder.pt")
    sup_ck = os.path.join(checkpoint_dir or ".", "supervisor.pt")
    adv_ck = os.path.join(checkpoint_dir or ".", "adversarial.pt")

    if verbose:
        logger.info("Stage3: starting autoencoder pretrain")
    ae_out = pretrain_autoencoder(
        sequences, epochs=ae_epochs, batch_size=batch_size, lr=lr, device=device, save_path=ae_ck, verbose=verbose
    )

    # load embedder/recovery states
    ae_state = torch.load(ae_ck, map_location=device)

    if verbose:
        logger.info("Stage3: starting supervisor pretrain")
    sup_out = pretrain_supervisor(
        sequences, epochs=sup_epochs, batch_size=batch_size, lr=lr, device=device, emb_state_dict=ae_state.get("embedder_state"), save_path=sup_ck, verbose=verbose
    )

    sup_state = torch.load(sup_ck, map_location=device)

    if verbose:
        logger.info("Stage3: starting adversarial training")
    adv_out = train_timegan_adversarial(
        sequences,
        epochs=adv_epochs,
        batch_size=batch_size,
        lr=lr,
        device=device,
        emb_state_dict=ae_state.get("embedder_state"),
        rec_state_dict=ae_state.get("recovery_state"),
        sup_state_dict=sup_state.get("supervisor_state"),
        save_path=adv_ck,
        verbose=verbose,
    )

    return {
        "autoencoder": ae_out,
        "supervisor": sup_out,
        "adversarial": adv_out,
        "checkpoints": {"autoencoder": ae_ck, "supervisor": sup_ck, "adversarial": adv_ck},
    }


if __name__ == "__main__":
    # quick smoke run if executed directly
    rng = np.random.RandomState(42)
    data = rng.rand(200, 24, 5).astype(np.float32)
    out = pretrain_autoencoder(data, epochs=3, batch_size=32)
    print("losses:", out["losses"]) 
