"""
btc_scraper/execution/controlled_rollout.py
Phase 6 — Task 6.9: Controlled Rollout with Stage Promotion and Demotion

Stages:
    Stage 1 → Stage 2 → Stage 3
    Stage 3 → Stage 2 → Stage 1 → HALTED  (demotion)

Promotion criteria per stage:
    - min_duration_hours
    - min_real_trades    (prevents promotion on thin data)
    - critical_incidents = 0
    - max reject_rate
    - min fill_rate
    - max slippage_mae_bps
    - position_mismatch_count = 0

Demotion triggers:
    - Critical incident
    - Slippage degradation
    - Fill rate drop
    - Daily loss breach
    - Position mismatch
    - Data quality degradation
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .hard_risk_limits import HardRiskLimits, STAGE_LIMITS
from .kill_switch import KillSwitch
from .live_audit_log import LiveAuditLog

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
ROLLOUT_STATE_PATH = BASE_DIR / "data" / "execution" / "rollout_state.json"


# ── Promotion criteria per stage ──────────────────────────────────────────────

@dataclass
class PromotionCriteria:
    min_duration_hours: float
    min_real_trades: int
    max_reject_rate: float         # fraction, e.g. 0.20
    min_fill_rate: float           # fraction, e.g. 0.80
    max_slippage_mae_bps: float
    max_critical_incidents: int = 0
    max_position_mismatch_count: int = 0


PROMOTION_RULES: Dict[int, PromotionCriteria] = {
    # Stage 1 → Stage 2
    1: PromotionCriteria(
        min_duration_hours=48,
        min_real_trades=20,
        max_reject_rate=0.20,
        min_fill_rate=0.80,
        max_slippage_mae_bps=10.0,
    ),
    # Stage 2 → Stage 3
    2: PromotionCriteria(
        min_duration_hours=72,
        min_real_trades=50,
        max_reject_rate=0.15,
        min_fill_rate=0.85,
        max_slippage_mae_bps=8.0,
    ),
}

# Demotion thresholds (opposite direction)
DEMOTION_TRIGGERS = {
    "critical_incident":        3,   # Stage back one level
    "slippage_mae_bps":         12.0,
    "fill_rate_below":          0.70,
    "reject_rate_above":        0.30,
    "position_mismatch":        True,
    "data_quality_below":       0.85,
}


@dataclass
class StageMetrics:
    """Live metrics snapshot used for promotion/demotion evaluation."""
    real_trades: int = 0
    critical_incidents: int = 0
    position_mismatch_count: int = 0
    reject_rate: float = 0.0
    fill_rate: float = 1.0
    slippage_mae_bps: float = 0.0
    data_quality_pct: float = 1.0
    stage_started_at: float = field(default_factory=time.time)

    def duration_hours(self) -> float:
        return (time.time() - self.stage_started_at) / 3600


@dataclass
class RolloutState:
    current_stage: int = 1
    previous_stage: Optional[int] = None
    last_transition: Optional[str] = None   # "PROMOTED" | "DEMOTED" | "HALTED"
    last_transition_reason: Optional[str] = None
    last_transition_at: Optional[str] = None
    stage_started_at: float = field(default_factory=time.time)
    history: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ControlledRollout:
    """
    Manages staged live rollout with automatic promotion and demotion.

    Promotion requires minimum real_trades (prevents thin-data decisions).
    Demotion is triggered automatically by metric degradation or incidents.
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        hard_risk_limits: Optional[HardRiskLimits] = None,
        audit_log: Optional[LiveAuditLog] = None,
        initial_stage: int = 1,
    ):
        self._ks = kill_switch or KillSwitch()
        self._risk = hard_risk_limits or HardRiskLimits(stage=initial_stage)
        self._audit = audit_log or LiveAuditLog()
        self._state = RolloutState(current_stage=initial_stage)
        self._metrics = StageMetrics(stage_started_at=time.time())
        self._load_state()

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if ROLLOUT_STATE_PATH.exists():
                raw = json.loads(ROLLOUT_STATE_PATH.read_text(encoding="utf-8"))
                self._state = RolloutState(**{
                    k: v for k, v in raw.items()
                    if k in RolloutState.__dataclass_fields__
                })
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            ROLLOUT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = ROLLOUT_STATE_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._state.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            tmp.replace(ROLLOUT_STATE_PATH)
        except Exception as exc:
            logger.error(f"[Rollout] Failed to save state: {exc}")

    # ── Metrics update ────────────────────────────────────────────────────────

    def record_trade(self, filled: bool = True, slippage_bps: float = 0.0) -> None:
        if filled:
            self._metrics.real_trades += 1
            # Rolling slippage MAE update
            n = self._metrics.real_trades
            self._metrics.slippage_mae_bps = (
                self._metrics.slippage_mae_bps * (n - 1) + abs(slippage_bps)
            ) / n
        self._metrics.fill_rate = (
            self._metrics.real_trades / max(self._metrics.real_trades + (0 if filled else 1), 1)
        )

    def record_reject(self) -> None:
        total = self._metrics.real_trades
        # Approximate reject rate
        self._metrics.reject_rate = min(
            self._metrics.reject_rate + (1.0 / max(total + 1, 1)), 1.0
        )

    def record_critical_incident(self) -> None:
        self._metrics.critical_incidents += 1
        self._check_demotion_triggers()

    def record_position_mismatch(self) -> None:
        self._metrics.position_mismatch_count += 1
        self._check_demotion_triggers()

    def update_data_quality(self, quality_pct: float) -> None:
        self._metrics.data_quality_pct = quality_pct
        self._check_demotion_triggers()

    # ── Promotion evaluation ──────────────────────────────────────────────────

    def evaluate_promotion(self) -> Dict[str, Any]:
        """
        Check whether current stage meets promotion criteria.
        Returns a report with met/unmet criteria.
        """
        stage = self._state.current_stage
        if stage not in PROMOTION_RULES:
            return {"eligible": False, "reason": "already_at_max_stage"}

        criteria = PROMOTION_RULES[stage]
        m = self._metrics
        duration = m.duration_hours()

        checks = {
            "min_duration_hours": (duration >= criteria.min_duration_hours, duration, criteria.min_duration_hours),
            "min_real_trades": (m.real_trades >= criteria.min_real_trades, m.real_trades, criteria.min_real_trades),
            "critical_incidents": (m.critical_incidents <= criteria.max_critical_incidents, m.critical_incidents, criteria.max_critical_incidents),
            "reject_rate": (m.reject_rate <= criteria.max_reject_rate, m.reject_rate, criteria.max_reject_rate),
            "fill_rate": (m.fill_rate >= criteria.min_fill_rate, m.fill_rate, criteria.min_fill_rate),
            "slippage_mae_bps": (m.slippage_mae_bps <= criteria.max_slippage_mae_bps, m.slippage_mae_bps, criteria.max_slippage_mae_bps),
            "position_mismatch": (m.position_mismatch_count <= criteria.max_position_mismatch_count, m.position_mismatch_count, criteria.max_position_mismatch_count),
        }

        all_met = all(v[0] for v in checks.values())
        unmet = [k for k, v in checks.items() if not v[0]]

        return {
            "eligible": all_met,
            "current_stage": stage,
            "target_stage": stage + 1,
            "unmet_criteria": unmet,
            "checks": {k: {"met": v[0], "actual": v[1], "required": v[2]} for k, v in checks.items()},
        }

    def promote(self) -> bool:
        """
        Attempt to promote to next stage. Returns True if promoted.
        """
        eval_result = self.evaluate_promotion()
        if not eval_result.get("eligible"):
            logger.info(f"[Rollout] Promotion blocked: {eval_result.get('unmet_criteria')}")
            return False

        prev = self._state.current_stage
        new_stage = prev + 1
        now = datetime.now(timezone.utc).isoformat()

        self._state.history.append({
            "event": "PROMOTED",
            "from": prev, "to": new_stage,
            "at": now, "metrics": asdict(self._metrics),
        })
        self._state.previous_stage = prev
        self._state.current_stage = new_stage
        self._state.last_transition = "PROMOTED"
        self._state.last_transition_reason = f"All Stage {prev} criteria met"
        self._state.last_transition_at = now
        self._state.stage_started_at = time.time()
        self._metrics = StageMetrics(stage_started_at=time.time())

        # Update limits to new stage
        self._risk.update_stage(new_stage)
        self._save_state()
        self._audit.log_rollout_transition(prev, new_stage, "PROMOTED", f"Stage {prev} criteria met")
        logger.info(f"[Rollout] PROMOTED: Stage {prev} → Stage {new_stage}")
        return True

    # ── Demotion ──────────────────────────────────────────────────────────────

    def _check_demotion_triggers(self) -> None:
        m = self._metrics
        reasons = []

        if m.critical_incidents > 0:
            reasons.append(f"critical_incidents={m.critical_incidents}")
        if m.slippage_mae_bps > DEMOTION_TRIGGERS["slippage_mae_bps"]:
            reasons.append(f"slippage_mae={m.slippage_mae_bps:.1f}bps > {DEMOTION_TRIGGERS['slippage_mae_bps']}")
        if m.fill_rate < DEMOTION_TRIGGERS["fill_rate_below"]:
            reasons.append(f"fill_rate={m.fill_rate:.2f} < {DEMOTION_TRIGGERS['fill_rate_below']}")
        if m.reject_rate > DEMOTION_TRIGGERS["reject_rate_above"]:
            reasons.append(f"reject_rate={m.reject_rate:.2f} > {DEMOTION_TRIGGERS['reject_rate_above']}")
        if m.position_mismatch_count > 0:
            reasons.append(f"position_mismatch={m.position_mismatch_count}")
        if m.data_quality_pct < DEMOTION_TRIGGERS["data_quality_below"]:
            reasons.append(f"data_quality={m.data_quality_pct:.2f} < {DEMOTION_TRIGGERS['data_quality_below']}")

        if reasons:
            self.demote(reason="; ".join(reasons))

    def demote(self, reason: str = "metric_degradation") -> int:
        """
        Demote by one stage. If already Stage 1, trigger kill-switch HALTED.
        Returns new stage.
        """
        prev = self._state.current_stage
        now = datetime.now(timezone.utc).isoformat()

        if prev <= 1:
            # At minimum stage → halt
            logger.critical(f"[Rollout] HALTED from Stage 1: {reason}")
            self._state.history.append({"event": "HALTED", "from": prev, "at": now, "reason": reason})
            self._state.last_transition = "HALTED"
            self._state.last_transition_reason = reason
            self._state.last_transition_at = now
            self._save_state()
            self._ks.trigger("daily_loss_breach", value=0.0, threshold=0.0)  # conservative halt
            self._audit.log_rollout_transition(prev, 0, "HALTED", reason)
            return 0

        new_stage = prev - 1
        self._state.history.append({"event": "DEMOTED", "from": prev, "to": new_stage, "at": now, "reason": reason})
        self._state.previous_stage = prev
        self._state.current_stage = new_stage
        self._state.last_transition = "DEMOTED"
        self._state.last_transition_reason = reason
        self._state.last_transition_at = now
        self._state.stage_started_at = time.time()
        self._metrics = StageMetrics(stage_started_at=time.time())

        self._risk.update_stage(new_stage)
        self._save_state()
        self._audit.log_rollout_transition(prev, new_stage, "DEMOTED", reason)
        logger.warning(f"[Rollout] DEMOTED: Stage {prev} → Stage {new_stage}: {reason}")
        return new_stage

    def get_state(self) -> Dict[str, Any]:
        return {
            **self._state.to_dict(),
            "metrics": asdict(self._metrics),
            "metrics_duration_hours": round(self._metrics.duration_hours(), 2),
            "limits": asdict(STAGE_LIMITS.get(self._state.current_stage, STAGE_LIMITS[1])),
        }
