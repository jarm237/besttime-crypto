#!/usr/bin/env python3
import json
import hashlib
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import joblib

from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, log_loss

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Paths
MC5_AUTH = REPO_ROOT / "model_coverage_mc5_qualification_authorization.json"
MC5_POPULATION = REPO_ROOT / "model_coverage_mc5_qualification_population.json"
MC5_CONTRACT = REPO_ROOT / "model_coverage_mc5_qualification_contract.json"
MC5_CALIBRATION_RUNS = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"

MC5_REGISTRY = REPO_ROOT / "model_coverage_mc5_qualification_registry.json"
MC5_REPORT = REPO_ROOT / "model_coverage_mc5_oos_report.json"
MC5_VERDICT = REPO_ROOT / "model_coverage_mc5_final_verdict.json"

DATA_DIR = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
CANDIDATE_DIR = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"
CALIBRATOR_DIR = REPO_ROOT / "research" / "model_coverage_mc5"

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

def compute_ece(probs: np.ndarray, y_true: np.ndarray, n_bins: int = 10) -> float:
    bin_limits = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        bin_idx = (probs >= bin_limits[i]) & (probs < bin_limits[i+1])
        if np.sum(bin_idx) > 0:
            bin_acc = np.mean(y_true[bin_idx])
            bin_conf = np.mean(probs[bin_idx])
            ece += (np.sum(bin_idx) / len(probs)) * np.abs(bin_acc - bin_conf)
    return ece

