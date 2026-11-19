from __future__ import annotations

import random
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_END,
    AUDIT_START,
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
    CausalSigmaNormalizer,
    ChronologicalSplitter,
    FeatureScaler,
    ForecastError,
    ProtocolViolationError,
    RidgeBaseline,
    UnifiedNeuralForecaster,
    build_causal_partitions,
    build_neural_forecaster,
    select_ridge_alpha,
    set_seed,
)
from btc_scraper.research.s4_evaluation import (
    EXPECTED_FROZEN_HASHES,
    EXPECTED_NEURAL_PARAMS,
    EXPECTED_RIDGE_ALPHA,
    SPREAD_THRESHOLD_BPS,
    btc_relative_spread_diagnostics,
    compute_pearson_ic,
    compute_primary_statistics,
    decompose_common_and_relative,
    evaluate_scientific_verdict,
    extreme_day_sensitivity,
    fisher_z_aggregate,
    mincer_zarnowitz_calibration,
    paired_stationary_bootstrap,
    verify_and_load_frozen_artifacts,
)
from scripts.run_s4_stage1_screen import run_preflight


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


def test_historical_warmup_carries_into_2022_only_dataset() -> None:
    """Verify that supplying a 2022-only decision calendar carries all 2021 warmup labels without discarding."""
    dev_decisions = pd.date_range("2022-01-01", periods=10, freq="D", tz="UTC")
    panels = _synthetic_panel("2021-10-01", 24 * 120)
    partitions = build_causal_partitions(panels, dev_decisions, warmup_start=AUDIT_START)

    normalizer = partitions.sigma_normalizer
    first_dev = pd.Timestamp("2022-01-01", tz="UTC")
    for symbol in UNIVERSE:
        completed = normalizer.get_completed_count(symbol, first_dev)
        # Exactly 60 daily decisions from 2021-11-01 to 2021-12-30 completed before 2022-01-01 00:00
        assert completed == 60
        latest_c = normalizer.get_latest_completion(symbol, first_dev)
        assert latest_c <= first_dev
        assert np.isfinite(normalizer.get_raw_sigma(symbol, first_dev))


def test_validation_folds_respect_label_completion_boundaries() -> None:
    """Verify each validation fold evaluates only decisions whose labels complete no later than validation end."""
    for fold in FOLDS:
        val_dates = ChronologicalSplitter.get_validation_dates(fold)
        nominal_end = pd.Timestamp(fold.validation_end, tz="UTC")
        val_end_cutoff = nominal_end + pd.Timedelta(days=1)

        # The nominal last day completes at nominal_end + 1 day 01:00 UTC > val_end_cutoff, so must be excluded
        assert nominal_end not in val_dates
        assert all(d + pd.Timedelta(days=1, hours=1) <= val_end_cutoff for d in val_dates)

    # Verify specific F1 example: 2022-06-15 excluded, 2022-06-14 included
    f1_val = ChronologicalSplitter.get_validation_dates(FOLDS[0])
    assert pd.Timestamp("2022-06-15", tz="UTC") not in f1_val
    assert pd.Timestamp("2022-06-14", tz="UTC") in f1_val


def test_fold_specific_scaling_and_sigma_floors() -> None:
    """Verify sigma floors and feature scaler are fitted strictly on fit partition."""
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

        assert nominal_fit_end not in purged
        assert all(d + pd.Timedelta(days=1, hours=1) <= val_start for d in purged)


def test_exclusion_of_2022_12_31_from_final_fitting() -> None:
    """Verify decision 2022-12-31 is excluded from 2022 full development fit."""
    full_dev = ChronologicalSplitter.get_full_dev_dates()
    assert pd.Timestamp("2022-12-30", tz="UTC") in full_dev
    assert pd.Timestamp("2022-12-31", tz="UTC") not in full_dev
    assert max(full_dev) == LAST_2022_DEV_DECISION


def test_exclusion_of_2023_12_31_from_future_screening() -> None:
    """Verify decision 2023-12-31 is excluded from 2023 screen."""
    screen_dates = ChronologicalSplitter.get_screen_dates()
    assert pd.Timestamp("2023-12-30", tz="UTC") in screen_dates
    assert pd.Timestamp("2023-12-31", tz="UTC") not in screen_dates
    assert max(screen_dates) == LAST_SCREEN_DECISION


