"""Stage 4: Synthetic Data Generation Pipeline.

Generates synthetic OHLCV candles using trained TimeGAN generator.
"""

import os
import pickle
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import torch
import logging

from btc_scraper.ml_engine.timegan_model import (
    Embedder, Recovery, Generator, Supervisor, Discriminator
)
from btc_scraper.ml_engine.timegan import OHLCVScaler, postprocess_synthetic_sequences

logger = logging.getLogger(__name__)


def load_timegan_checkpoint(
    checkpoint_path: str,
    latent_dim: int = 32,
    hidden_dim: int = 64,
    device: str = "cpu"
) -> Tuple[Generator, Recovery]:
    """Load pre-trained Generator and Recovery from checkpoint.
    
    Args:
        checkpoint_path: Path to adversarial training checkpoint
        latent_dim: Latent dimension
        hidden_dim: Hidden dimension  
        device: Device to load on ("cpu" or "cuda")
        
    Returns:
        Tuple of (Generator, Recovery) models in eval mode
    """
    gen = Generator(noise_dim=latent_dim, hidden_dim=hidden_dim, latent_dim=latent_dim)
    rec = Recovery(latent_dim=latent_dim, hidden_dim=hidden_dim, output_size=5)
    
    if os.path.exists(checkpoint_path):
        ckpt = torch.load(checkpoint_path, map_location=device)
        if "generator_state" in ckpt and "recovery_state" in ckpt:
            gen.load_state_dict(ckpt["generator_state"])
            rec.load_state_dict(ckpt["recovery_state"])
            logger.info(f"Loaded generator and recovery from {checkpoint_path}")
        elif "generator_state" in ckpt:
            gen.load_state_dict(ckpt["generator_state"])
            logger.info(f"Loaded generator (recovery random) from {checkpoint_path}")
    else:
        logger.warning(f"Checkpoint not found: {checkpoint_path}. Using untrained models.")
    
    gen = gen.to(device)
    rec = rec.to(device)
    gen.eval()
    rec.eval()
    return gen, rec


def load_timegan_generator(
    checkpoint_path: str,
    latent_dim: int = 32,
    hidden_dim: int = 64,
    device: str = "cpu"
) -> Generator:
    """Load pre-trained Generator from checkpoint (legacy function).
    
    Args:
        checkpoint_path: Path to adversarial training checkpoint
        latent_dim: Generator latent dimension
        hidden_dim: Generator hidden dimension  
        device: Device to load on ("cpu" or "cuda")
        
    Returns:
        Generator model in eval mode on specified device
    """
    gen, _ = load_timegan_checkpoint(checkpoint_path, latent_dim, hidden_dim, device)
    return gen


def generate_synthetic_sequences(
    generator: Generator,
    recovery: Recovery,
    n_sequences: int = 10000,
    seq_len: int = 24,
    batch_size: int = 256,
    device: str = "cpu"
) -> np.ndarray:
    """Generate synthetic OHLCV sequences using trained generator + recovery.
    
    Args:
        generator: Trained Generator model (noise -> latent)
        recovery: Trained Recovery model (latent -> OHLCV)
        n_sequences: Number of sequences to generate
        seq_len: Sequence length (timesteps)
        batch_size: Generation batch size
        device: Device to generate on ("cpu" or "cuda")
        
    Returns:
        NumPy array of shape (n_sequences, seq_len, 5) with synthetic OHLCV in [0,1]
    """
    all_sequences = []
    
    with torch.no_grad():
        n_batches = (n_sequences + batch_size - 1) // batch_size
        
        for batch_idx in range(n_batches):
            # Calculate how many sequences for this batch
            start_idx = batch_idx * batch_size
            end_idx = min((batch_idx + 1) * batch_size, n_sequences)
            batch_n = end_idx - start_idx
            
            # Generate noise
            z = torch.randn(batch_n, seq_len, 32, device=device)
            
            # Generate synthetic latent
            e_fake = generator(z)  # (batch_n, seq_len, 32)
            
            # Recover to OHLCV space
            x_fake = recovery(e_fake)  # (batch_n, seq_len, 5)
            
            # Move to CPU and convert to numpy
            synthetic = x_fake.cpu().numpy().astype(np.float32)
            all_sequences.append(synthetic)
    
    # Stack all batches
    sequences = np.vstack(all_sequences)
    
    # Clip to [0, 1] range (sometimes outputs can slightly exceed bounds)
    sequences = np.clip(sequences, 0, 1)
    
    logger.info(f"Generated {len(sequences)} synthetic sequences")
    logger.info(f"  Shape: {sequences.shape}")
    logger.info(f"  Range: [{sequences.min():.4f}, {sequences.max():.4f}]")
    
    return sequences


def generate_and_postprocess(
    generator: Generator,
    recovery: Recovery,
    scaler: OHLCVScaler,
    n_sequences: int = 10000,
    seq_len: int = 24,
    batch_size: int = 256,
    device: str = "cpu",
    enforce_ohlc: bool = True
) -> np.ndarray:
    """Generate synthetic sequences and postprocess to real OHLCV values.
    
    Args:
        generator: Trained Generator model
        recovery: Trained Recovery model
        scaler: Fitted OHLCVScaler for inverse transformation
        n_sequences: Number of sequences to generate
        seq_len: Sequence length
        batch_size: Generation batch size
        device: Device to generate on
        enforce_ohlc: Whether to enforce OHLC constraints
        
    Returns:
        NumPy array of shape (n_sequences, seq_len, 5) with real-scale OHLCV values
    """
    # Generate synthetic sequences in [0,1]
    synthetic_scaled = generate_synthetic_sequences(
        generator,
        recovery,
        n_sequences=n_sequences,
        seq_len=seq_len,
        batch_size=batch_size,
        device=device
    )
    
    # Postprocess: denormalize + enforce constraints
    synthetic_real = postprocess_synthetic_sequences(
        synthetic_scaled,
        scaler=scaler,
        device=device,
        enforce_ohlc=enforce_ohlc
    )
    
    logger.info(f"Postprocessed {len(synthetic_real)} sequences")
    logger.info(f"  Real price range: [{synthetic_real.min():.2f}, {synthetic_real.max():.2f}]")
    
    return synthetic_real


def save_synthetic_candles(
    synthetic_sequences: np.ndarray,
    output_path: str = "data/rl_synthetic_candles.pkl"
) -> str:
    """Save synthetic candles to pickle file.
    
    Args:
        synthetic_sequences: Array of shape (N, T, 5) with OHLCV data
        output_path: Path to save pickle file
        
    Returns:
        Path to saved file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "sequences": synthetic_sequences,
        "n_sequences": len(synthetic_sequences),
        "seq_len": synthetic_sequences.shape[1],
        "features": ["open", "high", "low", "close", "volume"]
    }
    
    with open(output_path, "wb") as f:
        pickle.dump(data, f)
    
    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Saved {len(synthetic_sequences)} synthetic sequences to {output_path} ({size_mb:.2f} MB)")
    
    return str(output_path)


def load_synthetic_candles(path: str = "data/rl_synthetic_candles.pkl") -> Dict:
    """Load synthetic candles from pickle file.
    
    Args:
        path: Path to pickle file
        
    Returns:
        Dict with keys: sequences, n_sequences, seq_len, features
    """
    with open(path, "rb") as f:
        data = pickle.load(f)
    
    logger.info(f"Loaded {data['n_sequences']} synthetic sequences from {path}")
    return data


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example usage
    print("Stage 4 generation module loaded successfully")
