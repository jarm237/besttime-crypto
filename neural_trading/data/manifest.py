"""
neural_trading/data/manifest.py

Dataset manifest generation, serialization, and quality audit checks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping
import numpy as np

from neural_trading.data.schema import TensorMetadata


def create_dataset_manifest(
    metadata: TensorMetadata,
    X: np.ndarray,
    y: np.ndarray,
    output_path: Path | None = None,
) -> Dict[str, Any]:
    """Generates a cryptographic dataset manifest with quality diagnostics."""
    # Compute content hash of X and y arrays
    hasher = hashlib.sha256()
    hasher.update(X.tobytes()[:1_000_000])  # Sample 1MB for fast hash
    hasher.update(y.tobytes()[:500_000])
    content_hash = hasher.hexdigest()

    nan_count_X = int(np.isnan(X).sum())
    inf_count_X = int(np.isinf(X).sum())
    nan_count_y = int(np.isnan(y).sum())

    manifest = {
        "manifest_version": "1.0.0",
        "dataset_id": "greenfield_neural_n0_v1",
        "dataset_content_hash": content_hash,
        "sample_count": metadata.num_samples,
        "universe_assets": metadata.symbols,
        "lookback_window_bars": metadata.lookback_window,
        "feature_channels": metadata.channel_names,
        "timeframe": metadata.timeframe,
        "temporal_range": {
            "start": metadata.start_timestamp,
            "end": metadata.end_timestamp,
        },
        "quality_audit": {
            "nan_values_in_features": nan_count_X,
            "inf_values_in_features": inf_count_X,
            "nan_values_in_targets": nan_count_y,
            "is_clean_and_finite": (nan_count_X == 0 and inf_count_X == 0 and nan_count_y == 0),
        },
        "shape_dimensions": {
            "X": list(X.shape),
            "y": list(y.shape),
        },
        "research_designation": "GREENFIELD_NEURAL_RESEARCH",
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    return manifest
