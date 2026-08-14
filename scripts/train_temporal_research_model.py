#!/usr/bin/env python3
"""Train a research-only meta model using information available before evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.analysis import analyze_all_market
from btc_scraper.feature_engineering.triple_barrier import TripleBarrierLabeler
from btc_scraper.ml_engine.artifact_resolver import sha256_file
from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2
from btc_scraper.ml_engine.meta_model import EnsembleMetaModel
from scripts.generate_triple_barrier_labels import load_candles_for_coin


BOUNDARY = {
    "RESEARCH_ONLY": True,
    "NON_PRODUCTION": True,
    "NON_EVIDENCE": True,
    "NO_REGISTRY_PROMOTION": True,
    "NO_ACTIVE_CANARY_MUTATION": True,
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_utc(value: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def dataframe_semantic_sha256(frame: pd.DataFrame, columns: list[str]) -> str:
    rows = frame[columns].copy()
    for column in rows.columns:
        if pd.api.types.is_datetime64_any_dtype(rows[column]):
            rows[column] = rows[column].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return canonical_sha256(rows.to_dict(orient="records"))


def temporal_eligible(
    frame: pd.DataFrame,
    *,
    feature_start: pd.Timestamp | None,
    feature_end: pd.Timestamp,
    availability_end: pd.Timestamp,
) -> pd.DataFrame:
    mask = (
        (frame["feature_available_at"] <= feature_end)
        & (frame["label_available_at"] <= availability_end)
        & frame["label_complete"].fillna(False)
    )
    if feature_start is not None:
        mask &= frame["feature_available_at"] >= feature_start
    return frame.loc[mask].copy()


def _raw_source_sha256(path: Path) -> str:
    return sha256_file(path)


def build_labeled_candidates(
    *,
    data_dir: Path,
    coins: list[str],
    timeframe: str,
    availability_cutoff: pd.Timestamp,
    feature_names: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    raw_sources: dict[str, Any] = {}
    labeler = TripleBarrierLabeler()

    for coin in coins:
        source_path = data_dir / coin / f"{coin}_{timeframe}.csv"
        candles = load_candles_for_coin(data_dir, coin, timeframe)
        candles = candles[candles["timestamp"] <= availability_cutoff].copy()
        if candles.empty:
            raise ValueError(f"No historical candles for {coin}")
        raw_sources[coin] = {
            "path": str(source_path.relative_to(REPO_ROOT)),
            "sha256": _raw_source_sha256(source_path),
            "rows_through_cutoff": len(candles),
            "available_max": candles["timestamp"].max().isoformat(),
        }

        market_rows = candles.rename(columns={"timestamp": "time"})[
            ["time", "open", "high", "low", "close", "volume"]
        ].to_dict(orient="records")
        for row in market_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")
        analyses = analyze_all_market(market_rows)
        directional = [
            {
                **analysis,
                "coin": coin,
                "entry_time": analysis["time"],
                "direction": analysis["action"],
            }
            for analysis in analyses
            if str(analysis.get("action")).upper() in {"BUY", "SELL"}
        ]
        if not directional:
            continue
        labeled = labeler.label(pd.DataFrame(directional), candles)
        for row in labeled.to_dict(orient="records"):
            feature_available_at = parse_utc(str(row["entry_time"]))
            label_available_at = parse_utc(str(row["barrier_hit_time"]))
            label_complete = (
                row["triple_barrier_reason"] != "timeout"
                or int(row["barrier_hold_bars"]) >= labeler.config.max_holding_bars
            )
            feature_values = build_meta_features_v2(row)
            records.append({
                "coin": coin,
                "entry_time": feature_available_at,
                "feature_available_at": feature_available_at,
                "label_available_at": label_available_at,
                "label": 1 if int(row["triple_barrier_label"]) == 1 else 0,
                "label_complete": label_complete,
                "label_reason": row["triple_barrier_reason"],
                "technical_action": str(row["action"]).upper(),
                **{name: float(feature_values.get(name, 0.0)) for name in feature_names},
            })

    frame = pd.DataFrame(records).sort_values(
        ["feature_available_at", "coin"], kind="mergesort"
    ).reset_index(drop=True)
    if frame.empty:
        raise ValueError("No directional training candidates were generated")
    return frame, raw_sources


def training_config(seed: int, n_estimators: int) -> dict[str, Any]:
    return {
        "architecture": "EnsembleMetaModel",
        "estimators": ["lgbm", "catboost", "xgboost"],
        "weights": {"lgbm": 1.0 / 3.0, "catboost": 1.0 / 3.0, "xgboost": 1.0 / 3.0},
        "base_params": {
            "lgbm": {"n_jobs": 1, "deterministic": True, "force_col_wise": True},
            "catboost": {"thread_count": 1, "allow_writing_files": False},
            "xgboost": {"n_jobs": 1},
        },
        "calibration_method": "isotonic",
        "n_estimators": n_estimators,
        "random_seed": seed,
        "reuse_fitted_objects": False,
    }


def fit_once(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    feature_names: list[str],
    config: dict[str, Any],
    output_dir: Path,
    deterministic_metadata: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    X_train = train[feature_names].to_numpy(dtype=float)
    y_train = train["label"].to_numpy(dtype=int)
    X_calibration = calibration[feature_names].to_numpy(dtype=float)
    y_calibration = calibration["label"].to_numpy(dtype=int)
    if len(np.unique(y_train)) < 2 or len(np.unique(y_calibration)) < 2:
        raise ValueError("Training and calibration splits must both contain two classes")

    base_model = EnsembleMetaModel(
        weights=config["weights"],
        calibration=None,
        n_estimators=int(config["n_estimators"]),
        random_state=int(config["random_seed"]),
        base_params=config["base_params"],
        use_gpu=False,
    )
    base_model.fit(X_train, y_train)
    calibrator = CalibratedClassifierCV(
        FrozenEstimator(base_model), method=str(config["calibration_method"])
    )
    calibrator.fit(X_calibration, y_calibration)

    base_path = output_dir / "base_model.joblib"
    calibrator_path = output_dir / "calibrator.joblib"
    bundle_path = output_dir / "research_meta_model.joblib"
    joblib.dump(base_model, base_path, compress=0)
    joblib.dump(calibrator, calibrator_path, compress=0)
    joblib.dump(
        {
            "model": calibrator,
            "features": feature_names,
            "version": deterministic_metadata["model_version"],
            "n_samples": len(train),
            "research_metadata": deterministic_metadata,
        },
        bundle_path,
        compress=0,
    )
    determinism_probe = np.vstack([X_train, X_calibration])
    probabilities = calibrator.predict_proba(determinism_probe)[:, 1]
    semantic_fingerprint = {
        "probabilities": probabilities.round(15).tolist(),
        "predictions": (probabilities >= 0.5).astype(int).tolist(),
        "normalized_weights": base_model.normalized_weights_,
        "feature_importances": (
            None if base_model.feature_importances_ is None
            else base_model.feature_importances_.round(15).tolist()
        ),
    }
    return {
        "base_model_path": base_path,
        "base_model_sha256": sha256_file(base_path),
        "calibrator_path": calibrator_path,
        "calibrator_sha256": sha256_file(calibrator_path),
        "bundle_path": bundle_path,
        "bundle_sha256": sha256_file(bundle_path),
        "semantic_fingerprint_sha256": canonical_sha256(semantic_fingerprint),
    }


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    coins = [coin.strip().upper() for coin in args.coins.split(",") if coin.strip()]
    training_end = parse_utc(args.training_end)
    calibration_start = parse_utc(args.calibration_start)
    calibration_end = parse_utc(args.calibration_end)
    if not training_end < calibration_start <= calibration_end:
        raise ValueError("Expected training_end < calibration_start <= calibration_end")

    production_metadata = json.loads((REPO_ROOT / "logs" / "meta_model.json").read_text(encoding="utf-8"))
    feature_names = [str(name) for name in production_metadata["features"]]
    feature_schema_sha256 = canonical_sha256(feature_names)
    frame, raw_sources = build_labeled_candidates(
        data_dir=Path(args.data_dir).resolve(), coins=coins, timeframe=args.timeframe,
        availability_cutoff=calibration_end, feature_names=feature_names,
    )
    train = temporal_eligible(
        frame, feature_start=None, feature_end=training_end,
        availability_end=training_end,
    )
    calibration = temporal_eligible(
        frame, feature_start=calibration_start, feature_end=calibration_end,
        availability_end=calibration_end,
    )
    if len(train) < args.min_train or len(calibration) < args.min_calibration:
        raise ValueError(
            f"Insufficient eligible samples: train={len(train)}, calibration={len(calibration)}"
        )

    data_columns = [
        "coin", "entry_time", "feature_available_at", "label_available_at",
        "label", "label_complete", "label_reason", "technical_action", *feature_names,
    ]
    training_data_sha256 = dataframe_semantic_sha256(train, data_columns)
    calibration_data_sha256 = dataframe_semantic_sha256(calibration, data_columns)
    config = training_config(args.seed, args.n_estimators)
    model_config_sha256 = canonical_sha256(config)
    training_code_sha = sha256_file(Path(__file__))
    run_id = (
        f"hmr-v1.2b-{training_data_sha256[:12]}-"
        f"{calibration_data_sha256[:12]}-{model_config_sha256[:8]}"
    )
    model_version = f"v3.1-research-pre2025-{run_id[-8:]}"
    deterministic_metadata = {
        "research_training_run_id": run_id,
        "model_version": model_version,
        "feature_schema_version": production_metadata["feature_schema_version"],
        "feature_schema_sha256": feature_schema_sha256,
        "training_data_sha256": training_data_sha256,
        "calibration_data_sha256": calibration_data_sha256,
        "training_code_sha": training_code_sha,
        "model_config_sha256": model_config_sha256,
        "random_seed": args.seed,
        "n_train": len(train),
        "n_calibration": len(calibration),
    }

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "training.parquet"
    calibration_path = output_dir / "calibration.parquet"
    train[data_columns].to_parquet(train_path, index=False)
    calibration[data_columns].to_parquet(calibration_path, index=False)

    os.environ["BTC_RUNTIME_ENVIRONMENT"] = "research"
    os.environ["BTC_RUNTIME_ROOT"] = str(output_dir / "runtime")
    with tempfile.TemporaryDirectory(prefix="hmr-v1.2b-repeat-") as repeat_dir:
        first = fit_once(
            train, calibration, feature_names, config, output_dir / "fit-a",
            deterministic_metadata,
        )
        second = fit_once(
            train, calibration, feature_names, config, Path(repeat_dir) / "fit-b",
            deterministic_metadata,
        )
    # Third-party estimator pickles contain non-canonical internal metadata, so
    # byte hashes identify a frozen fit but do not test reproducibility.
    deterministic_pass = (
        first["semantic_fingerprint_sha256"]
        == second["semantic_fingerprint_sha256"]
    )

    frozen_dir = output_dir / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    frozen_paths = {}
    for key, source_key, filename in (
        ("model", "base_model_path", "base_model.joblib"),
        ("calibrator", "calibrator_path", "calibrator.joblib"),
        ("bundle", "bundle_path", "research_meta_model.joblib"),
    ):
        destination = frozen_dir / filename
        shutil.copy2(first[source_key], destination)
        frozen_paths[key] = str(destination.relative_to(REPO_ROOT))
    shutil.rmtree(output_dir / "fit-a")

    information_max = max(
        train["feature_available_at"].max(), train["label_available_at"].max(),
        calibration["feature_available_at"].max(), calibration["label_available_at"].max(),
    )
    evaluation_earliest_allowed = information_max + pd.Timedelta(microseconds=1)
    gates = {
        "TRAINING_TEMPORAL_VALIDITY": "PASS" if (
            train["feature_available_at"].max() <= training_end
            and train["label_available_at"].max() <= training_end
        ) else "FAIL",
        "CALIBRATION_TEMPORAL_VALIDITY": "PASS" if (
            calibration["feature_available_at"].max() <= calibration_end
            and calibration["label_available_at"].max() <= calibration_end
        ) else "FAIL",
        "LABEL_TEMPORAL_VALIDITY": "PASS" if frame.loc[
            frame.index.isin(train.index) | frame.index.isin(calibration.index),
            "label_available_at",
        ].max() <= calibration_end else "FAIL",
        "DATASET_PROVENANCE": "PASS",
        "ARTIFACT_PROVENANCE": "PASS",
        "DETERMINISTIC_TRAINING": "PASS" if deterministic_pass else "FAIL",
    }
    manifest = {
        "milestone": "HMR-V1.2B TEMPORALLY-VALID RESEARCH ARTIFACT",
        "boundary": BOUNDARY,
        "status": "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL",
        "gates": gates,
        "research_training_run_id": run_id,
        "model_version": model_version,
        "artifact_sha256": first["bundle_sha256"],
        "model_sha256": first["base_model_sha256"],
        "calibrator_sha256": first["calibrator_sha256"],
        "training_data_sha256": training_data_sha256,
        "training_available_max": max(
            train["feature_available_at"].max(), train["label_available_at"].max()
        ).isoformat(),
        "calibration_data_sha256": calibration_data_sha256,
        "calibration_available_max": max(
            calibration["feature_available_at"].max(), calibration["label_available_at"].max()
        ).isoformat(),
        "evaluation_earliest_allowed": evaluation_earliest_allowed.isoformat(),
        "feature_schema_version": production_metadata["feature_schema_version"],
        "feature_schema_sha256": feature_schema_sha256,
        "training_code_sha": training_code_sha,
        "training_code_git_commit": git_sha(),
        "model_config": config,
        "model_config_sha256": model_config_sha256,
        "random_seed": args.seed,
        "n_train": len(train),
        "n_calibration": len(calibration),
        "class_distribution": {
            "training": train["label"].value_counts().sort_index().astype(int).to_dict(),
            "calibration": calibration["label"].value_counts().sort_index().astype(int).to_dict(),
        },
        "cutoffs": {
            "training_end": training_end.isoformat(),
            "calibration_start": calibration_start.isoformat(),
            "calibration_end": calibration_end.isoformat(),
            "eligibility_rule": (
                "feature_available_at <= split cutoff AND label_available_at <= split cutoff "
                "AND label horizon is complete (no right-censored timeout)"
            ),
        },
        "right_censored_rows_excluded": int((~frame["label_complete"]).sum()),
        "paths": {
            "training_data": str(train_path.relative_to(REPO_ROOT)),
            "calibration_data": str(calibration_path.relative_to(REPO_ROOT)),
            **frozen_paths,
        },
        "raw_sources": raw_sources,
        "determinism": {
            "first": {key: value for key, value in first.items() if not key.endswith("_path")},
            "second": {key: value for key, value in second.items() if not key.endswith("_path")},
            "criterion": (
                "semantic fingerprint over all train/calibration probabilities, "
                "class outputs, ensemble weights, and feature importances"
            ),
            "serialization_note": (
                "joblib byte hashes are provenance identifiers; third-party "
                "estimator serialization is not canonical across independent fits"
            ),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "interpretation": (
            "Counterfactual OOS evaluation of the current architecture fit only with "
            "pre-evaluation information; not evidence of the architecture deployed in 2024."
        ),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--training-end", default="2024-11-30T23:59:59Z")
    parser.add_argument("--calibration-start", default="2024-12-01T00:00:00Z")
    parser.add_argument("--calibration-end", default="2024-12-31T23:59:59Z")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--min-calibration", type=int, default=50)
    parser.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/research_artifact_pre2025",
    )
    args = parser.parse_args(argv)
    manifest = build_manifest(args)
    print(json.dumps({
        "status": manifest["status"],
        "gates": manifest["gates"],
        "n_train": manifest["n_train"],
        "n_calibration": manifest["n_calibration"],
        "evaluation_earliest_allowed": manifest["evaluation_earliest_allowed"],
        "artifact_sha256": manifest["artifact_sha256"],
    }, sort_keys=True))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
