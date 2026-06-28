"""TimeGAN core architecture (Stage 2).

Implements lightweight GRU-based modules:
- Embedder
- Recovery
- Generator
- Supervisor
- Discriminator

These are minimal implementations with clear input/output shapes and smoke tests.
"""

from typing import Optional

import torch
import torch.nn as nn


class _GRUBlock(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_layers: int = 1, bidirectional: bool = False):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, num_layers=num_layers, batch_first=True, bidirectional=bidirectional)

    def forward(self, x, hx=None):
        out, h = self.gru(x, hx)
        return out, h


class Embedder(nn.Module):
    def __init__(self, input_size: int = 5, hidden_dim: int = 64, latent_dim: int = 32):
        super().__init__()
        self.fc_in = nn.Linear(input_size, hidden_dim)
        self.gru = _GRUBlock(hidden_dim, latent_dim)

    def forward(self, x):
        # x: (B, T, input_size)
        h = torch.relu(self.fc_in(x))
        out, _ = self.gru(h)
        return out


class Recovery(nn.Module):
    def __init__(self, latent_dim: int = 32, hidden_dim: int = 64, output_size: int = 5):
        super().__init__()
        self.gru = _GRUBlock(latent_dim, hidden_dim)
        self.fc_out = nn.Linear(hidden_dim, output_size)

    def forward(self, h):
        out, _ = self.gru(h)
        return self.fc_out(out)


class Generator(nn.Module):
    def __init__(self, noise_dim: int = 32, hidden_dim: int = 64, latent_dim: int = 32):
        super().__init__()
        self.gru = _GRUBlock(noise_dim, hidden_dim)
        self.fc = nn.Linear(hidden_dim, latent_dim)

    def forward(self, z):
        out, _ = self.gru(z)
        return self.fc(out)


class Supervisor(nn.Module):
    def __init__(self, latent_dim: int = 32, hidden_dim: int = 64):
        super().__init__()
        self.gru = _GRUBlock(latent_dim, hidden_dim)
        self.fc = nn.Linear(hidden_dim, latent_dim)

    def forward(self, h):
        out, _ = self.gru(h)
        return self.fc(out)


class Discriminator(nn.Module):
    def __init__(self, latent_dim: int = 32, hidden_dim: int = 64):
        super().__init__()
        self.gru = _GRUBlock(latent_dim, hidden_dim)
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, h):
        out, _ = self.gru(h)
        logits = self.fc(out)
        return torch.sigmoid(logits)
