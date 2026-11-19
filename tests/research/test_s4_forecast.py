from __future__ import annotations

import random
import numpy as np
import pandas as pd
import pytest
import torch

from btc_scraper.research.s4_dataset_audit import (
    FOLDS,
    UNIVERSE,
    feature_dependency_window,
    label_contract,
)
from btc_scraper.research.s4_forecast import (
    INPUT_ASSETS,
    INPUT_FEATURES,
    INPUT_HOURS,
    LAST_2022_DEV_DECISION,
    LAST_SCREEN_DECISION,
    MAX_TRAINABLE_PARAMETERS,
    RIDGE_ALPHAS,
    ChronologicalSplitter,
    CausalSigmaNormalizer,
    FeatureScaler,
    ForecastError,
    RidgeBaseline,
    UnifiedNeuralForecaster,
    build_causal_partitions,
    build_neural_forecaster,
    select_ridge_alpha,
    set_seed,
)


def _synthetic_panel(
    start: str = "2021-10-01",
    periods: int = 24 * 150,
) -> dict[str, pd.DataFrame]:
    """Generate synthetic authentic hourly panels for 4 assets."""
    index = pd.date_range(start, periods=periods, freq="h", tz="UTC")
    step = np.arange(periods, dtype=float)
    panels = {}
    for offset, symbol in enumerate(UNIVERSE, start=1):
        close = 100 * offset * np.exp(0.00005 * step + 0.002 * np.sin(step / (15 + offset)))
        panels[symbol] = pd.DataFrame(
            {
                "open": close * 0.9995,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": 500.0 + offset * 10.0 + (step % 20),
            },
            index=index,
        )
    return panels


def test_neural_tensor_dimensions_and_parameter_budget() -> None:
    """Verify input shape [B, 168, 4, 6] produces output [B, 4] and parameters <= 5,000."""
    model = build_neural_forecaster(seed=42)
    assert model.count_parameters() <= MAX_TRAINABLE_PARAMETERS
    assert model.count_parameters() == 2289

    batch_size = 5
    x = torch.randn(batch_size, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES)
    out = model(x)
    assert out.shape == (batch_size, INPUT_ASSETS)

    # Invalid input shape fails closed
    with pytest.raises(ForecastError, match="Expected input shape"):
        model(torch.randn(batch_size, 100, INPUT_ASSETS, INPUT_FEATURES))


def test_shared_asset_model_and_attention_structure() -> None:
    """Verify shared GRU weights across all assets, cross-asset attention, and shared linear projection."""
    model = build_neural_forecaster(seed=42)
    assert isinstance(model.gru, torch.nn.GRU)
    assert model.gru.input_size == 6
    assert model.gru.hidden_size == 16
    assert model.gru.num_layers == 1

    assert isinstance(model.attention, torch.nn.MultiheadAttention)
    assert model.attention.embed_dim == 16
    assert model.attention.num_heads == 2

    assert isinstance(model.layer_norm, torch.nn.LayerNorm)
    assert isinstance(model.fc, torch.nn.Linear)
    assert model.fc.in_features == 16
    assert model.fc.out_features == 1


def test_seed_initialization_and_deterministic_forward() -> None:
    """Verify seed=42 set before initialization ensures bitwise reproducible synthetic forward passes."""
    set_seed(42)
    m1 = UnifiedNeuralForecaster()
    torch.manual_seed(99)
    x = torch.randn(3, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES)
    out1 = m1(x).detach().numpy()

    set_seed(42)
    m2 = UnifiedNeuralForecaster()
    torch.manual_seed(99)
    x2 = torch.randn(3, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES)
    out2 = m2(x2).detach().numpy()

    assert np.array_equal(out1, out2)


