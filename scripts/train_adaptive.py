#!/usr/bin/env python3
"""Train adaptive scoring model from logged outcomes.

Usage:
    python3 scripts/train_adaptive.py --train
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from btc_scraper.ml_engine import adaptive_scoring

p = argparse.ArgumentParser()
p.add_argument("--train", action="store_true", help="Train and save model")
args = p.parse_args()

stats = adaptive_scoring.compute_score_stats()
print("Adaptive stats summary:")
import json
print(json.dumps(stats, indent=2, ensure_ascii=False))

if args.train:
    model = adaptive_scoring.train_adaptive_model(save=True)
    print("Saved model:")
    print(json.dumps(model, indent=2, ensure_ascii=False))
else:
    print('\nRun with --train to build and save an adaptive model (logs/adaptive_model.json)')