def main():
    print("Executing MC5 Final OOS Qualification...")
    
    if not MC5_AUTH.exists() or not MC5_CALIBRATION_RUNS.exists():
        print("ERROR: Authorization or calibration registry files missing.")
        sys.exit(1)
        
    auth_data = json.loads(MC5_AUTH.read_text(encoding="utf-8"))
    if auth_data.get("qualification_authorization") != "PASS":
        print("ERROR: Authorization check failed.")
        sys.exit(1)
        
    pop_data = json.loads(MC5_POPULATION.read_text(encoding="utf-8"))
    population = pop_data.get("population", [])
    
    cal_data = json.loads(MC5_CALIBRATION_RUNS.read_text(encoding="utf-8"))
    cal_map = {x["symbol"]: x for x in cal_data.get("runs", [])}
    
    contract = json.loads(MC5_CONTRACT.read_text(encoding="utf-8"))
    limits = contract["statistical_acceptance_thresholds"]
    econ_limits = contract["economic_acceptance_thresholds"]
    econ_assumptions = contract["economic_assumptions"]
    
    registry = []
    oos_reports = []
    qualified_symbols = []
    
    for entry in population:
        sym = entry["symbol"]
        cand_sha = entry["mc4_artifact_sha256"]
        
        cal_info = cal_map.get(sym, {})
        if cal_info.get("status") != "CALIBRATED":
            print(f"Skipping OOS evaluation for {sym} due to lack of calibration stage support.")
            registry.append({
                "symbol": sym,
                "mc4_artifact_id": entry["mc4_artifact_id"],
                "calibrator_id": None,
                "oos_dataset_id": entry["oos_split_id"],
                "statistical_verdict": "FAIL",
                "calibration_verdict": "FAIL",
                "economic_verdict": "FAIL",
                "final_verdict": "REJECTED_CALIBRATION",
                "routing_eligibility": "NOT_QUALIFIED_FOR_ROUTING"
            })
            continue
            
        # Load model and calibrator
        cand_model_path = CANDIDATE_DIR / sym / "model.joblib"
        calibrator_path = CALIBRATOR_DIR / sym / "calibrator.joblib"
        
        cand_pkg = joblib.load(cand_model_path)
        cal_pkg = joblib.load(calibrator_path)
        
        base_model = cand_pkg["model"]
        calibrator = cal_pkg["calibrator"]
        
        # Load OOS split (15% from 85% to 100%)
        file_path = DATA_DIR / sym / f"{sym}_15m.csv"
        df = load_data(file_path)
        X, y = generate_features_and_labels(df)
        
        n = len(df)
        val_end = int(n * 0.85)
        
        X_oos, y_oos = X.iloc[val_end:].values, y.iloc[val_end:].values
        
        # Invariance check: OOS split requirements
        if len(y_oos) < limits["minimum_oos_samples"] or len(np.unique(y_oos)) < 2:
            print(f"Skipping OOS evaluation for {sym} due to insufficient samples or class balance.")
            registry.append({
                "symbol": sym,
                "mc4_artifact_id": entry["mc4_artifact_id"],
                "calibrator_id": f"{sym}_calibrator_v1",
                "oos_dataset_id": entry["oos_split_id"],
                "statistical_verdict": "FAIL",
                "calibration_verdict": "FAIL",
                "economic_verdict": "FAIL",
                "final_verdict": "INCONCLUSIVE_INSUFFICIENT_OOS",
                "routing_eligibility": "NOT_QUALIFIED_FOR_ROUTING"
            })
            continue
            
        # Evaluate model outputs
        raw_probs = base_model.predict_proba(X_oos)[:, 1]
        cal_probs = calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
        
        # Statistical evaluation
        auc = roc_auc_score(y_oos, cal_probs)
        pr_auc = average_precision_score(y_oos, cal_probs)
        brier = brier_score_loss(y_oos, cal_probs)
        loss = log_loss(y_oos, cal_probs)
        ece = compute_ece(cal_probs, y_oos)
        
        statistical_verdict = "PASS" if (auc >= limits["minimum_roc_auc"] and 
                                         pr_auc >= limits["minimum_pr_auc"] and 
                                         brier <= limits["maximum_brier"]) else "FAIL"
                                         
        calibration_verdict = "PASS" if ece <= limits["maximum_ece"] else "FAIL"
        
        # Economic evaluation
        # Calculate simulated trades when calibrated probability >= threshold (e.g. 0.65 signal trigger)
        signals = cal_probs >= 0.65
        trade_count = np.sum(signals)
        
        # Calculate net profits using simulated labels (each positive trade earns 1.5% profit, negative loses 1%)
        # Deduct transaction fees/slippage: fee = 5 bps, slippage = 5 bps (total 10 bps per trade)
        gross_ev = 0.0
        net_ev = 0.0
        
        if trade_count > 0:
            active_y = y_oos[signals]
            profits = np.where(active_y == 1, 0.015, -0.010)
            # deduct fees & slippage
            costs = (econ_assumptions["fee_bps"] + econ_assumptions["slippage_bps"]) / 10000.0
            net_profits = profits - costs
            
            gross_ev = float(np.mean(profits))
            net_ev = float(np.mean(net_profits))
            
        economic_verdict = "PASS" if (trade_count >= econ_limits["minimum_trade_count"] and 
                                      net_ev >= econ_limits["minimum_net_ev"]) else "FAIL"
                                      
        # Final Verdict classification
        final_verdict = "QUALIFIED"
        if statistical_verdict == "FAIL":
            final_verdict = "REJECTED_STATISTICAL"
        elif calibration_verdict == "FAIL":
            final_verdict = "REJECTED_CALIBRATION"
        elif economic_verdict == "FAIL":
            final_verdict = "REJECTED_ECONOMIC"
            
        routing_eligibility = "QUALIFIED_FOR_ROUTING" if final_verdict == "QUALIFIED" else "NOT_QUALIFIED_FOR_ROUTING"
        if routing_eligibility == "QUALIFIED_FOR_ROUTING":
            qualified_symbols.append(sym)
            
        registry.append({
            "symbol": sym,
            "mc4_artifact_id": entry["mc4_artifact_id"],
            "calibrator_id": f"{sym}_calibrator_v1",
            "oos_dataset_id": entry["oos_split_id"],
            "statistical_verdict": statistical_verdict,
            "calibration_verdict": calibration_verdict,
            "economic_verdict": economic_verdict,
            "final_verdict": final_verdict,
            "routing_eligibility": routing_eligibility
        })
        
        oos_reports.append({
            "symbol": sym,
            "metrics": {
                "roc_auc": float(auc),
                "pr_auc": float(pr_auc),
                "brier_score": float(brier),
                "log_loss": float(loss),
                "ece": float(ece),
                "trade_count": int(trade_count),
                "gross_ev": gross_ev,
                "net_ev": net_ev
            }
        })
        
    # Write deliverables
    write_json_with_sha(MC5_REGISTRY, {
        "artifact": "model_coverage_mc5_qualification_registry",
        "candidates": registry
    })
    write_json_with_sha(MC5_REPORT, {
        "artifact": "model_coverage_mc5_oos_report",
        "reports": oos_reports
    })
    
    # Final verdict
    verdict = {
        "artifact": "model_coverage_mc5_final_verdict",
        "mc5_state": "CLOSED",
        "qualification_population_count": len(population),
        "qualified_count": len(qualified_symbols),
        "qualified_symbols": qualified_symbols,
        "calibration": "CALIBRATED_PLATT",
        "final_oos_qualification": "COMPLETED",
        "runtime_routing": "UNCHANGED",
        "activation": "NOT_AUTHORIZED"
    }
    write_json_with_sha(MC5_VERDICT, verdict)
    print("OOS qualification complete. Final verdicts issued.")

if __name__ == "__main__":
    main()
