"""Unit tests for TimeGAN Stage 1 (Preprocessing Pipeline).

Tests:
- Coin extraction from filenames
- Sequence loading and chunking
- Scaler fit/transform/inverse_transform
- OHLC constraints enforcement
- DataLoader integration
"""

import os
import tempfile
import numpy as np
import pytest
import pandas as pd
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan import (
    _extract_coin_from_filename,
    load_historical_15m_sequences,
    OHLCVScaler,
    AltcoinSequenceDataset,
    build_timegan_dataloader,
    _enforce_ohlc_constraints,
    postprocess_synthetic_sequences,
)


class TestCoinExtraction:
    """Test coin symbol extraction from filenames."""
    
    def test_modern_format(self):
        """Test format: 2025_01_BTC_15m.csv"""
        assert _extract_coin_from_filename("2025_01_BTC_15m.csv") == "BTC"
        assert _extract_coin_from_filename("2026_06_ETH_15m.csv") == "ETH"
        assert _extract_coin_from_filename("2025_12_TRUMP_15m.csv") == "TRUMP"
    
    def test_legacy_format(self):
        """Test format: april_2025_BTC_15m.csv"""
        assert _extract_coin_from_filename("april_2025_BTC_15m.csv") == "BTC"
        assert _extract_coin_from_filename("january_2025_ETH_15m.csv") == "ETH"
    
    def test_simple_format(self):
        """Test format: BTC_15m.csv"""
        assert _extract_coin_from_filename("BTC_15m.csv") == "BTC"
        assert _extract_coin_from_filename("SOL_1h.csv") == "SOL"
    
    def test_daily_format(self):
        """Test 1d files"""
        assert _extract_coin_from_filename("2025_01_BTC_1d.csv") == "BTC"
    
    def test_with_path(self):
        """Test full path"""
        assert _extract_coin_from_filename("/data/2025_01_BTC_15m.csv") == "BTC"


class TestOHLCVScaler:
    """Test OHLCV MinMax scaler."""
    
    def create_dummy_sequences(self, n_seq=10, seq_len=24):
        """Create dummy OHLCV sequences for testing."""
        np.random.seed(42)
        sequences = np.random.rand(n_seq, seq_len, 5).astype(np.float32)
        # Adjust prices to realistic scale
        sequences[:, :, :4] *= 1000  # Price in USD
        sequences[:, :, 4] *= 1e6     # Volume
        
        # Enforce OHLC constraints
        for i in range(n_seq):
            for t in range(seq_len):
                o, h, l, c = sequences[i, t, :4]
                sequences[i, t, 1] = max(sequences[i, t, 1], o, c)  # High
                sequences[i, t, 2] = min(sequences[i, t, 2], o, c)  # Low
        
        return sequences
    
    def test_fit_transform(self):
        """Test fit and transform."""
        sequences = self.create_dummy_sequences()
        scaler = OHLCVScaler(feature_range=(0, 1))
        
        scaled = scaler.fit_transform(sequences)
        
        assert scaled.shape == sequences.shape
        assert np.all(scaled >= 0.0) and np.all(scaled <= 1.0)
        assert scaler.fitted
    
    def test_inverse_transform(self):
        """Test inverse transform recovers original values."""
        sequences = self.create_dummy_sequences()
        scaler = OHLCVScaler()
        
        scaled = scaler.fit_transform(sequences)
        recovered = scaler.inverse_transform(scaled)
        
        # Should recover original values (within numerical precision)
        np.testing.assert_allclose(recovered, sequences, rtol=1e-5)
    
    def test_unfitted_error(self):
        """Test error when using unfitted scaler."""
        scaler = OHLCVScaler()
        sequences = np.random.rand(10, 24, 5).astype(np.float32)
        
        with pytest.raises(ValueError, match="not been fitted"):
            scaler.transform(sequences)


