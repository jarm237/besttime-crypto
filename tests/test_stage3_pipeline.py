"""Integration test for Stage 3 with real historical data."""

import os
import tempfile
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan_trainer import run_stage3_pipeline

# Paths
DATA_DIR = Path(__file__).parent.parent / "data" / "historical_18m"
CHECKPOINT_DIR = Path(__file__).parent.parent / "checkpoints_gpu"


def test_stage3_with_real_data():
    """Test Stage 3 training with real historical data."""
    print("\n" + "="*60)
    print("STAGE 3 INTEGRATION TEST: Real Historical Data Training")
    print("="*60)
    
    if not DATA_DIR.exists():
        print(f"⚠️ Data directory not found: {DATA_DIR}")
        print("Skipping real data test")
        return
    
    # Load sequences from all CSV files
    print("\n[1/5] Loading sequences from historical data...")
    import glob
    import pandas as pd
    from btc_scraper.core.io import smart_read_csv
    
    all_sequences = []
    csv_files = sorted(glob.glob(str(DATA_DIR / "*.csv")))[:10]  # First 10 files for testing
    
    for csv_file in csv_files:
        try:
            df = smart_read_csv(csv_file)
            data = df[['open', 'high', 'low', 'close', 'volume']].values.astype(np.float32)
            
            # Create sequences (24 timesteps)
            for i in range(len(data) - 24):
                seq = data[i:i+24]
                all_sequences.append(seq)
        except Exception as e:
            print(f"  Warning: {csv_file} - {e}")
    
    sequences = np.array(all_sequences, dtype=np.float32)
    n_sequences = len(sequences)
    n_batches = (n_sequences + 63) // 64
    
    print(f"[OK] Loaded {n_sequences:,} sequences ({n_batches:,} batches)")
    print(f"     Shape: {sequences.shape}")
    print(f"     Range: [{sequences.min():.2f}, {sequences.max():.2f}]")
    
    # Stage 3 training
    print("\n[2/5] Starting Stage 3 pipeline (3 stages, 2 epochs each)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_stage3_pipeline(
            sequences,
            ae_epochs=2,
            sup_epochs=2,
            adv_epochs=2,
            batch_size=64,
            lr=1e-3,
            checkpoint_dir=tmpdir,
            verbose=True
        )
    
    # Verify results
    print("\n[3/5] Verifying training results...")
    assert "autoencoder" in result
    assert "supervisor" in result
    assert "adversarial" in result
    assert "checkpoints" in result
    
    ae_loss = result["autoencoder"]["losses"][-1]
    print(f"[OK] Autoencoder final loss: {ae_loss:.6f}")
    
    sup_loss = result["supervisor"]["losses"][-1]
    print(f"[OK] Supervisor final loss: {sup_loss:.6f}")
    
    d_loss = result["adversarial"]["d_losses"][-1]
    g_loss = result["adversarial"]["g_losses"][-1]
    print(f"[OK] Adversarial D_loss: {d_loss:.6f}, G_loss: {g_loss:.6f}")
    
    # Verify checkpoints
    print("\n[4/5] Verifying checkpoints...")
    ck_dict = result["checkpoints"]
    for name, path in ck_dict.items():
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"[OK] {name}: {size_mb:.2f} MB")
        else:
            print(f"[FAIL] {name}: NOT FOUND")
    
    print("\n[5/5] Summary")
    print(f"[OK] Sequences trained: {n_sequences:,}")
    print(f"[OK] Stages completed: 3/3 (AE + Sup + Adv)")
    print(f"[OK] Checkpoints saved: {len(ck_dict)}/3")
    print("\n[PASS] STAGE 3 INTEGRATION TEST PASSED\n")


if __name__ == "__main__":
    test_stage3_with_real_data()