def test_select_ridge_alpha_executes_all_registered_alphas_and_folds() -> None:
    """Verify select_ridge_alpha evaluates all 8 registered alphas and all 4 folds."""
    panels = _synthetic_panel("2021-11-01", 24 * 420)
    dev_dates = ChronologicalSplitter.get_full_dev_dates()
    partitions = build_causal_partitions(panels, dev_dates)

    best_alpha, mean_mses, fold_mses = select_ridge_alpha(
        partitions.features,
        partitions.raw_labels,
        partitions.sigma_normalizer,
    )
    assert set(mean_mses.keys()) == set(RIDGE_ALPHAS)
    assert set(fold_mses.keys()) == {"F1", "F2", "F3", "F4"}
    for f in fold_mses:
        assert set(fold_mses[f].keys()) == set(RIDGE_ALPHAS)
        assert all(np.isfinite(fold_mses[f][a]) for a in RIDGE_ALPHAS)
    assert best_alpha in RIDGE_ALPHAS


def test_no_access_to_2024_2026() -> None:
    """Verify decisions or labels extending past authorized 2023-12-31 are rejected fail-closed."""
    panels = _synthetic_panel("2023-12-01", 24 * 40)
    forbidden_decision = pd.Timestamp("2023-12-31", tz="UTC")
    res = label_contract(panels["BTCUSDT"], forbidden_decision, authorized_end=AUDIT_END)
    assert res["valid"] is False
    assert res["reason"] == "EXIT_AFTER_AUTHORIZED_WINDOW"


def test_no_dependency_on_s3_portfolio_policy_or_gate() -> None:
    """Verify model and pipeline do not contain S3 portfolio gates, cash heads, or hold policies."""
    model = build_neural_forecaster()
    named_modules = dict(model.named_modules())
    assert "gru" in named_modules
    assert "attention" in named_modules
    assert "layer_norm" in named_modules
    assert "fc" in named_modules

    for name in named_modules:
        assert "gate" not in name.lower()
        assert "portfolio" not in name.lower()
        assert "cash" not in name.lower()
        assert "hold" not in name.lower()
        assert "allocator" not in name.lower()


def test_cli_development_mode_respects_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify development-2022 fails closed when --authorize-development flag is omitted."""
    import sys
    from scripts.run_s4_stage1_screen import main
    monkeypatch.setattr(sys, "argv", ["run_s4_stage1_screen.py", "--mode", "development-2022"])
    assert main() == 2


def test_cli_screen_mode_fails_closed_and_protects_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Verify screen-2023 fails closed without authorization and refuses to overwrite existing evidence."""
    import sys
    from scripts.run_s4_stage1_screen import main

    # Without authorization flag -> fails closed
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_s4_stage1_screen.py", "--mode", "screen-2023", "--output-dir", str(tmp_path)],
    )
    assert main() == 2

    # With authorization flag, if evidence already exists -> fails closed (immutable)
    evidence_file = tmp_path / "s4_stage1_2023_screen_evidence.json"
    evidence_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_s4_stage1_screen.py",
            "--mode",
            "screen-2023",
            "--authorize-one-shot-2023-screen",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert main() == 2


def test_verify_and_load_frozen_artifacts() -> None:
    """Verify loading real committed frozen artifacts matches all expected hashes and parameters."""
    evidence_dir = Path("research/s4_forecast_information_screening/stage1_evidence")
    frozen = verify_and_load_frozen_artifacts(evidence_dir)
    assert frozen.neural_model.count_parameters() == EXPECTED_NEURAL_PARAMS
    assert getattr(frozen.ridge_model.model, "alpha", None) == EXPECTED_RIDGE_ALPHA
    assert set(frozen.sigma_floors.keys()) == set(UNIVERSE)
    assert len(frozen.artifact_hashes) == 4

    # Test tampering or non-existent path fails closed
    with pytest.raises(ProtocolViolationError):
        verify_and_load_frozen_artifacts(Path("non_existent_directory"))


