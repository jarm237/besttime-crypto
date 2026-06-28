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


def pretrain_autoencoder(
    sequences: np.ndarray,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: Optional[str] = None,
    save_path: Optional[str] = None,
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

    for epoch in range(epochs):
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

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({"embedder_state": emb.state_dict(), "recovery_state": rec.state_dict()}, save_path)

    return {"losses": losses}


def pretrain_supervisor(
    sequences: np.ndarray,
    epochs: int = 10,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: Optional[str] = None,
    emb_state_dict: Optional[dict] = None,
    save_path: Optional[str] = None,
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

    for epoch in range(epochs):
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

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({"supervisor_state": sup.state_dict()}, save_path)

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

    for epoch in range(epochs):
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

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({
            "generator_state": gen.state_dict(),
            "supervisor_state": sup.state_dict(),
            "discriminator_state": disc.state_dict(),
        }, save_path)

    return {"d_losses": d_losses, "g_losses": g_losses}


if __name__ == "__main__":
    # quick smoke run if executed directly
    rng = np.random.RandomState(42)
    data = rng.rand(200, 24, 5).astype(np.float32)
    out = pretrain_autoencoder(data, epochs=3, batch_size=32)
    print("losses:", out["losses"]) 
