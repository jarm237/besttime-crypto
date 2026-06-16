#!/usr/bin/env python3
"""
Fast Meta Model Trainer (V2)
============================
This script trains the ensemble meta model using the existing dataset file
(e.g., logs/adaptive_signals_v2.json). 

Unlike `calibrate_meta_model.py`, this script DOES NOT run the expensive 18-month 
rolling window simulation. It assumes that the feature dataset has already been 
generated (for example, by running `scripts/migrate_features.py`).

Usage:
  python scripts/train_model_fast.py
"""

import sys
import os
from pathlib import Path

# Force stdout to UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure btc_scraper is in PYTHONPATH
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from btc_scraper.ml_engine.meta_model import train_meta_model, INPUT

def main():
    print("=" * 65)
    print("  FAST META MODEL TRAINER (V2)")
    print("=" * 65)

    if not INPUT.exists():
        print(f"\n[ERROR] Dataset not found at: {INPUT}")
        print("Please run `python scripts/migrate_features.py` first to generate the dataset.")
        sys.exit(1)

    print(f"[+] Found dataset at {INPUT}")
    print("[+] Starting ensemble meta model training (with calibration)...\n")

    try:
        # Train with 200 estimators and Platt calibration enabled
        metrics = train_meta_model(n_estimators=200, cv=5, calibrate=True)
        print("\n[OK] Training completed successfully!")
        print("\n--- Metrics Summary ---")
        import json
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\n[ERROR] Training failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
