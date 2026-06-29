"""Stage 5: RL Integration - Load synthetic data into trading environment."""

import os
import tempfile
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan import OHLCVScaler
from btc_scraper.ml_engine.timegan_trainer import run_stage3_pipeline
from btc_scraper.ml_engine.timegan_generate import (
    load_timegan_checkpoint,
    generate_and_postprocess,
    save_synthetic_candles,
    load_synthetic_candles,
)


def test_stage5_integration():
    """Test Stage 5: Loading synthetic candles for RL training."""
    print("\n" + "="*60)
    print("STAGE 5 INTEGRATION TEST: Synthetic Data for RL")
    print("="*60)
    
    # Create training data
    print("\n[1/5] Creating training data...")
    real_data = np.random.rand(300, 24, 5).astype(np.float32) * 100
    real_data[:, :, 0] = real_data[:, :, 0] * 50000 + 25000    # open
    real_data[:, :, 1] = real_data[:, :, 1] * 50000 + 30000    # high
    real_data[:, :, 2] = real_data[:, :, 2] * 50000 + 20000    # low
    real_data[:, :, 3] = real_data[:, :, 3] * 50000 + 25000    # close
    real_data[:, :, 4] = real_data[:, :, 4] * 100000           # volume
    
    scaler = OHLCVScaler()
    scaler.fit(real_data)
    real_scaled = scaler.transform(real_data)
    
    print(f"[OK] Real data: {real_scaled.shape}")
    
    # Train models
    print("\n[2/5] Training TimeGAN (Stage 3)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_stage3_pipeline(
            real_scaled,
            ae_epochs=1,
            sup_epochs=1,
            adv_epochs=1,
            batch_size=64,
            checkpoint_dir=tmpdir,
            verbose=False
        )
        
        adv_ckpt = result["checkpoints"]["adversarial"]
        
        # Generate synthetic data
        print("\n[3/5] Generating synthetic candles...")
        gen, rec = load_timegan_checkpoint(adv_ckpt, device="cpu")
        
        synthetic = generate_and_postprocess(
            gen,
            rec,
            scaler,
            n_sequences=1000,
            seq_len=24,
            batch_size=256,
            device="cpu"
        )
        
        print(f"[OK] Generated {len(synthetic)} sequences")
        
        # Save synthetic candles
        print("\n[4/5] Saving synthetic candles for RL...")
        candle_path = os.path.join(tmpdir, "rl_synthetic_candles.pkl")
        save_synthetic_candles(synthetic, candle_path)
        print(f"[OK] Saved to {candle_path}")
        
        # Load and verify
        print("\n[5/5] Verifying synthetic candles...")
        data = load_synthetic_candles(candle_path)
        
        print(f"[OK] Loaded {data['n_sequences']} synthetic sequences")
        print(f"     Features: {data['features']}")
        print(f"     Seq length: {data['seq_len']}")
        print(f"     Shape: {data['sequences'].shape}")
        print(f"     Price range: [{data['sequences'].min():.2f}, {data['sequences'].max():.2f}]")
        
        # Verify structure for RL integration
        sequences = data["sequences"]
        assert sequences.ndim == 3, "Sequences must be 3D"
        assert sequences.shape[2] == 5, "Each sequence must have 5 features (OHLCV)"
        assert sequences.dtype == np.float32, "Sequences must be float32"
        
        # Check value ranges are realistic
        opens = sequences[:, :, 0]
        highs = sequences[:, :, 1]
        lows = sequences[:, :, 2]
        closes = sequences[:, :, 3]
        volumes = sequences[:, :, 4]
        
        # Basic sanity checks
        assert (highs >= opens).mean() > 0.7, "High should be >= Open (70%)"
        assert (highs >= closes).mean() > 0.7, "High should be >= Close (70%)"
        assert (lows <= opens).mean() > 0.7, "Low should be <= Open (70%)"
        assert (lows <= closes).mean() > 0.7, "Low should be <= Close (70%)"
        
        print(f"\n[OK] Sanity checks passed")
        print(f"     High >= Open: {(highs >= opens).mean()*100:.1f}%")
        print(f"     High >= Close: {(highs >= closes).mean()*100:.1f}%")
        print(f"     Low <= Open: {(lows <= opens).mean()*100:.1f}%")
        print(f"     Low <= Close: {(lows <= closes).mean()*100:.1f}%")
    
    print("\n[PASS] STAGE 5 INTEGRATION TEST PASSED")
    print("\nNext steps:")
    print("1. Load synthetic candles in RL environment")
    print("2. Use as curriculum learning phase (easy data before real data)")
    print("3. Train RL agent on synthetic data")
    print("4. Fine-tune on real data")
    print()


if __name__ == "__main__":
    test_stage5_integration()
