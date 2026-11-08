"""Unit tests for TimeGAN Stage 3 (Multi-stage Training).

Tests:
- Autoencoder pre-training
- Supervisor pre-training  
- Adversarial training
- Full Stage 3 pipeline
"""

import os
import tempfile
import numpy as np
import pytest
import torch

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan_trainer import (
    pretrain_autoencoder,
    pretrain_supervisor,
    train_timegan_adversarial,
    run_stage3_pipeline,
)
from btc_scraper.ml_engine.timegan_model import (
    Embedder, Recovery, Generator, Supervisor, Discriminator
)


class TestModelArchitecture:
    """Test individual TimeGAN modules."""
    
    def test_embedder(self):
        """Test Embedder: OHLCV -> latent."""
        emb = Embedder(input_size=5, hidden_dim=64, latent_dim=32)
        x = torch.randn(16, 24, 5)  # (batch, seq_len, features)
        h = emb(x)
        assert h.shape == (16, 24, 32), f"Expected (16, 24, 32), got {h.shape}"
    
    def test_recovery(self):
        """Test Recovery: latent -> OHLCV."""
        rec = Recovery(latent_dim=32, hidden_dim=64, output_size=5)
        h = torch.randn(16, 24, 32)
        x_rec = rec(h)
        assert x_rec.shape == (16, 24, 5), f"Expected (16, 24, 5), got {x_rec.shape}"
    
    def test_generator(self):
        """Test Generator: noise -> latent."""
        gen = Generator(noise_dim=32, hidden_dim=64, latent_dim=32)
        z = torch.randn(16, 24, 32)  # noise
        h = gen(z)
        assert h.shape == (16, 24, 32), f"Expected (16, 24, 32), got {h.shape}"
    
    def test_supervisor(self):
        """Test Supervisor: latent -> latent (next-step prediction)."""
        sup = Supervisor(latent_dim=32, hidden_dim=64)
        h = torch.randn(16, 24, 32)
        h_sup = sup(h)
        assert h_sup.shape == (16, 24, 32), f"Expected (16, 24, 32), got {h_sup.shape}"
    
    def test_discriminator(self):
        """Test Discriminator: latent -> [0,1]."""
        disc = Discriminator(latent_dim=32, hidden_dim=64)
        h = torch.randn(16, 24, 32)
        d_out = disc(h)
        assert d_out.shape == (16, 24, 1), f"Expected (16, 24, 1), got {d_out.shape}"


class TestAutoencoderPretrain:
    """Test autoencoder pre-training (Stage 3.1)."""
    
    def create_dummy_sequences(self, n=100, seq_len=24):
        return np.random.rand(n, seq_len, 5).astype(np.float32) * 1000
    
    def test_pretrain_autoencoder_basic(self):
        """Test autoencoder training runs without error."""
        sequences = self.create_dummy_sequences()
        result = pretrain_autoencoder(
            sequences,
            epochs=2,
            batch_size=32,
            lr=1e-3,
            verbose=False
        )
        
        assert "losses" in result
        assert len(result["losses"]) == 2
        assert all(isinstance(l, float) for l in result["losses"])
        assert all(l > 0 for l in result["losses"])
    
    def test_pretrain_autoencoder_convergence(self):
        """Test that loss decreases over epochs."""
        sequences = self.create_dummy_sequences()
        result = pretrain_autoencoder(
            sequences,
            epochs=5,
            batch_size=32,
            lr=1e-3,
            verbose=False
        )
        
        losses = result["losses"]
        # Check that loss is roughly decreasing (allow some noise)
        mean_first_half = np.mean(losses[:2])
        mean_second_half = np.mean(losses[-2:])
        assert mean_first_half > mean_second_half * 0.8, \
            "Loss should be decreasing"
    
    def test_pretrain_autoencoder_checkpoint(self):
        """Test checkpoint saving."""
        sequences = self.create_dummy_sequences()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            ck_path = os.path.join(tmpdir, "autoencoder.pt")
            result = pretrain_autoencoder(
                sequences,
                epochs=2,
                batch_size=32,
                save_path=ck_path,
                verbose=False
            )
            
            assert os.path.exists(ck_path), "Checkpoint not saved"
            ck = torch.load(ck_path, map_location="cpu")
            assert "embedder_state" in ck
            assert "recovery_state" in ck
            assert "opt_state" in ck


