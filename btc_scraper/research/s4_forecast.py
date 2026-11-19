"""S4-P1A Forecasting Components: Causal Pipeline, Ridge Baseline, and Shared Neural Forecaster.

Frozen specification: research/s4_forecast_information_screening/s4_p0_executable_preregistration.md
Frozen commit: 7b5a97becbd6da1249a484ed588133761cc57bd0
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
import torch
import torch.nn as nn

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_END,
    AUDIT_START,
    BINANCE_COLUMNS,
    FOLDS,
    LAMBDA,
    MIN_SIGMA_HISTORY,
    UNIVERSE,
    Fold,
    _decision_range,
    build_feature_tensor,
    causal_raw_sigma,
    feature_dependency_window,
    indexed_panel,
    label_contract,
    load_binance_archives,
)

S4_PREREGISTRATION_COMMIT = "7b5a97becbd6da1249a484ed588133761cc57bd0"
INPUT_HOURS = 168
INPUT_ASSETS = 4
INPUT_FEATURES = 6
MAX_TRAINABLE_PARAMETERS = 5000
TARGET_CLIP = 4.0
MIN_SIGMA_FLOOR = 0.0001
SIGMA_FLOOR_FACTOR = 0.1
RIDGE_ALPHAS = (0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)

LAST_2022_DEV_DECISION = pd.Timestamp("2022-12-30", tz="UTC")
LAST_SCREEN_DECISION = pd.Timestamp("2023-12-30", tz="UTC")


class ForecastError(RuntimeError):
    """Raised when a forecast pipeline contract or protocol guard is violated."""


class ProtocolViolationError(ForecastError):
    """Raised when an attempt is made to violate the frozen research protocol."""


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 42
    learning_rate: float = 0.001
    weight_decay: float = 0.001
    batch_size: int = 32
    epochs: int = 30
    shuffle: bool = False
    checkpoint: str = "final_epoch"


def set_seed(seed: int = 42) -> None:
    """Set random seeds before model initialization for deterministic execution."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)


class FeatureScaler:
    """Computes mean and population standard deviation (ddof=0) across all fit-partition

    asset/hour observations for each of the 6 feature channels. Applied identically to all assets.
    """

    def __init__(self, mean: np.ndarray | None = None, std: np.ndarray | None = None) -> None:
        self.mean = np.asarray(mean, dtype=float) if mean is not None else None
        self.std = np.asarray(std, dtype=float) if std is not None else None

    def fit(self, X: np.ndarray) -> FeatureScaler:
        """Fit scaler parameters on fit-partition tensors.

        X shape: [N, 168, 4, 6]
        """
        if X.ndim != 4 or X.shape[1:] != (INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES):
            raise ForecastError(f"Expected X with shape (N, 168, 4, 6), got {X.shape}")
        if not np.isfinite(X).all():
            raise ForecastError("Fit-partition features contain non-finite values")

        mean = np.mean(X, axis=(0, 1, 2))  # shape: (6,)
        std = np.std(X, axis=(0, 1, 2), ddof=0)  # shape: (6,)

        if not np.isfinite(mean).all() or not np.isfinite(std).all():
            raise ForecastError("Fitted scaler parameters contain non-finite values")
        if (std < 1e-12).any():
            raise ForecastError(f"Fitted feature std < 1e-12: {std}")

        self.mean = mean
        self.std = std
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.mean is None or self.std is None:
            raise ForecastError("FeatureScaler must be fitted before transforming")
        if not np.isfinite(X).all():
            raise ForecastError("Transform input contains non-finite values")
        return (X - self.mean) / self.std

    def to_dict(self) -> dict[str, list[float]]:
        if self.mean is None or self.std is None:
            raise ForecastError("FeatureScaler is not fitted")
        return {
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, list[float]]) -> FeatureScaler:
        return cls(
            mean=np.array(data["mean"], dtype=float),
            std=np.array(data["std"], dtype=float),
        )


