import os
import numpy as np
import pandas as pd
import pytest
import torch
from pathlib import Path

from btc_scraper.ml_engine.timegan import (
    AltcoinSequenceDataset,
    OHLCVScaler,
    build_timegan_dataloader,
    load_historical_15m_sequences,
)


def _write_csv(path: Path, rows):
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def test_load_historical_15m_sequences(tmp_path):
    data_dir = tmp_path / "historical_18m"
    data_dir.mkdir()

    rows = [
        {"time": f"2025-01-01 00:{i:02d}", "open": 1 + i, "high": 2 + i, "low": 0 + i, "close": 1.5 + i, "volume": 100 + i}
        for i in range(6)
    ]
    _write_csv(data_dir / "2025_01_BTC_15m.csv", rows)

    sequences = load_historical_15m_sequences(str(data_dir), seq_len=3)
    assert sequences.shape == (4, 3, 5)
    assert np.allclose(sequences[0, 0], np.array([1.0, 2.0, 0.0, 1.5, 100.0], dtype=np.float32))


def test_ohlcv_scaler_transform_inverse_preserves_limits():
    sequences = np.array(
        [
            [
                [1.0, 2.0, 0.5, 1.5, 10.0],
                [1.1, 2.2, 0.4, 1.6, 12.0],
                [0.9, 1.9, 0.3, 1.3, 9.5],
            ]
        ],
        dtype=np.float32,
    )

    scaler = OHLCVScaler()
    scaled = scaler.fit_transform(sequences)

    assert scaled.shape == sequences.shape
    assert np.all(scaled >= 0.0) and np.all(scaled <= 1.0)
    assert np.all(scaled[:, :, 1] >= scaled[:, :, 2])

    restored = scaler.inverse_transform(scaled)
    assert restored.shape == sequences.shape
    assert np.allclose(restored, sequences, atol=1e-5)


def test_altcoin_sequence_dataset_and_dataloader():
    sequences = np.random.rand(10, 24, 5).astype(np.float32)
    dataset = AltcoinSequenceDataset(sequences)

    assert len(dataset) == 10
    item = dataset[0]
    assert item.shape == (24, 5)
    assert item.dtype == torch.float32

    dataloader = build_timegan_dataloader(sequences, batch_size=4, shuffle=False)
    batch = next(iter(dataloader))
    assert batch.shape == (4, 24, 5)
    assert batch.dtype == torch.float32
