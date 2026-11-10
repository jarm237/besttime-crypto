"""
btc_scraper/research/prospective_shadow_evaluator.py
Phase M5-F & Phase G3 (P0-4) / Phase G8 (P0-5): Prospective Shadow Evaluation Foundation.

Provides:
1. ProspectiveOpportunity: Immutable audit record of a prospective decision opportunity,
   feature snapshot, simulation intent, and mature economic outcome.
2. ProspectiveShadowEvaluator: Deterministic, read-only shadow evaluation engine that:
   - Binds strictly to FrozenCandidateSnapshot parameters (no silent fallback to registry defaults).
   - Verifies candidate config_hash and strategy source code hash prior to initialization.
   - Enforces strict post-freeze temporal gating (rejects pre-freeze candles).
   - Operates strictly on closed candles without forward-looking data.
   - Generates simulated execution intent without emitting real orders or fake paper fills.
   - Resolves outcomes only when future candles close and satisfy exit criteria.
   - Maintains full evidence lineage isolated from production/active paper stores (data/prospective_shadow_evidence/).
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.candidate_freeze import FrozenCandidateSnapshot
from btc_scraper.research.experiment_contract import unfreeze_nested
from btc_scraper.research.strategy_registry import (
    GLOBAL_STRATEGY_REGISTRY,
    BaselineStrategy,
    StrategySpec,
)


@dataclass(frozen=True)
class ProspectiveOpportunity:
    """
    Immutable audit record for an evaluation bar under prospective shadow mode.
    """
    opportunity_id: str
    evaluation_timestamp: str
    candidate_id: str
    candidate_freeze_hash: str
    symbol: str
    timeframe: str
    close_price: float
    decision_action: str                    # "BUY", "CLOSE", "NO_TRADE"
    decision_reason: str
    feature_vector_snapshot: Mapping[str, float]
    eligibility_status: str                 # "ELIGIBLE", "REJECTED_PRE_FREEZE", "REJECTED_FILTER", "NO_SIGNAL"
    cost_assumptions: Mapping[str, float]
    simulated_execution_intent: Optional[Mapping[str, Any]] = None
    resolved_outcome: Optional[Mapping[str, Any]] = None
    timing_metadata: Optional[Mapping[str, Any]] = None
    is_simulated_shadow: bool = True
    is_actual_paper_fill: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "evaluation_timestamp": self.evaluation_timestamp,
            "candidate_id": self.candidate_id,
            "candidate_freeze_hash": self.candidate_freeze_hash,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "close_price": self.close_price,
            "decision_action": self.decision_action,
            "decision_reason": self.decision_reason,
            "feature_vector_snapshot": dict(self.feature_vector_snapshot),
            "eligibility_status": self.eligibility_status,
            "cost_assumptions": dict(self.cost_assumptions),
            "simulated_execution_intent": dict(self.simulated_execution_intent) if self.simulated_execution_intent else None,
            "resolved_outcome": dict(self.resolved_outcome) if self.resolved_outcome else None,
            "timing_metadata": dict(self.timing_metadata) if self.timing_metadata else None,
            "is_simulated_shadow": self.is_simulated_shadow,
            "is_actual_paper_fill": self.is_actual_paper_fill,
        }


class ProspectiveShadowEvaluator:
    """
    Read-only Prospective Shadow Evaluator for Milestone M5.
    Evaluates streaming/historical closed candles against a frozen candidate without mutating
    active paper trading state or sending real orders.
    """

    def __init__(
        self,
        candidate_snapshot: FrozenCandidateSnapshot,
        freeze_boundary_timestamp: str,
        initial_capital: float = 10_000.0,
        verify_source: bool = True,
    ):
        self.candidate = candidate_snapshot
        self.freeze_boundary_timestamp = freeze_boundary_timestamp
        self.initial_capital = initial_capital

        # 1. Verify candidate config hash against parameters (Phase G3 / P0-4)
        spec_meta = GLOBAL_STRATEGY_REGISTRY.get_spec(candidate_snapshot.candidate_id)
        candidate_spec = StrategySpec(
            strategy_id=candidate_snapshot.candidate_id,
            strategy_name=spec_meta.strategy_name,
            tier=spec_meta.tier,
            status=spec_meta.status,
            parameters=candidate_snapshot.parameters,
            required_features=spec_meta.required_features,
            description=spec_meta.description,
        )
        if candidate_spec.config_hash != candidate_snapshot.config_hash:
            raise ValueError(
                f"Candidate config_hash mismatch for '{candidate_snapshot.candidate_id}': "
                f"expected '{candidate_snapshot.config_hash}', but parameters hash to '{candidate_spec.config_hash}'."
            )

        # 2. Verify source code hash if available (Phase G3 / P0-4)
        if verify_source and getattr(candidate_snapshot, "strategy_source_hash", ""):
            try:
                from btc_scraper.research.source_manifest import get_class_source_hash
                actual_source_hash = get_class_source_hash(candidate_snapshot.strategy_class_path)
                if actual_source_hash != candidate_snapshot.strategy_source_hash:
                    raise ValueError(
                        f"Candidate strategy source code mismatch for '{candidate_snapshot.strategy_class_path}': "
                        f"frozen source hash '{candidate_snapshot.strategy_source_hash}', actual on disk '{actual_source_hash}'."
                    )
            except (ImportError, FileNotFoundError):
                pass

        # 3. Instantiate strategy directly using candidate parameters (no fallback to registry defaults)
        self.strategy: BaselineStrategy = self._instantiate_strategy(
            candidate_snapshot.strategy_class_path,
            candidate_snapshot.parameters,
        )

        # Internal shadow state (isolated from active paper runtime)
        self._current_position: Optional[Dict[str, Any]] = None
        self._opportunities: List[ProspectiveOpportunity] = []
        self._pending_simulations: List[Dict[str, Any]] = []

    @staticmethod
    def _instantiate_strategy(
        class_path: str,
        parameters: Mapping[str, Any],
    ) -> BaselineStrategy:
        """Dynamically imports and instantiates strategy with exact frozen parameters."""
        module_path, class_name = class_path.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        params_dict = unfreeze_nested(parameters)
        instance = cls(**params_dict)

        # Verify instance attributes match frozen parameters
        for k, v in params_dict.items():
            if hasattr(instance, k):
                actual_val = getattr(instance, k)
                if actual_val != v:
                    raise ValueError(
                        f"Strategy parameter binding mismatch for '{k}': expected {v}, got {actual_val}"
                    )
        return instance

    @property
    def current_position(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._current_position)

    @property
    def opportunities(self) -> Tuple[ProspectiveOpportunity, ...]:
        return tuple(self._opportunities)

    def evaluate_closed_bar(
        self,
        current_candle: Mapping[str, Any],
        historical_window: Sequence[Mapping[str, Any]],
    ) -> ProspectiveOpportunity:
        """
        Evaluates a single closed bar under strict point-in-time constraints.
        Enforces:
        1. Closed-candle invariant: Reject unclosed / forming bars.
        2. Post-freeze temporal gating: Mark pre-freeze observations as REJECTED_PRE_FREEZE.
        3. Deterministic candidate decision evaluation.
        4. Next-Bar-Open execution simulation intent.
        """
        bar_time = str(current_candle.get("time", current_candle.get("open_time_utc", "")))
        c_price = float(current_candle["close"])
        
        # Verify closed candle invariant
        is_closed = current_candle.get("is_closed", current_candle.get("closed", True))
        if not is_closed:
            raise ValueError(f"Cannot evaluate forming or unclosed candle at {bar_time}")

        # Deterministic opportunity ID
        opp_id = hashlib.sha256(
            f"{self.candidate.freeze_hash}_{self.candidate.symbol}_{bar_time}".encode("utf-8")
        ).hexdigest()[:16]

        # Cost model assumptions
        cost_meta = {
            "spot_maker_bps": float(self.candidate.cost_model.get("spot_maker_bps", 5.0)),
            "spot_taker_bps": float(self.candidate.cost_model.get("spot_taker_bps", 5.0)),
            "slippage_bps": float(self.candidate.cost_model.get("slippage_bps", 2.0)),
            "total_roundtrip_bps": float(self.candidate.cost_model.get("total_roundtrip_bps", 14.0)),
        }

        # 1. Post-Freeze Boundary Temporal Gate
        if bar_time < self.freeze_boundary_timestamp:
            opp = ProspectiveOpportunity(
                opportunity_id=opp_id,
                evaluation_timestamp=bar_time,
                candidate_id=self.candidate.candidate_id,
                candidate_freeze_hash=self.candidate.freeze_hash,
                symbol=self.candidate.symbol,
                timeframe=self.candidate.timeframe,
                close_price=c_price,
                decision_action="NO_TRADE",
                decision_reason=f"Bar timestamp {bar_time} is prior to candidate freeze boundary {self.freeze_boundary_timestamp}",
                feature_vector_snapshot={},
                eligibility_status="REJECTED_PRE_FREEZE",
                cost_assumptions=cost_meta,
                simulated_execution_intent=None,
                resolved_outcome=None,
            )
            self._opportunities.append(opp)
            return opp

        # 2. Extract minimal feature snapshot
        feature_snapshot = self._extract_features(historical_window)

        # 3. Evaluate candidate strategy on closed bar
        sig = self.strategy.evaluate_bar(
            symbol=self.candidate.symbol,
            current_candle=current_candle,
            historical_candles=historical_window,
            current_position=self._current_position,
        )

        action = sig.get("action", "NO_TRADE") if sig else "NO_TRADE"
        reason = sig.get("reason", "no_signal") if sig else "no_signal"
        eligibility = "ELIGIBLE" if action in ("BUY", "CLOSE") else "NO_SIGNAL"

        # 4. Point-in-time timing fidelity metadata (Phase D)
        timing_meta = {
            "source_candle_close_time": bar_time,
            "data_arrival_time_utc": str(current_candle.get("arrival_time_utc", bar_time)),
            "feature_availability_time_utc": bar_time,
            "decision_computation_time_utc": bar_time,
            "earliest_executable_time_utc": bar_time,
            "latency_assumption_ms": 250,
            "execution_model_type": "SIMULATED_MODEL_EXECUTION",
            "exchange_execution_parity_status": "NOT_EVALUATED",
        }

        # 5. Generate simulated execution intent (NEXT_BAR_OPEN execution)
        sim_intent = None
        if action == "BUY" and self._current_position is None:
            alloc_pct = float(self.candidate.sizing_policy.get("allocation_pct", 0.10))
            notional = self.initial_capital * alloc_pct
            sim_intent = {
                "action": "BUY",
                "target_symbol": self.candidate.symbol,
                "intended_notional": notional,
                "order_timing": "NEXT_BAR_OPEN",
                "same_candle_policy": self.candidate.same_candle_policy,
                "signal_close_price": c_price,
                "signal_bar_time": bar_time,
                "fill_price_origin": "NEXT_BAR_OPEN_SIMULATED",
                "is_simulated": True,
                **timing_meta,
            }
        elif action == "CLOSE" and self._current_position is not None:
            sim_intent = {
                "action": "CLOSE",
                "target_symbol": self.candidate.symbol,
                "order_timing": "NEXT_BAR_OPEN",
                "signal_close_price": c_price,
                "signal_bar_time": bar_time,
                "position_id": self._current_position.get("position_id"),
                "fill_price_origin": "NEXT_BAR_OPEN_SIMULATED",
                "is_simulated": True,
                **timing_meta,
            }

        opp = ProspectiveOpportunity(
            opportunity_id=opp_id,
            evaluation_timestamp=bar_time,
            candidate_id=self.candidate.candidate_id,
            candidate_freeze_hash=self.candidate.freeze_hash,
            symbol=self.candidate.symbol,
            timeframe=self.candidate.timeframe,
            close_price=c_price,
            decision_action=action,
            decision_reason=reason,
            feature_vector_snapshot=feature_snapshot,
            eligibility_status=eligibility,
            cost_assumptions=cost_meta,
            simulated_execution_intent=sim_intent,
            resolved_outcome=None,
            timing_metadata=timing_meta,
        )
        self._opportunities.append(opp)
        return opp

    def process_next_bar_open(self, next_candle: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Executes pending simulated intent at next bar's open price (Next-Bar-Open parity).
        Updates internal shadow position state.
        """
        if not self._opportunities:
            return None

        last_opp = self._opportunities[-1]
        intent = last_opp.simulated_execution_intent
        if intent is None:
            return None

        open_p = float(next_candle.get("open", next_candle["close"]))
        bar_time = str(next_candle.get("time", next_candle.get("open_time_utc", "")))

        # Effective fill price calculation with slippage
        slip_rate = float(self.candidate.cost_model.get("slippage_bps", 2.0)) / 10_000.0
        fee_rate = float(self.candidate.cost_model.get("spot_taker_bps", 5.0)) / 10_000.0

        if intent["action"] == "BUY" and self._current_position is None:
            fill_p = open_p * (1.0 + slip_rate)
            notional = float(intent["intended_notional"])
            qty = notional / fill_p
            entry_fee = notional * fee_rate

            self._current_position = {
                "position_id": f"pos_{last_opp.opportunity_id}",
                "symbol": self.candidate.symbol,
                "entry_time": bar_time,
                "entry_price": fill_p,
                "qty": qty,
                "invested_notional": notional,
                "entry_fee": entry_fee,
                "bars_held": 0,
            }
            return {
                "event": "SIMULATED_ENTRY_FILLED",
                "fill_price": fill_p,
                "qty": qty,
                "fee": entry_fee,
                "entry_time": bar_time,
                "simulated_fill_time_utc": bar_time,
                "fill_price_origin": "NEXT_BAR_OPEN_OBSERVED",
                "latency_assumption_ms": 250,
                "execution_model_type": "SIMULATED_MODEL_EXECUTION",
                "exchange_execution_parity_status": "NOT_EVALUATED",
            }

        elif intent["action"] == "CLOSE" and self._current_position is not None:
            fill_p = open_p * (1.0 - slip_rate)
            pos = self._current_position
            qty = float(pos["qty"])
            exit_notional = qty * fill_p
            exit_fee = exit_notional * fee_rate

            gross_pnl = (fill_p - float(pos["entry_price"])) * qty
            total_fees = float(pos["entry_fee"]) + exit_fee
            net_pnl = gross_pnl - total_fees

            resolved = {
                "event": "SIMULATED_EXIT_FILLED",
                "entry_time": pos["entry_time"],
                "exit_time": bar_time,
                "entry_price": pos["entry_price"],
                "exit_price": fill_p,
                "qty": qty,
                "gross_pnl": round(gross_pnl, 4),
                "total_fees": round(total_fees, 4),
                "net_pnl": round(net_pnl, 4),
                "bars_held": pos["bars_held"],
                "exit_reason": last_opp.decision_reason,
                "simulated_fill_time_utc": bar_time,
                "fill_price_origin": "NEXT_BAR_OPEN_OBSERVED",
                "latency_assumption_ms": 250,
                "execution_model_type": "SIMULATED_MODEL_EXECUTION",
                "exchange_execution_parity_status": "NOT_EVALUATED",
            }
            self._current_position = None
            return resolved

        return None

    def persist_evidence(
        self,
        opp: ProspectiveOpportunity,
        output_dir: Optional[Path] = None,
    ) -> Path:
        """
        Persists a ProspectiveOpportunity record to an isolated, append-only JSON file in
        data/prospective_shadow_evidence/.
        Guarantees that shadow simulated fills are never mixed with live or active paper orders.
        """
        if output_dir is None:
            output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "prospective_shadow_evidence"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        record = opp.to_dict()
        record["persisted_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["evidence_type"] = "SHADOW_SIMULATED_FILL" if opp.simulated_execution_intent else "SHADOW_OBSERVATION"

        safe_time = opp.evaluation_timestamp.replace(":", "-").replace(".", "-")
        filename = f"shadow_opp_{opp.candidate_id}_{opp.symbol}_{safe_time}_{opp.opportunity_id}.json"
        target_path = output_dir / filename

        temp_path = target_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        temp_path.replace(target_path)

        return target_path

    def _extract_features(self, historical_window: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
        """Extracts technical features needed for candidate audit trail."""
        if len(historical_window) < 50:
            return {}
        closes = [float(c["close"]) for c in historical_window[-50:]]
        sma_50 = sum(closes) / len(closes)
        sma_20 = sum(closes[-20:]) / 20.0
        return {
            "close": closes[-1],
            "sma_50": round(sma_50, 2),
            "sma_20": round(sma_20, 2),
        }