class CausalSigmaNormalizer:
    """Manages causal volatility states, independent fold sigma floors, and standardized targets.

    Floor epsilon_i = max(0.0001, 0.1 * median(raw sigma on eligible fit-partition decision dates)).
    Target = clip(y / effective_sigma, -4, +4).
    """

    def __init__(
        self,
        raw_sigma_df: pd.DataFrame,
        floors: dict[str, float] | None = None,
    ) -> None:
        # raw_sigma_df is indexed by (symbol, decision) with columns: completed_count, latest_completion, raw_sigma
        self.raw_sigma_df = raw_sigma_df
        self.floors = floors.copy() if floors is not None else {}

    @classmethod
    def from_labels(
        cls,
        labels_by_symbol: Mapping[str, pd.DataFrame],
        decisions: Iterable[pd.Timestamp],
    ) -> CausalSigmaNormalizer:
        frames = []
        for symbol in UNIVERSE:
            raw = causal_raw_sigma(labels_by_symbol[symbol], decisions)
            raw["symbol"] = symbol
            frames.append(raw.reset_index())
        combined = pd.concat(frames, ignore_index=True).set_index(["symbol", "decision"])
        return cls(combined)

    def fit_floors(self, fit_decisions: Iterable[pd.Timestamp]) -> dict[str, float]:
        fit_decisions_set = set(pd.Timestamp(d) for d in fit_decisions)
        floors = {}
        for symbol in UNIVERSE:
            sigmas = []
            for d in fit_decisions_set:
                key = (symbol, d)
                if key in self.raw_sigma_df.index:
                    val = self.raw_sigma_df.at[key, "raw_sigma"]
                    if np.isfinite(val):
                        sigmas.append(float(val))
            if len(sigmas) == 0:
                raise ForecastError(f"No finite raw sigma for symbol {symbol} in fit partition")
            med = float(np.median(sigmas))
            floor = max(MIN_SIGMA_FLOOR, SIGMA_FLOOR_FACTOR * med)
            floors[symbol] = floor
        self.floors = floors
        return floors

    def get_raw_sigma(self, symbol: str, decision: pd.Timestamp) -> float:
        key = (symbol, pd.Timestamp(decision))
        if key not in self.raw_sigma_df.index:
            raise ForecastError(f"Missing sigma record for {symbol} at {decision}")
        return float(self.raw_sigma_df.at[key, "raw_sigma"])

    def get_latest_completion(self, symbol: str, decision: pd.Timestamp) -> pd.Timestamp:
        key = (symbol, pd.Timestamp(decision))
        if key not in self.raw_sigma_df.index:
            raise ForecastError(f"Missing sigma record for {symbol} at {decision}")
        return self.raw_sigma_df.at[key, "latest_completion"]

    def get_effective_sigma(self, symbol: str, decision: pd.Timestamp) -> float:
        if symbol not in self.floors:
            raise ForecastError(f"Sigma floor has not been fitted for symbol {symbol}")
        raw = self.get_raw_sigma(symbol, decision)
        if not np.isfinite(raw):
            raise ForecastError(f"Non-finite raw sigma for {symbol} at {decision}")
        return max(raw, self.floors[symbol])

    def standardize_target(
        self,
        y: float,
        symbol: str,
        decision: pd.Timestamp,
        clip: bool = True,
    ) -> float:
        sigma = self.get_effective_sigma(symbol, decision)
        z = y / sigma
        if clip:
            return float(np.clip(z, -TARGET_CLIP, TARGET_CLIP))
        return float(z)

    def standardize_target_vector(
        self,
        y_vec: Sequence[float],
        decision: pd.Timestamp,
        clip: bool = True,
    ) -> np.ndarray:
        if len(y_vec) != len(UNIVERSE):
            raise ForecastError(f"Expected {len(UNIVERSE)} targets, got {len(y_vec)}")
        res = []
        for symbol, y in zip(UNIVERSE, y_vec):
            res.append(self.standardize_target(y, symbol, decision, clip=clip))
        return np.array(res, dtype=float)

    def to_dict(self) -> dict[str, float]:
        return self.floors.copy()


