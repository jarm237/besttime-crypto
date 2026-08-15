#!/usr/bin/env python3
"""HMR-V2.4.8: Tuned Classifiers and Feature Engineering Sweep.

Tests whether more flexible models (LightGBM/Tuned GBT) or engineered features
can resolve the ranking failure in Fold 1 (2023-H2) and achieve our target
Top-5% OOS Gross EV >= 25 bps.
"""

import json
import sys
import warnings
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v2_4_3_baseline_models import prepare, fold_split, _econ, _econ_top, FOLDS

# ── Feature Engineering ───────────────────────────────────────────────────────
from typing import Tuple, List

def engineer_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, list]:
    df = df.copy()
    
    # 1. Log transforms for positive skewed features
    df["log_break_distance"] = np.log1p(df["break_distance_atr"])
    df["log_candle_body"] = np.log1p(df["candle_body_atr"])
    df["log_room_structure"] = np.log1p(df["room_to_structure_atr"])
    
    # 2. Interaction terms
    df["break_dist_x_room"] = df["break_distance_atr"] * df["room_to_structure_atr"]
    df["body_x_room"] = df["candle_body_atr"] * df["room_to_structure_atr"]
    
    engineered_list = [
        "log_break_distance", "log_candle_body", "log_room_structure",
        "break_dist_x_room", "body_x_room",
        "trend_regime_enc", "volatility_regime_enc", "recent_cross_count_16bars", "volume_ratio"
    ]
    return df, engineered_list

def run_sweeps():
    base = Path("research/historical_market_replay_v2/v2_4_economic_models")
    path_d = base / "datasets/g1_d_pre2025.parquet"
    
    df_raw = pd.read_parquet(path_d)
    df_prep = prepare(df_raw)
    df, eng_features = engineer_features(df_prep)
    
    base_features = [
        "trend_regime_enc", "volatility_regime_enc", "break_distance_atr", 
        "candle_body_atr", "room_to_structure_atr", "recent_cross_count_16bars", "volume_ratio"
    ]
    
    # Define candidate models
    models = {
        "LR_Baseline": (base_features, Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.1, class_weight="balanced", random_state=42))
        ])),
        "LR_Engineered": (eng_features, Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.1, class_weight="balanced", random_state=42))
        ])),
        "GBT_Tuned": (base_features, GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.03,
            subsample=0.8, min_samples_leaf=20, random_state=42
        )),
        "GBT_Tuned_Engineered": (eng_features, GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.03,
            subsample=0.8, min_samples_leaf=20, random_state=42
        ))
    }
    
    print("=== Model Tuning Sweep (G1-D Dataset) ===")
    for name, (features, model) in models.items():
        print(f"\nModel: {name}")
        for fold in FOLDS:
            train, valid = fold_split(df, fold)
            
            X_tr = train[features].fillna(0).values
            y_tr = train["gross_gt30_72"].values.astype(int)
            X_va = valid[features].fillna(0).values
            y_va = valid["gross_gt30_72"].values.astype(int)
            rets = valid["gross_return_72"]
            
            model.fit(X_tr, y_tr)
            probs = model.predict_proba(X_va)[:, 1]
            sc = pd.Series(probs, index=valid.index)
            
            t5 = _econ_top(sc, rets, 0.05)
            t10 = _econ_top(sc, rets, 0.10)
            
            print(f"  Fold {fold['id']}: Top 5% EV = {t5.get('gross_ev_bps','?'):+6.2f} bps (n={t5.get('n')}) | Top 10% EV = {t10.get('gross_ev_bps','?'):+6.2f} bps")

if __name__ == "__main__":
    run_sweeps()
