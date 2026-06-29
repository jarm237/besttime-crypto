"""Integration test for Stage 4 with trained models."""

import os
import tempfile
from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan_trainer import run_stage3_pipeline
from btc_scraper.ml_engine.timegan import OHLCVScaler
from btc_scraper.ml_engine.timegan_generate import (
    load_timegan_checkpoint,
    generate_and_postprocess,
    save_synthetic_candles,
    load_synthetic_candles,
)


def test_stage4_with_trained_models():
    """Test Stage 4 generation with models trained on real data."""
    print("\n" + "="*60)
    print("STAGE 4 INTEGRATION TEST: Generation with Trained Models")
    print("="*60)
    
    # Create real training data
    print("\n[1/6] Creating training data...")
    real_data = np.random.rand(200, 24, 5).astype(np.float32) * 100
    real_data[:, :, 0] = real_data[:, :, 0] * 100 + 100   # open: 100-10100
    real_data[:, :, 1] = real_data[:, :, 1] * 100 + 200   # high: 200-10200
    real_data[:, :, 2] = real_data[:, :, 2] * 100         # low: 0-10000
    real_data[:, :, 3] = real_data[:, :, 3] * 100 + 100   # close: 100-10100
    real_data[:, :, 4] = real_data[:, :, 4] * 10000       # volume: 0-100000
    
    scaler = OHLCVScaler()
    scaler.fit(real_data)
    real_scaled = scaler.transform(real_data)
    
    print(f"[OK] Training data: {real_scaled.shape}")
    print(f"     Price range (real): [{real_data.min():.2f}, {real_data.max():.2f}]")
    
    # Train models
    print("\n[2/6] Training Stage 3 pipeline (AE + Sup + Adv)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_stage3_pipeline(
            real_scaled,
            ae_epochs=1,
            sup_epochs=1,
            adv_epochs=1,
            batch_size=32,
            checkpoint_dir=tmpdir,
            verbose=False
        )
        
        adv_ckpt = result["checkpoints"]["adversarial"]
        print(f"[OK] Training complete")
        print(f"     AE loss: {result['autoencoder']['losses'][-1]:.6f}")
        print(f"     Sup loss: {result['supervisor']['losses'][-1]:.6f}")
        print(f"     D loss: {result['adversarial']['d_losses'][-1]:.6f}")
        print(f"     G loss: {result['adversarial']['g_losses'][-1]:.6f}")
        
        # Load models
        print("\n[3/6] Loading Generator and Recovery from checkpoint...")
        gen, rec = load_timegan_checkpoint(adv_ckpt, device="cpu")
        print(f"[OK] Models loaded")
        
        # Generate synthetic data
        print("\n[4/6] Generating synthetic sequences...")
        synthetic_real = generate_and_postprocess(
            gen,
            rec,
            scaler,
            n_sequences=500,
            seq_len=24,
            batch_size=256,
            device="cpu",
            enforce_ohlc=True
        )
        
        print(f"[OK] Generated {len(synthetic_real)} sequences")
        print(f"     Shape: {synthetic_real.shape}")
        print(f"     Real price range: [{synthetic_real.min():.2f}, {synthetic_real.max():.2f}]")
        
        # Save synthetic candles
        print("\n[5/6] Saving synthetic candles...")
        output_path = os.path.join(tmpdir, "synthetic_candles.pkl")
        saved_path = save_synthetic_candles(synthetic_real, output_path)
        size_mb = os.path.getsize(saved_path) / (1024 * 1024)
        print(f"[OK] Saved to {saved_path} ({size_mb:.2f} MB)")
        
        # Load and verify
        print("\n[6/6] Loading and verifying...")
        data = load_synthetic_candles(saved_path)
        assert data["n_sequences"] == 500
        assert data["seq_len"] == 24
        assert len(data["features"]) == 5
        np.testing.assert_array_equal(data["sequences"], synthetic_real)
        print(f"[OK] Verification passed")
        print(f"     Sequences: {data['n_sequences']}")
        print(f"     Seq length: {data['seq_len']}")
        print(f"     Features: {data['features']}")
    
    print("\n[PASS] STAGE 4 INTEGRATION TEST PASSED\n")


if __name__ == "__main__":
    test_stage4_with_trained_models()