class ChronologicalSplitter:
    """Manages 2022 expanding-window cross-validation folds, purging, and evaluation calendars."""

    @staticmethod
    def get_folds() -> tuple[Fold, ...]:
        return FOLDS

    @staticmethod
    def get_purged_fit_dates(fold: Fold) -> list[pd.Timestamp]:
        """Return nominal fit dates whose label completes strictly on or before first validation decision cutoff."""
        nominal = _decision_range(fold.fit_start, fold.fit_end)
        validation_cutoff = pd.Timestamp(fold.validation_start, tz="UTC")
        completion = nominal + pd.Timedelta(days=1, hours=1)
        eligible = nominal[completion <= validation_cutoff]
        return list(eligible)

    @staticmethod
    def get_validation_dates(fold: Fold) -> list[pd.Timestamp]:
        """Return validation dates for fold whose label completes within authorized window."""
        nominal = _decision_range(fold.validation_start, fold.validation_end)
        authorized_end = pd.Timestamp("2023-12-31 23:00:00", tz="UTC")
        completion = nominal + pd.Timedelta(days=1, hours=1)
        eligible = nominal[completion <= authorized_end]
        return list(eligible)

    @staticmethod
    def get_full_dev_dates() -> list[pd.Timestamp]:
        """Decisions in 2022 with label completion <= 2023-01-01 00:00 UTC.

        Decision 2022-12-31 is explicitly excluded (completes 2023-01-01 01:00 UTC).
        """
        nominal = _decision_range("2022-01-01", "2022-12-30")
        return list(nominal)

    @staticmethod
    def get_screen_dates() -> list[pd.Timestamp]:
        """Screening decisions in 2023: 2023-01-01 through 2023-12-30.

        Decision 2023-12-31 is explicitly excluded to avoid 2024 label access.
        """
        nominal = _decision_range("2023-01-01", "2023-12-30")
        return list(nominal)


