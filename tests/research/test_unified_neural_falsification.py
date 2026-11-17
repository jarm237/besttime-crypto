"""Targeted regression tests for temporal fidelity, purge/embargo, and economic controls."""

import pytest
import numpy as np
import pandas as pd
import torch
from datetime import datetime, timezone, timedelta

from btc_scraper.research.unified_neural_pilot import (
    DatasetSplits,
    SampleMetadata,
    UnifiedNeuralPolicy,
    compute_cost_aware_loss,
    extract_point_in_time_features,
    prepare_dataset_splits,
    train_shuffled_control,
)


def test_temporal_metadata_and_forward_holding_return_alignment():
    """Verify exact alignment of decision_time, feature_cutoff_time, execution_time, and label_end_time."""
    symbols = ["ADAUSDT", "BTCUSDT"]
    # 600 hourly bars starting on a Saturday
    start_ts = pd.Timestamp("2023-01-07 00:00:00+00:00")
    timestamps = [start_ts + pd.Timedelta(hours=h) for h in range(600)]
    
    # Construct synthetic OHLC
    close_data = {s: np.linspace(100.0, 200.0, len(timestamps)) for s in symbols}
    open_data = {s: np.linspace(99.0, 199.0, len(timestamps)) for s in symbols}
    piv_close = pd.DataFrame(close_data, index=timestamps)
    piv_open = pd.DataFrame(open_data, index=timestamps)

    X, Y, dates, names, metadata = extract_point_in_time_features(
        piv_close=piv_close,
        piv_open=piv_open,
        include_regime=False,
        causal_delay_bars=2,
        rebalance_interval_hours=168,
        btc_symbol="BTCUSDT",
    )

    assert len(dates) > 0
    assert len(metadata) == len(dates)
    assert X.shape[0] == len(dates)
    assert Y.shape[0] == len(dates)

    for w, meta in enumerate(metadata):
        assert meta.decision_time == dates[w]
        assert meta.decision_time.weekday() == 6  # Sunday
        assert meta.decision_time.hour == 0       # 00:00 UTC
        assert meta.feature_cutoff_time == meta.decision_time - pd.Timedelta(hours=2)
        assert meta.execution_time == meta.decision_time
        assert meta.label_end_time == meta.decision_time + pd.Timedelta(hours=168)

        # Check holding return matches open-to-open execution
        p_open_exec = piv_open.loc[meta.execution_time].to_numpy()
        p_open_next = piv_open.loc[meta.label_end_time].to_numpy()
        expected_ret = (p_open_next / p_open_exec) - 1.0
        assert np.allclose(Y[w], expected_ret, atol=1e-5)


def test_purge_and_embargo_split_boundaries():
    """Verify that samples whose forward target crosses Train or Val boundary are purged/embargoed."""
    symbols = ["ADAUSDT", "BTCUSDT"]
    
    # Create 3 weekly decisions:
    # 1. 2023-12-24: label_end 2023-12-31 (<= train_end -> valid Train)
    # 2. 2023-12-31: label_end 2024-01-07 (> train_end -> MUST BE PURGED from Train!)
    # 3. 2024-01-07: label_end 2024-01-14 (<= val_end -> valid Val)
    # 4. 2024-12-29: label_end 2025-01-05 (> val_end -> MUST BE PURGED from Val!)
    # 5. 2025-01-05: label_end 2025-01-12 (> val_end -> valid Holdout)
    dates = [
        pd.Timestamp("2023-12-24 00:00:00+00:00"),
        pd.Timestamp("2023-12-31 00:00:00+00:00"),
        pd.Timestamp("2024-01-07 00:00:00+00:00"),
        pd.Timestamp("2024-12-29 00:00:00+00:00"),
        pd.Timestamp("2025-01-05 00:00:00+00:00"),
    ]
    W, N, F = len(dates), len(symbols), 8
    X = np.ones((W, N, F), dtype=np.float32)
    Y = np.zeros((W, N), dtype=np.float32)

    sample_meta = [
        SampleMetadata(
            decision_index=w,
            decision_time=ts,
            feature_cutoff_time=ts - pd.Timedelta(hours=2),
            execution_time=ts,
            label_end_time=ts + pd.Timedelta(hours=168),
        )
        for w, ts in enumerate(dates)
    ]

    train_end = pd.Timestamp("2023-12-31 23:59:59+00:00")
    val_end = pd.Timestamp("2024-12-31 23:59:59+00:00")

    splits = prepare_dataset_splits(
        X=X,
        Y=Y,
        dates=dates,
        symbols=symbols,
        feature_names=[f"f{i}" for i in range(F)],
        sample_metadata=sample_meta,
        train_end=train_end,
        val_end=val_end,
    )

    # Sample 0: Train
    assert splits.train_dates == [dates[0]]
    assert len(splits.train_x) == 1

    # Sample 1 (2023-12-31): MUST BE PURGED
    # Sample 3 (2024-12-29): MUST BE PURGED
    assert len(splits.purged_metadata) == 2
    purged_indices = [m.decision_index for m in splits.purged_metadata]
    assert 1 in purged_indices
    assert 3 in purged_indices

    # Sample 2: Val
    assert splits.val_dates == [dates[2]]
    assert len(splits.val_x) == 1

    # Sample 4: Holdout
    assert splits.holdout_dates == [dates[4]]
    assert len(splits.holdout_x) == 1

    # Ensure no training sample has label_end > train_end
    for meta in splits.all_metadata:
        if meta.split == "train":
            assert meta.label_end_time <= train_end
        elif meta.split == "val":
            assert meta.label_end_time <= val_end


def test_cost_aware_loss_with_drift_autograd():
    """Verify that compute_cost_aware_loss with use_drift=True computes clean gradients."""
    W, N, F = 10, 8, 8
    model = UnifiedNeuralPolicy(num_assets=N, in_features=F, hidden_dim=16)

    x = torch.randn(W, N, F)
    forward_rets = torch.randn(W, N) * 0.05

    weights = model(x)
    loss, mean_ret, downside, turnover = compute_cost_aware_loss(
        weights=weights,
        forward_returns=forward_rets,
        fee_bps=12.0,
        lambda_downside=1.0,
        lambda_turnover=0.002,
        use_drift=True,
    )

    loss.backward()

    # Check parameters have valid non-zero gradients
    has_grad = False
    for p in model.parameters():
        if p.grad is not None:
            assert not torch.isnan(p.grad).any()
            assert not torch.isinf(p.grad).any()
            if p.grad.abs().sum() > 0:
                has_grad = True
    assert has_grad is True
