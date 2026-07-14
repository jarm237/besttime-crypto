"""Mode and risk guard for RL exit recommendations."""
from __future__ import annotations

import os
from dataclasses import dataclass

ACTION_LABELS = {0: "HOLD", 1: "PARTIAL_CLOSE_50", 2: "MOVE_SL_TO_BREAKEVEN", 3: "TAKE_PROFIT", 4: "EXIT", 5: "TRAILING_SL_ATR"}
VALID_MODES = {"disabled", "shadow", "advisory", "active"}


@dataclass(frozen=True)
class GuardedRLAction:
    raw_action: int | None
    action: int
    mode: str
    decision: str
    reason: str | None = None


def rl_exit_mode() -> str:
    mode = os.getenv("RL_EXIT_MODE", "shadow").strip().lower()
    return mode if mode in VALID_MODES else "shadow"


def guard_rl_action(action: int | None, *, meta_probability: float | None = None, mode: str | None = None) -> GuardedRLAction:
    selected_mode = mode or rl_exit_mode()
    if action not in ACTION_LABELS:
        return GuardedRLAction(action, 0, selected_mode, "rejected", "invalid_action")
    if selected_mode in {"disabled", "shadow"}:
        return GuardedRLAction(action, 0, selected_mode, "shadowed", "mode_blocks_execution")
    if selected_mode == "advisory":
        return GuardedRLAction(action, 0, selected_mode, "advisory", "mode_blocks_execution")
    if os.getenv("RL_EXIT_ALLOW_LIVE_ACTION", "false").lower() != "true":
        return GuardedRLAction(action, 0, selected_mode, "rejected", "live_action_not_allowed")
    if action in {1, 3, 4} and meta_probability is not None and meta_probability >= 0.45:
        return GuardedRLAction(action, 0, selected_mode, "downgraded", "meta_confidence_gate")
    return GuardedRLAction(action, action, selected_mode, "accepted")
