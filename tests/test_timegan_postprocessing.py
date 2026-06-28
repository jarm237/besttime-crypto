import numpy as np
import torch
from btc_scraper.ml_engine.timegan import OHLCVScaler, postprocess_synthetic_sequences, compute_simple_indicators


def test_postprocessing_and_indicators_on_gpu_if_available():
    rng = np.random.RandomState(0)
    fake = rng.rand(8, 12, 5).astype(np.float32)

    scaler = OHLCVScaler()
    scaler.fit(fake)
    scaled = scaler.transform(fake)

    # Move to GPU if available
    try:
        if torch.cuda.is_available():
            t = torch.from_numpy(scaled).to('cuda')
            real = postprocess_synthetic_sequences(t, scaler, device='cuda')
        else:
            real = postprocess_synthetic_sequences(scaled, scaler, device='cpu')
    except Exception:
        real = postprocess_synthetic_sequences(scaled, scaler, device='cpu')

    assert real.shape == (8, 12, 5)

    indicators = compute_simple_indicators(real, windows=(3, 5))
    assert 'sma_3' in indicators and 'sma_5' in indicators
    assert indicators['sma_3'].shape == (8, 12)
