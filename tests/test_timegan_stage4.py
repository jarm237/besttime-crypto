"""Unit tests for TimeGAN Stage 4 (Synthetic Data Generation)."""

import os
import tempfile
import pickle
import numpy as np
import torch
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan_model import Generator
from btc_scraper.ml_engine.timegan import OHLCVScaler, postprocess_synthetic_sequences
from btc_scraper.ml_engine.timegan_generate import (
    load_timegan_checkpoint,
    load_timegan_generator,
    generate_synthetic_sequences,
    generate_and_postprocess,
    save_synthetic_candles,
    load_synthetic_candles,
)


class TestGeneratorLoading:
    """Test loading pre-trained generators."""
    
    def test_load_generator_creates_model(self):
        """Test that load_timegan_generator creates a Generator."""
        gen = load_timegan_generator("/nonexistent/path.pt", device="cpu")
        assert isinstance(gen, Generator)
        assert gen.training == False  # Should be in eval mode
    
    def test_generator_forward_pass(self):
        """Test generator forward pass with dummy noise."""
        gen = load_timegan_generator("/nonexistent/path.pt", device="cpu")
        z = torch.randn(8, 24, 32)  # (batch, seq_len, noise_dim)
        with torch.no_grad():
            output = gen(z)
        
        assert output.shape == (8, 24, 32), f"Expected (8, 24, 32), got {output.shape}"
        assert output.dtype == torch.float32


class TestSyntheticGeneration:
    """Test synthetic sequence generation."""
    
    def test_generate_sequences_basic(self):
        """Test basic sequence generation."""
        gen, rec = load_timegan_checkpoint("/nonexistent/path.pt", device="cpu")
        sequences = generate_synthetic_sequences(
            gen,
            rec,
            n_sequences=100,
            seq_len=24,
            batch_size=32,
            device="cpu"
        )
        
        assert sequences.shape == (100, 24, 5), f"Expected (100, 24, 5), got {sequences.shape}"
        assert sequences.dtype == np.float32
        assert sequences.min() >= 0 and sequences.max() <= 1
    
    def test_generate_sequences_batch_sizes(self):
        """Test generation with different batch sizes."""
        gen, rec = load_timegan_checkpoint("/nonexistent/path.pt", device="cpu")
        
        for batch_size in [16, 64, 256]:
            sequences = generate_synthetic_sequences(
                gen,
                rec,
                n_sequences=100,
                seq_len=24,
                batch_size=batch_size,
                device="cpu"
            )
            assert len(sequences) == 100


class TestPostprocessing:
    """Test postprocessing of synthetic sequences."""
    
    def create_scaler(self):
        """Create a fitted scaler."""
        # Create dummy real sequences
        real_data = np.random.rand(200, 24, 5).astype(np.float32)
        real_data[:, :, 0] = real_data[:, :, 0] * 1000 + 100   # open: 100-1100
        real_data[:, :, 1] = real_data[:, :, 1] * 1000 + 500   # high: 500-1500
        real_data[:, :, 2] = real_data[:, :, 2] * 1000         # low: 0-1000
        real_data[:, :, 3] = real_data[:, :, 3] * 1000 + 100   # close: 100-1100
        real_data[:, :, 4] = real_data[:, :, 4] * 10000        # volume: 0-10000
        
        scaler = OHLCVScaler()
        scaler.fit(real_data)
        return scaler
    
    def test_postprocess_synthetic(self):
        """Test postprocessing of synthetic sequences."""
        scaler = self.create_scaler()
        gen, rec = load_timegan_checkpoint("/nonexistent/path.pt", device="cpu")
        
        sequences = generate_synthetic_sequences(
            gen,
            rec,
            n_sequences=50,
            seq_len=24,
            batch_size=32,
            device="cpu"
        )
        
        real_sequences = postprocess_synthetic_sequences(
            sequences,
            scaler=scaler,
            device="cpu",
            enforce_ohlc=True
        )
        
        assert real_sequences.shape == sequences.shape
        assert real_sequences.dtype == np.float32
        # Check that values are in reasonable range (based on scaler fit)
        assert real_sequences.min() >= 0
    
    def test_generate_and_postprocess(self):
        """Test full generation + postprocessing pipeline."""
        scaler = self.create_scaler()
        gen, rec = load_timegan_checkpoint("/nonexistent/path.pt", device="cpu")
        
        real_sequences = generate_and_postprocess(
            gen,
            rec,
            scaler,
            n_sequences=50,
            seq_len=24,
            batch_size=32,
            device="cpu"
        )
        
        assert real_sequences.shape == (50, 24, 5)
        assert real_sequences.dtype == np.float32


class TestSerialization:
    """Test saving/loading synthetic candles."""
    
    def create_dummy_sequences(self, n=100):
        """Create dummy synthetic sequences."""
        return np.random.rand(n, 24, 5).astype(np.float32) * 100
    
    def test_save_synthetic_candles(self):
        """Test saving synthetic candles to pickle."""
        sequences = self.create_dummy_sequences()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "synthetic_candles.pkl")
            saved_path = save_synthetic_candles(sequences, output_path)
            
            assert os.path.exists(saved_path)
            assert saved_path.endswith(".pkl")
    
    def test_load_synthetic_candles(self):
        """Test loading synthetic candles from pickle."""
        sequences = self.create_dummy_sequences(n=100)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "synthetic_candles.pkl")
            save_synthetic_candles(sequences, output_path)
            
            data = load_synthetic_candles(output_path)
            
            assert "sequences" in data
            assert "n_sequences" in data
            assert "seq_len" in data
            assert "features" in data
            
            assert data["n_sequences"] == 100
            assert data["seq_len"] == 24
            assert len(data["features"]) == 5
            np.testing.assert_array_equal(data["sequences"], sequences)


class TestEndToEndGeneration:
    """Test complete generation pipeline."""
    
    def create_scaler(self):
        """Create a fitted scaler."""
        real_data = np.random.rand(200, 24, 5).astype(np.float32) * 1000
        scaler = OHLCVScaler()
        scaler.fit(real_data)
        return scaler
    
    def test_full_pipeline(self):
        """Test complete generation pipeline."""
        scaler = self.create_scaler()
        gen, rec = load_timegan_checkpoint("/nonexistent/path.pt", device="cpu")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate
            real_sequences = generate_and_postprocess(
                gen,
                rec,
                scaler,
                n_sequences=100,
                seq_len=24,
                batch_size=32,
                device="cpu"
            )
            
            # Save
            output_path = os.path.join(tmpdir, "synthetic_candles.pkl")
            saved_path = save_synthetic_candles(real_sequences, output_path)
            
            # Load
            data = load_synthetic_candles(saved_path)
            
            assert data["n_sequences"] == 100
            np.testing.assert_array_equal(data["sequences"], real_sequences)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