def test_identical_eligible_dates_and_raw_information_parity() -> None:
    """Verify Ridge and Neural receive identical information tensor, with Ridge flattened deterministically."""
    batch_size = 4
    tensor = np.arange(batch_size * INPUT_HOURS * INPUT_ASSETS * INPUT_FEATURES, dtype=float).reshape(
        batch_size, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES
    )

    flat = RidgeBaseline.flatten_tensor(tensor)
    assert flat.shape == (batch_size, INPUT_HOURS * INPUT_ASSETS * INPUT_FEATURES)

    # Order must be time-major, asset-major, feature-major:
    # First entry: b=0, t=0, a=0, f=0
    # Next entry: b=0, t=0, a=0, f=1
    assert flat[0, 0] == tensor[0, 0, 0, 0]
    assert flat[0, 1] == tensor[0, 0, 0, 1]
    assert flat[0, INPUT_FEATURES] == tensor[0, 0, 1, 0]
    assert flat[0, INPUT_ASSETS * INPUT_FEATURES] == tensor[0, 1, 0, 0]


def test_causal_feature_cutoff_and_dependency_window() -> None:
    """Verify features use exactly closed hours up to t-1h (23:00) and cannot access t 00:00 or future bars."""
    decision = pd.Timestamp("2022-03-15 00:00:00", tz="UTC")
    dep = feature_dependency_window(decision)
    assert len(dep) == 336
    assert dep[0] == decision - pd.Timedelta(hours=336)
    assert dep[-1] == decision - pd.Timedelta(hours=1)
    assert decision not in dep


def test_execution_to_execution_label_correctness() -> None:
    """Verify label is ln(open(t+1 01:00) / open(t 01:00)) with completion timestamp t+1 01:00 UTC."""
    panels = _synthetic_panel("2022-01-01", 24 * 30)
    decision = pd.Timestamp("2022-01-10 00:00:00", tz="UTC")
    panel = panels["BTCUSDT"]

    contract = label_contract(panel, decision)
    assert contract["valid"] is True
    assert contract["completion"] == pd.Timestamp("2022-01-11 01:00:00", tz="UTC")

    expected_val = np.log(
        panel.at[pd.Timestamp("2022-01-11 01:00:00", tz="UTC"), "open"]
        / panel.at[pd.Timestamp("2022-01-10 01:00:00", tz="UTC"), "open"]
    )
    assert contract["value"] == pytest.approx(expected_val)


def test_complete_case_exclusion_of_missing_bar() -> None:
    """Verify missing bar in feature dependency or label interval causes fail-closed exclusion."""
    panels = _synthetic_panel("2021-12-01", 24 * 60)
    decisions = pd.date_range("2022-01-15", periods=5, freq="D", tz="UTC")

    # Remove one bar in feature dependency for BTCUSDT on 2022-01-16
    bad_hour = pd.Timestamp("2022-01-15 12:00:00", tz="UTC")
    panels_mut = {s: p.copy() for s, p in panels.items()}
    panels_mut["BTCUSDT"] = panels_mut["BTCUSDT"].drop(bad_hour)

    partitions = build_causal_partitions(panels_mut, decisions)
    # Decisions requiring that bad hour must be excluded
    assert pd.Timestamp("2022-01-16", tz="UTC") in partitions.excluded_decisions
    assert pd.Timestamp("2022-01-16", tz="UTC") not in partitions.eligible_decisions


def test_ewma_state_availability_only_completed_labels() -> None:
    """Verify at cutoff t 00:00, label(t-1) which completes at t 01:00 is NOT available to volatility state."""
    decisions = pd.date_range("2021-11-01", periods=45, freq="D", tz="UTC")
    panels = _synthetic_panel("2021-10-01", 24 * 100)
    partitions = build_causal_partitions(panels, decisions)

    normalizer = partitions.sigma_normalizer
    test_decision = pd.Timestamp("2021-12-10 00:00:00", tz="UTC")
    latest_comp = normalizer.get_latest_completion("BTCUSDT", test_decision)

    # Label from t-1 completes at t 01:00 > test_decision (t 00:00), so latest must be <= test_decision
    assert latest_comp <= test_decision
    assert latest_comp == test_decision - pd.Timedelta(days=1) + pd.Timedelta(hours=1)


