"""
Meta Model (confidence layer) for adaptive trading system.

Provides training and prediction utilities. Train reads `logs/adaptive_signals.json`
and learns a binary label (win vs loss) from features + regime info.

Usage:
  .venv/bin/python -m btc_scraper.meta_model --train
  .venv/bin/python -m btc_scraper.meta_model --predict '{"score":63, ...}'
"""
import json
import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals.json"
MODEL_OUT = LOGS / "meta_model.joblib"
METRIC_OUT = LOGS / "meta_model.json"


def _load_records():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing {INPUT}")
    with open(INPUT, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_dataframe(records):
    df = pd.DataFrame(records)
    # label: win if pnl_pct > 0 or result == 'WIN'
    if 'pnl_pct' in df.columns:
        df['label'] = (df['pnl_pct'].astype(float) > 0).astype(int)
    else:
        df['label'] = (df.get('result') == 'WIN').astype(int)

    # select features
    features = [
        'score', 'confidence', 'position_size', 'regime_confidence',
        'rsi_15m', 'adx_15m', 'atr_pct_15m', 'vol_spike'
    ]
    for c in features:
        if c not in df.columns:
            df[c] = 0.0

    # regime one-hot
    df['regime'] = df['regime'].fillna('UNKNOWN')
    regimes = ['TRENDING_BULL', 'TRENDING_BEAR', 'RANGING', 'HIGH_VOLATILITY', 'UNKNOWN']
    for r in regimes:
        df[f'regime_{r.lower()}'] = (df['regime'] == r).astype(int)

    # signal type bools
    bool_cols = ['is_buy','is_sell','is_strong','is_sfp','is_crossover','is_reversal','is_pullback','is_break']
    for b in bool_cols:
        if b not in df.columns:
            df[b] = 0.0

    X_cols = features + [f'regime_{r.lower()}' for r in regimes] + bool_cols
    X = df[X_cols].astype(float).fillna(0.0)
    y = df['label'].astype(int)
    return X, y


def train_meta_model(n_estimators=100, cv=5):
    recs = _load_records()
    X, y = _make_dataframe(recs)
    if len(y) < 10:
        raise RuntimeError('Not enough samples to train meta model')

    clf = RandomForestClassifier(n_estimators=n_estimators, random_state=42)
    skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
    aucs = cross_val_score(clf, X, y, cv=skf, scoring='roc_auc')
    accs = cross_val_score(clf, X, y, cv=skf, scoring='accuracy')

    clf.fit(X, y)
    joblib.dump({'model': clf, 'features': list(X.columns)}, MODEL_OUT)
    metrics = {
        'n_samples': int(len(y)),
        'cv_auc_mean': float(np.mean(aucs)),
        'cv_auc_std': float(np.std(aucs)),
        'cv_acc_mean': float(np.mean(accs)),
        'cv_acc_std': float(np.std(accs)),
    }
    with open(METRIC_OUT, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    return metrics


def load_model():
    if not MODEL_OUT.exists():
        return None
    obj = joblib.load(MODEL_OUT)
    return obj


def predict_meta_confidence(record):
    obj = load_model()
    if obj is None:
        return {'error': 'no_model'}
    clf = obj['model'] if isinstance(obj, dict) and 'model' in obj else obj
    features = obj['features'] if isinstance(obj, dict) and 'features' in obj else None
    df = pd.DataFrame([record])
    # ensure same columns
    for col in features:
        if col not in df.columns:
            df[col] = 0.0
    X = df[features].astype(float).fillna(0.0)
    prob = clf.predict_proba(X)[0,1]
    return {'probability': float(prob)}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--train', action='store_true')
    p.add_argument('--n', type=int, default=100)
    args = p.parse_args()
    if args.train:
        print('Training meta model...')
        m = train_meta_model(n_estimators=args.n)
        print('Saved', MODEL_OUT)
        print(m)
    else:
        print('Run with --train to train the meta model')
