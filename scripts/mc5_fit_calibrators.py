#!/usr/bin/env python3
import json
import hashlib
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import joblib

from sklearn.linear_model import LogisticRegression

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Paths
MC5_AUTH = REPO_ROOT / "model_coverage_mc5_qualification_authorization.json"
MC5_POPULATION = REPO_ROOT / "model_coverage_mc5_qualification_population.json"
MC5_CONTRACT = REPO_ROOT / "model_coverage_mc5_qualification_contract.json"

MC5_RUNS = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"

DATA_DIR = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
CANDIDATE_DIR = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"
CALIBRATOR_OUT_DIR = REPO_ROOT / "research" / "model_coverage_mc5"

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
    close_prices = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    
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
    print("Executing MC5 Platt Calibrator Fitting...")
    
    # Pre-checks
    if not MC5_AUTH.exists():
        print("ERROR: MC5 authorization contract missing.")
        sys.exit(1)
        
    auth_data = json.loads(MC5_AUTH.read_text(encoding="utf-8"))
    if auth_data.get("qualification_authorization") != "PASS":
        print("ERROR: MC5 qualification authorization gate failed.")
        sys.exit(1)
        
    pop_data = json.loads(MC5_POPULATION.read_text(encoding="utf-8"))
    population = pop_data.get("population", [])
    
    runs = []
    
    CALIBRATOR_OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    for entry in population:
        sym = entry["symbol"]
        cand_sha = entry["mc4_artifact_sha256"]
        
        cand_model_path = CANDIDATE_DIR / sym / "model.joblib"
        if not cand_model_path.exists():
            print(f"ERROR: Candidate artifact missing for {sym}.")
            sys.exit(1)
            
        if get_sha256(cand_model_path) != cand_sha:
            print(f"ERROR: Candidate artifact SHA mismatch for {sym}.")
            sys.exit(1)
            
        # Load candidate
        cand_pkg = joblib.load(cand_model_path)
        base_model = cand_pkg["model"]
        
        # Load calibration dataset (exactly 15% from 70% to 85%)
        file_path = DATA_DIR / sym / f"{sym}_15m.csv"
        df = load_data(file_path)
        X, y = generate_features_and_labels(df)
        
        n = len(df)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)
        
        X_cal, y_cal = X.iloc[train_end:val_end].values, y.iloc[train_end:val_end].values
        
        # Ensure classes exist
        if len(np.unique(y_cal)) < 2:
            print(f"Skipping calibrator fitting for {sym} due to lack of class balance in split.")
            runs.append({
                "symbol": sym,
                "status": "CALIBRATION_REJECTED",
                "reason": "single-class calibration split"
            })
            continue
            
        # Compute raw model predictions/probabilities on calibration split
        # We pass model uncalibrated probability or raw decision function
        raw_probs = base_model.predict_proba(X_cal)[:, 1]
        
        # Platt Scaling model: Logistic regression on raw probability output to target classes
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", max_iter=100, random_state=42)
        calibrator.fit(raw_probs.reshape(-1, 1), y_cal)
        
        # Save calibrator model
        coin_out = CALIBRATOR_OUT_DIR / sym
        coin_out.mkdir(parents=True, exist_ok=True)
        calibrator_path = coin_out / "calibrator.joblib"
        calibrator_meta_path = coin_out / "calibrator_metadata.json"
        
        meta = {
            "status": "CANDIDATE_CALIBRATOR",
            "symbol": sym,
            "model_artifact_sha256": cand_sha,
            "calibration_dataset_sha256": get_sha256(file_path),
            "method": "PLATT_SIGMOID",
            "qualification": "NOT_STARTED"
        }
        
        joblib.dump({
            "calibrator": calibrator,
            "metadata": meta
        }, calibrator_path)
        
        write_json_with_sha(calibrator_meta_path, meta)
        
        runs.append({
            "symbol": sym,
            "candidate_artifact_sha256": cand_sha,
            "calibration_dataset_sha256": meta["calibration_dataset_sha256"],
            "method": "PLATT_SIGMOID",
            "sample_count": len(y_cal),
            "positive_count": int(np.sum(y_cal)),
            "negative_count": int(len(y_cal) - np.sum(y_cal)),
            "status": "CALIBRATED",
            "calibrator_sha256": get_sha256(calibrator_path)
        })
        
    write_json_with_sha(MC5_RUNS, {"artifact": "model_coverage_mc5_calibration_runs", "runs": runs})
    print("Calibration fit complete.")

if __name__ == "__main__":
    main()
