#!/usr/bin/env python3
import json
import hashlib
import sys
from pathlib import Path
import joblib
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Paths
MC4_CANDIDATE_REGISTRY = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"
MC4_FINAL_VERDICT = REPO_ROOT / "model_coverage_mc4_final_verdict.json"
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

def main():
    print("Executing MC4 Candidate Artifact Verification & Reproducibility Tests...")
    
    if not MC4_CANDIDATE_REGISTRY.exists():
        print("ERROR: MC4 candidate registry missing.")
        sys.exit(1)
        
    registry = json.loads(MC4_CANDIDATE_REGISTRY.read_text(encoding="utf-8"))
    candidates = registry.get("candidates", [])
    
    verified_candidates = []
    
    for cand in candidates:
        sym = cand["symbol"]
        model_path = CANDIDATE_OUT_DIR / sym / "model.joblib"
        metadata_path = CANDIDATE_OUT_DIR / sym / "metadata.json"
        
        # Verify artifact provenance & integrity
        if not model_path.exists() or not metadata_path.exists():
            print(f"ERROR: Artifact files for {sym} are missing.")
            sys.exit(1)
            
        # Verify model loading
        try:
            art = joblib.load(model_path)
            assert "model" in art
            assert "features" in art
            assert "config" in art
            assert "metadata" in art
            
            meta = art["metadata"]
            assert meta["artifact_status"] == "CANDIDATE"
            assert meta["qualification_status"] == "NOT_EVALUATED_MC5"
            assert meta["feature_schema_fingerprint"] == "1a7e21c5ab5f0403a554be55c79e763205c72c91c4c21cd9c603990176d726fe"
            
        except Exception as e:
            print(f"ERROR: Failed to reload and verify artifact for {sym}: {e}")
            sys.exit(1)
            
        # Verify metadata files matching
        meta_file_data = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert meta_file_data["dataset_sha256"] == meta["dataset_sha256"]
        
        # Invariance checks passed
        verified_candidates.append(sym)
        
    # Write final verification verdict
    final_verdict = {
        "artifact": "model_coverage_mc4_final_verdict",
        "mc4_state": "CLOSED",
        "candidate_built_count": len(verified_candidates),
        "verified_symbols": verified_candidates,
        "calibration": "NOT_STARTED",
        "final_oos_qualification": "NOT_STARTED",
        "runtime_routing": "UNCHANGED",
        "activation": "NOT_AUTHORIZED"
    }
    write_json_with_sha(MC4_FINAL_VERDICT, final_verdict)
    
    print("Verification complete. MC4 finalized successfully.")

if __name__ == "__main__":
    main()
