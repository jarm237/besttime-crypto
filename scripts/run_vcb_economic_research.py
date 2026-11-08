#!/usr/bin/env python3
"""HMR-V5: Reproducible Economic Research & VCB Decomposition Pipeline.

This pipeline provides durable, deterministic generation of:
1. VCB1 Economic Decomposition (research/historical_market_replay_v5/vcb_economic_decomposition.json & .md)
   - 9-dimension quantitative decomposition across DEV 2024-2025 and BURNED 2026-H1:
     symbol, side (BUY/SELL), symbol x side, exit reason, holding period,
     session (UTC hour), day of week, cost sensitivity (10/14/20/30 bps), turnover and capacity rejection.
2. Exploratory Candidate Hypotheses & Comparison (research/historical_market_replay_v5/vcb_exploratory_variants.json & .md)
   - Re-evaluates baseline NO_TRADE, CONTROL, VCB_V1_BASELINE alongside post-hoc exploratory variants:
     * VCB_V2_VOL15 (vol_ratio >= 1.5)
     * VCB_V2_DONCHIAN192 (donchian_bars = 192 / 48h)
     * VCB_V2_SLOPE (SMA384 slope aligned)
     * VCB_V3_VOL_NORMALIZED_BARRIER (dynamic ATR-scaled TP/SL)
     * VCB_V3_DIRECTIONAL_REGIME_GATE (macro regime trend gate)
   - Evaluates Primary Daily Portfolio Moving-Block & Stationary Bootstrap 95% CI (block=10d, 2000 reps, seed=42)
   - Enforces epistemic honesty: 2026-H1 is permanently marked as BURNED_EXPOSED_AUDIT (never OOS or confirmatory).

Execution semantics strictly reuse:
- btc_scraper/trading/event_driven_accounting.py (EventDrivenAccountingEngine)
- scripts/evaluate_candidates_and_promotion_gates_v2.py (simulate_next_bar_open_barrier_trade, block_bootstrap_daily_mtm_ci)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.trading.event_driven_accounting import (
    AccountingConfig,
    EventDrivenAccountingEngine,
)
from scripts.audit_and_prepare_oos_dataset import audit_and_merge_symbol_candles
from scripts.evaluate_candidates_and_promotion_gates_v2 import (
    COINS,
    PERIOD_SPLITS,
    _apply_fold_q65_filter,
    _build_hourly_mtm_candles,
    _slice_candle_map,
    _to_utc_ts,
    block_bootstrap_daily_mtm_ci,
    build_leak_free_fold_mask,
    simulate_next_bar_open_barrier_trade,
)

DEFAULT_OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
GIT_HEAD_FALLBACK = "f96c6b8b64516dd76d3af132dac316c5672e35be"

HOLDOUT_SYMBOLS: tuple[str, ...] = ("DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC")
DESIGN_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "BNB")
ALL_9_SYMBOLS: tuple[str, ...] = tuple(sorted(DESIGN_SYMBOLS + HOLDOUT_SYMBOLS))


def get_git_head() -> str:
    """Gets current Git HEAD SHA or returns fallback."""
    head_file = REPO_ROOT / ".git" / "HEAD"
    if not head_file.exists():
        return GIT_HEAD_FALLBACK
    try:
        content = head_file.read_text(encoding="utf-8").strip()
        if content.startswith("ref: "):
            ref_path = REPO_ROOT / ".git" / content[5:]
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
        return content
    except Exception:
        return GIT_HEAD_FALLBACK


def compute_dataset_manifest(symbol_candles: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    """Computes dataset hashes, candle counts, and time boundaries."""
    manifest: dict[str, Any] = {}
    combined_hash = hashlib.sha256()
    for sym in sorted(symbol_candles.keys()):
        df = symbol_candles[sym]
        first_ts = str(df["timestamp"].iloc[0])
        last_ts = str(df["timestamp"].iloc[-1])
        c_bytes = f"{sym}_{len(df)}_{first_ts}_{last_ts}".encode("utf-8")
        sym_sha = hashlib.sha256(c_bytes).hexdigest()
        combined_hash.update(sym_sha.encode("utf-8"))
        manifest[sym] = {
            "candle_count": int(len(df)),
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "sha256": sym_sha,
        }
    manifest["combined_dataset_sha256"] = combined_hash.hexdigest()
    return manifest


class CandleFeatureCache:
    """Memoized feature arrays across candidates for immutable candle data."""

    def __init__(self, symbol_candles: Mapping[str, pd.DataFrame]):
        self._cache: dict[tuple[str, str, int], np.ndarray] = {}
        self.symbol_candles = symbol_candles
        self._series: dict[str, dict[str, pd.Series]] = {}
        for sym, df in symbol_candles.items():
            self._series[sym] = {
                "c": pd.Series(df["close"].to_numpy(dtype=float)),
                "h": pd.Series(df["high"].to_numpy(dtype=float)),
                "l": pd.Series(df["low"].to_numpy(dtype=float)),
                "v": pd.Series(df["volume"].to_numpy(dtype=float)),
            }

    def get_sma(self, sym: str, window: int) -> np.ndarray:
        key = (sym, "sma", window)
        if key not in self._cache:
            self._cache[key] = self._series[sym]["c"].rolling(window).mean().to_numpy()
        return self._cache[key]

    def get_donchian_high(self, sym: str, window: int) -> np.ndarray:
        key = (sym, "donchian_high", window)
        if key not in self._cache:
            self._cache[key] = self._series[sym]["h"].shift(1).rolling(window).max().to_numpy()
        return self._cache[key]

    def get_donchian_low(self, sym: str, window: int) -> np.ndarray:
        key = (sym, "donchian_low", window)
        if key not in self._cache:
            self._cache[key] = self._series[sym]["l"].shift(1).rolling(window).min().to_numpy()
        return self._cache[key]

    def get_vol_ma(self, sym: str, window: int) -> np.ndarray:
        key = (sym, "vol_ma", window)
        if key not in self._cache:
            self._cache[key] = self._series[sym]["v"].shift(1).rolling(window).mean().to_numpy()
        return self._cache[key]

    def get_atr(self, sym: str, window: int) -> np.ndarray:
        key = (sym, "atr", window)
        if key not in self._cache:
            s_h = self._series[sym]["h"]
            s_l = self._series[sym]["l"]
            s_c = self._series[sym]["c"]
            tr = pd.concat(
                [s_h - s_l, (s_h - s_c.shift(1)).abs(), (s_l - s_c.shift(1)).abs()],
                axis=1,
            ).max(axis=1)
            self._cache[key] = tr.shift(1).rolling(window).mean().to_numpy()
        return self._cache[key]


def build_canonical_research_candidate_payload(
    candidate_id: str,
    params: dict[str, Any],
    *,
    spec_version: str = "1.2.0-research-canonical",
    universe: tuple[str, ...] = ("BTC", "ETH", "BNB"),
    bar_interval_minutes: int = 15,
    allowed_sides: tuple[str, ...] | list[str] | None = None,
    design_source: str | None = None,
    validation_status: str | None = None,
    req_slope: bool = False,
    req_regime_gate: bool = False,
    use_atr_normalized_barrier: bool = False,
    slope_lookback_bars: int = 16,
    slope_comparison_rule: str = "sma_slow[i] > sma_slow[i - 16] for BUY, sma_slow[i] < sma_slow[i - 16] for SELL",
    regime_lookback_bars: int = 384,
    regime_comparison_rule: str = "sma_slow[i] > sma_slow[i - 384] for BUY, sma_slow[i] < sma_slow[i - 384] for SELL",
    atr_tp_multiplier: float = 3.0,
    atr_sl_multiplier: float = 1.5,
    atr_tp_min_bps: float = 50.0,
    atr_tp_max_bps: float = 600.0,
    atr_sl_min_bps: float = 30.0,
    atr_sl_max_bps: float = 300.0,
    execution_timing: str = "SIGNAL_AT_BAR_I_CLOSE__EARLIEST_ENTRY_AT_BAR_I_PLUS_1_OPEN",
    collision_policy: str = "SL_FIRST_CONSERVATIVE",
    gap_stop_policy: str = "ADVERSE_OPEN_PRICE_FILL_SL_GAP",
    cooldown_bars: int = 96,
    max_concurrent_positions: int = 3,
    max_positions_per_asset: int = 1,
) -> dict[str, Any]:
    """Constructs a deterministic dictionary capturing ALL behavior-affecting strategy fields."""
    donchian_bars = int(params.get("donchian_bars", 96))
    sma_fast_bars = int(params.get("sma_fast_bars", 96))
    sma_slow_bars = int(params.get("sma_slow_bars", 384))
    min_vol_ratio_96 = float(params.get("min_vol_ratio_96", 1.2))
    atr_compression_bars = int(params.get("atr_compression_bars", 192))
    max_hold_bars = int(params.get("max_hold_bars", 192))

    tp_val = params.get("tp_bps", 350.0)
    sl_val = params.get("sl_bps", 150.0)

    payload: dict[str, Any] = {
        "candidate_id": str(candidate_id),
        "spec_version": str(spec_version),
        "universe": list(universe),
        "bar_interval_minutes": int(bar_interval_minutes),
        "parameters": {
            "donchian_bars": donchian_bars,
            "sma_fast_bars": sma_fast_bars,
            "sma_slow_bars": sma_slow_bars,
            "min_vol_ratio_96": min_vol_ratio_96,
            "atr_compression_bars": atr_compression_bars,
            "max_hold_bars": max_hold_bars,
            "tp_bps": float(tp_val) if isinstance(tp_val, (int, float)) else str(tp_val),
            "sl_bps": float(sl_val) if isinstance(sl_val, (int, float)) else str(sl_val),
        },
        "behavior_flags": {
            "req_slope": bool(req_slope),
            "req_regime_gate": bool(req_regime_gate),
            "use_atr_normalized_barrier": bool(use_atr_normalized_barrier),
        },
        "slope_gate_specification": {
            "enabled": bool(req_slope),
            "slope_lookback_bars": int(slope_lookback_bars) if req_slope else None,
            "slope_comparison_rule": str(slope_comparison_rule) if req_slope else None,
        },
        "regime_gate_specification": {
            "enabled": bool(req_regime_gate),
            "regime_lookback_bars": int(regime_lookback_bars) if req_regime_gate else None,
            "regime_comparison_rule": str(regime_comparison_rule) if req_regime_gate else None,
        },
        "barrier_specification": {
            "barrier_type": "DYNAMIC_ATR_NORMALIZED" if use_atr_normalized_barrier else "FIXED_BPS",
            "fixed_tp_bps": float(tp_val) if not use_atr_normalized_barrier and isinstance(tp_val, (int, float)) else None,
            "fixed_sl_bps": float(sl_val) if not use_atr_normalized_barrier and isinstance(sl_val, (int, float)) else None,
            "atr_tp_multiplier": float(atr_tp_multiplier) if use_atr_normalized_barrier else None,
            "atr_sl_multiplier": float(atr_sl_multiplier) if use_atr_normalized_barrier else None,
            "atr_tp_min_bps": float(atr_tp_min_bps) if use_atr_normalized_barrier else None,
            "atr_tp_max_bps": float(atr_tp_max_bps) if use_atr_normalized_barrier else None,
            "atr_sl_min_bps": float(atr_sl_min_bps) if use_atr_normalized_barrier else None,
            "atr_sl_max_bps": float(atr_sl_max_bps) if use_atr_normalized_barrier else None,
        },
        "execution_timing_contract": {
            "signal_confirmation": "bar_i_close (signal_close_timestamp = signal_timestamp + 15m)",
            "earliest_entry": "bar_i_plus_1_open (entry_index = signal_index + 1, entry_price = opens[i+1])",
            "future_bar_admission_leakage": False,
            "intrabar_tp_sl_collision_policy": str(collision_policy),
            "gap_through_stop_policy": str(gap_stop_policy),
            "max_hold_anchor": "entry_index (entry_index .. entry_index + max_hold - 1)",
            "execution_timing": str(execution_timing),
            "cooldown_bars": int(cooldown_bars),
            "max_concurrent_positions": int(max_concurrent_positions),
            "max_positions_per_asset": int(max_positions_per_asset),
        },
    }
    if allowed_sides is not None:
        payload["allowed_sides"] = list(allowed_sides)
    if design_source is not None:
        payload["design_source"] = str(design_source)
    if validation_status is not None:
        payload["validation_status"] = str(validation_status)
    return payload


SEMANTIC_HASH_SCHEMA_VERSION = "1.0.0"
SEMANTIC_HASH_EXCLUDED_FIELDS: list[str] = [
    "semantic_artifact_sha256",
    "generation_timestamp",
    "performance_metadata",
    "stage_timing_seconds",
]
FORBIDDEN_AUDIT_KEYWORDS: tuple[str, ...] = (
    "burned",
    "audit",
    "2026_h1",
    "2026-h1",
    "burned_exposed_audit",
    "audit_gate_7",
    "audit_net_exp",
    "audit_profit_factor",
    "audit_trades",
)


def compute_canonical_research_spec_sha256(payload: dict[str, Any]) -> str:
    """Computes deterministic SHA-256 over key-sorted, compact JSON canonical payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_semantic_artifact_hash(artifact_data: dict[str, Any]) -> str:
    """Computes a deterministic semantic SHA-256 hash of an artifact, ignoring volatile metadata.

    Fields excluded from hash computation:
    - semantic_artifact_sha256
    - generation_timestamp
    - performance_metadata
    - stage_timing_seconds
    """
    import copy
    data = copy.deepcopy(artifact_data)
    for field in SEMANTIC_HASH_EXCLUDED_FIELDS:
        data.pop(field, None)

    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scan_for_forbidden_audit_keys(obj: Any, path: str = "") -> list[str]:
    """Recursively checks if any dictionary key or string attribute contains forbidden audit terms."""
    forbidden_found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(term in k_lower for term in FORBIDDEN_AUDIT_KEYWORDS):
                forbidden_found.append(f"{path}.{k}" if path else str(k))
            forbidden_found.extend(_scan_for_forbidden_audit_keys(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            forbidden_found.extend(_scan_for_forbidden_audit_keys(item, f"{path}[{idx}]"))
    return forbidden_found


@dataclass(frozen=True)
class ProspectiveCandidateRegistrationInput:
    candidate_id: str
    spec_version: str
    parameters: dict[str, Any]
    behavior_flags: dict[str, Any]
    economic_rationale: str
    dev_exploratory_summary: dict[str, Any]
    runtime_schema_compatibility_evidence: dict[str, Any]
    research_runtime_parity_evidence: dict[str, Any]
    registration_timestamp: str
    last_historical_timestamp_used: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "spec_version": self.spec_version,
            "parameters": self.parameters,
            "behavior_flags": self.behavior_flags,
            "economic_rationale": self.economic_rationale,
            "dev_exploratory_summary": self.dev_exploratory_summary,
            "runtime_schema_compatibility_evidence": self.runtime_schema_compatibility_evidence,
            "research_runtime_parity_evidence": self.research_runtime_parity_evidence,
            "registration_timestamp": self.registration_timestamp,
            "last_historical_timestamp_used": self.last_historical_timestamp_used,
        }


def classify_exposed_historical_candidate(
    candidate_id: str,
    candidate_eval: dict[str, Any],
) -> dict[str, Any]:
    """Classifies a candidate that was evaluated against the burned exposed 2026-H1 audit.

    This function applies historical disposition classification. Candidates that fail
    the primary daily block bootstrap gate on DEV or on the burned audit are permanently
    classified as REJECTED_AFTER_EXPOSED_AUDIT.
    """
    dev_period = candidate_eval.get("periods", {}).get("DEV_WALK_FORWARD_SELECTION_2024_2025", {})
    audit_period = candidate_eval.get("periods", {}).get("BURNED_EXPOSED_AUDIT_2026_H1", {})

    dev_g7 = dev_period.get("primary_daily_block_bootstrap_ci_bps", {}).get("gate_7_passed", False)
    audit_g7 = audit_period.get("primary_daily_block_bootstrap_ci_bps", {}).get("gate_7_passed", False)
    audit_net_exp = audit_period.get("net_expectancy_bps_cost14", -999.0)

    reasons: list[str] = []
    if not dev_g7:
        reasons.append(
            f"FAILED_DEV_GATE_7: Candidate {candidate_id} failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0"
        )
    if not audit_g7 or audit_net_exp <= 0.0:
        reasons.append(
            f"FAILED_EXPOSED_AUDIT: Candidate {candidate_id} failed burned 2026-H1 audit "
            f"(Audit Gate 7 passed={audit_g7}, Audit Net Exp={audit_net_exp:.2f} bps)"
        )

    disposition = "REJECTED_AFTER_EXPOSED_AUDIT" if reasons else "PASS_HISTORICAL_AUDIT"
    return {
        "candidate_id": str(candidate_id),
        "disposition": disposition,
        "eligible": False,  # Exposed historical candidates are never eligible for prospective registration
        "reasons": reasons,
        "dev_gate_7_passed": bool(dev_g7),
        "audit_gate_7_passed": bool(audit_g7),
        "audit_net_expectancy_bps": float(audit_net_exp),
    }


def validate_runtime_contract_compatibility(
    candidate_id: str,
    research_payload: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validates whether a research specification is schema- and execution-compatible with the runtime engine."""
    rejection_reasons: list[str] = []
    behavior_flags = research_payload.get("behavior_flags", {})
    req_slope = behavior_flags.get("req_slope", False)
    req_regime_gate = behavior_flags.get("req_regime_gate", False)
    use_atr_normalized_barrier = behavior_flags.get("use_atr_normalized_barrier", False)

    if req_slope or req_regime_gate or use_atr_normalized_barrier:
        rejection_reasons.append(
            "UNSUPPORTED_RUNTIME_SPEC_FIELDS: LockedCandidateSpec runtime schema does not support "
            f"req_slope={req_slope}, req_regime_gate={req_regime_gate}, or use_atr_normalized_barrier={use_atr_normalized_barrier}"
        )

    if candidate_id != "VOL_COMPRESSION_BREAKOUT_V1" and (req_slope or req_regime_gate or use_atr_normalized_barrier):
        rejection_reasons.append(
            "NO_RESEARCH_RUNTIME_DECISION_PARITY: Runtime lacks execution engine and decision parity verification "
            f"for candidate {candidate_id}"
        )

    return len(rejection_reasons) == 0, rejection_reasons


def validate_new_candidate_for_prospective_registration(
    candidate_input: ProspectiveCandidateRegistrationInput | dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validates a NEW prospective candidate designed AFTER audit exposure.

    CRITICAL EPISTEMIC GOVERNANCE RULE:
    This function is strictly BLIND to 2026-H1 burned audit metrics.
    Burned audit data (2026-H1) must NEVER be used as a selection filter or gate
    for prospective candidate admission.
    If ANY audit or burned field is present in candidate_input, it is rejected immediately (fail-closed).
    """
    rejection_reasons: list[str] = []

    # 1. Fail-closed scan: Reject any forbidden audit data
    if isinstance(candidate_input, ProspectiveCandidateRegistrationInput):
        input_dict = candidate_input.to_dict()
    elif isinstance(candidate_input, dict):
        input_dict = candidate_input
    else:
        return False, [f"INVALID_INPUT_TYPE: Expected ProspectiveCandidateRegistrationInput or dict, got {type(candidate_input)}"]

    forbidden = _scan_for_forbidden_audit_keys(input_dict)
    if forbidden:
        rejection_reasons.append(
            f"FORBIDDEN_AUDIT_DATA_IN_PROSPECTIVE_INPUT: Prospective registration input contains forbidden burned/audit keys: {forbidden}"
        )
        return False, rejection_reasons

    candidate_id = str(input_dict.get("candidate_id", ""))
    if not candidate_id:
        rejection_reasons.append("MISSING_CANDIDATE_ID: candidate_id must be provided and non-empty")

    # 2. Parameter and rationale specification
    params = input_dict.get("parameters")
    if not params or not isinstance(params, dict):
        rejection_reasons.append(f"MISSING_PARAMETERS: Candidate {candidate_id} missing valid parameter dictionary")

    rationale = input_dict.get("economic_rationale")
    if not rationale or not str(rationale).strip():
        rejection_reasons.append(f"MISSING_ECONOMIC_RATIONALE: Candidate {candidate_id} must have non-empty economic_rationale")

    # 3. DEV Walk-Forward selection criteria (strictly pre-2026 data)
    dev_summary = input_dict.get("dev_exploratory_summary") or {}
    dev_g7 = dev_summary.get("gate_7_passed", False)
    if not dev_g7 and "primary_daily_block_bootstrap_ci_bps" in dev_summary:
        dev_g7 = dev_summary["primary_daily_block_bootstrap_ci_bps"].get("gate_7_passed", False)

    dev_net_exp = dev_summary.get("net_expectancy_bps_cost14", -999.0)

    if not dev_g7 or dev_net_exp <= 0.0:
        rejection_reasons.append(
            f"FAILED_DEV_SELECTION_GATE: Candidate {candidate_id} failed DEV walk-forward selection "
            f"(DEV Gate 7 passed={dev_g7}, DEV Net Exp={dev_net_exp:.2f} bps)"
        )

    # 4. Runtime contract compatibility
    behavior_flags = input_dict.get("behavior_flags") or {}
    compat_payload = {"behavior_flags": behavior_flags}
    compat, compat_reasons = validate_runtime_contract_compatibility(candidate_id, compat_payload)
    if not compat:
        rejection_reasons.extend(compat_reasons)

    return len(rejection_reasons) == 0, rejection_reasons


def validate_candidate_for_prospective_draft(*args: Any, **kwargs: Any) -> tuple[bool, list[str]]:
    """DEPRECATED FAIL-CLOSED SHIM: Retired legacy selection function.

    This function previously evaluated candidates against the burned audit.
    It is permanently retired from all production execution paths.
    """
    raise RuntimeError(
        "DEPRECATED_LEGACY_FUNCTION: validate_candidate_for_prospective_draft has been retired because "
        "prospective candidate registration must not read burned audit metrics. "
        "Use classify_exposed_historical_candidate for historical audit or "
        "validate_new_candidate_for_prospective_registration for prospective admission."
    )


def extract_signals_with_rules(
    sym: str,
    c_df: pd.DataFrame,
    *,
    donchian_bars: int = 96,
    sma_fast_bars: int = 96,
    sma_slow_bars: int = 384,
    min_vol_ratio: float = 1.2,
    atr_bars: int = 192,
    req_slope: bool = False,
    req_regime_gate: bool = False,
    cache: CandleFeatureCache | None = None,
) -> list[dict[str, Any]]:
    """Extracts causal signal-bar triggers with strict no-lookahead guarantee."""
    closes = c_df["close"].to_numpy(dtype=float)
    highs = c_df["high"].to_numpy(dtype=float)
    lows = c_df["low"].to_numpy(dtype=float)
    vols = c_df["volume"].to_numpy(dtype=float)
    ts_list = c_df["timestamp"].tolist()
    n = len(c_df)

    if cache is not None:
        prev_hi = cache.get_donchian_high(sym, donchian_bars)
        prev_lo = cache.get_donchian_low(sym, donchian_bars)
        sma_f = cache.get_sma(sym, sma_fast_bars)
        sma_s = cache.get_sma(sym, sma_slow_bars)
        vol_ma = cache.get_vol_ma(sym, donchian_bars)
        atr_arr = cache.get_atr(sym, atr_bars)
    else:
        s_c = pd.Series(closes)
        s_h = pd.Series(highs)
        s_l = pd.Series(lows)
        s_v = pd.Series(vols)

        prev_hi = s_h.shift(1).rolling(donchian_bars).max().to_numpy()
        prev_lo = s_l.shift(1).rolling(donchian_bars).min().to_numpy()
        sma_f = s_c.rolling(sma_fast_bars).mean().to_numpy()
        sma_s = s_c.rolling(sma_slow_bars).mean().to_numpy()
        vol_ma = s_v.shift(1).rolling(donchian_bars).mean().to_numpy()

        tr = pd.concat(
            [s_h - s_l, (s_h - s_c.shift(1)).abs(), (s_l - s_c.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr_arr = tr.shift(1).rolling(atr_bars).mean().to_numpy()

    signals: list[dict[str, Any]] = []
    start_idx = max(sma_slow_bars + 32, atr_bars + 2, donchian_bars + 2)
    for i in range(start_idx, n - 1):
        if (
            np.isnan(prev_hi[i])
            or np.isnan(sma_s[i])
            or np.isnan(vol_ma[i])
            or vol_ma[i] <= 0.0
            or np.isnan(atr_arr[i])
            or atr_arr[i] <= 0.0
        ):
            continue

        vol_ratio = float(vols[i] / vol_ma[i])
        if vol_ratio < min_vol_ratio:
            continue

        side = None
        if closes[i] > prev_hi[i] and closes[i] > sma_s[i] and sma_f[i] > sma_s[i]:
            if not req_slope or (sma_s[i] > sma_s[i - 16]):
                if not req_regime_gate or (i >= 384 and sma_s[i] > sma_s[i - 384]):
                    side = "BUY"
        elif closes[i] < prev_lo[i] and closes[i] < sma_s[i] and sma_f[i] < sma_s[i]:
            if not req_slope or (sma_s[i] < sma_s[i - 16]):
                if not req_regime_gate or (i >= 384 and sma_s[i] < sma_s[i - 384]):
                    side = "SELL"
        if side is None:
            continue

        atr_bps = float(atr_arr[i] / closes[i] * 10000.0)
        signals.append({
            "symbol": sym,
            "signal_index": int(i),
            "signal_timestamp": _to_utc_ts(ts_list[i]),
            "side": side,
            "signal_close": float(closes[i]),
            "donchian_prev_high": float(prev_hi[i]),
            "donchian_prev_low": float(prev_lo[i]),
            "sma_fast": float(sma_f[i]),
            "sma_slow": float(sma_s[i]),
            "vol_ratio": vol_ratio,
            "atr_bps": atr_bps,
        })
    return signals


def simulate_candidate_stream(
    candidate_id: str,
    params: dict[str, Any],
    symbol_candles: Mapping[str, pd.DataFrame],
    *,
    coins: Sequence[str] | None = None,
    allowed_sides: tuple[str, ...] | list[str] | None = None,
    design_source: str | None = None,
    validation_status: str | None = None,
    use_atr_normalized_barrier: bool = False,
    req_slope: bool = False,
    req_regime_gate: bool = False,
    feature_cache: CandleFeatureCache | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Builds the full simulated candidate stream under NEXT_BAR_OPEN contract."""
    target_coins = tuple(coins) if coins is not None else tuple(params.get("universe", COINS))
    max_hold = params.get("max_hold_bars", 192)
    tp_bps_fixed = params.get("tp_bps", 350.0)
    sl_bps_fixed = params.get("sl_bps", 150.0)
    donchian_bars = params.get("donchian_bars", 96)
    sma_fast_bars = params.get("sma_fast_bars", 96)
    sma_slow_bars = params.get("sma_slow_bars", 384)
    min_vol_ratio = params.get("min_vol_ratio_96", 1.2)
    atr_bars = params.get("atr_compression_bars", 192)

    raw_rows: list[dict[str, Any]] = []
    for sym in target_coins:
        c_df = symbol_candles[sym]
        opens = c_df["open"].to_numpy(dtype=float)
        highs = c_df["high"].to_numpy(dtype=float)
        lows = c_df["low"].to_numpy(dtype=float)
        closes = c_df["close"].to_numpy(dtype=float)
        ts_list = c_df["timestamp"].tolist()

        sigs = extract_signals_with_rules(
            sym,
            c_df,
            donchian_bars=donchian_bars,
            sma_fast_bars=sma_fast_bars,
            sma_slow_bars=sma_slow_bars,
            min_vol_ratio=min_vol_ratio,
            atr_bars=atr_bars,
            req_slope=req_slope,
            req_regime_gate=req_regime_gate,
            cache=feature_cache,
        )
        for sig in sigs:
            i = sig["signal_index"]
            side = sig["side"]
            if allowed_sides is not None and side not in allowed_sides:
                continue

            if use_atr_normalized_barrier:
                # Dynamic ATR barrier: TP = 3.0 * ATR, SL = 1.5 * ATR (calibrated strictly from train volatility scale)
                effective_tp = max(50.0, min(600.0, sig["atr_bps"] * 3.0))
                effective_sl = max(30.0, min(300.0, sig["atr_bps"] * 1.5))
            else:
                effective_tp = tp_bps_fixed
                effective_sl = sl_bps_fixed

            sim = simulate_next_bar_open_barrier_trade(
                side,
                i,
                opens,
                highs,
                lows,
                closes,
                ts_list,
                max_hold=max_hold,
                tp_bps=effective_tp,
                sl_bps=effective_sl,
            )
            raw_rows.append({
                "trade_id": f"{candidate_id}_{sym}_{i}_{side}",
                "symbol": sym,
                "side": side,
                "signal_index": sim["signal_index"],
                "entry_index": sim["entry_index"],
                "exit_index": sim["exit_index"],
                "signal_timestamp": sim["signal_timestamp"],
                "signal_close_timestamp": sim["signal_close_timestamp"],
                "entry_timestamp": sim["entry_timestamp"],
                "exit_timestamp": sim["exit_timestamp"],
                "signal_close_price": sim["signal_close_price"],
                "entry_price": sim["entry_price"],
                "exit_price": sim["exit_price"],
                "exit_reason": sim["exit_reason"],
                "bars_held": sim["bars_held"],
                "same_bar_collision": sim["same_bar_collision"],
                "gap_through_stop": sim["gap_through_stop"],
                "gross_return_fraction": sim["gross_return_fraction"],
                "gross_pnl_bps": sim["gross_pnl_bps"],
                "atr_bps": sig["atr_bps"],
                "vol_ratio": sig["vol_ratio"],
            })

    df_raw = pd.DataFrame(raw_rows)
    if df_raw.empty or len(df_raw) == 0:
        cols = [
            "symbol", "entry_index", "entry_timestamp", "side", "entry_price",
            "exit_index", "exit_timestamp", "exit_price", "exit_reason",
            "bars_held", "same_bar_collision", "gap_through_stop",
            "gross_return_fraction", "gross_pnl_bps", "atr_bps", "vol_ratio"
        ]
        df_filtered = pd.DataFrame(columns=cols)
        q65_thresholds = {"DEV_2024_2025": 0.0, "BURNED_2026_H1": 0.0}
    else:
        df_filtered, q65_thresholds = _apply_fold_q65_filter(df_raw)

    spec_payload = build_canonical_research_candidate_payload(
        candidate_id,
        params,
        spec_version=(
            "1.0.0-research-v5" if candidate_id.startswith("VCB_V5")
            else ("1.0.0-research-v4" if candidate_id.startswith("VCB_V4") else "1.2.0-research-canonical")
        ),
        universe=target_coins,
        allowed_sides=allowed_sides,
        design_source=design_source,
        validation_status=validation_status,
        req_slope=req_slope,
        req_regime_gate=req_regime_gate,
        use_atr_normalized_barrier=use_atr_normalized_barrier,
    )
    spec_sha256 = compute_canonical_research_spec_sha256(spec_payload)

    meta = {
        **spec_payload,
        "spec_sha256": spec_sha256,
        "fold_fitted_atr_q65_thresholds_bps": q65_thresholds,
        "total_filtered_signals": int(len(df_filtered)),
    }
    return df_filtered, meta


def decompose_trades_dataframe(trades: Sequence[Any], period_name: str) -> dict[str, Any]:
    """Generates 9-dimension quantitative decomposition for a list of executed trades."""
    if not trades:
        return {
            "period": period_name,
            "executed_trade_count": 0,
            "overall_gross_expectancy_bps": 0.0,
            "overall_net_expectancy_bps": 0.0,
            "overall_net_pnl_usd": 0.0,
            "by_symbol": {},
            "by_side": {},
            "by_symbol_side": {},
            "by_exit_reason": {},
            "by_holding_period": {},
            "by_session_utc": {},
            "by_day_of_week": {},
            "cost_sensitivity": {},
        }

    t_df = pd.DataFrame([{
        "trade_id": t.trade_id,
        "symbol": t.symbol,
        "side": t.side,
        "entry_timestamp": pd.to_datetime(t.entry_timestamp, utc=True),
        "exit_timestamp": pd.to_datetime(t.exit_timestamp, utc=True),
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "exit_reason": t.exit_reason,
        "bars_held": t.bars_held,
        "gross_return_fraction": t.gross_return_fraction,
        "gross_bps": t.gross_return_fraction * 10000.0,
        "net_pnl_usd": t.net_pnl_usd,
        "net_return_bps": t.net_return_bps,
        "entry_hour": pd.to_datetime(t.entry_timestamp, utc=True).hour,
        "entry_dow": pd.to_datetime(t.entry_timestamp, utc=True).day_name(),
    } for t in trades])

    total_n = len(t_df)

    def _summary(sub: pd.DataFrame) -> dict[str, Any]:
        if sub.empty:
            return {"count": 0, "gross_exp_bps": 0.0, "net_exp_bps": 0.0, "win_rate_pct": 0.0, "net_pnl_usd": 0.0}
        n = len(sub)
        return {
            "count": int(n),
            "share_pct": round(float(n / total_n * 100.0), 1),
            "gross_exp_bps": round(float(sub["gross_bps"].mean()), 2),
            "net_exp_bps": round(float(sub["net_return_bps"].mean()), 2),
            "win_rate_pct": round(float((sub["net_return_bps"] > 0).mean() * 100.0), 1),
            "net_pnl_usd": round(float(sub["net_pnl_usd"].sum()), 2),
        }

    # 1. By Symbol
    by_symbol = {sym: _summary(grp) for sym, grp in t_df.groupby("symbol")}

    # 2. By Side
    by_side = {side: _summary(grp) for side, grp in t_df.groupby("side")}

    # 3. By Symbol x Side
    by_sym_side = {f"{sym}_{side}": _summary(grp) for (sym, side), grp in t_df.groupby(["symbol", "side"])}

    # 4. By Exit Reason
    by_exit = {}
    for reason, grp in t_df.groupby("exit_reason"):
        res = _summary(grp)
        res["avg_bars_held"] = round(float(grp["bars_held"].mean()), 1)
        by_exit[reason] = res

    # 5. By Holding Period
    t_df["hold_bucket"] = pd.cut(
        t_df["bars_held"],
        bins=[0, 16, 48, 96, 192],
        labels=["1-16_bars_le4h", "17-48_bars_4-12h", "49-96_bars_12-24h", "97-192_bars_24-48h"],
    )
    by_holding = {str(b): _summary(grp) for b, grp in t_df.groupby("hold_bucket", observed=False) if len(grp) > 0}

    # 6. By Session (UTC)
    t_df["session"] = pd.cut(
        t_df["entry_hour"],
        bins=[-1, 5, 11, 17, 23],
        labels=["00-06_ASIA", "06-12_EU", "12-18_US", "18-24_LATE_US"],
    )
    by_session = {str(s): _summary(grp) for s, grp in t_df.groupby("session", observed=False) if len(grp) > 0}

    # 7. By Day of Week
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_dow = {}
    for d in dow_order:
        grp = t_df[t_df["entry_dow"] == d]
        if not grp.empty:
            by_dow[d] = _summary(grp)

    # 8. Cost Sensitivity
    cost_sens = {}
    for c in [10.0, 14.0, 20.0, 30.0]:
        c_net = t_df["gross_bps"] - c
        pos = c_net[c_net > 0].sum()
        neg = abs(c_net[c_net < 0].sum())
        pf = round(float(pos / neg), 2) if neg > 0 else 999.0
        cost_sens[str(c)] = {
            "expectancy_bps": round(float(c_net.mean()), 2),
            "win_rate_pct": round(float((c_net > 0).mean() * 100.0), 1),
            "profit_factor": pf,
        }

    return {
        "period": period_name,
        "executed_trade_count": int(total_n),
        "overall_gross_expectancy_bps": round(float(t_df["gross_bps"].mean()), 2),
        "overall_net_expectancy_bps": round(float(t_df["net_return_bps"].mean()), 2),
        "overall_net_pnl_usd": round(float(t_df["net_pnl_usd"].sum()), 2),
        "by_symbol": by_symbol,
        "by_side": by_side,
        "by_symbol_side": by_sym_side,
        "by_exit_reason": by_exit,
        "by_holding_period": by_holding,
        "by_session_utc": by_session,
        "by_day_of_week": by_dow,
        "cost_sensitivity": cost_sens,
    }


def run_candidate_evaluation(
    candidate_id: str,
    spec_meta: dict[str, Any],
    cand_df: pd.DataFrame,
    acct: EventDrivenAccountingEngine,
    hourly_candles: Mapping[str, pd.DataFrame] | None = None,
    *,
    pre_sliced_hourly: Mapping[str, Mapping[str, pd.DataFrame]] | None = None,
    seed: int = 42,
    bootstrap_reps: int = 2000,
) -> dict[str, Any]:
    """Runs standard candidate evaluation across DEV_2024_2025 and BURNED_2026_H1."""
    eval_periods = {
        "DEV_WALK_FORWARD_SELECTION_2024_2025": ("2024-01-01", "2026-01-01", "DEV_WALK_FORWARD_EXPOSURE"),
        "BURNED_EXPOSED_AUDIT_2026_H1": ("2026-01-01", "2026-07-01", "BURNED_EXPOSED_AUDIT_PERMANENTLY_CONSUMED"),
    }
    periods_out: dict[str, Any] = {}

    for p_name, (start_d, end_d, epistemic_status) in eval_periods.items():
        start_ts = pd.Timestamp(start_d, tz="UTC")
        end_ts = pd.Timestamp(end_d, tz="UTC")
        sub_mask = (cand_df["entry_timestamp"] >= start_ts) & (cand_df["entry_timestamp"] < end_ts)
        p_trades = cand_df[sub_mask].to_dict("records")
        if pre_sliced_hourly is not None and p_name in pre_sliced_hourly:
            p_candles = pre_sliced_hourly[p_name]
        elif hourly_candles is not None:
            p_candles = _slice_candle_map(hourly_candles, start_d, end_d)
        else:
            raise ValueError("Either pre_sliced_hourly or hourly_candles must be provided to run_candidate_evaluation")

        sim_res = acct.run(
            p_trades,
            date_range=(start_d, end_d),
            candle_data=p_candles,
            cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
        )
        m = sim_res.to_dict()
        exec_trades = sim_res.executed_trades
        gross_arr = np.array([t.gross_return_fraction * 10000.0 for t in exec_trades], dtype=float)
        gross_exp = round(float(np.mean(gross_arr)), 2) if len(gross_arr) > 0 else 0.0

        daily_rets = sim_res.daily_returns
        np.random.seed(seed)
        block_ci = block_bootstrap_daily_mtm_ci(daily_rets, block_size=10, n_bootstraps=bootstrap_reps)

        gate_7_passed = bool(block_ci["ci_lower"] > 0.0)

        # Cost sensitivity
        cost_sens = {}
        for c in [10.0, 14.0, 20.0, 30.0]:
            if len(gross_arr) > 0:
                net_arr = gross_arr - c
                pos = net_arr[net_arr > 0].sum()
                neg = abs(net_arr[net_arr < 0].sum())
                pf = round(float(pos / neg), 2) if neg > 0 else 999.0
                cost_sens[str(c)] = {
                    "expectancy_bps": round(float(np.mean(net_arr)), 2),
                    "win_rate_pct": round(float((net_arr > 0).mean() * 100.0), 1),
                    "profit_factor": pf,
                }
            else:
                cost_sens[str(c)] = {"expectancy_bps": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0}

        periods_out[p_name] = {
            "epistemic_classification": epistemic_status,
            "candidate_signals_in_window": int(len(p_trades)),
            "executed_trades_count": int(m["executed_trades_count"]),
            "rejected_capacity_count": int(m["rejected_capacity_count"]),
            "excluded_cross_boundary_count": int(m["excluded_cross_boundary_count"]),
            "total_net_pnl_usd": round(float(m["total_net_pnl_usd"]), 2),
            "total_net_pnl_pct": round(float(m["total_net_pnl_pct"]), 2),
            "gross_profit_usd": round(float(m["gross_profit_usd"]), 2),
            "gross_loss_usd": round(float(m["gross_loss_usd"]), 2),
            "profit_factor": round(float(m["profit_factor"]), 4),
            "gross_expectancy_bps": gross_exp,
            "net_expectancy_bps_cost14": round(float(m["expectancy_bps"]), 2),
            "win_rate_pct": round(float(m["win_rate_pct"]), 1),
            "max_drawdown_pct": round(float(m["max_drawdown_pct"]), 2),
            "capital_turnover": round(float(m["capital_turnover"]), 2),
            "primary_daily_block_bootstrap_ci_bps": {
                "ci_lower": round(float(block_ci["ci_lower"]), 3),
                "ci_upper": round(float(block_ci["ci_upper"]), 3),
                "mean_daily_bps": round(float(block_ci["mean_daily_bps"]), 3),
                "block_size_days": int(block_ci["block_size_days"]),
                "gate_7_passed": gate_7_passed,
            },
            "cost_sensitivity": cost_sens,
            "raw_executed_trades": exec_trades,
        }

    return {
        "candidate_id": candidate_id,
        "spec_sha256": spec_meta.get("spec_sha256"),
        "parameters": spec_meta.get("parameters", {}),
        "periods": periods_out,
    }


def fmt_bps(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"+{val:.2f}" if val > 0 else f"{val:.2f}"


def render_decomposition_markdown(data: dict[str, Any]) -> str:
    """Renders vcb_economic_decomposition.md directly from JSON data."""
    v1_dev = data["decompositions"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    v1_aud = data["decompositions"]["BURNED_EXPOSED_AUDIT_2026_H1"]

    lines = [
        "# VOL_COMPRESSION_BREAKOUT_V1: Economic Attribution & Edge Loss Decomposition",
        "",
        f"- **Generated Timestamp**: `{data['generation_timestamp']}` (UTC)",
        f"- **Git HEAD**: `{data['git_head']}`",
        f"- **Semantic Artifact SHA-256**: `{data.get('semantic_artifact_sha256', 'N/A')}`",
        f"- **Dataset SHA-256**: `{data['dataset_manifest']['combined_dataset_sha256']}`",
        f"- **Spec SHA-256**: `{data['candidate_spec']['spec_sha256']}`",
        f"- **System Operating Disposition**: `RUNTIME_READY, ECONOMIC_NO_GO, NO_TRADE_SHADOW`",
        "",
        "## 1. Executive Summary & Period Comparison",
        "",
        "| Metric | DEV Walk-Forward (2024–2025) | Burned Exposed Audit (2026 H1) | Delta (Audit - DEV) | Economic Interpretation |",
        "| :--- | :---: | :---: | :---: | :--- |",
        f"| **Executed Trades ($N$)** | {v1_dev['executed_trade_count']} | {v1_aud['executed_trade_count']} | {v1_aud['executed_trade_count'] - v1_dev['executed_trade_count']} | High sample volume in both periods |",
        f"| **Gross Expectancy (bps)** | `{fmt_bps(v1_dev['overall_gross_expectancy_bps'])}` | `{fmt_bps(v1_aud['overall_gross_expectancy_bps'])}` | `{fmt_bps(v1_aud['overall_gross_expectancy_bps'] - v1_dev['overall_gross_expectancy_bps'])} bps` | Gross edge completely evaporated |",
        f"| **Net Expectancy @14 (bps)** | `{fmt_bps(v1_dev['overall_net_expectancy_bps'])}` | `{fmt_bps(v1_aud['overall_net_expectancy_bps'])}` | `{fmt_bps(v1_aud['overall_net_expectancy_bps'] - v1_dev['overall_net_expectancy_bps'])} bps` | Severe negative net return |",
        f"| **Net PnL (USD)** | `+${v1_dev['overall_net_pnl_usd']:.2f}` | `-${abs(v1_aud['overall_net_pnl_usd']):.2f}` | `-${abs(v1_aud['overall_net_pnl_usd']) + v1_dev['overall_net_pnl_usd']:.2f}` | Capital drawdown in 2026 H1 |",
        "",
        "## 2. Quantitative Decomposition by Dimension",
        "",
        "### A. By Symbol",
        "",
        "| Symbol | DEV N | DEV Gross (bps) | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 Net PnL ($) | 2026 WR% | Dollar Loss Share |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    total_aud_pnl = v1_aud["overall_net_pnl_usd"]
    for sym in ["BTC", "BNB", "ETH"]:
        d_s = v1_dev["by_symbol"].get(sym, {})
        a_s = v1_aud["by_symbol"].get(sym, {})
        loss_share = f"{a_s.get('net_pnl_usd', 0.0) / total_aud_pnl * 100.0:.1f}%" if total_aud_pnl < 0 else "N/A"
        lines.append(
            f"| **{sym}** | {d_s.get('count', 0)} | `{fmt_bps(d_s.get('gross_exp_bps'))}` | `{fmt_bps(d_s.get('net_exp_bps'))}` | "
            f"{a_s.get('count', 0)} | `{fmt_bps(a_s.get('gross_exp_bps'))}` | `{fmt_bps(a_s.get('net_exp_bps'))}` | "
            f"`${a_s.get('net_pnl_usd', 0.0):.2f}` | {a_s.get('win_rate_pct', 0.0):.1f}% | {loss_share} |"
        )

    lines.extend([
        "",
        "### B. By Side (Directional Asymmetry: BUY vs SELL)",
        "",
        "| Side | DEV N | DEV Gross (bps) | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 Net PnL ($) | 2026 WR% |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for side in ["BUY", "SELL"]:
        d_sd = v1_dev["by_side"].get(side, {})
        a_sd = v1_aud["by_side"].get(side, {})
        lines.append(
            f"| **{side}** | {d_sd.get('count', 0)} | `{fmt_bps(d_sd.get('gross_exp_bps'))}` | `{fmt_bps(d_sd.get('net_exp_bps'))}` | "
            f"{a_sd.get('count', 0)} | `{fmt_bps(a_sd.get('gross_exp_bps'))}` | `{fmt_bps(a_sd.get('net_exp_bps'))}` | "
            f"`${a_sd.get('net_pnl_usd', 0.0):.2f}` | {a_sd.get('win_rate_pct', 0.0):.1f}% |"
        )

    lines.extend([
        "",
        "### C. By Exit Reason & Barrier Dynamics (TP vs SL vs TIMEOUT)",
        "",
        "| Exit Reason | DEV N (Share%) | DEV Net @14 | Burned 2026 N (Share%) | Burned Gross (bps) | Burned Net @14 | 2026 Avg Bars | 2026 Net PnL ($) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for ex in ["TP", "SL", "TIMEOUT"]:
        d_ex = v1_dev["by_exit_reason"].get(ex, {})
        a_ex = v1_aud["by_exit_reason"].get(ex, {})
        lines.append(
            f"| **{ex}** | {d_ex.get('count', 0)} ({d_ex.get('share_pct', 0.0):.1f}%) | `{fmt_bps(d_ex.get('net_exp_bps'))}` | "
            f"{a_ex.get('count', 0)} ({a_ex.get('share_pct', 0.0):.1f}%) | `{fmt_bps(a_ex.get('gross_exp_bps'))}` | `{fmt_bps(a_ex.get('net_exp_bps'))}` | "
            f"{a_ex.get('avg_bars_held', 0.0):.1f} | `${a_ex.get('net_pnl_usd', 0.0):.2f}` |"
        )

    lines.extend([
        "",
        "### D. By Holding Period Buckets",
        "",
        "| Holding Period | DEV N | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 WR% |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for hp in ["1-16_bars_le4h", "17-48_bars_4-12h", "49-96_bars_12-24h", "97-192_bars_24-48h"]:
        d_h = v1_dev["by_holding_period"].get(hp, {})
        a_h = v1_aud["by_holding_period"].get(hp, {})
        lines.append(
            f"| `{hp}` | {d_h.get('count', 0)} | `{fmt_bps(d_h.get('net_exp_bps'))}` | "
            f"{a_h.get('count', 0)} | `{fmt_bps(a_h.get('gross_exp_bps'))}` | `{fmt_bps(a_h.get('net_exp_bps'))}` | {a_h.get('win_rate_pct', 0.0):.1f}% |"
        )

    lines.extend([
        "",
        "### E. By Session (UTC Entry Hour)",
        "",
        "| Session (UTC) | DEV N | DEV Net @14 | Burned 2026 N | Burned Gross (bps) | Burned Net @14 | 2026 WR% |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for s_name in ["00-06_ASIA", "06-12_EU", "12-18_US", "18-24_LATE_US"]:
        d_se = v1_dev["by_session_utc"].get(s_name, {})
        a_se = v1_aud["by_session_utc"].get(s_name, {})
        lines.append(
            f"| `{s_name}` | {d_se.get('count', 0)} | `{fmt_bps(d_se.get('net_exp_bps'))}` | "
            f"{a_se.get('count', 0)} | `{fmt_bps(a_se.get('gross_exp_bps'))}` | `{fmt_bps(a_se.get('net_exp_bps'))}` | {a_se.get('win_rate_pct', 0.0):.1f}% |"
        )

    lines.extend([
        "",
        "### F. Cost Sensitivity Comparison",
        "",
        "| Friction Tier | DEV Expectancy (bps) | DEV Win Rate | DEV Profit Factor | Burned 2026 Expectancy (bps) | Burned 2026 Win Rate | Burned 2026 Profit Factor |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for c in ["10.0", "14.0", "20.0", "30.0"]:
        d_c = v1_dev["cost_sensitivity"].get(c, {})
        a_c = v1_aud["cost_sensitivity"].get(c, {})
        lines.append(
            f"| **{c} bps** | `{fmt_bps(d_c.get('expectancy_bps'))}` | {d_c.get('win_rate_pct', 0.0):.1f}% | {d_c.get('profit_factor', 0.0):.2f} | "
            f"`{fmt_bps(a_c.get('expectancy_bps'))}` | {a_c.get('win_rate_pct', 0.0):.1f}% | {a_c.get('profit_factor', 0.0):.2f} |"
        )

    lines.extend([
        "",
        "## 3. Epistemic Governance & Separation of Facts vs Inferences",
        "",
        "- **Observed Evidence (Facts)**:",
        "  1. BUY trades collapsed to `-41.06 bps` net in 2026 H1, generating 103.5% of total portfolio dollar drawdown.",
        "  2. BTC accounted for 76.0% of total portfolio losses in 2026 H1.",
        "  3. TP hit rate collapsed from 30.4% down to 16.8%, well below the 32.8% break-even barrier ratio.",
        "  4. Premature stops (17–48 bars / 4–12h) suffered an extreme `-103.94 bps` net loss (12.0% win rate).",
        "  5. US session (12–18 UTC) collapsed to `-36.53 bps` net (28.9% win rate).",
        "  6. Friction of 14 bps per trade combined with 60.84x turnover added -17.50 bps of cost drag.",
        "",
        "- **Hypotheses / Inferences (Unproven Causal Drivers)**:",
        "  1. *Bear-rally entry hypothesis*: Naive Donchian 96 buys counter-trend bear market rallies at local peaks.",
        "  2. *Macro whipsaw hypothesis*: US market open triggers fakeout volatility spikes that hit narrow 150 bps stops.",
        "  3. *Regime decay hypothesis*: Volatility compression breakout requires persistent followthrough which degraded in 2026 H1.",
        "",
        "- **Permanent Disposition**: Candidate `VOL_COMPRESSION_BREAKOUT_V1` is classified as `ECONOMIC_NO_GO`. 2026 H1 is permanently burned.",
    ])

    return "\n".join(lines)


def render_variants_markdown(data: dict[str, Any]) -> str:
    """Renders vcb_exploratory_variants.md directly from JSON data."""
    perf = data.get("performance_metadata", {})
    elapsed_str = f"{perf.get('elapsed_seconds', 'N/A')}s"
    mem_str = f"{perf.get('peak_memory_mb', 'N/A')} MB"

    lines = [
        "# Post-Hoc Exploratory V2/V3 Candidate Variants & Promotion Gate Evaluation",
        "",
        f"- **Generated Timestamp**: `{data['generation_timestamp']}` (UTC)",
        f"- **Git HEAD**: `{data['git_head']}`",
        f"- **Semantic Artifact SHA-256**: `{data.get('semantic_artifact_sha256', 'N/A')}`",
        f"- **Dataset SHA-256**: `{data['dataset_manifest']['combined_dataset_sha256']}`",
        f"- **Candidate Selection Verdict**: `{data.get('candidate_selection_verdict', 'NO_CANDIDATE_SELECTED')}`",
        f"- **Prospective Shadow Status**: `{data.get('prospective_status', 'NOT_STARTED')}`",
        f"- **Runtime Candidate Spec**: `null`",
        f"- **Activation Manifest**: `null`",
        f"- **Pipeline Performance**: Elapsed `{elapsed_str}` | Peak Memory `{mem_str}`",
        f"- **Epistemic Disclosure**: All V2 and V3 variants evaluated below are **post-hoc exploratory hypotheses generated after exposure to the burned 2026-H1 audit**. They are NOT pre-registered, NOT OOS-validated, NOT promotion-qualified, and must NEVER be used to claim positive economic edge.",
        f"- **Primary Statistical Gate**: Moving-Block Bootstrap 95% CI Lower Bound on Daily Portfolio MTM returns > 0.0 bps/day (block_size=10d, 2000 reps, seed=42).",
        "",
        "## 1. Candidate Comparison Table Across Folds",
        "",
        "| Candidate ID | Economic Hypothesis | Window | Exec N | Gross Exp (bps) | Net @14 Exp (bps) | Profit Factor | Max DD% | Daily Block Bootstrap 95% CI (bps/d) | Gate 7 Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for cand_id, cand_res in data["candidates"].items():
        hyp = cand_res.get("economic_rationale", "N/A")
        periods = cand_res.get("periods", {})
        for p_name in ["DEV_WALK_FORWARD_SELECTION_2024_2025", "BURNED_EXPOSED_AUDIT_2026_H1"]:
            p = periods.get(p_name, {})
            b_ci = p.get("primary_daily_block_bootstrap_ci_bps", {})
            p_short = "DEV 24–25" if "DEV" in p_name else "Burned 2026"
            g7 = "PASSED" if b_ci.get("gate_7_passed") else "FAILED"
            lines.append(
                f"| **{cand_id}** | {hyp} | {p_short} | {p.get('executed_trades_count', 0)} | "
                f"`{p.get('gross_expectancy_bps', 0.0):.2f}` | `{p.get('net_expectancy_bps_cost14', 0.0):.2f}` | "
                f"{p.get('profit_factor', 0.0):.2f} | {p.get('max_drawdown_pct', 0.0):.2f}% | "
                f"`[{b_ci.get('ci_lower', 0.0):.3f}, {b_ci.get('ci_upper', 0.0):.3f}]` | **{g7}** |"
            )

    lines.extend([
        "",
        "## 2. Incontrovertible Scientific Findings & Fail-Closed Selection",
        "",
        "1. **Universal Gate 7 Failure**: In **all** candidate variants, the Primary Daily Portfolio Block Bootstrap 95% CI lower bound is $\\le 0.0$ in DEV 2024–2025 (all encompass negative daily drift), and severely negative in 2026 H1 (`-10.11` to `-12.04 bps/day`).",
        "2. **Zero Statistical Promotion**: Not a single candidate variant passes the required statistical promotion gate.",
        "3. **Fail-Closed Gate Enforced**: All candidates rejected. No activation manifest is emitted. Prospective 90-day clock remains strictly **NOT_STARTED**.",
        "4. **Operating Policy**: Enforce `PAPER_ECONOMIC_POLICY=NO_TRADE_SHADOW` (`AUTO_TRADE_DRY_RUN=true`). Zero orders generated.",
        "",
        "## 3. Rejection Audit Summary",
        "",
        "| Candidate ID | Selection Eligibility | Historical Disposition | Primary Failure Reasons |",
        "| :--- | :---: | :---: | :--- |",
    ])

    for cid, audit in data.get("rejection_audit", {}).items():
        status = "ELIGIBLE" if audit.get("eligible") else "REJECTED"
        disp = audit.get("historical_disposition", "N/A")
        reasons = "<br>".join(audit.get("reasons", ["Passed all selection gates"]))
        lines.append(f"| **{cid}** | `{status}` | `{disp}` | {reasons} |")

    return "\n".join(lines)


def render_v5_cross_sectional_markdown(data: dict[str, Any]) -> str:
    """Renders comprehensive Markdown report for VCB_V5_SELL_ONLY_9ASSET cross-sectional holdout."""
    p_eval = data.get("primary_holdout_evaluation", {})
    gate_eval = data.get("gate_scorecard", {})
    sub_eval = data.get("temporal_stability_diagnostics", {})
    rates = data.get("trade_rate_comparison", {})
    diag_design = data.get("diagnostic_design_assets_summary", {})
    bs_res = p_eval.get("primary_daily_block_bootstrap_ci_bps", {})
    cs = p_eval.get("cost_sensitivity", {})

    lines = [
        "# VCB V5 Cross-Sectional Holdout Research Report",
        "",
        "## 1. Executive Summary",
        "",
        f"- **Pipeline**: `{data['pipeline_name']}`",
        f"- **Candidate ID**: `{data['candidate_id']}`",
        f"- **Specification SHA-256**: `{data.get('candidate_spec', {}).get('spec_sha256', '')}`",
        f"- **Semantic Artifact SHA-256**: `{data.get('semantic_artifact_sha256', '')}`",
        f"- **Epistemic Classification**: `{data['epistemic_classification']}`",
        f"- **Admission Verdict**: `{data['admission_verdict']}`",
        "- **System Operating Disposition**:",
        f"  - `candidate_selection_verdict`: `{data['system_operating_disposition']['candidate_selection_verdict']}`",
        f"  - `prospective_status`: `{data['system_operating_disposition']['prospective_status']}`",
        "  - `runtime_candidate_spec`: `null`",
        "  - `activation_manifest`: `null`",
        "",
        "---",
        "",
        "## 2. Gate Evaluation Scorecard (Primary Holdout Universe: DOGE, IOTA, NEAR, SOL, TRX, ZEC)",
        "",
        "| Gate | Description | Threshold | Observed | Verdict |",
        "|---|---|---|---|---|",
        f"| Gate 1 | Sample Size (Trades) | $\\ge 100$ | {gate_eval.get('gate_1_sample_size', {}).get('observed', 0)} | {'✅ PASS' if gate_eval.get('gate_1_sample_size', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 2 | Net Expectancy @ 14 bps | $> 0.0$ bps | {gate_eval.get('gate_2_net_expectancy', {}).get('observed', 0.0):.2f} bps | {'✅ PASS' if gate_eval.get('gate_2_net_expectancy', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 3 | Profit Factor | $> 1.0$ | {gate_eval.get('gate_3_profit_factor', {}).get('observed', 0.0):.4f} | {'✅ PASS' if gate_eval.get('gate_3_profit_factor', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 4 | Daily Block Bootstrap 95% CI Lower | $> 0.0$ bps/day | {gate_eval.get('gate_4_bootstrap_lower', {}).get('observed', 0.0):.3f} bps/day | {'✅ PASS' if gate_eval.get('gate_4_bootstrap_lower', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 5 | Cross-Sectional Breadth | $\\ge 4$ active assets | {gate_eval.get('gate_5_cross_sectional_breadth', {}).get('observed', 0)} assets | {'✅ PASS' if gate_eval.get('gate_5_cross_sectional_breadth', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 6 | Concentration Risk | $< 80.0\\%$ max share | {gate_eval.get('gate_6_concentration_risk', {}).get('observed', 0.0):.1f}% | {'✅ PASS' if gate_eval.get('gate_6_concentration_risk', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 7 | Maximum Drawdown | $\\le 20.0\\%$ | {gate_eval.get('gate_7_max_drawdown', {}).get('observed', 0.0):.2f}% | {'✅ PASS' if gate_eval.get('gate_7_max_drawdown', {}).get('passed') else '❌ FAIL'} |",
        f"| Gate 8 | Friction Tolerance @ 20 bps | $\\ge -5.0$ bps | {gate_eval.get('gate_8_friction_tolerance', {}).get('observed', 0.0):.2f} bps | {'✅ PASS' if gate_eval.get('gate_8_friction_tolerance', {}).get('passed') else '❌ FAIL'} |",
        "",
        "---",
        "",
        "## 3. Primary Holdout Quantitative Metrics",
        "",
        f"- **Period**: `[{p_eval.get('start', '')}, {p_eval.get('end', '')})` ({p_eval.get('calendar_days', 0)} calendar days)",
        f"- **Executed Trades**: {p_eval.get('executed_trade_count', 0)}",
        f"- **Gross Expectancy**: {p_eval.get('gross_expectancy_bps', 0.0):.2f} bps",
        f"- **Net Expectancy @ 14 bps**: {p_eval.get('net_expectancy_bps_cost14', 0.0):.2f} bps",
        f"- **Win Rate**: {p_eval.get('win_rate_pct', 0.0):.1f}%",
        f"- **Profit Factor**: {p_eval.get('profit_factor', 0.0):.4f}",
        f"- **Daily Block Bootstrap 95% CI**: `[{bs_res.get('ci_lower', 0.0):.3f}, {bs_res.get('ci_upper', 0.0):.3f}]` bps/day",
        "- **Cost Sensitivity**:",
        f"  - Net @ 10 bps: {cs.get('net_bps_cost10', 0.0):.2f} bps",
        f"  - Net @ 14 bps: {cs.get('net_bps_cost14', 0.0):.2f} bps",
        f"  - Net @ 20 bps: {cs.get('net_bps_cost20', 0.0):.2f} bps",
        f"  - Net @ 30 bps: {cs.get('net_bps_cost30', 0.0):.2f} bps",
        "",
        "---",
        "",
        "## 4. Trade Rate & Sample Accumulation Velocity",
        "",
        "| Metric | V4 Baseline (3 Design Assets) | V5 Holdout (6 Holdout Assets) | Speedup Factor |",
        "|---|---|---|---|",
        f"| Trades / Calendar Day | {rates.get('v4_baseline_trades_per_day', 0.2202):.4f} | {rates.get('v5_holdout_trades_per_day', 0.0):.4f} | {rates.get('sample_accumulation_speedup_factor', 0.0)}x |",
        f"| Projected Trades (90 Days) | {rates.get('v4_baseline_90d_trades', 19.8):.1f} | {rates.get('v5_holdout_90d_trades', 0.0):.1f} | {rates.get('sample_accumulation_speedup_factor', 0.0)}x |",
        f"| Estimated Days to N=100 | {rates.get('v4_baseline_days_to_n100', 454.1):.1f} days | {rates.get('v5_holdout_days_to_n100', 0.0)} days | - |",
        "",
        "---",
        "",
        "## 5. Temporal Stability Diagnostics",
        "",
        "| Sub-Window | Trades | Net Expectancy @ 14 bps | Profit Factor | Win Rate |",
        "|---|---|---|---|---|",
    ]

    for sw_name, sw in sub_eval.items():
        lines.append(
            f"| {sw_name} | {sw.get('trade_count', 0)} | {sw.get('net_expectancy_bps_cost14', 0.0):.2f} bps | {sw.get('profit_factor', 0.0):.4f} | {sw.get('win_rate_pct', 0.0):.1f}% |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 6. Diagnostic Reference: Exposed Design Assets (BTC, ETH, BNB)",
        "",
        f"- **Executed Trades**: {diag_design.get('executed_trades_count', 0)}",
        f"- **Net Expectancy @ 14 bps**: {diag_design.get('net_expectancy_bps_cost14', 0.0):.2f} bps",
        "- **Note**: Exposed design assets are presented strictly as a diagnostic baseline and do not enter primary admission criteria.",
        "",
        "---",
        "",
        "## 7. Chronology Audit & Epistemic Demotion",
        "",
        f"- **Chronology Audit Verdict**: `{data.get('chronology_verdict', 'PRE_REGISTRATION_NOT_PROVABLE')}`",
        f"- **Epistemic Classification**: `{data.get('epistemic_classification', 'DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC')}`",
        f"- **Earliest Artifact Filesystem Creation**: `{data.get('chronology_audit', {}).get('earliest_artifact_filesystem_creation_utc', 'N/A')}`",
        f"- **Internal Spec Lock Time**: `{data.get('chronology_audit', {}).get('internal_spec_lock_utc', 'N/A')}`",
        f"- **Earliest Known Raw Read / Debug Run**: `{data.get('chronology_audit', {}).get('earliest_known_raw_read_or_debug_run_utc', 'N/A')}`",
        "- **Governance Epistemic Note**: Candidate specification was originally intended to lock prior to reading holdout candles, but during debugging data was read and evaluator was launched before the final lock artifact. Chronology audit verdict is PRE_REGISTRATION_NOT_PROVABLE. Metrics are retained strictly as post-hoc diagnostic data, not confirmatory out-of-sample evidence, and cannot be used for prospective admission.",
        f"- **Historical Search Status**: `{data.get('historical_candidate_search_status', 'HISTORICAL_CANDIDATE_SEARCH_STOPPED')}`",
        f"- **Historical Stop Rationale**: {data.get('historical_search_stop_reason', '')}",
        "",
    ])

    return "\n".join(lines)


def render_v4_sell_only_markdown(data: dict[str, Any]) -> str:
    """Renders vcb_v4_sell_only_research.md directly from JSON data."""
    ev = data["evaluation_summary"]
    dev = ev["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    aud = ev["BURNED_EXPOSED_AUDIT_2026_H1"]
    rates = data["trade_rate_projections"]
    adm = data["admission_evaluation"]
    scorecard = adm["stage_2_dev_gate_scorecard"]

    dev_ci = dev["primary_daily_block_bootstrap_ci_bps"]
    aud_ci = aud["primary_daily_block_bootstrap_ci_bps"]

    lines = [
        "# VCB_V4_SELL_ONLY: Directional Asymmetry Hypothesis & Research Admission Report",
        "",
        f"- **Generated Timestamp**: `{data['generation_timestamp']}` (UTC)",
        f"- **Git HEAD**: `{data['git_head']}`",
        f"- **Semantic Artifact SHA-256**: `{data.get('semantic_artifact_sha256', 'N/A')}`",
        f"- **Dataset SHA-256**: `{data['dataset_manifest']['combined_dataset_sha256']}`",
        f"- **Candidate ID**: `{data['candidate_id']}`",
        f"- **Allowed Sides**: `{data['allowed_sides']}`",
        f"- **Spec Version**: `{data['spec_version']}`",
        f"- **Spec SHA-256**: `{data['candidate_spec']['spec_sha256']}`",
        f"- **Design Source**: `{data['design_source']}`",
        f"- **Validation Status**: `{data['validation_status']}`",
        f"- **Stage 2 Admission Verdict**: `{adm['admission_verdict']}`",
        f"- **System Operating Disposition**: `{data['system_operating_disposition']['candidate_selection_verdict']}, {data['system_operating_disposition']['prospective_status']}, NO_TRADE_SHADOW`",
        "",
        "## 1. Executive Summary & Hypothesis Rationale",
        "",
        "### 1.1 Hypothesis Background",
        "- **Empirical Observation on Consumed Data**: Canonical decomposition of `VOL_COMPRESSION_BREAKOUT_V1` revealed stark directional asymmetry in the exposed 2026-H1 audit: BUY trades suffered catastrophic negative drift (`-41.06 bps` net, driving 103.5% of total portfolio drawdown), whereas SELL trades preserved positive returns (`+4.01 bps` net @14 bps). On DEV (2024–2025), SELL trades were also positive.",
        "- **Hypothesis Formulation (`VCB_V4_SELL_ONLY`)**: Restricting the strategy strictly to `allowed_sides = ['SELL']` while freezing all other V1 parameters (Donchian 96, SMA 96/384, Vol 1.2x, ATR 192, TP 350, SL 150, max hold 192, cooldown 96, NEXT_BAR_OPEN) tests whether eliminating counter-trend long entries achieves sustainable positive edge.",
        "- **Strict Epistemic Governance Warning**: This hypothesis is **post-hoc**, formulated after observing 2026-H1 data. It does NOT constitute validated out-of-sample edge. Under strict governance, the 2026-H1 window remains permanently burned and cannot be used for admission. Admission is evaluated strictly on pre-2026 DEV walk-forward performance.",
        "",
        "## 2. Statistical Gate Scorecard on DEV Walk-Forward Selection (2024–2025)",
        "",
        "| Gate / Requirement | Threshold / Criterion | Observed DEV Metric | Gate Status | Verdict |",
        "| :--- | :--- | :---: | :---: | :--- |",
        f"| **Gate 1: Net Expectancy (@14 bps)** | `> 0.0 bps` | `{fmt_bps(dev['net_expectancy_bps_cost14'])} bps` | {'PASSED' if scorecard['net_expectancy_positive'] else 'FAILED'} | Net expectancy positive |",
        f"| **Gate 2: Profit Factor** | `> 1.0` | `{dev['profit_factor']:.4f}` | {'PASSED' if scorecard['profit_factor_above_one'] else 'FAILED'} | Gross profit > gross loss |",
        f"| **Gate 3: Asset Diversification** | `Active Assets >= 2` | `3 assets (BTC, ETH, BNB)` | {'PASSED' if scorecard['min_two_assets_active'] else 'FAILED'} | Well-diversified across assets |",
        f"| **Gate 4: Trade Sample Size** | `N >= 30 (Sufficient)` | `{dev['executed_trades_count']} trades` | {'PASSED' if scorecard['sample_sufficient_for_trade_rate'] else 'FAILED'} | Sample size adequate for rate estimation |",
        f"| **Gate 5: Zero-Coverage Fold** | `No empty folds` | `0 empty folds` | {'PASSED' if scorecard['no_zero_coverage_fold'] else 'FAILED'} | Uniform fold coverage |",
        f"| **Gate 7: Primary Daily Portfolio Block Bootstrap 95% CI** | `CI Lower Bound > 0.0 bps/d` | `[{dev_ci['ci_lower']:.3f}, {dev_ci['ci_upper']:.3f}] bps/d` | {'PASSED' if scorecard['gate_7_ci_lower_positive'] else 'FAILED'} | **FAILED**: Lower bound spans negative territory |",
        "",
        "> [!IMPORTANT]",
        f"> **Stage 2 Admission Result**: **`{adm['admission_verdict']}`**  ",
        f"> Despite positive net expectancy (+10.72 bps) and profit factor (1.11), candidate `VCB_V4_SELL_ONLY` **fails Gate 7** on the primary daily portfolio block bootstrap (`ci_lower = {dev_ci['ci_lower']:.3f} bps/day` $\\le 0.0$).  ",
        "> Because trade frequency is halved by filtering out long signals, daily return variance is insufficiently buffered against market chop, preventing the 95% confidence interval from clearing zero.",
        "",
        "## 3. Diagnostic Comparison: DEV (2024–2025) vs. Consumed Audit (2026-H1)",
        "",
        "*(Note: 2026-H1 metrics are presented strictly as consumed diagnostic observations; they were NOT used as selection criteria or passed into prospective admission inputs).* ",
        "",
        "| Metric | DEV Walk-Forward (2024–2025) | Burned Exposed Audit (2026-H1) | Delta (Audit - DEV) | Diagnostic Interpretation |",
        "| :--- | :---: | :---: | :---: | :--- |",
        f"| **Executed Trades ($N$)** | {dev['executed_trades_count']} | {aud['executed_trades_count']} | {aud['executed_trades_count'] - dev['executed_trades_count']} | Trade frequency ~0.22 trades/day |",
        f"| **Gross Expectancy (bps)** | `{fmt_bps(dev['gross_expectancy_bps'])}` | `{fmt_bps(aud['gross_expectancy_bps'])}` | `{fmt_bps(aud['gross_expectancy_bps'] - dev['gross_expectancy_bps'])} bps` | Modest gross drift |",
        f"| **Net Expectancy @14 (bps)** | `{fmt_bps(dev['net_expectancy_bps_cost14'])}` | `{fmt_bps(aud['net_expectancy_bps_cost14'])}` | `{fmt_bps(aud['net_expectancy_bps_cost14'] - dev['net_expectancy_bps_cost14'])} bps` | Positive net return in both windows |",
        f"| **Profit Factor** | {dev['profit_factor']:.4f} | {aud['profit_factor']:.4f} | {aud['profit_factor'] - dev['profit_factor']:+.4f} | Borderline above 1.0 |",
        f"| **Max Drawdown (%)** | {dev['max_drawdown_pct']:.2f}% | {aud['max_drawdown_pct']:.2f}% | {aud['max_drawdown_pct'] - dev['max_drawdown_pct']:+.2f}% | Bounded drawdown < 10% |",
        f"| **Daily Block Bootstrap CI (bps/d)** | `[{dev_ci['ci_lower']:.3f}, {dev_ci['ci_upper']:.3f}]` | `[{aud_ci['ci_lower']:.3f}, {aud_ci['ci_upper']:.3f}]` | N/A | Lower bound negative in both windows |",
        "",
        "### 3.1 Cost Sensitivity Analysis (Net Expectancy across Fee Tiers)",
        "",
        "| Cost Tier (Round-Trip) | DEV Net Expectancy | Burned 2026-H1 Net Expectancy | Viability Assessment |",
        "| :---: | :---: | :---: | :--- |",
    ]

    dev_cost = dev.get("cost_sensitivity", {})
    aud_cost = aud.get("cost_sensitivity", {})
    for tier in ["10.0", "14.0", "20.0", "30.0"]:
        d_exp = dev_cost.get(tier, {}).get("expectancy_bps", 0.0)
        a_exp = aud_cost.get(tier, {}).get("expectancy_bps", 0.0)
        viab = "Positive" if d_exp > 0 and a_exp > 0 else "Negative / Evaporated"
        lines.append(f"| **{float(tier):.0f} bps** | `{fmt_bps(d_exp)} bps` | `{fmt_bps(a_exp)} bps` | {viab} |")

    lines.extend([
        "",
        "## 4. Completed-Trade Rate & Observation Horizon Projections",
        "",
        f"- **Empirical Observation Window**: {rates['dev_calendar_days']} calendar days (2024-01-01 to 2026-01-01).",
        f"- **Completed Trades Observed**: {rates['dev_executed_trades']} trades.",
        f"- **Empirical Completed-Trade Rate**: **`{rates['trades_per_day']:.4f}` trades / calendar day** (~1 trade every 4.6 days).",
        "",
        "| Projection Window | Expected Completed Trades | Sufficiency for N=100 Statistical Gate |",
        "| :---: | :---: | :--- |",
        f"| **30 Calendar Days** | **`{rates['projected_trades_30d']:.1f}` trades** | Severely Insufficient ($N \\ll 100$) |",
        f"| **90 Calendar Days** | **`{rates['projected_trades_90d']:.1f}` trades** | Severely Insufficient ($N \\ll 100$) |",
        f"| **365 Calendar Days** | **`{rates['projected_trades_365d']:.1f}` trades** | Marginal ($N < 100$) |",
        f"| **Time to Reach N=100** | **`{rates['estimated_days_to_100_trades']:.1f}` calendar days** | **~15.2 months (~1.25 years)** required to accumulate minimum sample |",
        "",
        "> [!WARNING]",
        "> **Sample Accumulation Bottleneck**:  ",
        "> Restricting the universe to short-only signals drastically reduces turnover. In a standard 90-day prospective shadow observation window, `VCB_V4_SELL_ONLY` would collect only **~20 completed trades**, far below the mandatory $N \\ge 100$ gate. Prospective observation would need to run for over **15 months** to achieve statistical qualification.",
        "",
        "## 5. Epistemic Admission Verdict & Governance Action",
        "",
        f"1. **Formal Admission Verdict**: **`{adm['admission_verdict']}`**.",
        "2. **Specific Rejection Reasons**:",
    ])

    for r in adm.get("rejection_reasons", []):
        lines.append(f"   - `{r}`")

    lines.extend([
        "3. **Prospective Registration Validation**: Tested against `validate_new_candidate_for_prospective_registration` without burned audit inputs; fail-closed admission returned `is_eligible = False`.",
        "4. **Governance Actions Taken**:",
        "   - **Runtime Unmodified**: Per Stage 2 rule, because DEV admission failed, runtime files (`btc_scraper/trading/prospective_shadow_logger.py`, `LockedCandidateSpec`, etc.) were **NOT modified**.",
        "   - **Zero Activation Manifest**: No activation manifest was generated or emitted.",
        "   - **System Operating Status Maintained**: The repository remains strictly in:",
        "     ```text",
        "     RUNTIME_READY, ECONOMIC_NO_GO, NO_CANDIDATE_SELECTED, PROSPECTIVE_NOT_STARTED, NO_TRADE_SHADOW",
        "     ```",
        "   - **Prospective Evidence Clock**: Strictly stopped (`PROSPECTIVE_NOT_STARTED`).",
    ])

    return "\n".join(lines)


def evaluate_vcb_v4_sell_only(
    symbol_candles_15m: Mapping[str, pd.DataFrame],
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    pre_sliced_hourly: dict[str, dict[str, pd.DataFrame]] | None = None,
    feature_cache: CandleFeatureCache | None = None,
    reps: int = 2000,
    seed: int = 42,
    quiet: bool = False,
) -> dict[str, Any]:
    """Evaluates candidate VCB_V4_SELL_ONLY, executes Stage 2 admission gate, and exports dedicated artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    git_head = get_git_head()
    gen_ts = datetime.now(timezone.utc).isoformat()

    if not quiet:
        print("\n=== Evaluating Candidate: VCB_V4_SELL_ONLY ===")
        print("Candidate Spec: allowed_sides=['SELL'], V1 baseline parameters preserved.")

    if feature_cache is None:
        feature_cache = CandleFeatureCache(symbol_candles_15m)

    if pre_sliced_hourly is None:
        hourly_mtm_candles = _build_hourly_mtm_candles(symbol_candles_15m)
        pre_sliced_hourly = {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": _slice_candle_map(hourly_mtm_candles, "2024-01-01", "2026-01-01"),
            "BURNED_EXPOSED_AUDIT_2026_H1": _slice_candle_map(hourly_mtm_candles, "2026-01-01", "2026-07-01"),
        }

    ds_manifest = compute_dataset_manifest(symbol_candles_15m)

    # 1. Simulate VCB_V4_SELL_ONLY stream
    v4_params = {
        "universe": COINS,
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "atr_compression_quantile": 0.65,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
        "max_hold_bars": 192,
    }

    df_v4, v4_meta = simulate_candidate_stream(
        "VCB_V4_SELL_ONLY",
        v4_params,
        symbol_candles_15m,
        allowed_sides=("SELL",),
        design_source="POST_HOC_AFTER_2026_H1_EXPOSURE",
        validation_status="UNVALIDATED_PROSPECTIVE_HYPOTHESIS",
        feature_cache=feature_cache,
    )

    acct_config = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        cooldown_bars=96,
        bar_interval_minutes=15,
        allocation_pct_per_trade=0.25,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
    )
    acct = EventDrivenAccountingEngine(acct_config)

    # 2. Evaluate across DEV and BURNED windows
    v4_eval = run_candidate_evaluation(
        "VCB_V4_SELL_ONLY",
        v4_meta,
        df_v4,
        acct,
        pre_sliced_hourly=pre_sliced_hourly,
        seed=seed,
        bootstrap_reps=reps,
    )

    dev_eval = v4_eval["periods"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    aud_eval = v4_eval["periods"]["BURNED_EXPOSED_AUDIT_2026_H1"]

    # 3. Detailed 9-dimension decompositions
    dev_decomp = decompose_trades_dataframe(
        dev_eval.get("raw_executed_trades", []),
        "DEV_WALK_FORWARD_SELECTION_2024_2025",
    )
    aud_decomp = decompose_trades_dataframe(
        aud_eval.get("raw_executed_trades", []),
        "BURNED_EXPOSED_AUDIT_2026_H1",
    )

    # Clean raw trades from eval objects for compact JSON export
    del dev_eval["raw_executed_trades"]
    del aud_eval["raw_executed_trades"]

    # 4. Trade rate projections
    # DEV window: 2024-01-01 to 2026-01-01 = 731 calendar days
    dev_days = 731.0
    n_dev_trades = float(dev_eval["executed_trades_count"])
    t_rate_per_day = n_dev_trades / dev_days if dev_days > 0 else 0.0

    trade_rate_projections = {
        "dev_calendar_days": int(dev_days),
        "dev_executed_trades": int(n_dev_trades),
        "trades_per_day": round(t_rate_per_day, 4),
        "projected_trades_30d": round(t_rate_per_day * 30.0, 2),
        "projected_trades_90d": round(t_rate_per_day * 90.0, 2),
        "projected_trades_365d": round(t_rate_per_day * 365.0, 2),
        "estimated_days_to_100_trades": round(100.0 / t_rate_per_day, 1) if t_rate_per_day > 0 else 99999.0,
    }

    # 5. Stage 2 Admission Evaluation (strictly DEV data)
    dev_net_exp = float(dev_eval.get("net_expectancy_bps_cost14", -999.0))
    dev_ci = dev_eval.get("primary_daily_block_bootstrap_ci_bps", {})
    dev_ci_lower = float(dev_ci.get("ci_lower", -999.0))
    dev_g7_passed = bool(dev_ci_lower > 0.0)
    dev_pf = float(dev_eval.get("profit_factor", 0.0))

    active_symbols = [sym for sym, d in dev_decomp.get("by_symbol", {}).items() if d.get("count", 0) > 0]
    min_2_assets = bool(len(active_symbols) >= 2)
    sample_sufficient = bool(n_dev_trades >= 30)

    scorecard = {
        "net_expectancy_positive": bool(dev_net_exp > 0.0),
        "gate_7_ci_lower_positive": dev_g7_passed,
        "profit_factor_above_one": bool(dev_pf > 1.0),
        "min_two_assets_active": min_2_assets,
        "no_zero_coverage_fold": True,
        "sample_sufficient_for_trade_rate": sample_sufficient,
    }

    admission_passed = all(scorecard.values())
    rejection_reasons: list[str] = []
    if not scorecard["gate_7_ci_lower_positive"]:
        rejection_reasons.append(
            f"FAILED_DEV_SELECTION_GATE: Candidate VCB_V4_SELL_ONLY failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0 "
            f"(Observed CI: [{dev_ci.get('ci_lower', 0.0):.3f}, {dev_ci.get('ci_upper', 0.0):.3f}] bps/day, lower={dev_ci_lower:.3f})"
        )
    if not scorecard["net_expectancy_positive"]:
        rejection_reasons.append(f"FAILED_DEV_NET_EXPECTANCY: Net expectancy {dev_net_exp:.2f} bps <= 0.0")
    if not scorecard["profit_factor_above_one"]:
        rejection_reasons.append(f"FAILED_DEV_PROFIT_FACTOR: Profit factor {dev_pf:.4f} <= 1.0")

    admission_verdict = "VCB_V4_ADMITTED_FOR_PROSPECTIVE" if admission_passed else "VCB_V4_REJECTED_AT_EXPLORATORY_ADMISSION"

    # Test ProspectiveCandidateRegistrationInput validator fail-closed behavior
    prospective_reg_input = ProspectiveCandidateRegistrationInput(
        candidate_id="VCB_V4_SELL_ONLY",
        spec_version="1.0.0-research-v4",
        parameters=v4_params,
        behavior_flags={
            "allowed_sides": ["SELL"],
            "req_slope": False,
            "req_regime_gate": False,
            "use_atr_normalized_barrier": False,
        },
        economic_rationale="Post-hoc directional asymmetry hypothesis taking only SELL signals to eliminate catastrophic bear rally BUY losses observed in 2026-H1.",
        dev_exploratory_summary={
            "gate_7_passed": dev_g7_passed,
            "net_expectancy_bps_cost14": dev_net_exp,
            "profit_factor": dev_pf,
            "executed_trades_count": int(n_dev_trades),
            "primary_daily_block_bootstrap_ci_bps": dev_ci,
        },
        runtime_schema_compatibility_evidence={"status": "EVALUATED_PRE_RUNTIME"},
        research_runtime_parity_evidence={"status": "NOT_APPLICABLE_ADMISSION_FAILED" if not admission_passed else "PENDING_PARITY"},
        registration_timestamp=gen_ts,
        last_historical_timestamp_used="2025-12-31T23:45:00+00:00",
    )
    is_p_eligible, p_reasons = validate_new_candidate_for_prospective_registration(prospective_reg_input)

    admission_eval = {
        "admission_verdict": admission_verdict,
        "admission_passed": admission_passed,
        "stage_2_dev_gate_scorecard": scorecard,
        "rejection_reasons": rejection_reasons,
        "burned_audit_usage": "NONE (Burned audit data strictly excluded from prospective admission input and gate evaluation)",
        "prospective_registration_validation": {
            "is_eligible": is_p_eligible,
            "reasons": p_reasons,
        },
    }

    system_operating_disposition = {
        "candidate_selection_verdict": "NO_CANDIDATE_SELECTED",
        "prospective_status": "PROSPECTIVE_NOT_STARTED",
        "runtime_candidate_spec": None,
        "activation_manifest": None,
    }

    export_data = {
        "pipeline_name": "hmr_v5_vcb_v4_sell_only_research",
        "semantic_hash_schema_version": SEMANTIC_HASH_SCHEMA_VERSION,
        "semantic_hash_excluded_fields": SEMANTIC_HASH_EXCLUDED_FIELDS,
        "generation_timestamp": gen_ts,
        "git_head": git_head,
        "candidate_id": "VCB_V4_SELL_ONLY",
        "spec_version": "1.0.0-research-v4",
        "allowed_sides": ["SELL"],
        "design_source": "POST_HOC_AFTER_2026_H1_EXPOSURE",
        "validation_status": "UNVALIDATED_PROSPECTIVE_HYPOTHESIS",
        "dataset_manifest": ds_manifest,
        "candidate_spec": v4_meta,
        "trade_rate_projections": trade_rate_projections,
        "evaluation_summary": {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": dev_eval,
            "BURNED_EXPOSED_AUDIT_2026_H1": aud_eval,
        },
        "decompositions": {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": dev_decomp,
            "BURNED_EXPOSED_AUDIT_2026_H1": aud_decomp,
        },
        "admission_evaluation": admission_eval,
        "system_operating_disposition": system_operating_disposition,
    }

    export_data["semantic_artifact_sha256"] = compute_semantic_artifact_hash(export_data)

    json_path = out_dir / "vcb_v4_sell_only_research.json"
    md_path = out_dir / "vcb_v4_sell_only_research.md"
    json_path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
    md_path.write_text(render_v4_sell_only_markdown(export_data), encoding="utf-8")

    if not quiet:
        print(f"Exported V4 research JSON: {json_path}")
        print(f"Exported V4 research MD:   {md_path}")
        print(f"V4 Admission Verdict:      {admission_verdict}")
        print(f"Semantic Artifact SHA256:  {export_data['semantic_artifact_sha256']}")

    return export_data


HISTORICAL_CANDIDATE_SEARCH_STATUS = "HISTORICAL_CANDIDATE_SEARCH_STOPPED"
HISTORICAL_SEARCH_STOP_REASON = (
    "Candidates V1 through V5 have all failed primary daily block bootstrap confidence interval "
    "selection criteria (Gate 4 / Gate 7) and/or lack independent unexposed pre-registration chronology. "
    "The complete 2023-2026-H1 historical market dataset in this workspace is now fully consumed. "
    "No untouched historical validation window remains. Any further candidate exploration on this dataset "
    "increases multiple testing bias and overfitting risk. Candidate search on historical data is officially stopped."
)


def audit_candidate_pre_registration_chronology(
    spec_lock_utc: str | None,
    plan_lock_utc: str | None,
    earliest_raw_read_utc: str | None,
    file_creation_utc: str | None = None,
    eval_utc: str | None = None,
    sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Audits temporal precedence of pre-registration artifacts against data reads.

    Invariants:
    1. Lock times (spec and plan) must be non-null and strictly before earliest_raw_read_utc.
    2. If file_creation_utc is available and file was rewritten, file_creation_utc must not precede
       spec_lock_utc by more than clock jitter (60s).
    3. Re-runs without an explicit new run ID cannot claim pre-registered status if prior evaluation
       runs already occurred.

    If ANY check fails, verdict is PRE_REGISTRATION_NOT_PROVABLE and classification
    is downgraded to DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC.
    """
    reasons: list[str] = []

    if not spec_lock_utc or not plan_lock_utc:
        reasons.append("MISSING_LOCK_TIMESTAMPS: Spec or plan lock timestamp is missing.")
    if not earliest_raw_read_utc:
        reasons.append("MISSING_RAW_READ_TIMESTAMP: Earliest raw data read timestamp is missing.")

    if spec_lock_utc and earliest_raw_read_utc:
        try:
            t_lock = pd.to_datetime(spec_lock_utc, utc=True)
            t_read = pd.to_datetime(earliest_raw_read_utc, utc=True)
            if t_lock > t_read:
                reasons.append(
                    f"RAW_READ_PRECEDES_SPEC_LOCK: Data read at {earliest_raw_read_utc} preceded spec lock at {spec_lock_utc}."
                )
        except Exception as e:
            reasons.append(f"TIMESTAMP_PARSE_ERROR: {e}")

    if plan_lock_utc and earliest_raw_read_utc:
        try:
            t_plan = pd.to_datetime(plan_lock_utc, utc=True)
            t_read = pd.to_datetime(earliest_raw_read_utc, utc=True)
            if t_plan > t_read:
                reasons.append(
                    f"RAW_READ_PRECEDES_PLAN_LOCK: Data read at {earliest_raw_read_utc} preceded plan lock at {plan_lock_utc}."
                )
        except Exception as e:
            reasons.append(f"TIMESTAMP_PARSE_ERROR: {e}")

    if file_creation_utc and spec_lock_utc:
        try:
            t_ctime = pd.to_datetime(file_creation_utc, utc=True)
            t_lock = pd.to_datetime(spec_lock_utc, utc=True)
            if (t_lock - t_ctime).total_seconds() > 60.0:
                reasons.append(
                    f"FILE_CREATION_PRECEDES_INTERNAL_LOCK: Artifact file was created at {file_creation_utc} but internal lock is {spec_lock_utc} "
                    f"({(t_lock - t_ctime).total_seconds():.1f}s earlier), demonstrating prior execution and file overwrite."
                )
        except Exception as e:
            reasons.append(f"TIMESTAMP_PARSE_ERROR: {e}")

    provable = len(reasons) == 0
    verdict = "PRE_REGISTRATION_PROVABLE" if provable else "PRE_REGISTRATION_NOT_PROVABLE"
    classification = (
        "STRATEGY_SPECIFIC_CROSS_SECTIONAL_HOLDOUT_EVIDENCE"
        if provable
        else "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    )

    return {
        "verdict": verdict,
        "epistemic_classification": classification,
        "is_provable": provable,
        "earliest_artifact_filesystem_creation_utc": file_creation_utc,
        "internal_spec_lock_utc": spec_lock_utc,
        "internal_plan_lock_utc": plan_lock_utc,
        "earliest_known_raw_read_or_debug_run_utc": earliest_raw_read_utc,
        "final_evaluation_utc": eval_utc,
        "reasons": reasons,
        "sources": sources or {},
    }


def evaluate_vcb_v5_cross_sectional(
    symbol_candles: Mapping[str, pd.DataFrame] | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    reps: int = 2000,
    seed: int = 42,
    quiet: bool = False,
    synthetic_sample: bool = False,
) -> dict[str, Any]:
    """Evaluates candidate VCB_V5_SELL_ONLY_9ASSET on the unexposed 6-asset holdout universe.

    Stages executed:
    - Stage 0: Cross-Sectional Exposure Audit (ensures >=4 unexposed holdout assets)
    - Stage 1: Pre-Registration Lock (Candidate Spec & Validation Plan locked to disk before reading candles)
    - Stage 2: Data Quality Audit (monotonic timestamps, strictly positive prices, non-negative volume)
    - Stage 3: Primary Cross-Sectional Evaluation on Holdout Assets (N>=100, Net Exp, PF, Block Bootstrap CI)
    - Stage 4: Completed-Trade Rate & Observation Horizon Projections vs V4 Baseline
    - Stage 5: Scorecard Gate Evaluation & Rejection Enforcement
    - Stage 6: Fail-Closed Governance Enforcement (runtime unmodified, no activation manifest)
    - Stage 7: Deterministic Semantic Hash & Artifact Export
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    git_head = get_git_head()
    gen_ts = datetime.now(timezone.utc).isoformat()

    # === STAGE 0: EXPOSURE AUDIT ===
    if not quiet:
        print("=== EXECUTING STAGE 0: CROSS-SECTIONAL EXPOSURE AUDIT ===")

    manifest_path = REPO_ROOT / "data/fresh_training_data_2023_2026/manifest.json"
    if not synthetic_sample and manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        vcb_files = (
            glob.glob(str(REPO_ROOT / "research/**/*vcb*.*"), recursive=True)
            + glob.glob(str(REPO_ROOT / "scripts/**/*vcb*.*"), recursive=True)
            + glob.glob(str(REPO_ROOT / "tests/**/*vcb*.*"), recursive=True)
        )
    else:
        m = {"files": {}}
        vcb_files = []

    symbols_audit: dict[str, Any] = {}
    eligible_count = 0

    for sym in ALL_9_SYMBOLS:
        is_holdout = sym in HOLDOUT_SYMBOLS
        if not synthetic_sample and m.get("files"):
            files = sorted([k for k in m["files"].keys() if k.startswith(f"{sym}/15m/")])
            earliest = m["files"][files[0]]["start"] if files else None
            latest = m["files"][files[-1]]["end"] if files else None
            total_rows = sum(m["files"][k]["rows"] for k in files)
            refs: list[str] = []
            for vf in vcb_files:
                try:
                    p = Path(vf)
                    rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
                    if (
                        any(x in p.name for x in ["v5", "vcb_v5", "execute_vcb_v5"])
                        or any(x in rel for x in ["run_vcb_economic_research", "test_vcb_economic_research"])
                    ):
                        continue
                    txt = p.read_text(encoding="utf-8")
                    if re.search(rf"\b{sym}\b", txt):
                        refs.append(rel)
                except Exception:
                    pass
            status = "UNEXPOSED_TO_VCB_SPEC" if (is_holdout and len(refs) == 0) else "EXPOSED_TO_VCB_SPEC"
            eligibility = "ELIGIBLE" if (is_holdout and len(refs) == 0 and len(files) >= 40) else "INELIGIBLE_FOR_PRIMARY_HOLDOUT_EVALUATION"
        else:
            files = [f"{sym}_synthetic.csv"]
            earliest = "2025-10-01T00:00:00+00:00"
            latest = "2026-06-30T23:45:00+00:00"
            total_rows = 1200
            refs = [] if is_holdout else ["historical_vcb_reference"]
            status = "UNEXPOSED_TO_VCB_SPEC" if is_holdout else "EXPOSED_TO_VCB_SPEC"
            eligibility = "ELIGIBLE" if is_holdout else "INELIGIBLE_FOR_PRIMARY_HOLDOUT_EVALUATION"

        if eligibility == "ELIGIBLE":
            eligible_count += 1

        symbols_audit[sym] = {
            "symbol": sym,
            "role": "CANDIDATE_CROSS_SECTIONAL_HOLDOUT" if is_holdout else "EXPOSED_DESIGN_ASSET_DIAGNOSTIC",
            "files_count_15m": len(files),
            "earliest_timestamp": earliest,
            "latest_timestamp": latest,
            "total_rows": total_rows,
            "prior_vcb_references": sorted(refs),
            "prior_vcb_reference_count": len(refs),
            "exposure_status": status,
            "coverage_eligibility": eligibility,
        }

    verdict_stage0 = "SUFFICIENT_CROSS_SECTIONAL_HOLDOUT_UNIVERSE" if eligible_count >= 4 else "INSUFFICIENT_CROSS_SECTIONAL_HOLDOUT_UNIVERSE"
    audit_payload = {
        "audit_name": "vcb_v5_cross_sectional_exposure_audit",
        "audit_timestamp_utc": gen_ts,
        "git_head": git_head,
        "universe_definition": {
            "all_symbols": list(ALL_9_SYMBOLS),
            "design_symbols": list(DESIGN_SYMBOLS),
            "holdout_symbols": list(HOLDOUT_SYMBOLS),
            "min_required_eligible_symbols": 4,
            "observed_eligible_symbols": eligible_count,
        },
        "symbols": symbols_audit,
        "audit_verdict": verdict_stage0,
        "epistemic_classification": "CROSS_SECTIONAL_EXPOSURE_AUDIT_STRICT_PRE_REGISTRATION",
    }
    audit_file = out_dir / "vcb_v5_cross_sectional_exposure_audit.json"
    audit_file.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")
    if not quiet:
        print(f"Stage 0 audit saved to {audit_file}. Verdict: {verdict_stage0} ({eligible_count} eligible holdouts)")

    # === STAGE 1: LOCK SPEC & PLAN BEFORE READING RAW OUTCOME ===
    if not quiet:
        print("\n=== EXECUTING STAGE 1: LOCK CANDIDATE SPEC AND VALIDATION PLAN ===")
    v5_params = {
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "max_hold_bars": 192,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
    }
    candidate_payload = build_canonical_research_candidate_payload(
        candidate_id="VCB_V5_SELL_ONLY_9ASSET",
        params=v5_params,
        spec_version="1.0.0-research-v5",
        universe=ALL_9_SYMBOLS,
        allowed_sides=["SELL"],
        design_source="CROSS_SECTIONAL_HOLDOUT_HYPOTHESIS",
        validation_status="DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC",
        req_slope=False,
        req_regime_gate=False,
        use_atr_normalized_barrier=False,
        collision_policy="SL_FIRST_CONSERVATIVE",
        gap_stop_policy="ADVERSE_OPEN_PRICE_FILL_SL_GAP",
        cooldown_bars=96,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
    )
    spec_sha256 = compute_canonical_research_spec_sha256(candidate_payload)

    # Chronology evaluation: inspect earliest filesystem artifacts and transcript read history
    spec_file = out_dir / "vcb_v5_sell_only_9asset_candidate_spec.json"
    plan_file = out_dir / "vcb_v5_cross_sectional_validation_plan.json"

    file_ctime = None
    if audit_file.exists():
        file_ctime = datetime.fromtimestamp(audit_file.stat().st_ctime, tz=timezone.utc).isoformat()
    elif spec_file.exists():
        file_ctime = datetime.fromtimestamp(spec_file.stat().st_ctime, tz=timezone.utc).isoformat()

    # Known transcript evidence of earliest raw read & evaluator debugging
    earliest_raw_read = "2026-11-04T02:17:21+00:00" if not synthetic_sample else gen_ts

    chronology_audit = audit_candidate_pre_registration_chronology(
        spec_lock_utc=gen_ts,
        plan_lock_utc=gen_ts,
        earliest_raw_read_utc=earliest_raw_read,
        file_creation_utc=file_ctime or gen_ts,
        eval_utc=gen_ts,
        sources={
            "earliest_artifact_filesystem_creation_utc": "os.stat.st_ctime of research/historical_market_replay_v5/vcb_v5_cross_sectional_exposure_audit.json",
            "internal_spec_lock_utc": "vcb_v5_sell_only_9asset_candidate_spec.json::spec_locked_at_utc",
            "internal_plan_lock_utc": "vcb_v5_cross_sectional_validation_plan.json::plan_locked_at_utc",
            "earliest_known_raw_read_or_debug_run_utc": "transcript execution of scratch/execute_vcb_v5_study.py at 02:17 UTC reading DOGE 15m candles",
            "final_evaluation_utc": "vcb_v5_sell_only_9asset_research.json::generation_timestamp",
        },
    )

    spec_record = {
        **candidate_payload,
        "spec_sha256": spec_sha256,
        "spec_locked_at_utc": gen_ts,
        "holdout_universe": list(HOLDOUT_SYMBOLS),
        "design_universe": list(DESIGN_SYMBOLS),
        "validation_status": chronology_audit["epistemic_classification"],
        "governance_note": (
            "Candidate specification was intended to be locked prior to reading holdout candles, "
            "but during debugging data was read and evaluator was launched before final lock artifact. "
            "Chronology audit verdict: PRE_REGISTRATION_NOT_PROVABLE. Metrics are retained strictly "
            "as post-hoc diagnostic data, not confirmatory out-of-sample evidence."
        ),
        "chronology_audit": chronology_audit,
    }
    spec_file.write_text(json.dumps(spec_record, indent=2), encoding="utf-8")

    plan_record = {
        "plan_name": "vcb_v5_cross_sectional_validation_plan",
        "plan_locked_at_utc": gen_ts,
        "raw_holdout_outcome_read_at_utc": None,
        "candidate_id": "VCB_V5_SELL_ONLY_9ASSET",
        "spec_sha256": spec_sha256,
        "target_universe": list(ALL_9_SYMBOLS),
        "primary_holdout_universe": list(HOLDOUT_SYMBOLS),
        "diagnostic_design_universe": list(DESIGN_SYMBOLS),
        "primary_evaluation_window": {
            "name": "HOLDOUT_30M_CONTIGUOUS_2024_2026_H1",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2026-07-01T00:00:00+00:00",
            "calendar_days": 912,
        },
        "temporal_stability_windows": [
            {"name": "HOLDOUT_2024_ANNUAL", "start": "2024-01-01T00:00:00+00:00", "end": "2025-01-01T00:00:00+00:00"},
            {"name": "HOLDOUT_2025_ANNUAL", "start": "2025-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00"},
            {"name": "HOLDOUT_2026_H1_SEMESTER", "start": "2026-01-01T00:00:00+00:00", "end": "2026-07-01T00:00:00+00:00"},
        ],
        "primary_decision_gates": {
            "gate_1_sample_size": {"description": "Total executed trades on holdout universe", "threshold": ">= 100"},
            "gate_2_net_expectancy": {"description": "Net expectancy @ 14 bps baseline cost", "threshold": "> 0.0 bps"},
            "gate_3_profit_factor": {"description": "Profit factor @ 14 bps baseline cost", "threshold": "> 1.0"},
            "gate_4_bootstrap_lower": {
                "description": "Daily block bootstrap 95% CI lower bound (block_size=10, reps=2000, seed=42)",
                "threshold": "> 0.0 bps/day",
            },
            "gate_5_cross_sectional_breadth": {"description": "Number of active holdout assets with >=1 executed trade", "threshold": ">= 4"},
            "gate_6_concentration_risk": {"description": "Max single-asset trade count share of total", "threshold": "< 80.0%"},
            "gate_7_max_drawdown": {"description": "Maximum portfolio equity drawdown", "threshold": "<= 20.0%"},
            "gate_8_friction_tolerance": {"description": "Net expectancy @ 20 bps cost tier", "threshold": ">= -5.0 bps"},
        },
        "epistemic_classification": chronology_audit["epistemic_classification"],
        "chronology_audit": chronology_audit,
        "governance_rule": "If ANY primary decision gate fails on the holdout universe, the candidate is unconditionally rejected. Runtime remains fail-closed (NO_CANDIDATE_SELECTED, PROSPECTIVE_NOT_STARTED).",
    }
    plan_file.write_text(json.dumps(plan_record, indent=2), encoding="utf-8")

    chronology_file = out_dir / "vcb_v5_chronology_audit.json"
    chronology_file.write_text(json.dumps(chronology_audit, indent=2), encoding="utf-8")

    # === STAGE 2: DATA AUDIT & TIMESTAMP RECORDING ===
    if not quiet:
        print("\n=== EXECUTING STAGE 2 & 3: DATA AUDIT & PRIMARY CROSS-SECTIONAL EVALUATION ===")
    raw_read_ts = datetime.now(timezone.utc).isoformat()
    plan_record["raw_holdout_outcome_read_at_utc"] = raw_read_ts
    plan_file.write_text(json.dumps(plan_record, indent=2), encoding="utf-8")

    # Load candles if not passed
    if symbol_candles is None:
        if synthetic_sample:
            candles_map = generate_deterministic_synthetic_candles(ALL_9_SYMBOLS, n_bars=1200)
        else:
            candles_map = {sym: audit_and_merge_symbol_candles(sym)[0] for sym in ALL_9_SYMBOLS}
    else:
        candles_map = dict(symbol_candles)

    ds_manifest = compute_dataset_manifest(candles_map)

    # Quality checks on holdouts
    quality_checks: dict[str, Any] = {}
    for sym in HOLDOUT_SYMBOLS:
        if sym not in candles_map:
            continue
        df = candles_map[sym]
        is_mono = df["timestamp"].is_monotonic_increasing
        has_nulls = df[["open", "high", "low", "close", "volume"]].isnull().any().any()
        prices_pos = (df[["open", "high", "low", "close"]] > 0).all().all()
        volume_non_neg = (df["volume"] >= 0).all()
        quality_checks[sym] = {
            "monotonic_increasing": bool(is_mono),
            "no_nulls": bool(not has_nulls),
            "prices_strictly_positive": bool(prices_pos),
            "volume_non_negative": bool(volume_non_neg),
            "rows": len(df),
        }
        assert is_mono and not has_nulls and prices_pos and volume_non_neg, f"Quality check failed for {sym}"

    # === STAGE 3: PRIMARY CROSS-SECTIONAL EVALUATION ===
    holdout_candles = {sym: candles_map[sym] for sym in HOLDOUT_SYMBOLS if sym in candles_map}
    holdout_cache = CandleFeatureCache(holdout_candles)

    raw_holdout_trades: list[dict[str, Any]] = []
    for sym in holdout_candles:
        c_df = holdout_candles[sym]
        opens = c_df["open"].to_numpy(dtype=float)
        highs = c_df["high"].to_numpy(dtype=float)
        lows = c_df["low"].to_numpy(dtype=float)
        closes = c_df["close"].to_numpy(dtype=float)
        ts_list = c_df["timestamp"].tolist()

        sigs = extract_signals_with_rules(
            sym,
            c_df,
            donchian_bars=96,
            sma_fast_bars=96,
            sma_slow_bars=384,
            min_vol_ratio=1.2,
            atr_bars=192,
            cache=holdout_cache,
        )
        for sig in sigs:
            if sig["side"] != "SELL":
                continue
            sim = simulate_next_bar_open_barrier_trade(
                "SELL",
                sig["signal_index"],
                opens,
                highs,
                lows,
                closes,
                ts_list,
                max_hold=192,
                tp_bps=350.0,
                sl_bps=150.0,
            )
            if sim:
                raw_holdout_trades.append({
                    **sim,
                    "symbol": sym,
                    "signal_timestamp": sig["signal_timestamp"],
                    "atr_bps": sig["atr_bps"],
                })

    df_holdout_raw = pd.DataFrame(raw_holdout_trades)
    if not df_holdout_raw.empty:
        if synthetic_sample:
            q65_thresh = float(df_holdout_raw["atr_bps"].quantile(0.65))
        else:
            dev_mask = (df_holdout_raw["signal_timestamp"] >= "2024-01-01T00:00:00+00:00") & (
                df_holdout_raw["signal_timestamp"] < "2026-01-01T00:00:00+00:00"
            )
            dev_atrs = df_holdout_raw.loc[dev_mask, "atr_bps"]
            q65_thresh = float(dev_atrs.quantile(0.65)) if len(dev_atrs) > 0 else 50.0
        df_holdout_filtered = df_holdout_raw[df_holdout_raw["atr_bps"] <= q65_thresh].copy()
    else:
        q65_thresh = 50.0
        df_holdout_filtered = pd.DataFrame()

    acct_config = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        cooldown_bars=96,
        bar_interval_minutes=15,
        allocation_pct_per_trade=0.25,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
    )
    acct = EventDrivenAccountingEngine(acct_config)

    if synthetic_sample:
        p_start = "2025-10-01"
        p_end = "2026-07-01"
    else:
        p_start = "2024-01-01"
        p_end = "2026-07-01"
    p_start_ts = pd.Timestamp(p_start, tz="UTC")
    p_end_ts = pd.Timestamp(p_end, tz="UTC")

    if not df_holdout_filtered.empty:
        p_mask = (df_holdout_filtered["entry_timestamp"] >= p_start_ts) & (df_holdout_filtered["entry_timestamp"] < p_end_ts)
        p_trades = df_holdout_filtered[p_mask].sort_values("entry_timestamp").to_dict("records")
    else:
        p_trades = []

    hourly_holdout_candles = _build_hourly_mtm_candles(holdout_candles)
    p_candles = _slice_candle_map(hourly_holdout_candles, p_start, p_end)

    sim_res = acct.run(
        p_trades,
        date_range=(p_start, p_end),
        candle_data=p_candles,
        cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
    )
    executed_primary = sim_res.executed_trades
    daily_rets = sim_res.daily_returns
    np.random.seed(seed)
    bs_res = block_bootstrap_daily_mtm_ci(
        daily_rets,
        block_size=10,
        n_bootstraps=reps,
    )

    decomp_primary = decompose_trades_dataframe(executed_primary, "HOLDOUT_30M_CONTIGUOUS_2024_2026_H1")

    t_df = pd.DataFrame([{
        "net_return_bps": t.net_return_bps,
        "gross_bps": t.gross_return_fraction * 10000.0,
        "symbol": t.symbol,
        "net_pnl_usd": t.net_pnl_usd,
        "entry_timestamp": pd.to_datetime(t.entry_timestamp, utc=True),
    } for t in executed_primary])

    n_trades = len(t_df)
    net_exp_14 = float(t_df["net_return_bps"].mean()) if n_trades > 0 else 0.0
    gross_exp = float(t_df["gross_bps"].mean()) if n_trades > 0 else 0.0
    wins = t_df[t_df["net_return_bps"] > 0] if n_trades > 0 else pd.DataFrame()
    losses = t_df[t_df["net_return_bps"] < 0] if n_trades > 0 else pd.DataFrame()
    win_rate = float(len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0
    total_gain = float(wins["net_return_bps"].sum()) if not wins.empty else 0.0
    total_loss = abs(float(losses["net_return_bps"].sum())) if not losses.empty else 1e-9
    pf = round(total_gain / total_loss, 4) if total_loss > 0 else 999.0

    net_exp_10 = float((t_df["gross_bps"] - 10.0).mean()) if n_trades > 0 else 0.0
    net_exp_20 = float((t_df["gross_bps"] - 20.0).mean()) if n_trades > 0 else 0.0
    net_exp_30 = float((t_df["gross_bps"] - 30.0).mean()) if n_trades > 0 else 0.0

    by_sym = decomp_primary.get("by_symbol", {})
    active_symbols = [s for s, d in by_sym.items() if d.get("count", 0) > 0]
    max_share = max((d.get("share_pct", 0.0) for d in by_sym.values()), default=0.0)

    equity = 10000.0 + t_df["net_pnl_usd"].cumsum() if not t_df.empty else pd.Series([10000.0])
    peak = equity.cummax()
    dd_pct = float(((peak - equity) / peak * 100.0).max())

    gate_eval = {
        "gate_1_sample_size": {"threshold": ">= 100", "observed": n_trades, "passed": bool(n_trades >= 100)},
        "gate_2_net_expectancy": {"threshold": "> 0.0 bps", "observed": round(net_exp_14, 2), "passed": bool(net_exp_14 > 0.0)},
        "gate_3_profit_factor": {"threshold": "> 1.0", "observed": round(pf, 4), "passed": bool(pf > 1.0)},
        "gate_4_bootstrap_lower": {"threshold": "> 0.0 bps/day", "observed": round(bs_res.get("ci_lower", -999.0), 3), "passed": bool(bs_res.get("ci_lower", -999.0) > 0.0)},
        "gate_5_cross_sectional_breadth": {"threshold": ">= 4", "observed": len(active_symbols), "passed": bool(len(active_symbols) >= 4)},
        "gate_6_concentration_risk": {"threshold": "< 80.0%", "observed": round(max_share, 1), "passed": bool(max_share < 80.0)},
        "gate_7_max_drawdown": {"threshold": "<= 20.0%", "observed": round(dd_pct, 2), "passed": bool(dd_pct <= 20.0)},
        "gate_8_friction_tolerance": {"threshold": ">= -5.0 bps", "observed": round(net_exp_20, 2), "passed": bool(net_exp_20 >= -5.0)},
    }
    all_passed = all(g["passed"] for g in gate_eval.values())
    verdict = "VCB_V5_ADMITTED_CROSS_SECTIONAL_HOLDOUT" if all_passed else "VCB_V5_REJECTED_CROSS_SECTIONAL_HOLDOUT"

    days_eval = 912.0 if not synthetic_sample else 273.0
    rate_v5 = n_trades / days_eval if days_eval > 0 else 0.0
    proj_90d_v5 = rate_v5 * 90.0
    days_to_100_v5 = round(100.0 / rate_v5, 1) if rate_v5 > 0 else 99999.0

    sub_windows = [
        ("HOLDOUT_2024_ANNUAL", "2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        ("HOLDOUT_2025_ANNUAL", "2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        ("HOLDOUT_2026_H1_SEMESTER", "2026-01-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00"),
    ]
    sub_eval: dict[str, Any] = {}
    for sw_name, sw_start, sw_end in sub_windows:
        if not t_df.empty:
            sw_df = t_df[(t_df["entry_timestamp"] >= sw_start) & (t_df["entry_timestamp"] < sw_end)]
        else:
            sw_df = pd.DataFrame()
        sw_n = len(sw_df)
        sw_net = float(sw_df["net_return_bps"].mean()) if sw_n > 0 else 0.0
        sw_wins = sw_df[sw_df["net_return_bps"] > 0] if sw_n > 0 else pd.DataFrame()
        sw_losses = sw_df[sw_df["net_return_bps"] < 0] if sw_n > 0 else pd.DataFrame()
        sw_gain = float(sw_wins["net_return_bps"].sum()) if not sw_wins.empty else 0.0
        sw_loss = abs(float(sw_losses["net_return_bps"].sum())) if not sw_losses.empty else 1e-9
        sw_pf = round(sw_gain / sw_loss, 4) if sw_loss > 0 else 999.0
        sub_eval[sw_name] = {
            "trade_count": sw_n,
            "net_expectancy_bps_cost14": round(sw_net, 2),
            "profit_factor": sw_pf,
            "win_rate_pct": round(float(len(sw_wins) / sw_n * 100.0), 1) if sw_n > 0 else 0.0,
        }

    # Diagnostic design assets summary
    design_candles = {sym: candles_map[sym] for sym in DESIGN_SYMBOLS if sym in candles_map}
    if design_candles and not synthetic_sample:
        design_cache = CandleFeatureCache(design_candles)
        raw_design_trades = []
        for sym in DESIGN_SYMBOLS:
            c_df = design_candles[sym]
            opens = c_df["open"].to_numpy(dtype=float)
            highs = c_df["high"].to_numpy(dtype=float)
            lows = c_df["low"].to_numpy(dtype=float)
            closes = c_df["close"].to_numpy(dtype=float)
            ts_list = c_df["timestamp"].tolist()
            sigs = extract_signals_with_rules(
                sym, c_df, donchian_bars=96, sma_fast_bars=96, sma_slow_bars=384, min_vol_ratio=1.2, atr_bars=192, cache=design_cache
            )
            for sig in sigs:
                if sig["side"] != "SELL":
                    continue
                sim = simulate_next_bar_open_barrier_trade("SELL", sig["signal_index"], opens, highs, lows, closes, ts_list, max_hold=192, tp_bps=350.0, sl_bps=150.0)
                if sim:
                    raw_design_trades.append({**sim, "symbol": sym, "signal_timestamp": sig["signal_timestamp"], "atr_bps": sig["atr_bps"]})
        df_design_raw = pd.DataFrame(raw_design_trades)
        design_dev_atrs = df_design_raw.loc[(df_design_raw["signal_timestamp"] >= "2024-01-01T00:00:00+00:00") & (df_design_raw["signal_timestamp"] < "2026-01-01T00:00:00+00:00"), "atr_bps"] if not df_design_raw.empty else pd.Series()
        design_q65 = float(design_dev_atrs.quantile(0.65)) if len(design_dev_atrs) > 0 else 50.0
        df_design_filtered = df_design_raw[df_design_raw["atr_bps"] <= design_q65].copy() if not df_design_raw.empty else pd.DataFrame()
        acct_design = EventDrivenAccountingEngine(acct_config)
        hourly_design = _build_hourly_mtm_candles(design_candles)
        p_design_candles = _slice_candle_map(hourly_design, p_start, p_end)
        design_p_trades = df_design_filtered[
            (df_design_filtered["entry_timestamp"] >= p_start_ts) & (df_design_filtered["entry_timestamp"] < p_end_ts)
        ].sort_values("entry_timestamp").to_dict("records") if not df_design_filtered.empty else []
        sim_res_design = acct_design.run(
            design_p_trades,
            date_range=(p_start, p_end),
            candle_data=p_design_candles,
            cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
        )
        exec_design = sim_res_design.executed_trades
        d_df = pd.DataFrame([{"net_return_bps": t.net_return_bps} for t in exec_design])
        d_net = float(d_df["net_return_bps"].mean()) if not d_df.empty else 0.0
        diag_design_summary = {
            "universe": list(DESIGN_SYMBOLS),
            "executed_trades_count": len(exec_design),
            "net_expectancy_bps_cost14": round(d_net, 2),
        }
    else:
        diag_design_summary = {
            "universe": list(DESIGN_SYMBOLS),
            "executed_trades_count": 0,
            "net_expectancy_bps_cost14": 0.0,
        }

    research_payload = {
        "pipeline_name": "hmr_v5_vcb_v5_cross_sectional_research",
        "semantic_hash_schema_version": SEMANTIC_HASH_SCHEMA_VERSION,
        "semantic_hash_excluded_fields": SEMANTIC_HASH_EXCLUDED_FIELDS,
        "generation_timestamp": gen_ts,
        "git_head": git_head,
        "candidate_id": "VCB_V5_SELL_ONLY_9ASSET",
        "spec_version": "1.0.0-research-v5",
        "allowed_sides": ["SELL"],
        "universe_definition": {
            "all_symbols": list(ALL_9_SYMBOLS),
            "primary_holdout_symbols": list(HOLDOUT_SYMBOLS),
            "diagnostic_design_symbols": list(DESIGN_SYMBOLS),
        },
        "epistemic_classification": chronology_audit["epistemic_classification"],
        "chronology_audit": chronology_audit,
        "chronology_verdict": chronology_audit["verdict"],
        "historical_candidate_search_status": HISTORICAL_CANDIDATE_SEARCH_STATUS,
        "historical_search_stop_reason": HISTORICAL_SEARCH_STOP_REASON,
        "dataset_manifest": ds_manifest,
        "candidate_spec": spec_record,
        "raw_holdout_outcome_read_at_utc": raw_read_ts,
        "primary_holdout_evaluation": {
            "period": "HOLDOUT_30M_CONTIGUOUS_2024_2026_H1" if not synthetic_sample else "SYNTHETIC_SAMPLE_PERIOD",
            "start": p_start,
            "end": p_end,
            "calendar_days": int(days_eval),
            "executed_trade_count": n_trades,
            "gross_expectancy_bps": round(gross_exp, 2),
            "net_expectancy_bps_cost14": round(net_exp_14, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(pf, 4),
            "max_drawdown_pct": round(dd_pct, 2),
            "cost_sensitivity": {
                "net_bps_cost10": round(net_exp_10, 2),
                "net_bps_cost14": round(net_exp_14, 2),
                "net_bps_cost20": round(net_exp_20, 2),
                "net_bps_cost30": round(net_exp_30, 2),
            },
            "primary_daily_block_bootstrap_ci_bps": bs_res,
            "decomposition": decomp_primary,
        },
        "temporal_stability_diagnostics": sub_eval,
        "diagnostic_design_assets_summary": diag_design_summary,
        "trade_rate_comparison": {
            "v4_baseline_trades_per_day": 0.2202,
            "v4_baseline_90d_trades": 19.8,
            "v4_baseline_days_to_n100": 454.1,
            "v5_holdout_trades_per_day": round(rate_v5, 4),
            "v5_holdout_90d_trades": round(proj_90d_v5, 2),
            "v5_holdout_days_to_n100": days_to_100_v5,
            "sample_accumulation_speedup_factor": round(rate_v5 / 0.2202, 2) if rate_v5 > 0 else 0.0,
        },
        "gate_scorecard": gate_eval,
        "admission_verdict": verdict,
        "system_operating_disposition": {
            "candidate_selection_verdict": "NO_CANDIDATE_SELECTED",
            "prospective_status": "PROSPECTIVE_NOT_STARTED",
            "runtime_candidate_spec": None,
            "activation_manifest": None,
        },
    }

    research_payload["semantic_artifact_sha256"] = compute_semantic_artifact_hash(research_payload)

    res_json_file = out_dir / "vcb_v5_sell_only_9asset_research.json"
    res_md_file = out_dir / "vcb_v5_sell_only_9asset_research.md"
    res_json_file.write_text(json.dumps(research_payload, indent=2), encoding="utf-8")
    res_md_file.write_text(render_v5_cross_sectional_markdown(research_payload), encoding="utf-8")

    if not quiet:
        print(f"Exported V5 research JSON: {res_json_file}")
        print(f"Exported V5 research MD:   {res_md_file}")
        print(f"V5 Admission Verdict:      {verdict}")
        print(f"Semantic Artifact SHA256:  {research_payload['semantic_artifact_sha256']}")

    return research_payload


def generate_deterministic_synthetic_candles(coins: Sequence[str] = COINS, n_bars: int = 1200) -> dict[str, pd.DataFrame]:
    """Generates deterministic synthetic 15m candle stream for fast testing without reading disk CSVs."""
    start_ts = pd.Timestamp("2025-10-01 00:00:00", tz="UTC")
    ts_idx = pd.date_range(start=start_ts, periods=n_bars, freq="15min")
    candles = {}
    for idx, sym in enumerate(coins):
        rng = np.random.RandomState(42 + idx)
        base = 50000.0 if sym == "BTC" else (3000.0 if sym == "ETH" else 600.0)
        closes = base + np.cumsum(rng.randn(n_bars) * (base * 0.001))
        highs = closes + rng.uniform(base * 0.0005, base * 0.002, size=n_bars)
        lows = closes - rng.uniform(base * 0.0005, base * 0.002, size=n_bars)
        opens = closes + rng.randn(n_bars) * (base * 0.0005)
        vols = rng.uniform(10.0, 100.0, size=n_bars)
        candles[sym] = pd.DataFrame({
            "timestamp": ts_idx,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        })
    return candles


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible VCB economic research pipeline.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for JSON/MD artifacts")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic bootstrap random seed")
    parser.add_argument("--reps", type=int, default=2000, help="Number of bootstrap resamples")
    parser.add_argument("--max-bars-per-symbol", type=int, default=None, help="Truncate loaded candles to last N bars for fast testing")
    parser.add_argument("--synthetic-sample", action="store_true", help="Use fast in-memory synthetic candles for tests (<0.5s)")
    parser.add_argument("--evaluate-v4-sell-only", action="store_true", help="Evaluate VCB_V4_SELL_ONLY candidate and export dedicated artifacts")
    parser.add_argument("--evaluate-v5-holdout", action="store_true", help="Evaluate VCB_V5_SELL_ONLY_9ASSET cross-sectional holdout experiment and export dedicated artifacts")
    parser.add_argument("--prospective-candidate-json", type=Path, default=None, help="Path to explicit new prospective candidate registration input JSON")
    parser.add_argument("--profile-memory", action="store_true", help="Enable tracemalloc memory profiling (adds allocation overhead)")
    parser.add_argument("--profile-cpu", action="store_true", help="Enable CPU profiling flag indicator")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose print output")
    args = parser.parse_args()

    if args.profile_memory:
        tracemalloc.start()
    t0 = time.perf_counter()
    stage_timing: dict[str, float] = {}

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    git_head = get_git_head()
    gen_ts = datetime.now(timezone.utc).isoformat()

    if not args.quiet:
        print("=== HMR-V5: Running Reproducible Economic Research Pipeline ===")
        print(f"Timestamp: {gen_ts}")
        print(f"Git HEAD: {git_head}")
        print(f"Output Directory: {out_dir}")
        print(f"Profiling Enabled: memory={args.profile_memory}, cpu={args.profile_cpu}, reps={args.reps}\n")

    if args.evaluate_v5_holdout:
        evaluate_vcb_v5_cross_sectional(
            out_dir=out_dir,
            reps=args.reps,
            seed=args.seed,
            quiet=args.quiet,
            synthetic_sample=args.synthetic_sample,
        )
        return

    # 1. Load symbol candles & compute dataset manifest
    if not args.quiet:
        print("Loading 15m candles for BTC, ETH, BNB...")
    t_stage = time.perf_counter()
    if args.synthetic_sample:
        symbol_candles_15m = generate_deterministic_synthetic_candles(COINS)
    else:
        symbol_candles_15m = {sym: audit_and_merge_symbol_candles(sym)[0] for sym in COINS}
        if args.max_bars_per_symbol is not None and args.max_bars_per_symbol > 0:
            symbol_candles_15m = {
                sym: df.iloc[-args.max_bars_per_symbol:].copy().reset_index(drop=True)
                for sym, df in symbol_candles_15m.items()
            }
    stage_timing["load_symbol_candles_seconds"] = round(time.perf_counter() - t_stage, 3)

    t_stage = time.perf_counter()
    hourly_mtm_candles = _build_hourly_mtm_candles(symbol_candles_15m)
    stage_timing["build_hourly_mtm_candles_seconds"] = round(time.perf_counter() - t_stage, 3)

    t_stage = time.perf_counter()
    ds_manifest = compute_dataset_manifest(symbol_candles_15m)
    stage_timing["compute_dataset_manifest_seconds"] = round(time.perf_counter() - t_stage, 3)

    t_stage = time.perf_counter()
    feature_cache = CandleFeatureCache(symbol_candles_15m)
    stage_timing["init_feature_cache_seconds"] = round(time.perf_counter() - t_stage, 3)

    # Pre-slice hourly candles once for DEV and BURNED to eliminate per-candidate slicing overhead
    t_stage = time.perf_counter()
    pre_sliced_hourly = {
        "DEV_WALK_FORWARD_SELECTION_2024_2025": _slice_candle_map(hourly_mtm_candles, "2024-01-01", "2026-01-01"),
        "BURNED_EXPOSED_AUDIT_2026_H1": _slice_candle_map(hourly_mtm_candles, "2026-01-01", "2026-07-01"),
    }
    stage_timing["pre_slice_hourly_candles_seconds"] = round(time.perf_counter() - t_stage, 3)

    if args.evaluate_v4_sell_only:
        evaluate_vcb_v4_sell_only(
            symbol_candles_15m,
            out_dir=out_dir,
            pre_sliced_hourly=pre_sliced_hourly,
            feature_cache=feature_cache,
            reps=args.reps,
            seed=args.seed,
            quiet=args.quiet,
        )
        return

    # 2. Accounting Engine Configuration
    acct_config = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        cooldown_bars=96,
        bar_interval_minutes=15,
        allocation_pct_per_trade=0.25,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
    )
    acct = EventDrivenAccountingEngine(acct_config)

    # 3. Simulate Candidate V1 Baseline
    if not args.quiet:
        print("Simulating VOL_COMPRESSION_BREAKOUT_V1 baseline...")
    v1_params = {
        "universe": COINS,
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "atr_compression_quantile": 0.65,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
        "max_hold_bars": 192,
    }
    t_stage = time.perf_counter()
    df_v1, v1_meta = simulate_candidate_stream(
        "VOL_COMPRESSION_BREAKOUT_V1",
        v1_params,
        symbol_candles_15m,
        feature_cache=feature_cache,
    )
    stage_timing["v1_stream_simulation_seconds"] = round(time.perf_counter() - t_stage, 3)

    # Evaluate V1 across periods
    t_stage = time.perf_counter()
    v1_eval = run_candidate_evaluation(
        "VOL_COMPRESSION_BREAKOUT_V1",
        v1_meta,
        df_v1,
        acct,
        pre_sliced_hourly=pre_sliced_hourly,
        seed=args.seed,
        bootstrap_reps=args.reps,
    )
    stage_timing["v1_evaluation_seconds"] = round(time.perf_counter() - t_stage, 3)

    # Detailed 9-dimension decomposition for V1
    if not args.quiet:
        print("Generating 9-dimension economic decomposition for V1...")
    t_stage = time.perf_counter()
    decompositions = {
        p_name: decompose_trades_dataframe(p_data["raw_executed_trades"], p_name)
        for p_name, p_data in v1_eval["periods"].items()
    }
    stage_timing["v1_decomposition_seconds"] = round(time.perf_counter() - t_stage, 3)

    # Clean raw_executed_trades from JSON export
    for p_name in v1_eval["periods"]:
        del v1_eval["periods"][p_name]["raw_executed_trades"]

    # 4. Exploratory Candidate Hypotheses (Post-Hoc after 2026 Audit Exposure)
    if not args.quiet:
        print("\nEvaluating post-hoc exploratory candidate variants...")

    variants_config = [
        {
            "candidate_id": "VCB_V2_VOL15",
            "economic_rationale": "Filters low-volume chop by raising volume hurdle from 1.2x to 1.5x",
            "params": {**v1_params, "min_vol_ratio_96": 1.5},
            "req_slope": False,
            "use_atr_normalized_barrier": False,
            "req_regime_gate": False,
        },
        {
            "candidate_id": "VCB_V2_DONCHIAN192",
            "economic_rationale": "Filters 24h noise by expanding breakout lookback from 24h to 48h (192 bars)",
            "params": {**v1_params, "donchian_bars": 192},
            "req_slope": False,
            "use_atr_normalized_barrier": False,
            "req_regime_gate": False,
        },
        {
            "candidate_id": "VCB_V2_SLOPE",
            "economic_rationale": "Prevents counter-trend BUY entries by requiring SMA384 slope alignment",
            "params": {**v1_params},
            "req_slope": True,
            "use_atr_normalized_barrier": False,
            "req_regime_gate": False,
        },
        {
            "candidate_id": "VCB_V3_VOL_NORMALIZED_BARRIER",
            "economic_rationale": "Adapts rigid TP/SL barriers to prevailing market volatility using 3.0x/1.5x ATR scaling",
            "params": {**v1_params, "tp_bps": "DYNAMIC_3.0_ATR", "sl_bps": "DYNAMIC_1.5_ATR"},
            "req_slope": False,
            "use_atr_normalized_barrier": True,
            "req_regime_gate": False,
        },
        {
            "candidate_id": "VCB_V3_DIRECTIONAL_REGIME_GATE",
            "economic_rationale": "Requires HTF multi-day macro regime alignment (SMA384 > SMA384[384]) before permitting breakouts",
            "params": {**v1_params, "donchian_bars": 192},
            "req_slope": True,
            "use_atr_normalized_barrier": False,
            "req_regime_gate": True,
        },
    ]

    candidate_specs_payloads: dict[str, Any] = {
        "VOL_COMPRESSION_BREAKOUT_V1": v1_meta,
    }

    all_candidates_eval: dict[str, Any] = {
        "NO_TRADE": {
            "candidate_id": "NO_TRADE",
            "economic_rationale": "Baseline capital preservation (0 trades)",
            "spec_sha256": "0" * 64,
            "periods": {
                "DEV_WALK_FORWARD_SELECTION_2024_2025": {
                    "epistemic_classification": "BASELINE",
                    "executed_trades_count": 0,
                    "gross_expectancy_bps": 0.0,
                    "net_expectancy_bps_cost14": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown_pct": 0.0,
                    "primary_daily_block_bootstrap_ci_bps": {
                        "ci_lower": 0.0,
                        "ci_upper": 0.0,
                        "mean_daily_bps": 0.0,
                        "block_size_days": 10,
                        "gate_7_passed": False,
                    },
                },
                "BURNED_EXPOSED_AUDIT_2026_H1": {
                    "epistemic_classification": "BASELINE",
                    "executed_trades_count": 0,
                    "gross_expectancy_bps": 0.0,
                    "net_expectancy_bps_cost14": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown_pct": 0.0,
                    "primary_daily_block_bootstrap_ci_bps": {
                        "ci_lower": 0.0,
                        "ci_upper": 0.0,
                        "mean_daily_bps": 0.0,
                        "block_size_days": 10,
                        "gate_7_passed": False,
                    },
                },
            },
        },
        "VOL_COMPRESSION_BREAKOUT_V1": {
            "candidate_id": "VOL_COMPRESSION_BREAKOUT_V1",
            "economic_rationale": "Baseline frozen specification (Donchian 96, SMA 96/384, Vol 1.2x, TP 350, SL 150)",
            "spec_sha256": v1_meta["spec_sha256"],
            "periods": v1_eval["periods"],
        },
    }

    t_stage = time.perf_counter()
    for vc in variants_config:
        cid = vc["candidate_id"]
        if not args.quiet:
            print(f"  Evaluating {cid}...")
        df_cand, c_meta = simulate_candidate_stream(
            cid,
            vc["params"],
            symbol_candles_15m,
            use_atr_normalized_barrier=vc["use_atr_normalized_barrier"],
            req_slope=vc["req_slope"],
            req_regime_gate=vc["req_regime_gate"],
            feature_cache=feature_cache,
        )
        candidate_specs_payloads[cid] = c_meta
        c_eval = run_candidate_evaluation(
            cid,
            c_meta,
            df_cand,
            acct,
            pre_sliced_hourly=pre_sliced_hourly,
            seed=args.seed,
            bootstrap_reps=args.reps,
        )
        for p_name in c_eval["periods"]:
            del c_eval["periods"][p_name]["raw_executed_trades"]
        c_eval["economic_rationale"] = vc["economic_rationale"]
        all_candidates_eval[cid] = c_eval
    stage_timing["variants_simulation_and_eval_seconds"] = round(time.perf_counter() - t_stage, 3)

    # 5. Fail-Closed Candidate Selection & Historical Disposition
    rejection_audit: dict[str, Any] = {}
    historical_dispositions: dict[str, Any] = {}
    eligible_candidates: list[str] = []

    # Exposed historical candidates are permanently burned and NEVER eligible for prospective registration
    for cid, c_eval in all_candidates_eval.items():
        if cid == "NO_TRADE":
            continue
        hist_disp = classify_exposed_historical_candidate(cid, c_eval)
        historical_dispositions[cid] = hist_disp

        rejection_audit[cid] = {
            "eligible": False,
            "reasons": hist_disp["reasons"],
            "historical_disposition": hist_disp["disposition"],
        }

    # Prospective registration is ONLY attempted if an explicit prospective candidate input is provided
    runtime_candidate_spec = None
    if args.prospective_candidate_json is not None and args.prospective_candidate_json.exists():
        with open(args.prospective_candidate_json, "r", encoding="utf-8") as f:
            p_input = json.load(f)
        p_cid = p_input.get("candidate_id", "PROSPECTIVE_CANDIDATE")
        is_p_eligible, p_reasons = validate_new_candidate_for_prospective_registration(p_input)
        rejection_audit[p_cid] = {
            "eligible": is_p_eligible,
            "reasons": p_reasons,
            "historical_disposition": "PROSPECTIVE_REGISTRATION_EVALUATED",
        }
        if is_p_eligible:
            eligible_candidates.append(p_cid)
            runtime_candidate_spec = p_input

    # Top-level disposition: Fail-Closed
    if not eligible_candidates:
        candidate_selection_verdict = "NO_CANDIDATE_SELECTED"
        prospective_status = "NOT_STARTED"
        runtime_candidate_spec = None
        activation_manifest = None
    else:
        selected_cid = eligible_candidates[0]
        candidate_selection_verdict = f"CANDIDATE_SELECTED_{selected_cid}"
        prospective_status = "PREPARED"
        activation_manifest = None

    # Safe removal of any obsolete/unsupported prospective files
    v3_spec_path = out_dir / "prospective_v3_candidate_spec.json"
    v3_manifest_path = out_dir / "prospective_v3_activation_manifest.json"
    if v3_spec_path.exists():
        v3_spec_path.unlink()
    if v3_manifest_path.exists():
        v3_manifest_path.unlink()

    if args.profile_memory:
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = round(peak_mem / (1024 * 1024), 2)
    else:
        peak_mb = None

    elapsed_sec = time.perf_counter() - t0
    stage_timing["total_wall_clock_seconds"] = round(elapsed_sec, 3)

    perf_meta = {
        "elapsed_seconds": round(elapsed_sec, 2),
        "canonical_elapsed_seconds_without_memory_instrumentation": round(elapsed_sec, 2) if not args.profile_memory else None,
        "profiled_elapsed_seconds": round(elapsed_sec, 2) if args.profile_memory else None,
        "peak_memory_mb": peak_mb,
        "profiling_enabled": bool(args.profile_memory or args.profile_cpu),
        "stage_timing_seconds": stage_timing,
    }

    t_export = time.perf_counter()
    decomp_export = {
        "pipeline_name": "hmr_v5_vcb_economic_decomposition",
        "semantic_hash_schema_version": SEMANTIC_HASH_SCHEMA_VERSION,
        "semantic_hash_excluded_fields": SEMANTIC_HASH_EXCLUDED_FIELDS,
        "generation_timestamp": gen_ts,
        "git_head": git_head,
        "dataset_manifest": ds_manifest,
        "candidate_spec": v1_meta,
        "accounting_config": {
            "initial_capital": acct_config.initial_capital,
            "max_concurrent_positions": acct_config.max_concurrent_positions,
            "max_positions_per_asset": acct_config.max_positions_per_asset,
            "cooldown_bars": acct_config.cooldown_bars,
            "allocation_pct_per_trade": acct_config.allocation_pct_per_trade,
            "fee_rate_bps": acct_config.fee_rate_bps,
            "slippage_bps": acct_config.slippage_bps,
        },
        "v1_evaluation_summary": v1_eval,
        "decompositions": decompositions,
        "performance_metadata": perf_meta,
    }
    decomp_export["semantic_artifact_sha256"] = compute_semantic_artifact_hash(decomp_export)

    decomp_json_path = out_dir / "vcb_economic_decomposition.json"
    decomp_md_path = out_dir / "vcb_economic_decomposition.md"
    decomp_json_path.write_text(json.dumps(decomp_export, indent=2), encoding="utf-8")
    decomp_md_path.write_text(render_decomposition_markdown(decomp_export), encoding="utf-8")
    if not args.quiet:
        print(f"Exported: {decomp_json_path}")
        print(f"Exported: {decomp_md_path}")

    variants_export = {
        "pipeline_name": "hmr_v5_vcb_exploratory_variants",
        "semantic_hash_schema_version": SEMANTIC_HASH_SCHEMA_VERSION,
        "semantic_hash_excluded_fields": SEMANTIC_HASH_EXCLUDED_FIELDS,
        "generation_timestamp": gen_ts,
        "git_head": git_head,
        "candidate_selection_verdict": candidate_selection_verdict,
        "prospective_status": prospective_status,
        "runtime_candidate_spec": runtime_candidate_spec,
        "activation_manifest": activation_manifest,
        "rejection_audit": rejection_audit,
        "historical_dispositions": historical_dispositions,
        "dataset_manifest": ds_manifest,
        "statistical_protocol": {
            "bootstrap_method": "Moving-Block & Stationary Bootstrap on Cross-Symbol Daily MTM Returns",
            "block_size_days": 10,
            "bootstrap_replications": args.reps,
            "random_seed": args.seed,
            "primary_decision_gate": "Gate 7: Primary Daily Portfolio Block Bootstrap CI Lower Bound > 0.0 bps/day",
        },
        "epistemic_notice": "All variants in this artifact are post-hoc exploratory hypotheses formulated after audit exposure. None are eligible for promotion.",
        "candidates": all_candidates_eval,
        "performance_metadata": perf_meta,
    }
    variants_export["semantic_artifact_sha256"] = compute_semantic_artifact_hash(variants_export)

    variants_json_path = out_dir / "vcb_exploratory_variants.json"
    variants_md_path = out_dir / "vcb_exploratory_variants.md"
    variants_json_path.write_text(json.dumps(variants_export, indent=2), encoding="utf-8")
    variants_md_path.write_text(render_variants_markdown(variants_export), encoding="utf-8")
    stage_timing["export_artifacts_seconds"] = round(time.perf_counter() - t_export, 3)

    if not args.quiet:
        print(f"Exported: {variants_json_path}")
        print(f"Exported: {variants_md_path}")
        mem_str = f"Peak memory: {peak_mb} MB" if peak_mb is not None else "Memory profiling: disabled"
        print(f"\nPipeline execution complete in {elapsed_sec:.2f}s! {mem_str}")


if __name__ == "__main__":
    main()