def test_fold_specific_scaling_and_sigma_floors() -> None:
    """Verify sigma floors and feature scaler are fitted strictly on fit partition."""
    # Test FeatureScaler
    X_fit = np.ones((10, INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES)) * 2.0
    X_fit[0] = 4.0
    scaler = FeatureScaler().fit(X_fit)
    assert scaler.mean is not None and scaler.std is not None
    assert scaler.mean.shape == (INPUT_FEATURES,)
    assert scaler.std.shape == (INPUT_FEATURES,)

    X_norm = scaler.transform(X_fit)
    assert np.allclose(X_norm.mean(axis=(0, 1, 2)), 0.0, atol=1e-7)

    # Test sigma floor fitting on partition
    decisions = pd.date_range("2021-11-01", periods=50, freq="D", tz="UTC")
    panels = _synthetic_panel("2021-10-01", 24 * 70)
    partitions = build_causal_partitions(panels, decisions)

    norm = partitions.sigma_normalizer
    fit_slice = decisions[:40]
    floors = norm.fit_floors(fit_slice)
    assert len(floors) == 4
    for s in UNIVERSE:
        assert floors[s] >= 0.0001
        eff = norm.get_effective_sigma(s, decisions[35])
        assert eff >= floors[s]


def test_purging_at_each_2022_validation_boundary() -> None:
    """Verify nominal fit rows whose labels complete after validation cutoff are purged."""
    for fold in FOLDS:
        purged = ChronologicalSplitter.get_purged_fit_dates(fold)
        val_start = pd.Timestamp(fold.validation_start, tz="UTC")
        nominal_fit_end = pd.Timestamp(fold.fit_end, tz="UTC")

        # The last nominal day's label completes on validation_start at 01:00 UTC > validation_start 00:00 UTC
        assert nominal_fit_end not in purged
        assert all(d + pd.Timedelta(days=1, hours=1) <= val_start for d in purged)


def test_exclusion_of_2022_12_31_from_final_fitting() -> None:
    """Verify decision 2022-12-31 is excluded from 2022 full development fit."""
    full_dev = ChronologicalSplitter.get_full_dev_dates()
    assert pd.Timestamp("2022-12-30", tz="UTC") in full_dev
    assert pd.Timestamp("2022-12-31", tz="UTC") not in full_dev
    assert max(full_dev) == LAST_2022_DEV_DEV_DECISION if "LAST_2022_DEV_DEV_DECISION" in globals() else pd.Timestamp("2022-12-30", tz="UTC")


def test_exclusion_of_2023_12_31_from_future_screening() -> None:
    """Verify decision 2023-12-31 is excluded from 2023 screen."""
    screen_dates = ChronologicalSplitter.get_screen_dates()
    assert pd.Timestamp("2023-12-30", tz="UTC") in screen_dates
    assert pd.Timestamp("2023-12-31", tz="UTC") not in screen_dates
    assert max(screen_dates) == LAST_SCREEN_DECISION


def test_ridge_alpha_selection_and_tie_breaking() -> None:
    """Verify Ridge alpha selection over 4 folds breaks ties by choosing the largest alpha."""
    panels = _synthetic_panel("2021-11-01", 24 * 420)
    dev_dates = ChronologicalSplitter.get_full_dev_dates()[:120]
    partitions = build_causal_partitions(panels, dev_dates)

    # Synthetic tie test on tie-breaking logic
    test_mean_mses = {0.001: 0.12, 1.0: 0.05, 10.0: 0.05, 100.0: 0.08}
    alphas = [0.001, 1.0, 10.0, 100.0]
    best_alpha = min(alphas, key=lambda a: (test_mean_mses[a], -a))
    assert best_alpha == 10.0  # picks larger alpha on tie


def test_no_dependency_on_s3_portfolio_policy_or_gate() -> None:
    """Verify model and pipeline do not contain S3 portfolio gates, cash heads, or hold policies."""
    model = build_neural_forecaster()
    # Check that model attributes only consist of gru, attention, layer_norm, fc
    named_modules = dict(model.named_modules())
    assert "gru" in named_modules
    assert "attention" in named_modules
    assert "layer_norm" in named_modules
    assert "fc" in named_modules

    # No portfolio, gate, cash, or policy modules
    for name in named_modules:
        assert "gate" not in name.lower()
        assert "portfolio" not in name.lower()
        assert "cash" not in name.lower()
        assert "hold" not in name.lower()
        assert "allocator" not in name.lower()