class TestOHLCConstraints:
    """Test OHLC constraint enforcement."""
    
    def test_enforce_constraints(self):
        """Test constraint enforcement."""
        # Create sequences with violations
        sequences = np.array([
            [
                [100, 80, 120, 90, 1000],   # High < Low (violation)
                [100, 110, 90, 105, 1000],  # OK
                [100, 105, 95, 102, 1000],  # OK
            ]
        ], dtype=np.float32)
        
        corrected = _enforce_ohlc_constraints(sequences)
        
        # Check High >= Low everywhere
        assert np.all(corrected[:, :, 1] >= corrected[:, :, 2])
        # Check High >= Open and Close
        assert np.all(corrected[:, :, 1] >= corrected[:, :, 0])
        assert np.all(corrected[:, :, 1] >= corrected[:, :, 3])
        # Check Low <= Open and Close
        assert np.all(corrected[:, :, 2] <= corrected[:, :, 0])
        assert np.all(corrected[:, :, 2] <= corrected[:, :, 3])


class TestDataset:
    """Test AltcoinSequenceDataset."""
    
    def test_dataset_creation(self):
        """Test dataset initialization."""
        sequences = np.random.rand(100, 24, 5).astype(np.float32)
        dataset = AltcoinSequenceDataset(sequences)
        
        assert len(dataset) == 100
        assert dataset.feature_names == ["open", "high", "low", "close", "volume"]
    
    def test_dataset_getitem(self):
        """Test dataset indexing."""
        sequences = np.random.rand(10, 24, 5).astype(np.float32)
        dataset = AltcoinSequenceDataset(sequences)
        
        item = dataset[0]
        assert item.shape == (24, 5)
    
    def test_dataset_invalid_shape(self):
        """Test error on invalid shape."""
        sequences = np.random.rand(100, 24, 6).astype(np.float32)  # Wrong num features
        
        with pytest.raises(ValueError):
            AltcoinSequenceDataset(sequences)


class TestDataLoader:
    """Test PyTorch DataLoader integration."""
    
    def test_dataloader_creation(self):
        """Test DataLoader creation."""
        sequences = np.random.rand(100, 24, 5).astype(np.float32)
        dataloader = build_timegan_dataloader(
            sequences,
            batch_size=32,
            shuffle=False,
            num_workers=0
        )
        
        # Test iteration
        batch_count = 0
        for batch in dataloader:
            batch_count += 1
            assert batch.shape[0] <= 32  # batch size
            assert batch.shape[1] == 24  # seq_len
            assert batch.shape[2] == 5   # features
        
        # Should have at least 3 batches for 100 samples with batch_size 32
        assert batch_count >= 3
    
    def test_dataloader_shuffle(self):
        """Test DataLoader shuffling."""
        sequences = np.arange(100 * 24 * 5).reshape(100, 24, 5).astype(np.float32)
        
        dataloader1 = build_timegan_dataloader(sequences, shuffle=True, num_workers=0)
        dataloader2 = build_timegan_dataloader(sequences, shuffle=True, num_workers=0)
        
        batch1 = next(iter(dataloader1))
        batch2 = next(iter(dataloader2))
        
        # With shuffle, batches should be different
        # (not guaranteed but very likely)
        assert not np.array_equal(batch1, batch2)


class TestIntegration:
    """Integration tests for Stage 1 pipeline."""
    
    def test_scaler_dataset_pipeline(self):
        """Test full pipeline: create -> scale -> dataset -> loader."""
        # Create dummy sequences
        sequences = np.random.rand(50, 24, 5).astype(np.float32) * 1000
        sequences[:, :, 4] *= 1e6  # volume
        
        # Enforce OHLC
        sequences = _enforce_ohlc_constraints(sequences)
        
        # Scale
        scaler = OHLCVScaler()
        scaled_sequences = scaler.fit_transform(sequences)
        
        # Create dataset and loader
        dataset = AltcoinSequenceDataset(scaled_sequences)
        dataloader = build_timegan_dataloader(dataset.sequences, batch_size=16, shuffle=False)
        
        # Verify
        assert len(dataloader) > 0
        batch = next(iter(dataloader))
        assert batch.shape[0] > 0 and batch.shape[2] == 5


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
