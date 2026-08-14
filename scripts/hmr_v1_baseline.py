#!/usr/bin/env python3
"""Historical Market Replay V1 baseline smoke runner.

This is deliberately small: it reuses the existing institutional backtest
engine with sanitized current-policy signals, fixed replay windows, and gates
that make temporal/accounting gaps explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import BacktestEngine
from scripts.generate_triple_barrier_labels import load_candles_for_coin


FORBIDDEN_SIGNAL_FIELDS = {
    "exit_time",
    "pnl_pct",
    "result",
    "return_15m",
    "return_1h",
    "return_4h",
    "return_1d",
    "triple_barrier_label",
    "barrier_hit_time",
}


@dataclass(frozen=True)
class ReplayProfile:
    name: str
    alternative_policy: str
    evidence_tag: str | None = None


STRICT_V1 = ReplayProfile(
    name="STRICT_V1",
    alternative_policy="PIT-safe/reconstructed-safe data plus production fallback",
)

RESEARCH_V1 = ReplayProfile(
    name="RESEARCH_V1",
    alternative_policy="STRICT_V1 plus historical H1/H2 data tagged NON_PIT_VERIFIED",
    evidence_tag="NON_PIT_VERIFIED",
)


def parse_utc(value: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def load_signals(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "records" in raw:
        raw = raw["records"]
    elif isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raise ValueError(f"Signal file must contain records: {path}")
    frame = pd.DataFrame(raw)
    if frame.empty:
        return frame
    if "coin" not in frame.columns or "entry_time" not in frame.columns:
        raise ValueError("Signals must contain coin and entry_time")
    frame["coin"] = frame["coin"].astype(str).str.upper()
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["entry_time", "coin"])
    return frame


def sanitize_signals(signals: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    forbidden_present = sorted(FORBIDDEN_SIGNAL_FIELDS & set(signals.columns))
    sanitized = signals.drop(columns=forbidden_present, errors="ignore").copy()
    return sanitized, {
        "forbidden_fields_present": forbidden_present,
        "forbidden_fields_removed": forbidden_present,
        "future_outcome_fields_removed": len(forbidden_present),
    }


def load_closed_candles(
    data_dir: Path,
    coins: list[str],
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    settlement_end: pd.Timestamp,
    warmup_bars: int = 260,
) -> dict[str, list[dict[str, Any]]]:
    candles: dict[str, list[dict[str, Any]]] = {}
    for coin in coins:
        frame = load_candles_for_coin(data_dir=data_dir, coin=coin, timeframe=timeframe)
        if frame.empty:
            continue
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        warmup_start = start - pd.Timedelta(timeframe) * warmup_bars
        window = frame[
            (frame["timestamp"] >= warmup_start)
            & (frame["timestamp"] <= settlement_end)
        ].copy()
        if window.empty:
            continue
        window = window.rename(columns={"timestamp": "time"})
        candles[coin] = window[["time", "open", "high", "low", "close", "volume"]].to_dict(orient="records")
    return candles


def restrict_timeline(
    signals: pd.DataFrame,
    candles: dict[str, list[dict[str, Any]]],
    coins: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    signals = signals[
        signals["coin"].isin(coins)
        & (signals["entry_time"] >= start)
        & (signals["entry_time"] <= end)
    ].copy()
    signals["entry_time"] = signals["entry_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for coin_rows in candles.values():
        for row in coin_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")
    return signals.to_dict(orient="records"), candles


@contextmanager
def research_model_override(manifest_path: str | None):
    if not manifest_path:
        yield None
        return

    import joblib
    from btc_scraper.ml_engine import artifact_resolver as resolver_module
    from btc_scraper.ml_engine import meta_model
    from btc_scraper.ml_engine.artifact_resolver import ArtifactLoadResult, sha256_file

    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required_gates = (
        "TRAINING_TEMPORAL_VALIDITY", "CALIBRATION_TEMPORAL_VALIDITY",
        "LABEL_TEMPORAL_VALIDITY", "DATASET_PROVENANCE",
        "ARTIFACT_PROVENANCE", "DETERMINISTIC_TRAINING",
    )
    if manifest.get("status") != "PASS" or any(
        manifest.get("gates", {}).get(gate) != "PASS" for gate in required_gates
    ):
        raise ValueError("research artifact manifest gates are not all PASS")
    if not all(manifest.get("boundary", {}).values()):
        raise ValueError("research artifact boundary is incomplete")
    bundle_path = REPO_ROOT / manifest["paths"]["bundle"]
    if sha256_file(bundle_path) != manifest["artifact_sha256"]:
        raise ValueError("research artifact SHA-256 mismatch")
    metadata = {
        "model_version": manifest["model_version"],
        "artifact_sha256": manifest["artifact_sha256"],
        "feature_schema_version": manifest["feature_schema_version"],
        "runtime_contract": "sklearn-joblib-v1",
        "status": "research_only",
        "research_training_run_id": manifest["research_training_run_id"],
        "evaluation_earliest_allowed": manifest["evaluation_earliest_allowed"],
    }

    class ResearchResolver:
        def resolve(self, model_name: str, require_metadata: bool = False):
            if model_name != "meta_model":
                return ArtifactLoadResult(model_name, None, None, False, False, "research_override_unknown_model")
            return ArtifactLoadResult(
                model_name=model_name,
                path=bundle_path,
                metadata_path=path,
                available=True,
                healthy=True,
                sha256=manifest["artifact_sha256"],
                schema_version=manifest["feature_schema_version"],
                status="research_only",
                metadata=metadata,
            )

    previous_resolver = resolver_module.get_artifact_resolver
    previous_cache = meta_model._MODEL_CACHE
    previous_cached = meta_model._CACHED_MODEL
    previous_error = meta_model._MODEL_LOAD_ERROR
    previous_version = meta_model.MODEL_VERSION
    resolver = ResearchResolver()
    resolver_module.get_artifact_resolver = lambda: resolver
    meta_model._MODEL_CACHE = joblib.load(bundle_path)
    meta_model._CACHED_MODEL = None
    meta_model._MODEL_LOAD_ERROR = None
    meta_model.MODEL_VERSION = manifest["model_version"]
    try:
        yield manifest
    finally:
        resolver_module.get_artifact_resolver = previous_resolver
        meta_model._MODEL_CACHE = previous_cache
        meta_model._CACHED_MODEL = previous_cached
        meta_model._MODEL_LOAD_ERROR = previous_error
        meta_model.MODEL_VERSION = previous_version


@contextmanager
def isolated_policy_runtime():
    keys = {
        "BTC_RUNTIME_ENVIRONMENT": "research",
        # The isolated store must enforce committed-decision lineage exactly as
        # production does. Its files are deleted and never qualify as evidence.
        "BTC_EVIDENCE_ELIGIBLE": "true",
        "BTC_DEPLOYMENT_ID": "hmr-v1-policy-parity",
        "BTC_PAPER_RUN_ID": "hmr-v1-policy-parity",
        "BTC_RUNTIME_ID": "hmr-v1-policy-parity",
    }
    previous = {key: os.environ.get(key) for key in (*keys, "BTC_RUNTIME_ROOT")}
    with tempfile.TemporaryDirectory(prefix="hmr-v1-policy-") as runtime_root:
        os.environ.update(keys)
        os.environ["BTC_RUNTIME_ROOT"] = runtime_root
        from btc_scraper.ml_engine import runtime_evidence_store as evidence_module

        evidence_module._STORE = evidence_module.RuntimeEvidenceStore(
            Path(runtime_root) / "runtime_evidence.sqlite"
        )
        _activate_replay_evidence_epoch(evidence_module._STORE)
        try:
            yield Path(runtime_root)
        finally:
            evidence_module._STORE = None
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _activate_replay_evidence_epoch(store) -> None:
    from btc_scraper.core.config import analysis_universe_hash, get_runtime_universe
    from btc_scraper.ml_engine.artifact_resolver import get_artifact_resolver
    from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
    from btc_scraper.ml_engine.prediction_logger import _git_commit

    deployment_id = "hmr-v1-policy-parity"
    universe = get_runtime_universe().analysis_symbols
    artifact = get_artifact_resolver().resolve("meta_model")
    metadata = dict(artifact.metadata or {})
    metadata_bytes = json.dumps(
        metadata, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    code_commit = str(_git_commit() or "unknown")
    model_version = str(metadata.get("model_version") or metadata.get("version") or "v3.1")
    feature_schema_version = str(metadata.get("feature_schema_version") or "meta-v3.1-43f")
    release_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": code_commit,
        "artifact_sha256": artifact.sha256,
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "registry_sha256": hashlib.sha256(b"hmr-v1-isolated-registry").hexdigest(),
        "deployment_id": deployment_id,
        "paper_run_id": deployment_id,
        "feature_schema_version": feature_schema_version,
        "analysis_universe": ",".join(universe),
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = EvidenceEpoch(
        epoch_id="hmr-v1-policy-parity-epoch",
        deployment_id=deployment_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha=code_commit,
        model_version=model_version,
        artifact_sha256=artifact.sha256,
        feature_schema_version=feature_schema_version,
        analysis_universe=universe,
        analysis_universe_hash=analysis_universe_hash(universe),
        paper_run_id=deployment_id,
        release_manifest=release_manifest,
    )
    store.create_evidence_epoch(epoch)
    store.transition_evidence_epoch(epoch.epoch_id, "ACTIVE")


def _semantic_hash(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _policy_contract_mismatches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "time": row["time"],
            "coin": row["coin"],
            "canonical_action": row["canonical_action"],
            "final_action": row["final_action"],
        }
        for row in rows
        if row["final_action"] in {"BUY", "SELL"}
        and row["canonical_action"] != row["final_action"]
    ]


def _model_temporal_validity(
    start: pd.Timestamp,
    research_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if research_manifest is not None:
        earliest = parse_utc(str(research_manifest["evaluation_earliest_allowed"]))
        required_gates = (
            "TRAINING_TEMPORAL_VALIDITY", "CALIBRATION_TEMPORAL_VALIDITY",
            "LABEL_TEMPORAL_VALIDITY", "DATASET_PROVENANCE",
            "ARTIFACT_PROVENANCE", "DETERMINISTIC_TRAINING",
        )
        passed = earliest <= start and all(
            research_manifest.get("gates", {}).get(gate) == "PASS"
            for gate in required_gates
        )
        return {
            "status": "PASS" if passed else "FAIL",
            "classification": "PROVEN_PRE_WINDOW" if passed else "PROVEN_POST_WINDOW",
            "metadata_path": "research artifact manifest",
            "model_version": research_manifest["model_version"],
            "artifact_sha256": research_manifest["artifact_sha256"],
            "research_training_run_id": research_manifest["research_training_run_id"],
            "training_cutoff": research_manifest["training_available_max"],
            "calibration_cutoff": research_manifest["calibration_available_max"],
            "evaluation_earliest_allowed": earliest.isoformat(),
            "evaluation_start": start.isoformat(),
            "reason": None if passed else "Research artifact is not available before replay start.",
        }
    metadata_path = REPO_ROOT / "logs" / "meta_model.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    cutoff_fields = (
        "training_cutoff",
        "training_data_end",
        "data_cutoff",
        "trained_through",
    )
    cutoff_field = next((field for field in cutoff_fields if metadata.get(field)), None)
    cutoff = parse_utc(str(metadata[cutoff_field])) if cutoff_field else None
    passed = cutoff is not None and cutoff <= start
    return {
        "status": "PASS" if passed else "FAIL",
        "metadata_path": str(metadata_path.relative_to(REPO_ROOT)),
        "model_version": metadata.get("model_version") or metadata.get("version"),
        "artifact_sha256": metadata.get("artifact_sha256"),
        "training_cutoff_field": cutoff_field,
        "training_cutoff": cutoff.isoformat() if cutoff is not None else None,
        "evaluation_start": start.isoformat(),
        "reason": None if passed else "Model metadata does not prove training_cutoff <= replay evaluation start.",
    }


def _replay_world_state(analysis: dict[str, Any]):
    from btc_scraper.core.world_state import WorldState, risk_appetite_from_signal

    timestamp = pd.Timestamp(analysis["time"], tz="UTC").to_pydatetime()
    state = WorldState(
        timestamp=timestamp,
        regime=risk_appetite_from_signal(analysis.get("action")),
        is_snapshot=True,
        snapshot_id=f"hmr-{analysis.get('coin')}-{pd.Timestamp(timestamp).strftime('%Y%m%dT%H%M%SZ')}",
        source="replay",
    )
    sentiment = analysis.get("sentiment") or {}
    state.sentiment.FearGreed = float(sentiment.get("raw_value") or 50.0)
    state.crypto.BTC_Price = float(analysis.get("close") or 0.0)
    state.liquidity.BTC_Funding = 0.0
    state.liquidity.OI_Delta = 0.0
    state.macro.DXY = 100.0
    state.macro.VIX = 20.0
    state.macro.RealYield = 0.0
    state.macro.BondYield = 4.5
    return state


def build_production_policy_signals(
    candles: dict[str, list[dict[str, Any]]],
    coins: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    timeframe: str,
    observation_filter: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from btc_scraper.analysis import analyze_all_market
    from btc_scraper.ml_engine.causal_context_bridge import get_hybrid_provider
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
    from btc_scraper.ml_engine.signal_score import evaluate_signal_score
    from btc_scraper.trading.auto_trader import AutoTrader

    analysis_by_time: dict[str, dict[str, dict[str, Any]]] = {}
    for coin in coins:
        rows = []
        for candle in candles.get(coin, []):
            row = dict(candle)
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(row)
        for analysis in analyze_all_market(rows):
            observed_at = pd.Timestamp(analysis["time"], tz="UTC")
            observation_key = (str(analysis["time"]), coin)
            if (
                start <= observed_at <= end
                and (observation_filter is None or observation_key in observation_filter)
            ):
                analysis_by_time.setdefault(analysis["time"], {})[coin] = analysis

    expected_observations = (
        len(observation_filter)
        if observation_filter is not None
        else len(pd.date_range(start, end, freq=pd.Timedelta(timeframe))) * len(coins)
    )
    funnel = {
        "market_observations": expected_observations,
        "feature_vectors": 0,
        "technical_directional": 0,
        "inference_completed": 0,
        "posterior_directional": 0,
        "meta_threshold_passed": 0,
        "signal_score_threshold_passed": 0,
        "canonical_policy_directional": 0,
        "entry_risk_eligible": 0,
        "final_actions": {"BUY": 0, "SELL": 0, "HOLD": 0},
    }
    errors: list[dict[str, Any]] = []
    captures: dict[str, dict[str, Any]] = {}
    semantic_rows: list[dict[str, Any]] = []
    execution_signals: list[dict[str, Any]] = []
    artifacts: set[str] = set()
    coordinator = InferenceCoordinator()
    decision_engine = MetaDecisionEngine()
    provider = get_hybrid_provider(alpha=0.0)
    trader = AutoTrader()
    trader._check_circuit_breaker = lambda: (True, "")
    trader._has_open_position = lambda _coin, _direction: False

    for observed_at in sorted(analysis_by_time):
        cycle_id = f"hmr-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"
        for coin in coins:
            if observation_filter is not None and (observed_at, coin) not in observation_filter:
                continue
            analysis = analysis_by_time[observed_at].get(coin)
            if analysis is None:
                errors.append({"time": observed_at, "coin": coin, "stage": "FEATURE_PIPELINE_PATH", "error": "missing_analysis"})
                continue
            analysis = dict(analysis)
            analysis.update({
                "coin": coin,
                "symbol": f"{coin}USDT",
                "timeframe": timeframe,
                "cycle_id": cycle_id,
                "observed_at": observed_at,
            })
            funnel["feature_vectors"] += 1
            if str(analysis.get("action")).upper() in {"BUY", "SELL"}:
                funnel["technical_directional"] += 1
            try:
                prediction = coordinator.predict_once(
                    analysis,
                    symbol=coin,
                    timeframe=timeframe,
                    decision_context="entry",
                    caller_context="hmr_v1_policy_parity",
                )
                prediction_dict = prediction.to_dict()
                funnel["inference_completed"] += 1
                artifacts.add(prediction.artifact_sha256)
                score = evaluate_signal_score(analysis, meta_prediction=prediction_dict)
                analysis["signal_score"] = score
                for field in (
                    "signal_id", "prediction_id", "model_version", "artifact_sha256",
                    "model_artifact_sha256", "feature_schema_version", "deployment_id",
                    "paper_run_id", "cycle_id", "decision_context", "caller_context", "feature_hash",
                ):
                    if score.get(field) is not None:
                        analysis[field] = score[field]
                decision_input = {**analysis, **score, "_meta_prediction": prediction_dict}
                base_decision = decision_engine.decide(decision_input, persist_final=False)
                if str(base_decision.get("action")).upper() in {"BUY", "SELL"}:
                    funnel["posterior_directional"] += 1
                meta_probability = float(score.get("meta_probability") or 0.0)
                if meta_probability >= trader.meta_threshold:
                    funnel["meta_threshold_passed"] += 1
                strength = float(score.get("strength") or 0.0)
                if strength >= trader.score_threshold:
                    funnel["signal_score_threshold_passed"] += 1
                final_decision = decision_engine.decide_with_provider(
                    decision_input, provider, _replay_world_state(analysis)
                )
                analysis["causal_decision"] = final_decision
                if str(final_decision.get("action")).upper() in {"BUY", "SELL"}:
                    funnel["canonical_policy_directional"] += 1
                entry_decision = trader.build_entry_decision(analysis, coin)
                final_action = entry_decision.action.value if entry_decision.eligible else "HOLD"
                if entry_decision.eligible:
                    funnel["entry_risk_eligible"] += 1
                funnel["final_actions"][final_action] += 1
                signal = {
                    **analysis,
                    "entry_time": observed_at,
                    "signal_raw": final_action,
                    "policy_final_action": final_action,
                }
                execution_signals.append(signal)
                semantic = {
                    "time": observed_at,
                    "coin": coin,
                    "feature_hash": prediction.feature_hash,
                    "artifact_sha256": prediction.artifact_sha256,
                    "raw_model_output": prediction.probability,
                    "posterior": final_decision.get("posterior_probability"),
                    "meta_probability": score.get("meta_probability"),
                    "signal_score_strength": score.get("strength"),
                    "technical_action": analysis.get("action"),
                    "technical_score": score.get("score"),
                    "risk_status": score.get("risk_status"),
                    "gates": {
                        "technical_directional": str(analysis.get("action")).upper() in {"BUY", "SELL"},
                        "posterior_directional": str(base_decision.get("action")).upper() in {"BUY", "SELL"},
                        "meta_threshold_passed": meta_probability >= trader.meta_threshold,
                        "signal_score_threshold_passed": strength >= trader.score_threshold,
                        "canonical_policy_directional": str(final_decision.get("action")).upper() in {"BUY", "SELL"},
                        "risk_eligible": bool(entry_decision.eligible),
                    },
                    "canonical_action": final_decision.get("action"),
                    "final_decision_reason": final_decision.get("reason"),
                    "final_action": final_action,
                    "rejection_reason": (
                        entry_decision.rejection_reason.value
                        if entry_decision.rejection_reason else None
                    ),
                }
                semantic_rows.append(semantic)
                technical_capture_key = (
                    "technical_BUY" if analysis.get("action") == "BUY"
                    else "technical_SELL" if analysis.get("action") == "SELL"
                    else "technical_HOLD"
                )
                captures.setdefault(technical_capture_key, semantic)
                captures.setdefault(f"final_{final_action}", semantic)
                captures.setdefault("fallback_alternative_data", {
                    **semantic,
                    "alternative_policy": "production fallback",
                    "world_state_source": "replay",
                })
            except Exception as exc:
                errors.append({
                    "time": observed_at,
                    "coin": coin,
                    "stage": "PRODUCTION_POLICY_PATH",
                    "error": f"{type(exc).__name__}: {exc}",
                })

    for action in ("BUY", "SELL", "HOLD"):
        captures.setdefault(f"final_{action}", {"status": "NOT_OBSERVED"})
    contract_mismatches = _policy_contract_mismatches(semantic_rows)
    contract_consistent = (
        not contract_mismatches
        and funnel["entry_risk_eligible"] <= funnel["canonical_policy_directional"]
    )
    complete = len(semantic_rows) == expected_observations and not errors
    component_status = "PASS" if complete else "FAIL"
    contract_status = "PASS" if complete and contract_consistent else "FAIL"
    path = {
        "status": contract_status,
        "FEATURE_PIPELINE_PATH": "PASS" if funnel["feature_vectors"] == expected_observations else "FAIL",
        "MODEL_ARTIFACT_PATH": "PASS" if len(artifacts) == 1 and None not in artifacts else "FAIL",
        "INFERENCE_COORDINATOR_PATH": "PASS" if funnel["inference_completed"] == expected_observations else "FAIL",
        "META_DECISION_PATH": component_status,
        "FINAL_POLICY_GATE_PATH": contract_status,
        "RISK_GATE_PATH": contract_status,
        "DECISION_CONTRACT": contract_status,
        "input_mode": "HISTORICAL_MARKET_STATE_THROUGH_PRODUCTION_POLICY",
        "observations_expected": expected_observations,
        "observations_completed": len(semantic_rows),
        "artifact_sha256": sorted(artifacts),
        "semantic_hash": _semantic_hash(semantic_rows),
        "errors": errors[:20],
        "error_count": len(errors),
        "contract_mismatch_count": len(contract_mismatches),
        "contract_mismatches": contract_mismatches[:20],
        "funnel": funnel,
        "captures": captures,
        "semantic_rows": semantic_rows,
    }
    return execution_signals, path


def no_lookahead_gate(
    signals: list[dict[str, Any]],
    candles: dict[str, list[dict[str, Any]]],
    timeframe: str,
    forbidden_fields: set[str] | None = None,
) -> dict[str, Any]:
    forbidden_fields = forbidden_fields or FORBIDDEN_SIGNAL_FIELDS
    closed_bar_times = {
        coin: {row["time"] for row in rows}
        for coin, rows in candles.items()
    }
    missing_bar = []
    for signal in signals:
        coin = str(signal.get("coin", "")).upper()
        entry_time = signal.get("entry_time")
        if entry_time not in closed_bar_times.get(coin, set()):
            missing_bar.append({"coin": coin, "entry_time": entry_time})
    forbidden = sorted(
        field for signal in signals for field in forbidden_fields if field in signal
    )
    passed = not missing_bar and not forbidden
    return {
        "status": "PASS" if passed else "FAIL",
        "timeframe": timeframe,
        "signals_checked": len(signals),
        "missing_closed_bars": missing_bar[:20],
        "missing_closed_bar_count": len(missing_bar),
        "forbidden_fields_remaining": sorted(set(forbidden)),
    }


def replay_parity_gate(
    signals: list[dict[str, Any]],
    candles: dict[str, list[dict[str, Any]]],
    coins: list[str],
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    production_policy_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = pd.date_range(start=start, end=end, freq=pd.Timedelta(timeframe))
    expected_times = {stamp.strftime("%Y-%m-%d %H:%M:%S") for stamp in expected}
    symbol_accounting: dict[str, Any] = {}
    replay_times: set[str] = set()
    for coin in coins:
        actual = {
            row["time"]
            for row in candles.get(coin, [])
            if start <= pd.Timestamp(row["time"], tz="UTC") <= end
        }
        replay_times.update(actual)
        missing = sorted(expected_times - actual)
        extra = sorted(actual - expected_times)
        symbol_accounting[coin] = {
            "status": "PASS" if not missing and not extra else "FAIL",
            "expected": len(expected_times),
            "actual": len(actual),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "first_missing": missing[:5],
            "first_extra": extra[:5],
        }
    cadence_pass = timeframe == "15m" and all(
        row["status"] == "PASS" for row in symbol_accounting.values()
    )
    policy_path = production_policy_path or {
        "status": "FAIL",
        "input_mode": "PERSISTED_SIGNAL_RECORDS",
        "same_features": "NOT_PROVEN",
        "same_technical_gates": "NOT_PROVEN",
        "same_meta_threshold": "NOT_PROVEN",
        "same_posterior_threshold": "NOT_PROVEN",
        "same_signal_score_threshold": "NOT_PROVEN",
        "same_final_decision_implementation": "NOT_PROVEN",
        "same_policy_version": "NOT_PROVEN",
        "reason": "Runner consumes stored signal_raw values and does not regenerate the production decision path.",
    }
    return {
        "status": "PASS" if cadence_pass and policy_path["status"] == "PASS" else "FAIL",
        "timeframe": {"status": "PASS" if timeframe == "15m" else "FAIL", "actual": timeframe, "expected": "15m"},
        "expected_cycle_count": len(expected_times),
        "actual_cycle_count": len(replay_times),
        "signal_cycle_count": len({signal["entry_time"] for signal in signals}),
        "symbol_accounting": symbol_accounting,
        "production_policy_path": policy_path,
    }


def accounting_gate(result: dict[str, Any], tolerance: float) -> dict[str, Any]:
    metrics = result.get("metrics", {})
    trades = result.get("trades", [])
    first_bad_trade = None
    max_trade_residual = 0.0
    for index, trade in enumerate(trades):
        expected_net = float(trade.get("gross_pnl", 0.0)) - float(trade.get("fee_paid", 0.0))
        actual_net = float(trade.get("pnl", 0.0))
        residual = actual_net - expected_net
        max_trade_residual = max(max_trade_residual, abs(residual))
        if first_bad_trade is None and abs(residual) > tolerance:
            first_bad_trade = {
                "trade_index": index,
                "coin": trade.get("coin"),
                "entry_time": trade.get("entry_time"),
                "expected_net": expected_net,
                "actual_net": actual_net,
                "residual": residual,
            }

    opening = float(metrics.get("opening_balance", 0.0))
    ending_cash = float(metrics.get("ending_cash", 0.0))
    ending_equity = float(metrics.get("ending_equity", 0.0))
    realized_net = float(metrics.get("realized_net_pnl", 0.0))
    unrealized_pnl = float(metrics.get("unrealized_pnl", 0.0))
    open_count = int(metrics.get("open_position_count", -1))
    open_quantity = float(metrics.get("open_quantity", math.inf))
    cash_residual = ending_cash - (opening + realized_net)
    equity_residual = ending_equity - (opening + realized_net + unrealized_pnl)
    trade_pass = first_bad_trade is None
    position_pass = open_count == 0 and abs(open_quantity) <= tolerance
    cash_pass = position_pass and abs(cash_residual) <= tolerance
    equity_pass = abs(equity_residual) <= tolerance
    passed = trade_pass and position_pass and cash_pass and equity_pass
    return {
        "status": "PASS" if passed else "FAIL",
        "trade_reconciliation": {
            "status": "PASS" if trade_pass else "FAIL",
            "trades_checked": len(trades),
            "max_abs_residual": max_trade_residual,
            "first_bad_trade": first_bad_trade,
        },
        "cash_ledger": {"status": "PASS" if cash_pass else "FAIL", "ending_cash": ending_cash, "residual": cash_residual},
        "position_ledger": {
            "status": "PASS" if position_pass else "FAIL",
            "open_position_count": open_count,
            "open_quantity": open_quantity,
            "open_positions": metrics.get("open_positions", []),
        },
        "equity_reconciliation": {
            "status": "PASS" if equity_pass else "FAIL",
            "opening_balance": opening,
            "realized_net_pnl": realized_net,
            "unrealized_pnl": unrealized_pnl,
            "ending_equity": ending_equity,
            "residual": equity_residual,
        },
        "identity_residual": equity_residual,
        "tolerance": tolerance,
        "slippage_semantics": "Execution prices include slippage; attribution is reported but not debited again.",
    }


def deterministic_gate(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    keys = ["metrics", "trade_counts", "decision_counts"]
    deltas = {key: first.get(key) == second.get(key) for key in keys}
    return {"status": "PASS" if all(deltas.values()) else "FAIL", "comparisons": deltas}


def summarize_result(
    result: dict[str, Any],
    signals: list[dict[str, Any]],
    replay_cycles: int,
) -> dict[str, Any]:
    trades = result.get("trades", [])
    metrics = result.get("metrics", {})
    decision_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    for signal in signals:
        raw = str(signal.get("signal_raw", signal.get("signal", ""))).upper()
        if "BUY" in raw:
            decision_counts["BUY"] += 1
        elif "SELL" in raw:
            decision_counts["SELL"] += 1
        else:
            decision_counts["HOLD"] += 1
    breakdown_by_coin: dict[str, dict[str, Any]] = {}
    breakdown_by_side: dict[str, dict[str, Any]] = {}
    monthly_breakdown: dict[str, dict[str, Any]] = {}
    regime_breakdown: dict[str, dict[str, Any]] = {}
    for trade in trades:
        coin = str(trade.get("coin", "UNKNOWN")).upper()
        side = str(trade.get("type", "UNKNOWN")).upper()
        try:
            month = pd.Timestamp(trade.get("exit_time") or trade.get("entry_time")).strftime("%Y-%m")
        except Exception:
            month = "UNKNOWN"
        regime = str(trade.get("regime", "UNKNOWN"))
        for bucket, key in (
            (breakdown_by_coin, coin),
            (breakdown_by_side, side),
            (monthly_breakdown, month),
            (regime_breakdown, regime),
        ):
            row = bucket.setdefault(key, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            row["trades"] += 1
            pnl = float(trade.get("pnl", 0.0))
            row["net_pnl"] += pnl
            row["wins"] += pnl > 0
    for bucket in (breakdown_by_coin, breakdown_by_side, monthly_breakdown, regime_breakdown):
        for row in bucket.values():
            row["win_rate"] = row["wins"] / row["trades"] if row["trades"] else 0.0
    return {
        "cycles": replay_cycles,
        "signal_cycles": len({signal["entry_time"] for signal in signals}),
        "predictions": len(signals),
        "decision_counts": decision_counts,
        "execution_eligible": decision_counts["BUY"] + decision_counts["SELL"],
        "trade_counts": {
            "opened": metrics.get("positions_opened", 0),
            "closed": metrics.get("positions_closed", len(trades)),
            "open_at_end": metrics.get("open_position_count", 0),
        },
        "metrics": {
            "gross_pnl": metrics.get("realized_gross_pnl", metrics.get("gross_pnl", 0.0)),
            "fees": metrics.get("realized_fees", metrics.get("total_fees", 0.0)),
            "slippage_attribution": metrics.get("total_slippage_attribution", 0.0),
            "spread_attribution": metrics.get("total_spread_attribution", 0.0),
            "net_pnl": metrics.get("realized_net_pnl", metrics.get("net_pnl", 0.0)),
            "ending_equity": metrics.get("ending_equity", 0.0),
            "win_rate": metrics.get("win_rate", 0.0),
            "avg_win": metrics.get("avg_win", 0.0),
            "avg_loss": metrics.get("avg_loss", 0.0),
            "expectancy_per_trade": metrics.get("expectancy", 0.0),
            "profit_factor": metrics.get("profit_factor", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "n_trades": metrics.get("n_trades", 0),
        },
        "breakdown_by_coin": breakdown_by_coin,
        "breakdown_by_side": breakdown_by_side,
        "monthly_breakdown": monthly_breakdown,
        "regime_breakdown": regime_breakdown,
    }


def markdown_report(report: dict[str, Any]) -> str:
    metrics = report["current_policy_metrics"]["metrics"]
    gates = report["gates"]
    lines = [
        "# Historical Market Replay V1 STRICT Smoke",
        "",
        f"Milestone: `{report['milestone']}`",
        f"Window: `{report['window']['start']}` to `{report['window']['end']}` ({report['window']['timeframe']})",
        f"Coins: `{', '.join(report['coins'])}`",
        "",
        "## Gates",
        "",
        "| Gate | Status | Note |",
        "| --- | --- | --- |",
        f"| NO_LOOKAHEAD | {gates['NO_LOOKAHEAD']['status']} | checked {gates['NO_LOOKAHEAD']['signals_checked']} sanitized signals |",
        f"| REPLAY_PARITY_SANITY | {gates['REPLAY_PARITY_SANITY']['status']} | market cycles `{gates['REPLAY_PARITY_SANITY']['actual_cycle_count']}/{gates['REPLAY_PARITY_SANITY']['expected_cycle_count']}`; production policy path `{gates['REPLAY_PARITY_SANITY']['production_policy_path']['status']}` |",
        f"| PRODUCTION_POLICY_PATH_PARITY | {gates['PRODUCTION_POLICY_PATH_PARITY']['status']} | `{gates['PRODUCTION_POLICY_PATH_PARITY']['observations_completed']}/{gates['PRODUCTION_POLICY_PATH_PARITY']['observations_expected']}` observations |",
        f"| MODEL_TEMPORAL_VALIDITY | {gates['MODEL_TEMPORAL_VALIDITY']['status']} | cutoff `{gates['MODEL_TEMPORAL_VALIDITY']['training_cutoff']}` |",
        f"| DETERMINISTIC_REPLAY | {gates['DETERMINISTIC_REPLAY']['status']} | metrics/trade/decision summaries match across rerun |",
        f"| EXECUTION_ACCOUNTING | {gates['EXECUTION_ACCOUNTING']['status']} | residual `{gates['EXECUTION_ACCOUNTING']['identity_residual']}` |",
        "",
        "## Current Policy Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in [
        "gross_pnl",
        "fees",
        "slippage_attribution",
        "spread_attribution",
        "net_pnl",
        "ending_equity",
        "win_rate",
        "avg_win",
        "avg_loss",
        "expectancy_per_trade",
        "profit_factor",
        "max_drawdown",
        "n_trades",
    ]:
        lines.append(f"| {key} | {metrics.get(key, 0.0)} |")
    summary = report["current_policy_metrics"]
    funnel = gates["PRODUCTION_POLICY_PATH_PARITY"].get("funnel", {})
    lines.extend([
        "",
        "## Activity",
        "",
        f"- cycles: `{summary['cycles']}`",
        f"- signal cycles: `{summary['signal_cycles']}`",
        f"- predictions: `{summary['predictions']}`",
        f"- decisions: `{summary['decision_counts']}`",
        f"- execution eligible: `{summary['execution_eligible']}`",
        f"- trades opened/closed: `{summary['trade_counts']}`",
        "",
        "## Decision Funnel",
        "",
        "```json",
        json.dumps(funnel, indent=2, sort_keys=True),
        "```",
        "",
        "## Breakdowns",
        "",
        "```json",
        json.dumps(
            {
                "by_coin": summary["breakdown_by_coin"],
                "by_side": summary["breakdown_by_side"],
                "monthly": summary["monthly_breakdown"],
                "regime": summary["regime_breakdown"],
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Status",
        "",
        (
            "This report is a COUNTERFACTUAL_OOS_EFFICACY_SAMPLE, not a strategy conclusion."
            if report["evidence_status"] == "OOS_EFFICACY_SAMPLE"
            else "This report is SMOKE_DIAGNOSTIC_ONLY and NOT_EFFICACY_EVIDENCE until every gate passes."
        ),
    ])
    return "\n".join(lines) + "\n"


def run_once(
    config: BacktestConfig,
    candles: dict[str, list[dict[str, Any]]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    result = BacktestEngine(config).run(candles, signals)
    return result.to_dict()


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if end <= start:
        raise ValueError("--end must be after --start")
    coins = [coin.strip().upper() for coin in args.coins.split(",") if coin.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars
    candles = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start, end, settlement_end,
        warmup_bars=args.warmup_bars,
    )
    policy_mode = str(args.policy_mode).lower()
    research_manifest_path = getattr(args, "research_artifact_manifest", None)
    research_manifest = None
    if policy_mode == "production":
        with research_model_override(research_manifest_path) as research_manifest:
            with isolated_policy_runtime():
                generated, policy_path = build_production_policy_signals(
                    candles, coins, start, end, args.timeframe
                )
                fixture_filter = {
                    (str(row["time"]), str(row["coin"]))
                    for row in policy_path["captures"].values()
                    if row.get("time") is not None and row.get("coin") is not None
                }
                _, policy_path_second = build_production_policy_signals(
                    candles, coins, start, end, args.timeframe,
                    observation_filter=fixture_filter,
                )
        first_fixture_rows = [
            row for row in policy_path["semantic_rows"]
            if (str(row["time"]), str(row["coin"])) in fixture_filter
        ]
        first_fixture_hash = _semantic_hash(first_fixture_rows)
        policy_deterministic = (
            policy_path["status"] == "PASS"
            and policy_path_second["status"] == "PASS"
            and first_fixture_hash == policy_path_second["semantic_hash"]
        )
        policy_path["deterministic_semantic_replay"] = {
            "status": "PASS" if policy_deterministic else "FAIL",
            "fixture_count": len(fixture_filter),
            "first_hash": first_fixture_hash,
            "second_hash": policy_path_second["semantic_hash"],
        }
        policy_path.pop("semantic_rows", None)
        signals_frame = pd.DataFrame(generated)
        signals_frame["entry_time"] = pd.to_datetime(
            signals_frame["entry_time"], utc=True
        )
        sanitization = {
            "source": "production_policy_generated",
            "future_outcome_fields_removed": 0,
        }
    else:
        raw_signals = load_signals(Path(args.signals))
        signals_frame, sanitization = sanitize_signals(raw_signals)
        policy_path = {
            "status": "FAIL",
            "input_mode": "PERSISTED_SIGNAL_RECORDS",
            "observations_expected": 0,
            "observations_completed": 0,
            "reason": "Stored signal mode does not regenerate production policy.",
            "funnel": {},
        }
        policy_deterministic = False
    signals, candles = restrict_timeline(signals_frame, candles, coins, start, end)
    config = BacktestConfig.from_dict({
        "coins": coins,
        "timeframe": args.timeframe,
        "initial_capital": args.initial_capital,
        "same_candle_policy": "CONSERVATIVE_SL_FIRST",
    })
    first = run_once(config, candles, signals)
    second = run_once(config, candles, signals)
    parity = replay_parity_gate(
        signals, candles, coins, args.timeframe, start, end, policy_path
    )
    replay_cycles = parity["actual_cycle_count"]
    first_summary = summarize_result(first, signals, replay_cycles)
    second_summary = summarize_result(second, signals, replay_cycles)
    forbidden_fields = FORBIDDEN_SIGNAL_FIELDS
    if policy_mode == "production":
        forbidden_fields = FORBIDDEN_SIGNAL_FIELDS - {
            "return_15m", "return_1h", "return_4h", "return_1d"
        }
    no_lookahead = no_lookahead_gate(
        signals, candles, args.timeframe, forbidden_fields
    )
    accounting = accounting_gate(first, args.accounting_tolerance)
    deterministic = deterministic_gate(first_summary, second_summary)
    deterministic["comparisons"]["production_policy_semantics"] = policy_deterministic
    deterministic["status"] = (
        "PASS" if all(deterministic["comparisons"].values()) else "FAIL"
    )
    temporal_validity = _model_temporal_validity(start, research_manifest if policy_mode == "production" else None)
    parity_accepted = (
        no_lookahead["status"] == "PASS"
        and parity["status"] == "PASS"
        and deterministic["status"] == "PASS"
        and accounting["status"] == "PASS"
    )
    efficacy_ready = parity_accepted and temporal_validity["status"] == "PASS"
    return {
        "milestone": (
            "HMR-V1.3 OOS EFFICACY SAMPLE"
            if efficacy_ready
            else "HMR-V1.1 PRODUCTION POLICY PARITY PASS"
            if parity_accepted
            else "HMR-V1.1 PRODUCTION POLICY PARITY BLOCKED"
        ),
        "evidence_status": (
            "OOS_EFFICACY_SAMPLE"
            if efficacy_ready
            else "REPLAY_MECHANICS_ONLY_NOT_EFFICACY_EVIDENCE"
        ),
        "profile": asdict(STRICT_V1),
        "research_profile_defined": asdict(RESEARCH_V1),
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": args.timeframe,
            "settlement_end": settlement_end.isoformat(),
        },
        "coins": coins,
        "input": {
            "policy_mode": policy_mode,
            "signals": args.signals,
            "data_dir": args.data_dir,
            "research_artifact_manifest": research_manifest_path,
        },
        "sanitization": sanitization,
        "gates": {
            "NO_LOOKAHEAD": no_lookahead,
            "REPLAY_PARITY_SANITY": parity,
            "PRODUCTION_POLICY_PATH_PARITY": policy_path,
            "MODEL_TEMPORAL_VALIDITY": temporal_validity,
            "DETERMINISTIC_REPLAY": deterministic,
            "EXECUTION_ACCOUNTING": accounting,
        },
        "current_policy_metrics": first_summary,
        "engine_result_run_id": first.get("run_id"),
        "notes": [
            "Decision window is unchanged; settlement bars only allow positions already open at end to close.",
            "Production mode calls the canonical analysis, inference, decision, and entry-policy components in an isolated non-evidence runtime.",
            (
                "The research artifact evaluates the current architecture fitted only with pre-window information; "
                "it does not prove that this architecture or its hyperparameters were deployed in 2024."
                if research_manifest
                else "Current model replay remains mechanics-only until artifact training cutoff is point-in-time valid."
            ),
            "A seven-day OOS sample is insufficient for a strategy efficacy conclusion.",
            "Open Wave 2 only if STRICT_V1/RESEARCH_V1 deltas later show material alternative-data impact.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HMR-V1 STRICT baseline smoke.")
    parser.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-01-07T23:45:00+00:00")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--signals", default="logs/adaptive_signals_v2.json")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--accounting-tolerance", type=float, default=1e-6)
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    parser.add_argument(
        "--policy-mode", choices=("production", "stored"), default="production"
    )
    parser.add_argument("--research-artifact-manifest")
    parser.add_argument(
        "--output",
        default="research/historical_market_replay_v1/strict_v1_smoke_report.json",
    )
    args = parser.parse_args(argv)
    report = build_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(output)
    print(json.dumps({k: v["status"] for k, v in report["gates"].items()}, sort_keys=True))
    print(json.dumps(report["current_policy_metrics"]["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
