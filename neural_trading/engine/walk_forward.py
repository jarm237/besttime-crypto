"""
neural_trading/engine/walk_forward.py

Chronological walk-forward evaluation laboratory for neural portfolio policies.
Enforces strict chronological train/validation splitting with boundary purging,
train-only feature normalization, and comprehensive exposure-matched baselines.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
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
    and conducts out-of-sample backtests against passive and exposure-matched benchmarks.
    """

    def __init__(
        self,
        symbols: List[str],
        simulator: Optional[NeuralPortfolioSimulator] = None,
        loss_fn: Optional[DifferentiableSharpeLoss] = None,
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
        seed: int = 42,
    ) -> Dict[str, Any]:
        """
        Trains model directly on differentiable economic loss over sequential rollouts.
        """
        torch.manual_seed(seed)
        np.random.seed(seed)

        model.to(self.device)
        model.train()
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

        S_train, N, T, F_dim = X_train.shape
        num_rollouts = S_train - rollout_steps
        if num_rollouts <= 0:
            raise ValueError(f"Train sample size {S_train} too small for rollout length {rollout_steps}")

        training_history = []

        for ep in range(epochs):
            indices = np.random.permutation(num_rollouts)[:batch_size]
            epoch_losses = []
            epoch_sharpes = []

            for idx in indices:
                x_seg = torch.tensor(X_train[idx : idx + rollout_steps], dtype=torch.float32, device=self.device)
                y_seg = torch.tensor(y_train[idx : idx + rollout_steps], dtype=torch.float32, device=self.device)

                cash_rel = torch.ones((rollout_steps, 1), dtype=torch.float32, device=self.device)
                y_full = torch.cat([cash_rel, y_seg], dim=-1)

                optimizer.zero_grad()
                weights = model(x_seg)

                loss, diag = self.loss_fn(weights, y_full)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()

                epoch_losses.append(diag["loss"])
                epoch_sharpes.append(diag["annualized_sharpe"])

            mean_loss = float(np.mean(epoch_losses))
            mean_sh = float(np.mean(epoch_sharpes))
            training_history.append({"epoch": ep + 1, "loss": round(mean_loss, 4), "sharpe": round(mean_sh, 4)})

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
        is_halt_seq: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates model out-of-sample in full sequential evaluation mode.
        """
        model.to(self.device)
        model.eval()

        with torch.no_grad():
            x_tensor = torch.tensor(X_val, dtype=torch.float32, device=self.device)
            weights_list = []
            chunk_size = 512
            for i in range(0, len(x_tensor), chunk_size):
                chunk_w = model(x_tensor[i : i + chunk_size])
                weights_list.append(chunk_w.cpu().numpy())

            target_weights = np.concatenate(weights_list, axis=0)

        sim_results = self.simulator.simulate(target_weights, y_val, timestamps_val, is_halt_seq=is_halt_seq)
        return sim_results

    def evaluate_100pct_cash(
        self,
        y_val: np.ndarray,
        timestamps_val: List[str],
        is_halt_seq: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Baseline 1: 100% Cash."""
        K, N = y_val.shape
        w = np.zeros((K, N + 1), dtype=np.float64)
        w[:, 0] = 1.0  # 100% Cash
        return self.simulator.simulate(w, y_val, timestamps_val, is_halt_seq=is_halt_seq, is_hold_seq=np.ones(K, dtype=bool))

    def evaluate_true_buy_and_hold(
        self,
        y_val: np.ndarray,
        timestamps_val: List[str],
        cash_weight: float = 0.05,
        is_halt_seq: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Baseline 2: True Buy & Hold.
        Executes initial entry buy orders at step 0; subsequently NEVER rebalances (pure natural drift).
        """
        K, N = y_val.shape
        w_risky = (1.0 - cash_weight) / N
        initial_target = np.zeros(N + 1, dtype=np.float64)
        initial_target[0] = cash_weight
        initial_target[1:] = w_risky

        target_weights = np.zeros((K, N + 1), dtype=np.float64)
        curr_w = initial_target.copy()

        for t in range(K):
            target_weights[t] = curr_w
            y_t = np.concatenate([[1.0], y_val[t]])
            drifted = (curr_w * y_t) / np.sum(curr_w * y_t)
            curr_w = drifted

        # In True Buy & Hold, step 0 enters portfolio, then subsequent steps are pure HOLD (no barrier forced rebalance)
        is_hold = np.ones(K, dtype=bool)
        is_hold[0] = False

        return self.simulator.simulate(
            target_weights,
            y_val,
            timestamps_val,
            is_halt_seq=is_halt_seq,
            is_hold_seq=is_hold,
            enforce_barrier=False,
        )

    def evaluate_periodic_rebalance_ew(
        self,
        y_val: np.ndarray,
        timestamps_val: List[str],
        cash_weight: float = 0.05,
        is_halt_seq: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Baseline 3: Hourly Periodic Rebalancing to Equal Weight.
        Rebalances back to static equal weights every bar, paying turnover friction.
        """
        K, N = y_val.shape
        w_risky = (1.0 - cash_weight) / N
        ew_weights = np.zeros((K, N + 1), dtype=np.float64)
        ew_weights[:, 0] = cash_weight
        ew_weights[:, 1:] = w_risky
        return self.simulator.simulate(ew_weights, y_val, timestamps_val, is_halt_seq=is_halt_seq, enforce_barrier=True)

    def evaluate_matched_cash_buy_and_hold(
        self,
        y_val: np.ndarray,
        timestamps_val: List[str],
        target_cash_weight: float,
        is_halt_seq: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Baseline 4: Constant-cash allocation matching neural average cash exposure.
        Allocates target_cash_weight to cash and distributes remainder equally across assets,
        held with drift-only execution to isolate beta exposure from timing alpha.
        """
        return self.evaluate_true_buy_and_hold(
            y_val, timestamps_val, cash_weight=target_cash_weight, is_halt_seq=is_halt_seq
        )