def test_compute_pearson_ic_and_fisher_z() -> None:
    """Verify Pearson IC and Fisher-z aggregation against exact mathematical formulations."""
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    assert pytest.approx(compute_pearson_ic(x, y), abs=1e-7) == 1.0

    y_neg = np.array([-1.0, -2.0, -3.0, -4.0, -5.0])
    assert pytest.approx(compute_pearson_ic(x, y_neg), abs=1e-7) == -1.0

    # Zero variance fails closed
    with pytest.raises(ForecastError, match="Zero variance"):
        compute_pearson_ic(np.ones(5), y)

    # Fisher-z aggregation
    ics = [0.1, 0.2, 0.3, 0.4]
    expected_s = np.tanh(np.mean([np.arctanh(ic) for ic in ics]))
    assert pytest.approx(fisher_z_aggregate(ics), abs=1e-7) == expected_s


def test_compute_primary_statistics() -> None:
    """Verify compute_primary_statistics returns valid per-asset ICs, S_neural, S_ridge, and Delta_S."""
    rng = np.random.default_rng(123)
    n = 100
    realized_z = rng.normal(0, 1, size=(n, 4))
    # neural has positive signal, ridge has weaker signal
    neural_zhat = realized_z * 0.2 + rng.normal(0, 1, size=(n, 4))
    ridge_zhat = realized_z * 0.05 + rng.normal(0, 1, size=(n, 4))

    stats = compute_primary_statistics(realized_z, neural_zhat, ridge_zhat)
    assert len(stats.per_asset_neural_ic) == 4
    assert len(stats.per_asset_ridge_ic) == 4
    assert stats.s_neural > stats.s_ridge
    assert pytest.approx(stats.delta_s, abs=1e-7) == (stats.s_neural - stats.s_ridge)


def test_paired_stationary_bootstrap_determinism_and_bounds() -> None:
    """Verify stationary bootstrap is deterministic given seed and produces valid 95% CIs."""
    rng = np.random.default_rng(42)
    n = 100
    realized_z = rng.normal(0, 1, size=(n, 4))
    neural_zhat = realized_z * 0.3 + rng.normal(0, 1, size=(n, 4))
    ridge_zhat = realized_z * 0.1 + rng.normal(0, 1, size=(n, 4))

    boot1 = paired_stationary_bootstrap(realized_z, neural_zhat, ridge_zhat, block_length=14.0, n_draws=100, seed=42)
    boot2 = paired_stationary_bootstrap(realized_z, neural_zhat, ridge_zhat, block_length=14.0, n_draws=100, seed=42)

    assert boot1.ci_lower_95 == boot2.ci_lower_95
    assert boot1.ci_upper_95 == boot2.ci_upper_95
    assert boot1.ci_lower_95 <= boot1.ci_upper_95
    assert boot1.valid_draws_count == 100
    assert boot1.invalid_draws_count == 0


def test_decompose_common_and_relative() -> None:
    """Verify decomposition separates market-wide signal from relative cross-asset signal."""
    rng = np.random.default_rng(101)
    n = 80
    market_factor = rng.normal(0, 1, size=(n, 1))
    asset_idiosyncratic = rng.normal(0, 0.5, size=(n, 4))
    realized_z = market_factor + asset_idiosyncratic
    neural_zhat = realized_z * 0.2 + rng.normal(0, 0.1, size=(n, 4))
    ridge_zhat = realized_z * 0.1 + rng.normal(0, 0.1, size=(n, 4))

    decomp = decompose_common_and_relative(realized_z, neural_zhat, ridge_zhat)
    assert "common_market_ic_neural" in decomp
    assert "common_market_ic_ridge" in decomp
    assert "relative_delta_s" in decomp
    assert len(decomp["per_asset_relative_ic_neural"]) == 4


