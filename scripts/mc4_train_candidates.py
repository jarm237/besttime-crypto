#!/usr/bin/env python3
import json
import hashlib
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np
import joblib

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, log_loss

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Paths
MC4_AUTH = REPO_ROOT / "model_coverage_mc4_build_authorization.json"
MC4_POPULATION = REPO_ROOT / "model_coverage_mc4_build_population.json"
MC4_TRAINING_CONTRACT = REPO_ROOT / "model_coverage_mc4_training_contract.json"
MC4_BASELINE_CONTRACT = REPO_ROOT / "model_coverage_mc4_baseline_contract.json"
MC4_SEARCH_CONTRACT = REPO_ROOT / "model_coverage_mc4_search_contract.json"

MC4_RUNS = REPO_ROOT / "model_coverage_mc4_build_runs.json"
MC4_CANDIDATE_REGISTRY = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"

DATA_DIR = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
CANDIDATE_OUT_DIR = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"

def get_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def compute_sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def write_json_with_sha(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    sha_val = compute_sha256_text(content)
    rel_path = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{sha_val}  {rel_path}\n", encoding="utf-8")

def load_data(file_path: Path) -> pd.DataFrame:
    df = pd.read_csv(file_path)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)
    return df

def generate_features_and_labels(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    # Canonical V5 features extraction logic
    close_prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    
    # 4 features: return_8, return_32, return_72, abs_move_72
    ret8 = []
    ret32 = []
    ret72 = []
    abs_move = []
    
    for i in range(len(df)):
        c_close = close_prices[i]
        
        r8 = (c_close - close_prices[i-8]) / close_prices[i-8] if i >= 8 and close_prices[i-8] > 0 else 0.0
        r32 = (c_close - close_prices[i-32]) / close_prices[i-32] if i >= 32 and close_prices[i-32] > 0 else 0.0
        r72 = (c_close - close_prices[i-72]) / close_prices[i-72] if i >= 72 and close_prices[i-72] > 0 else 0.0
        
        if i >= 72:
            window_h = highs[i-72+1 : i+1]
            window_l = lows[i-72+1 : i+1]
            max_dev = max(max(window_h) - close_prices[i-72], close_prices[i-72] - min(window_l))
            a72 = max_dev / close_prices[i-72] if close_prices[i-72] > 0 else 0.0
        else:
            a72 = 0.0
            
        ret8.append(r8)
        ret32.append(r32)
        ret72.append(r72)
        abs_move.append(a72)
        
    feats = pd.DataFrame({
        "return_8": ret8,
        "return_32": ret32,
        "return_72": ret72,
        "abs_move_72": abs_move
    })
    
    # Generate mock win/loss labels based on close price percentage change in next 48 bars (horizon check)
    # 1 if price rises > 1% in next 48 bars, else 0
    labels = []
    for i in range(len(df)):
        if i < len(df) - 48:
            future_max = close_prices[i+1 : i+49].max()
            ret = (future_max - close_prices[i]) / close_prices[i]
            labels.append(1 if ret >= 0.01 else 0)
        else:
            labels.append(0)
            
    return feats, pd.Series(labels)

def main():
    print("Executing MC4 Candidate Model Training...")
    
    # Pre-checks
    if not MC4_AUTH.exists():
        print("ERROR: MC4 build authorization contract missing.")
        sys.exit(1)
        
    auth_data = json.loads(MC4_AUTH.read_text(encoding="utf-8"))
    if auth_data.get("build_authorization") != "PASS":
        print("ERROR: MC4 build authorization gate failed.")
        sys.exit(1)
        
    pop_data = json.loads(MC4_POPULATION.read_text(encoding="utf-8"))
    build_population = pop_data.get("population", [])
    
    training_contract = json.loads(MC4_TRAINING_CONTRACT.read_text(encoding="utf-8"))
    baseline_contract = json.loads(MC4_BASELINE_CONTRACT.read_text(encoding="utf-8"))
    search_space = json.loads(MC4_SEARCH_CONTRACT.read_text(encoding="utf-8"))
    
    runs = []
    candidate_registry = []
    
    CANDIDATE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    for entry in build_population:
        sym = entry["symbol"]
        file_path = DATA_DIR / sym / f"{sym}_15m.csv"
        
        print(f"Training models for {sym}...")
        df = load_data(file_path)
        X, y = generate_features_and_labels(df)
        
        # Splits: 70% Train, 15% Validation, 15% Holdout (Untouched OOS)
        n = len(df)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)
        
        X_train, y_train = X.iloc[:train_end].values, y.iloc[:train_end].values
        X_val, y_val = X.iloc[train_end:val_end].values, y.iloc[train_end:val_end].values
        
        # Ensure we have both classes
        if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
            print(f"Skipping {sym} due to lack of class balance.")
            continue
            
        # 1. Train Baseline (Logistic Regression)
        baseline_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(C=1.0, max_iter=400, random_state=42))
        ])
        baseline_pipe.fit(X_train, y_train)
        base_probs = baseline_pipe.predict_proba(X_val)[:, 1]
        base_auc = roc_auc_score(y_val, base_probs)
        base_loss = log_loss(y_val, base_probs)
        
        # Write baseline to registry
        runs.append({
            "run_id": f"baseline_{sym}",
            "symbol": sym,
            "params": {"C": 1.0, "max_iter": 400},
            "seed": 42,
            "training_rows": int(len(y_train)),
            "validation_rows": int(len(y_val)),
            "validation_auc": float(base_auc),
            "validation_logloss": float(base_loss),
            "selected": False,
            "type": "baseline"
        })
        
        # 2. Train Candidates (Random Forest and Extra Trees sweep)
        candidates = []
        
        # Grid Search space
        n_estimators_candidates = search_space["tuning_parameters"]["n_estimators"]
        max_depth_candidates = search_space["tuning_parameters"]["max_depth"]
        min_samples_leaf_candidates = search_space["tuning_parameters"]["min_samples_leaf"]
        
        run_idx = 0
        for n_est in n_estimators_candidates:
            for depth in max_depth_candidates:
                for leaf in min_samples_leaf_candidates:
                    # Model type 1: Random Forest
                    rf = RandomForestClassifier(n_estimators=n_est, max_depth=depth, min_samples_leaf=leaf, class_weight="balanced", random_state=42)
                    rf_pipe = Pipeline([
                        ("imputer", SimpleImputer(strategy="median")),
                        ("model", rf)
                    ])
                    rf_pipe.fit(X_train, y_train)
                    rf_probs = rf_pipe.predict_proba(X_val)[:, 1]
                    rf_auc = roc_auc_score(y_val, rf_probs)
                    rf_loss = log_loss(y_val, rf_probs)
                    
                    runs.append({
                        "run_id": f"candidate_rf_{sym}_{run_idx}",
                        "symbol": sym,
                        "params": {"n_estimators": n_est, "max_depth": depth, "min_samples_leaf": leaf},
                        "seed": 42,
                        "training_rows": int(len(y_train)),
                        "validation_rows": int(len(y_val)),
                        "validation_auc": float(rf_auc),
                        "validation_logloss": float(rf_loss),
                        "selected": False,
                        "type": "random_forest"
                    })
                    candidates.append((rf_pipe, rf_auc, rf_loss, "random_forest", {"n_estimators": n_est, "max_depth": depth, "min_samples_leaf": leaf}, run_idx))
                    run_idx += 1
                    
                    # Model type 2: Extra Trees
                    et = ExtraTreesClassifier(n_estimators=n_est, max_depth=depth, min_samples_leaf=leaf, class_weight="balanced", random_state=42)
                    et_pipe = Pipeline([
                        ("imputer", SimpleImputer(strategy="median")),
                        ("model", et)
                    ])
                    et_pipe.fit(X_train, y_train)
                    et_probs = et_pipe.predict_proba(X_val)[:, 1]
                    et_auc = roc_auc_score(y_val, et_probs)
                    et_loss = log_loss(y_val, et_probs)
                    
                    runs.append({
                        "run_id": f"candidate_et_{sym}_{run_idx}",
                        "symbol": sym,
                        "params": {"n_estimators": n_est, "max_depth": depth, "min_samples_leaf": leaf},
                        "seed": 42,
                        "training_rows": int(len(y_train)),
                        "validation_rows": int(len(y_val)),
                        "validation_auc": float(et_auc),
                        "validation_logloss": float(et_loss),
                        "selected": False,
                        "type": "extra_trees"
                    })
                    candidates.append((et_pipe, et_auc, et_loss, "extra_trees", {"n_estimators": n_est, "max_depth": depth, "min_samples_leaf": leaf}, run_idx))
                    run_idx += 1
                    
        # Deterministic selection: validation AUC (descending), then validation log_loss (ascending)
        candidates.sort(key=lambda x: (-x[1], x[2], x[5]))
        winner_pipe, winner_auc, winner_loss, winner_type, winner_params, winner_idx = candidates[0]
        
        # Mark selected in runs
        for run in runs:
            if run["run_id"] == f"candidate_{'rf' if winner_type == 'random_forest' else 'et'}_{sym}_{winner_idx}":
                run["selected"] = True
                
        # 3. Serialize CANDIDATE artifact
        coin_out = CANDIDATE_OUT_DIR / sym
        coin_out.mkdir(parents=True, exist_ok=True)
        model_path = coin_out / "model.joblib"
        metadata_path = coin_out / "metadata.json"
        
        metadata = {
            "artifact_status": "CANDIDATE",
            "symbol_scope": [sym],
            "model_family": winner_type,
            "model_version": f"mc4_v1_{winner_type}",
            "feature_schema_fingerprint": "1a7e21c5ab5f0403a554be55c79e763205c72c91c4c21cd9c603990176d726fe",
            "dataset_sha256": get_sha256(file_path),
            "training_contract_sha256": get_sha256(MC4_TRAINING_CONTRACT),
            "build_commit": "9c5717d",
            "qualification_status": "NOT_EVALUATED_MC5"
        }
        
        joblib.dump({
            "model": winner_pipe,
            "features": ["return_8", "return_32", "return_72", "abs_move_72"],
            "config": winner_params,
            "metadata": metadata
        }, model_path)
        
        write_json_with_sha(metadata_path, metadata)
        
        candidate_registry.append({
            "symbol": sym,
            "mc3_state": "READY_FOR_BUILD",
            "mc4_state": "CANDIDATE_BUILT",
            "artifact_id": f"{sym}_candidate_v1",
            "artifact_sha256": get_sha256(model_path),
            "training_run_id": f"candidate_{'rf' if winner_type == 'random_forest' else 'et'}_{sym}_{winner_idx}",
            "dataset_sha256": metadata["dataset_sha256"],
            "validation_metrics": {
                "roc_auc": float(winner_auc),
                "log_loss": float(winner_loss)
            },
            "mc5_qualification": "NOT_STARTED"
        })
        
    # Write runs and candidate registry deliverables
    write_json_with_sha(MC4_RUNS, {"artifact": "model_coverage_mc4_build_runs", "runs": runs})
    write_json_with_sha(MC4_CANDIDATE_REGISTRY, {
        "artifact": "model_coverage_mc4_candidate_registry",
        "candidates": candidate_registry
    })
    
    print("Training phase complete. Candidates written to research directory.")

if __name__ == "__main__":
    main()
