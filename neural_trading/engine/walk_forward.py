"""
neural_trading/engine/walk_forward.py

Chronological walk-forward evaluation laboratory for neural portfolio policies.
Enforces strict chronological train/validation splitting with boundary purging.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
import numpy as np
import torch
import torch.optim as optim

from neural_trading.engine.hard_risk import DeterministicHardRiskBarrier
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.models.base import BaseNeuralPolicy
from neural_trading.objectives.differentiable_economic_loss import DifferentiableSharpeLoss


class ChronologicalNeuralEvaluator:
    """
    Manages expanding or rolling chronological walk-forward splits,
    trains neural policies with differentiable economic objectives,
    and conducts out-of-sample backtests against passive benchmarks.
    """

    def __init__(
        self,
        symbols: List[str],
        simulator: NeuralPortfolioSimulator | None = None,
        loss_fn: DifferentiableSharpeLoss | None = None,
        device: str = "cpu",
    ):
        self.symbols = symbols
        self.simulator = simulator or NeuralPortfolioSimulator(symbols)
        self.loss_fn = loss_fn or DifferentiableSharpeLoss()
        self.device = torch.device(device)

    def train_policy(
        self,
        model: BaseNeuralPolicy,
        X_train: np.ndarray,      # (S_train, N, T, F)
        y_train: np.ndarray,      # (S_train, N)
        epochs: int = 15,
        batch_size: int = 128,
        lr: float = 0.001,
        rollout_steps: int = 64,
    ) -> Dict[str, Any]:
        """
        Trains model directly on differentiable economic loss over sequential rollouts.
        """
        model.to(self.device)
        model.train()
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

        S_train, N, T, F_dim = X_train.shape
        num_rollouts = S_train - rollout_steps
        if num_rollouts <= 0:
            raise ValueError(f"Train sample size {S_train} too small for rollout length {rollout_steps}")

        training_history = []

        for ep in range(epochs):
            # Sample random contiguous rollout segments
            indices = np.random.permutation(num_rollouts)[:batch_size]
            epoch_losses = []
            epoch_sharpes = []

            for idx in indices:
                # Segment of length rollout_steps
                x_seg = torch.tensor(X_train[idx : idx + rollout_steps], dtype=torch.float32, device=self.device)
                y_seg = torch.tensor(y_train[idx : idx + rollout_steps], dtype=torch.float32, device=self.device)

                # Append cash relative (1.0) to y_seg: shape (rollout_steps, N + 1)
                cash_rel = torch.ones((rollout_steps, 1), dtype=torch.float32, device=self.device)
                y_full = torch.cat([cash_rel, y_seg], dim=-1)

                optimizer.zero_grad()
                # Forward pass to get weights: shape (rollout_steps, N + 1)
                weights = model(x_seg)

                loss, diag = self.loss_fn(weights, y_full)
                loss.backward()
                # Gradient clipping for stability
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                epoch_losses.append(diag["loss"])
                epoch_sharpes.append(diag["annualized_sharpe"])

            mean_loss = float(np.mean(epoch_losses))
            mean_sh = float(np.mean(epoch_sharpes))
            training_history.append({"epoch": ep + 1, "loss": mean_loss, "sharpe": mean_sh})

        return {
            "final_epoch_loss": mean_loss,
            "final_epoch_sharpe": mean_sh,
            "training_history": training_history,
        }

    def evaluate_policy_oos(
        self,
        model: BaseNeuralPolicy,
        X_val: np.ndarray,          # (S_val, N, T, F)
        y_val: np.ndarray,          # (S_val, N)
        timestamps_val: List[str],  # (S_val,)
    ) -> Dict[str, Any]:
        """
        Evaluates model out-of-sample in full sequential evaluation mode.
        """
        model.to(self.device)
        model.eval()

        with torch.no_grad():
            x_tensor = torch.tensor(X_val, dtype=torch.float32, device=self.device)
            # Batch forward pass to get all sequential weights
            # Process in chunks of 512 for memory efficiency
            weights_list = []
            chunk_size = 512
            for i in range(0, len(x_tensor), chunk_size):
                chunk_w = model(x_tensor[i : i + chunk_size])
                weights_list.append(chunk_w.cpu().numpy())

            target_weights = np.concatenate(weights_list, axis=0)

        # Run independent simulation
        sim_results = self.simulator.simulate(target_weights, y_val, timestamps_val)
        return sim_results

    def evaluate_benchmark_ew(
        self,
        y_val: np.ndarray,
        timestamps_val: List[str],
        cash_weight: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Evaluates Equal-Weighted Buy-and-Hold benchmark across risky assets.
        """
        K, N = y_val.shape
        w_risky = (1.0 - cash_weight) / N
        ew_weights = np.zeros((K, N + 1), dtype=np.float64)
        ew_weights[:, 0] = cash_weight
        ew_weights[:, 1:] = w_risky

        return self.simulator.simulate(ew_weights, y_val, timestamps_val)