def test_mincer_zarnowitz_and_btc_relative_spread() -> None:
    """Verify Mincer-Zarnowitz OLS regressions and BTC-relative spread diagnostics."""
    n = 100
    rng = np.random.default_rng(99)
    y = rng.normal(0, 0.02, size=(n, 4))
    yhat = y * 0.8 + rng.normal(0, 0.005, size=(n, 4))

    mz = mincer_zarnowitz_calibration(y, yhat)
    assert set(mz.keys()) == set(UNIVERSE)
    for sym in UNIVERSE:
        assert mz[sym]["beta"] > 0.5
        assert mz[sym]["r_squared"] > 0.0

    # Spread diagnostics
    ridge_yhat = yhat * 0.5
    spread_diag = btc_relative_spread_diagnostics(y, yhat, ridge_yhat)
    assert "ETH-BTC" in spread_diag
    assert "SOL-BTC" in spread_diag
    assert "BNB-BTC" in spread_diag
    for pair in ["ETH-BTC", "SOL-BTC", "BNB-BTC"]:
        assert spread_diag[pair]["total_dates"] == n
        assert "sign_accuracy_pct" in spread_diag[pair]["neural"]


def test_extreme_day_sensitivity() -> None:
    """Verify extreme day sensitivity excludes exactly ceil(0.05 * N) days."""
    n = 100
    rng = np.random.default_rng(77)
    decisions = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    realized_y = rng.normal(0, 0.02, size=(n, 4))
    # Make first 5 days extreme
    for i in range(5):
        realized_y[i, :] = (0.5 - i * 0.05)
    realized_z = realized_y * 10.0
    neural_zhat = realized_z * 0.1 + rng.normal(0, 0.01, size=(n, 4))
    ridge_zhat = realized_z * 0.05 + rng.normal(0, 0.01, size=(n, 4))

    sens = extreme_day_sensitivity(decisions, realized_y, realized_z, neural_zhat, ridge_zhat, drop_pct=0.05)
    assert sens["dropped_count"] == 5
    assert sens["kept_count"] == 95
    assert decisions[0].isoformat() in sens["dropped_dates"]


def test_scientific_verdict_engine() -> None:
    """Verify frozen 3-state decision logic maps correctly to SUPPORTED, NOT_SUPPORTED, INCONCLUSIVE."""
    # State 1: All criteria met -> SUPPORTED
    verdict, checks = evaluate_scientific_verdict(
        n_common=349,
        s_neural=0.08,
        ci_lower_14d=0.015,
        ci_upper_14d=0.09,
        mz_slopes=[0.5, 0.4, 0.6, 0.3],
        extreme_excluded_delta_s=0.02,
        protocol_valid=True,
    )
    assert verdict == "STAGE1_SIGNAL_SUPPORTED"
    assert all(checks.values())

    # State 2: S_neural <= 0 -> NOT_SUPPORTED
    verdict, checks = evaluate_scientific_verdict(
        n_common=349,
        s_neural=-0.01,
        ci_lower_14d=-0.05,
        ci_upper_14d=0.02,
        mz_slopes=[0.1, 0.2, 0.3, 0.4],
        extreme_excluded_delta_s=0.01,
        protocol_valid=True,
    )
    assert verdict == "STAGE1_SIGNAL_NOT_SUPPORTED"

    # State 2b: CI upper <= 0 -> NOT_SUPPORTED
    verdict, checks = evaluate_scientific_verdict(
        n_common=349,
        s_neural=0.02,
        ci_lower_14d=-0.04,
        ci_upper_14d=-0.001,
        mz_slopes=[0.1, 0.2, 0.3, 0.4],
        extreme_excluded_delta_s=0.01,
        protocol_valid=True,
    )
    assert verdict == "STAGE1_SIGNAL_NOT_SUPPORTED"

    # State 3: S_neural > 0, CI upper > 0, but CI lower <= 0 -> INCONCLUSIVE
    verdict, checks = evaluate_scientific_verdict(
        n_common=349,
        s_neural=0.04,
        ci_lower_14d=-0.01,
        ci_upper_14d=0.06,
        mz_slopes=[0.1, 0.2, 0.3, 0.4],
        extreme_excluded_delta_s=0.01,
        protocol_valid=True,
    )
    assert verdict == "STAGE1_SIGNAL_INCONCLUSIVE"

    # Invalid protocol
    verdict, checks = evaluate_scientific_verdict(
        n_common=349,
        s_neural=0.08,
        ci_lower_14d=0.015,
        ci_upper_14d=0.09,
        mz_slopes=[0.5, 0.4, 0.6, 0.3],
        extreme_excluded_delta_s=0.02,
        protocol_valid=False,
    )
    assert verdict == "INVALID_PROTOCOL"