class UnifiedNeuralForecaster(nn.Module):
    """Exactly one shared neural forecaster:

    Shared GRU(input_size=6, hidden_size=16, num_layers=1)
    Cross-asset MultiheadAttention(embed_dim=16, num_heads=2, dropout=0)
    Residual + LayerNorm(16)
    Shared Linear(16, 1) -> [B, 4]

    Trainable parameters <= 5,000.
    """

    def __init__(
        self,
        input_size: int = INPUT_FEATURES,
        hidden_size: int = 16,
        num_heads: int = 2,
    ) -> None:
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_heads = num_heads

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
        )
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=num_heads,
            batch_first=True,
            dropout=0.0,
        )
        self.layer_norm = nn.LayerNorm(hidden_size)
        self.fc = nn.Linear(hidden_size, 1)

        param_count = self.count_parameters()
        if param_count > MAX_TRAINABLE_PARAMETERS:
            raise ForecastError(
                f"Model parameter count {param_count} exceeds budget {MAX_TRAINABLE_PARAMETERS}"
            )

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Input: [B, 168, 4, 6]
        Output: [B, 4]
        """
        if x.ndim != 4 or x.shape[1:] != (INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES):
            raise ForecastError(f"Expected input shape (B, 168, 4, 6), got {x.shape}")

        batch_size, seq_len, num_assets, feat_dim = x.shape
        # Permute to [B, num_assets, seq_len, feat_dim] -> reshape to [B * num_assets, seq_len, feat_dim]
        x_reshaped = x.permute(0, 2, 1, 3).reshape(batch_size * num_assets, seq_len, feat_dim)
        _, h_n = self.gru(x_reshaped)  # h_n shape: [1, B * num_assets, hidden_size]
        h = h_n.squeeze(0).reshape(batch_size, num_assets, self.hidden_size)  # [B, 4, 16]

        attn_out, _ = self.attention(query=h, key=h, value=h)  # [B, 4, 16]
        h_norm = self.layer_norm(h + attn_out)  # [B, 4, 16]
        out = self.fc(h_norm)  # [B, 4, 1]
        return out.squeeze(-1)  # [B, 4]


def build_neural_forecaster(seed: int = 42) -> UnifiedNeuralForecaster:
    """Build and initialize the single shared neural forecaster with deterministic seed."""
    set_seed(seed)
    return UnifiedNeuralForecaster()


class RidgeBaseline:
    """Multi-output Ridge baseline receiving identical information flattened deterministically."""

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = float(alpha)
        self.model = Ridge(alpha=self.alpha, fit_intercept=True)

    @staticmethod
    def flatten_tensor(X: np.ndarray) -> np.ndarray:
        """Flatten [B, 168, 4, 6] deterministically into [B, 168*4*6] in time-major, asset-major, feature-major order."""
        if X.ndim != 4 or X.shape[1:] != (INPUT_HOURS, INPUT_ASSETS, INPUT_FEATURES):
            raise ForecastError(f"Expected X with shape (B, 168, 4, 6), got {X.shape}")
        return X.reshape(X.shape[0], INPUT_HOURS * INPUT_ASSETS * INPUT_FEATURES)

    def fit(self, X: np.ndarray, y: np.ndarray) -> RidgeBaseline:
        """Fit Ridge on flattened features and multi-output clipped standardized targets.

        X: [B, 168, 4, 6] or [B, 4032]
        y: [B, 4]
        """
        X_flat = self.flatten_tensor(X) if X.ndim == 4 else X
        if y.ndim != 2 or y.shape[1] != INPUT_ASSETS:
            raise ForecastError(f"Expected y with shape (B, 4), got {y.shape}")
        if len(X_flat) != len(y):
            raise ForecastError(f"Length mismatch: X={len(X_flat)}, y={len(y)}")
        self.model.fit(X_flat, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X_flat = self.flatten_tensor(X) if X.ndim == 4 else X
        return self.model.predict(X_flat)


def select_ridge_alpha(
    features_by_date: Mapping[pd.Timestamp, np.ndarray],
    raw_labels_by_date: Mapping[pd.Timestamp, np.ndarray],
    sigma_normalizer: CausalSigmaNormalizer,
    folds: Sequence[Fold] = FOLDS,
    alphas: Sequence[float] = RIDGE_ALPHAS,
) -> tuple[float, dict[float, float], dict[str, dict[float, float]]]:
    """Select alpha minimizing arithmetic mean of the four fold MSEs on clipped standardized targets.

    Ties break by choosing the largest alpha.
    """
    fold_mses: dict[str, dict[float, float]] = {f.name: {} for f in folds}
    mean_mses: dict[float, float] = {}

    for fold in folds:
        purged_fit_dates = [d for d in ChronologicalSplitter.get_purged_fit_dates(fold) if d in features_by_date and d in raw_labels_by_date]
        val_dates = [d for d in ChronologicalSplitter.get_validation_dates(fold) if d in features_by_date and d in raw_labels_by_date]

        if len(purged_fit_dates) == 0 or len(val_dates) == 0:
            raise ForecastError(f"Fold {fold.name} has empty fit or validation partition")

        # Fit feature scaler on fold fit partition
        X_fit_raw = np.stack([features_by_date[d] for d in purged_fit_dates], axis=0)
        scaler = FeatureScaler().fit(X_fit_raw)
        X_fit_norm = scaler.transform(X_fit_raw)
        X_fit_flat = RidgeBaseline.flatten_tensor(X_fit_norm)

        X_val_raw = np.stack([features_by_date[d] for d in val_dates], axis=0)
        X_val_norm = scaler.transform(X_val_raw)
        X_val_flat = RidgeBaseline.flatten_tensor(X_val_norm)

        # Fit fold sigma floors independently inside development folds
        fold_normalizer = CausalSigmaNormalizer(sigma_normalizer.raw_sigma_df)
        fold_normalizer.fit_floors(purged_fit_dates)

        # Compute clipped targets using fold's floor
        y_fit = np.stack([
            fold_normalizer.standardize_target_vector(raw_labels_by_date[d], d, clip=True)
            for d in purged_fit_dates
        ], axis=0)

        y_val = np.stack([
            fold_normalizer.standardize_target_vector(raw_labels_by_date[d], d, clip=True)
            for d in val_dates
        ], axis=0)

        for alpha in alphas:
            ridge = Ridge(alpha=alpha, fit_intercept=True)
            ridge.fit(X_fit_flat, y_fit)
            preds = ridge.predict(X_val_flat)
            mse = float(np.mean((y_val - preds) ** 2))
            fold_mses[fold.name][alpha] = mse

    for alpha in alphas:
        mean_mses[alpha] = float(np.mean([fold_mses[f.name][alpha] for f in folds]))

    # Tie breaking: minimize mean MSE, if tied pick largest alpha
    best_alpha = min(alphas, key=lambda a: (mean_mses[a], -a))
    return best_alpha, mean_mses, fold_mses


@dataclass(frozen=True)
class DatasetPartitions:
    features: dict[pd.Timestamp, np.ndarray]
    raw_labels: dict[pd.Timestamp, np.ndarray]
    sigma_normalizer: CausalSigmaNormalizer
    eligible_decisions: list[pd.Timestamp]
    excluded_decisions: dict[pd.Timestamp, str]


def build_causal_partitions(
    panels: Mapping[str, pd.DataFrame],
    decisions: Iterable[pd.Timestamp],
    authorized_end: pd.Timestamp = AUDIT_END,
) -> DatasetPartitions:
    """Extract complete-case feature tensors, labels, and causal sigma states.

    Fails closed on any missing bar or anomaly.
    """
    sorted_decisions = sorted(pd.Timestamp(d) for d in decisions)
    features: dict[pd.Timestamp, np.ndarray] = {}
    raw_labels: dict[pd.Timestamp, np.ndarray] = {}
    excluded: dict[pd.Timestamp, str] = {}

    labels_by_symbol: dict[str, list[dict[str, object]]] = {s: [] for s in UNIVERSE}
    all_label_decisions = _decision_range(
        sorted_decisions[0].strftime("%Y-%m-%d"),
        sorted_decisions[-1].strftime("%Y-%m-%d"),
    )

    for symbol in UNIVERSE:
        for d in all_label_decisions:
            res = label_contract(panels[symbol], d, authorized_end=authorized_end)
            labels_by_symbol[symbol].append({"decision": d, **res})
    labels_dfs = {s: pd.DataFrame(records).set_index("decision") for s, records in labels_by_symbol.items()}

    normalizer = CausalSigmaNormalizer.from_labels(labels_dfs, sorted_decisions)

    for d in sorted_decisions:
        # Check label validity across all 4 assets
        label_vals = []
        valid_label = True
        exclusion_reason = ""
        for symbol in UNIVERSE:
            rec = labels_dfs[symbol].loc[d]
            if not rec["valid"]:
                valid_label = False
                exclusion_reason = f"LABEL_INVALID:{symbol}:{rec['reason']}"
                break
            label_vals.append(float(rec["value"]))

        if not valid_label:
            excluded[d] = exclusion_reason
            continue

        # Check feature validity
        try:
            tensor = build_feature_tensor(panels, d)
        except Exception as exc:
            excluded[d] = f"FEATURE_INVALID:{exc}"
            continue

        features[d] = tensor
        raw_labels[d] = np.array(label_vals, dtype=float)

    eligible = sorted(features.keys())
    return DatasetPartitions(
        features=features,
        raw_labels=raw_labels,
        sigma_normalizer=normalizer,
        eligible_decisions=eligible,
        excluded_decisions=excluded,
    )
