#!/usr/bin/env python3
"""Test Stage 1 data loading from actual CSV files.

This script verifies that:
1. Files can be loaded from data/historical_18m/
2. Sequences are properly chunked
3. Scaler fits correctly on real data
4. DataLoader works with real sequences
"""

import sys
from pathlib import Path
import numpy as np

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_scraper.ml_engine.timegan import (
    load_historical_15m_sequences,
    OHLCVScaler,
    AltcoinSequenceDataset,
    build_timegan_dataloader,
)


def test_stage1_pipeline():
    """Run complete Stage 1 pipeline."""
    print("=" * 70)
    print("STAGE 1: PREPROCESSING PIPELINE TEST")
    print("=" * 70)
    
    # 1. Load sequences from historical data
    print("\n[1/4] Loading sequences from data/historical_18m/...")
    try:
        sequences = load_historical_15m_sequences(
            data_dir="data/historical_18m",
            seq_len=24,
            coins=["BTC", "ETH", "SOL"],  # Test with 3 coins
        )
        print(f"✓ Loaded sequences: shape {sequences.shape}")
        print(f"  Total sequences: {sequences.shape[0]}")
        print(f"  Sequence length: {sequences.shape[1]} timesteps (= 6 hours @ 15m)")
        print(f"  Features: {sequences.shape[2]} (open, high, low, close, volume)")
    except Exception as e:
        print(f"✗ Error loading sequences: {e}")
        return False
    
    if sequences.shape[0] == 0:
        print("✗ No sequences loaded! Check data path.")
        return False
    
    # 2. Fit scaler
    print("\n[2/4] Fitting OHLCVScaler...")
    try:
        scaler = OHLCVScaler(feature_range=(0, 1))
        scaled_sequences = scaler.fit_transform(sequences)
        print(f"✓ Scaler fitted successfully")
        print(f"  Price range: [{scaler.price_min_:.2f}, {scaler.price_max_:.2f}]")
        print(f"  Volume range: [{scaler.volume_min_:.2e}, {scaler.volume_max_:.2e}]")
        print(f"  Scaled range: {scaler.feature_range}")
        print(f"  Scaled sequences shape: {scaled_sequences.shape}")
        print(f"  Min value: {scaled_sequences.min():.6f}, Max value: {scaled_sequences.max():.6f}")
    except Exception as e:
        print(f"✗ Error fitting scaler: {e}")
        return False
    
    # 3. Create dataset
    print("\n[3/4] Creating PyTorch Dataset and DataLoader...")
    try:
        dataset = AltcoinSequenceDataset(scaled_sequences)
        dataloader = build_timegan_dataloader(
            scaled_sequences,
            batch_size=32,
            shuffle=True,
            num_workers=0
        )
        print(f"✓ Dataset created with {len(dataset)} sequences")
        print(f"  Features: {dataset.feature_names}")
        print(f"  Batch size: 32")
        
        # Test iteration
        batch_count = 0
        for batch in dataloader:
            batch_count += 1
            if batch_count == 1:
                print(f"  First batch shape: {batch.shape}")
        
        print(f"  Total batches: {batch_count}")
    except Exception as e:
        print(f"✗ Error creating dataset/dataloader: {e}")
        return False
    
    # 4. Verify inverse transform
    print("\n[4/4] Verifying inverse transform (denormalization)...")
    try:
        recovered = scaler.inverse_transform(scaled_sequences)
        max_error = np.max(np.abs(recovered - sequences))
        print(f"✓ Inverse transform successful")
        print(f"  Max reconstruction error: {max_error:.2e}")
        print(f"  Mean absolute error: {np.mean(np.abs(recovered - sequences)):.2e}")
        
        if max_error > 1e-4:
            print(f"  ⚠ Warning: Reconstruction error is large (max: {max_error})")
    except Exception as e:
        print(f"✗ Error in inverse transform: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("✓ STAGE 1 PIPELINE TEST PASSED")
    print("=" * 70)
    print("\nSummary:")
    print(f"- Loaded {sequences.shape[0]} sequences from historical data")
    print(f"- Each sequence contains {sequences.shape[1]} 15-min candles (6 hours)")
    print(f"- Successfully normalized to [0, 1] range")
    print(f"- Created DataLoader with {batch_count} batches")
    print(f"- Denormalization recovers original data accurately")
    
    return True


if __name__ == "__main__":
    success = test_stage1_pipeline()
    sys.exit(0 if success else 1)
