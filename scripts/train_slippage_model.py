#!/usr/bin/env python3
"""
scripts/train_slippage_model.py
Phase 10 – Sprint 10.8: ML Slippage Model v2

Trains a LightGBM regressor to predict slippage_bps from execution features.
Requires fill data collected from paper/live trading.

Usage:
    python scripts/train_slippage_model.py [--min-samples 100]
"""
import sys
import json
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


FEATURE_COLS = [
    "spread_bps_at_submit",
    "orderbook_imbalance_at_submit",
    "liquidity_score",
    "latency_ms",
    "intended_notional",
]
TARGET_COL = "total_slippage_bps"


def load_dataset(fills_dir: Path):
    records = []
    for f in sorted(fills_dir.glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("status") == "FILLED" and r.get("avg_fill_price", 0) > 0:
                        records.append(r)
                except Exception:
                    pass
    return records


def build_features(records):
    """Extract features and compute realized slippage target."""
    import numpy as np

    X_rows = []
    y_vals = []

    for r in records:
        dp = r.get("decision_price", 0.0)
        fp = r.get("avg_fill_price", 0.0)
        side = r.get("side", "BUY")
        if dp <= 0 or fp <= 0:
            continue

        is_buy = side.upper() in ("BUY", "LONG")
        sign = 1 if is_buy else -1
        realized_slip_bps = sign * (fp - dp) / dp * 10_000.0

        row = [
            r.get("spread_bps_at_submit", 0.0),
            r.get("orderbook_imbalance_at_submit", 0.0),
            r.get("liquidity_score", 0.5),
            r.get("latency_ms", 0),
            r.get("intended_notional", 0.0),
        ]
        X_rows.append(row)
        y_vals.append(max(0.0, realized_slip_bps))

    return X_rows, y_vals


def train(X, y, output_dir: Path):
    try:
        import numpy as np
        import lightgbm as lgb
        from sklearn.linear_model import Ridge
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        import joblib
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("   Install with: pip install lightgbm scikit-learn joblib")
        return

    X_arr = np.array(X)
    y_arr = np.array(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X_arr, y_arr, test_size=0.2, random_state=42
    )

    # Baseline: Ridge
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train)
    ridge_pred = ridge.predict(X_test)
    ridge_mae = mean_absolute_error(y_test, ridge_pred)
    print(f"  Ridge baseline — MAE: {ridge_mae:.3f} bps")

    # LightGBM
    model = lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.05, max_depth=6,
        num_leaves=31, min_child_samples=10, random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
    lgb_pred = model.predict(X_test)
    lgb_mae = mean_absolute_error(y_test, lgb_pred)
    lgb_rmse = np.sqrt(mean_squared_error(y_test, lgb_pred))
    sorted_pred = sorted(lgb_pred)
    p95_err = sorted_pred[int(len(sorted_pred) * 0.95)]
    print(f"  LightGBM — MAE: {lgb_mae:.3f} bps  RMSE: {lgb_rmse:.3f} bps  P95: {p95_err:.3f} bps")

    # Save model
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "slippage_model_v2.joblib"
    joblib.dump(model, model_path)

    # Save metadata
    meta = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "feature_cols": FEATURE_COLS,
        "lgbm_mae_bps": round(lgb_mae, 4),
        "lgbm_rmse_bps": round(lgb_rmse, 4),
        "lgbm_p95_bps": round(p95_err, 4),
        "ridge_mae_bps": round(ridge_mae, 4),
        "beats_baseline": lgb_mae < ridge_mae,
    }
    meta_path = output_dir / "slippage_model_v2.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\n✅ Model saved: {model_path}")
    print(f"   Metadata:    {meta_path}")
    if lgb_mae < ridge_mae:
        print("   ✅ LightGBM beats baseline!")
    else:
        print("   ⚠️  LightGBM did not beat baseline. More data may be needed.")

    return model_path


def main():
    parser = argparse.ArgumentParser(description="Train ML Slippage Model v2")
    parser.add_argument("--min-samples", type=int, default=50,
                        help="Minimum number of fill records required")
    parser.add_argument("--fills-dir", type=str,
                        default=str(REPO_ROOT / "data" / "execution" / "fills"))
    parser.add_argument("--output-dir", type=str,
                        default=str(REPO_ROOT))
    args = parser.parse_args()

    fills_dir = Path(args.fills_dir)
    output_dir = Path(args.output_dir)

    if not fills_dir.exists():
        print(f"❌ Fills directory not found: {fills_dir}")
        print("   Run paper execution to collect fill data first.")
        return

    print("Loading fill dataset...")
    records = load_dataset(fills_dir)
    print(f"  Found {len(records)} FILLED execution records")

    if len(records) < args.min_samples:
        print(f"⚠️  Only {len(records)} records found. Need at least {args.min_samples}.")
        print("   Run more paper executions before training the ML model.")
        return

    X, y = build_features(records)
    print(f"  Built dataset: {len(X)} samples × {len(FEATURE_COLS)} features")

    print("\nTraining slippage models...")
    train(X, y, output_dir)


if __name__ == "__main__":
    main()
