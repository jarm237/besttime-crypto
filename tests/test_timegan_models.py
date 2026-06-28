import torch
import numpy as np
from btc_scraper.ml_engine.timegan_model import Embedder, Recovery, Generator, Supervisor, Discriminator


def test_timegan_model_shapes():
    B, T = 2, 24
    x = torch.randn(B, T, 5)
    z = torch.randn(B, T, 32)

    emb = Embedder(input_size=5, hidden_dim=64, latent_dim=32)
    rec = Recovery(latent_dim=32, hidden_dim=64, output_size=5)
    gen = Generator(noise_dim=32, hidden_dim=64, latent_dim=32)
    sup = Supervisor(latent_dim=32, hidden_dim=64)
    disc = Discriminator(latent_dim=32, hidden_dim=64)

    h = emb(x)
    assert h.shape == (B, T, 32)

    x_rec = rec(h)
    assert x_rec.shape == (B, T, 5)

    h_hat = gen(z)
    assert h_hat.shape == (B, T, 32)

    h_sup = sup(h)
    assert h_sup.shape == (B, T, 32)

    d_out = disc(h_hat)
    assert d_out.shape == (B, T, 1)