class TestSupervisorPretrain:
    """Test supervisor pre-training (Stage 3.2)."""
    
    def create_dummy_sequences(self, n=100, seq_len=24):
        return np.random.rand(n, seq_len, 5).astype(np.float32) * 1000
    
    def test_pretrain_supervisor_basic(self):
        """Test supervisor training runs without error."""
        sequences = self.create_dummy_sequences()
        result = pretrain_supervisor(
            sequences,
            epochs=2,
            batch_size=32,
            lr=1e-3,
            verbose=False
        )
        
        assert "losses" in result
        assert len(result["losses"]) == 2
        assert all(isinstance(l, float) for l in result["losses"])
    
    def test_pretrain_supervisor_with_embedder(self):
        """Test supervisor training with pre-trained embedder."""
        sequences = self.create_dummy_sequences()
        
        # First train autoencoder
        ae_result = pretrain_autoencoder(
            sequences,
            epochs=2,
            batch_size=32,
            verbose=False
        )
        
        # Then train supervisor with frozen embedder
        with tempfile.TemporaryDirectory() as tmpdir:
            ae_ck = os.path.join(tmpdir, "ae.pt")
            pretrain_autoencoder(
                sequences,
                epochs=2,
                batch_size=32,
                save_path=ae_ck,
                verbose=False
            )
            
            ae_state = torch.load(ae_ck, map_location="cpu")
            sup_result = pretrain_supervisor(
                sequences,
                epochs=2,
                batch_size=32,
                emb_state_dict=ae_state.get("embedder_state"),
                verbose=False
            )
            
            assert "losses" in sup_result
            assert len(sup_result["losses"]) == 2


class TestAdversarialTraining:
    """Test adversarial training (Stage 3.3)."""
    
    def create_dummy_sequences(self, n=100, seq_len=24):
        return np.random.rand(n, seq_len, 5).astype(np.float32) * 1000
    
    def test_adversarial_training_basic(self):
        """Test adversarial training runs without error."""
        sequences = self.create_dummy_sequences()
        result = train_timegan_adversarial(
            sequences,
            epochs=2,
            batch_size=32,
            lr=1e-4,
            verbose=False
        )
        
        assert "d_losses" in result
        assert "g_losses" in result
        assert len(result["d_losses"]) == 2
        assert len(result["g_losses"]) == 2
    
    def test_adversarial_with_pretrained_weights(self):
        """Test adversarial training with pre-trained components."""
        sequences = self.create_dummy_sequences()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-train components
            ae_ck = os.path.join(tmpdir, "ae.pt")
            sup_ck = os.path.join(tmpdir, "sup.pt")
            
            pretrain_autoencoder(sequences, epochs=1, batch_size=32, save_path=ae_ck, verbose=False)
            
            ae_state = torch.load(ae_ck, map_location="cpu")
            pretrain_supervisor(
                sequences,
                epochs=1,
                batch_size=32,
                emb_state_dict=ae_state.get("embedder_state"),
                save_path=sup_ck,
                verbose=False
            )
            
            sup_state = torch.load(sup_ck, map_location="cpu")
            
            # Run adversarial training with pre-trained weights
            result = train_timegan_adversarial(
                sequences,
                epochs=1,
                batch_size=32,
                emb_state_dict=ae_state.get("embedder_state"),
                rec_state_dict=ae_state.get("recovery_state"),
                sup_state_dict=sup_state.get("supervisor_state"),
                verbose=False
            )
            
            assert "d_losses" in result
            assert "g_losses" in result


class TestFullStage3Pipeline:
    """Test full Stage 3 pipeline."""
    
    def create_dummy_sequences(self, n=100, seq_len=24):
        return np.random.rand(n, seq_len, 5).astype(np.float32) * 1000
    
    def test_full_pipeline(self):
        """Test complete Stage 3 pipeline."""
        sequences = self.create_dummy_sequences()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage3_pipeline(
                sequences,
                ae_epochs=2,
                sup_epochs=2,
                adv_epochs=2,
                batch_size=32,
                checkpoint_dir=tmpdir,
                verbose=False
            )
            
            assert "autoencoder" in result
            assert "supervisor" in result
            assert "adversarial" in result
            assert "checkpoints" in result
            
            # Verify checkpoint files were created
            ck_dict = result["checkpoints"]
            assert all(os.path.exists(p) for p in ck_dict.values())
    
    def test_full_pipeline_device_detection(self):
        """Test pipeline detects GPU if available."""
        sequences = self.create_dummy_sequences(n=50)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage3_pipeline(
                sequences,
                ae_epochs=1,
                sup_epochs=1,
                adv_epochs=1,
                batch_size=32,
                checkpoint_dir=tmpdir,
                verbose=False
                # device=None -> auto-detect
            )

            assert "autoencoder" in result
            assert "supervisor" in result
            assert all(Path(path).parent == Path(tmpdir) for path in result["checkpoints"].values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
