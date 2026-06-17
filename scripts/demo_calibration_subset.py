import json
import sys
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import brier_score_loss, roc_auc_score, accuracy_score

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from btc_scraper.ml_engine.feature_extractor import records_to_dataset

BASE = Path(__file__).parent.parent
INPUT = BASE / "logs" / "adaptive_signals_v2.json"


def compute_calibration_buckets(probs, labels, min_samples=10):
    bins = {
        "0.0-0.4": [],
        "0.4-0.6": [],
        "0.6-0.7": [],
        "0.7-0.8": [],
        "0.8-1.0": [],
    }
    for p, y in zip(probs, labels):
        if p < 0.4:
            bins["0.0-0.4"].append(y)
        elif p < 0.6:
            bins["0.4-0.6"].append(y)
        elif p < 0.7:
            bins["0.6-0.7"].append(y)
        elif p < 0.8:
            bins["0.7-0.8"].append(y)
        else:
            bins["0.8-1.0"].append(y)
    result = {}
    for name, ys in bins.items():
        if len(ys) < min_samples:
            result[name] = {
                "count": len(ys),
                "actual_wr": None,
                "predicted_wr": None,
                "calibration_error": None,
                "calibrated": False,
            }
            continue
        wins = sum(ys)
        actual_wr = wins / len(ys) * 100
        lo, hi = map(float, name.split("-"))
        predicted_wr = (lo + hi) / 2 * 100
        error = actual_wr - predicted_wr
        result[name] = {
            "count": len(ys),
            "wins": wins,
            "losses": len(ys) - wins,
            "actual_wr": round(actual_wr, 1),
            "predicted_wr": round(predicted_wr, 1),
            "calibration_error": round(error, 1),
            "calibrated": abs(error) <= 10.0,
        }
    return result


def load_dataset():
    with open(INPUT, "r", encoding="utf-8") as f:
        records = json.load(f)
    X, y, feature_names = records_to_dataset(records)
    return X, y, feature_names


def main():
    X, y, feature_names = load_dataset()
    if len(y) < 200:
        raise SystemExit("Dataset quá nhỏ để demo calibration tốt.")

    # 1) Split train/calib/test
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.30, random_state=42, stratify=y
    )
    X_calib, X_test, y_calib, y_test = train_test_split(
        X_temp, y_temp, test_size=0.50, random_state=42, stratify=y_temp
    )

    print(f"Train: {len(y_train)}, Calib: {len(y_calib)}, Test: {len(y_test)}\n")

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)
    raw_probs_test = clf.predict_proba(X_test)[:, 1]

    # === UNCALIBRATED ===
    print("=== UNCALIBRATED ===")
    preds = (raw_probs_test >= 0.5).astype(int)
    print(f"ROC AUC: {roc_auc_score(y_test, raw_probs_test):.4f}")
    print(f"Accuracy: {accuracy_score(y_test, preds):.4f}")
    print(f"Brier score: {brier_score_loss(y_test, raw_probs_test):.4f}")
    buckets_raw = compute_calibration_buckets(raw_probs_test, y_test)
    mean_error_raw = sum(abs(s["calibration_error"]) for s in buckets_raw.values() 
                         if s["calibration_error"] is not None) / len([s for s in buckets_raw.values() 
                         if s["calibration_error"] is not None])
    print(f"Mean calibration error: {mean_error_raw:.2f}\n")

    # === SIGMOID CALIBRATION ===
    print("=== SIGMOID CALIBRATION ===")
    sig_clf = LogisticRegression(solver="liblinear", random_state=42)
    calib_probs_sigmoid = clf.predict_proba(X_calib)[:, 1].reshape(-1, 1)
    sig_clf.fit(calib_probs_sigmoid, y_calib)
    
    raw_probs_test_reshaped = raw_probs_test.reshape(-1, 1)
    probs_sig = sig_clf.predict_proba(raw_probs_test_reshaped)[:, 1]
    preds_sig = (probs_sig >= 0.5).astype(int)
    
    print(f"ROC AUC: {roc_auc_score(y_test, probs_sig):.4f}")
    print(f"Accuracy: {accuracy_score(y_test, preds_sig):.4f}")
    print(f"Brier score: {brier_score_loss(y_test, probs_sig):.4f}")
    buckets_sig = compute_calibration_buckets(probs_sig, y_test)
    mean_error_sig = sum(abs(s["calibration_error"]) for s in buckets_sig.values() 
                         if s["calibration_error"] is not None) / len([s for s in buckets_sig.values() 
                         if s["calibration_error"] is not None])
    print(f"Mean calibration error: {mean_error_sig:.2f}\n")

    # === ISOTONIC CALIBRATION ===
    print("=== ISOTONIC CALIBRATION ===")
    from sklearn.isotonic import IsotonicRegression
    iso_clf = IsotonicRegression(out_of_bounds="clip")
    calib_probs_iso = clf.predict_proba(X_calib)[:, 1]
    iso_clf.fit(calib_probs_iso, y_calib)
    probs_iso = iso_clf.predict(raw_probs_test)
    preds_iso = (probs_iso >= 0.5).astype(int)
    
    print(f"ROC AUC: {roc_auc_score(y_test, probs_iso):.4f}")
    print(f"Accuracy: {accuracy_score(y_test, preds_iso):.4f}")
    print(f"Brier score: {brier_score_loss(y_test, probs_iso):.4f}")
    buckets_iso = compute_calibration_buckets(probs_iso, y_test)
    mean_error_iso = sum(abs(s["calibration_error"]) for s in buckets_iso.values() 
                         if s["calibration_error"] is not None) / len([s for s in buckets_iso.values() 
                         if s["calibration_error"] is not None])
    print(f"Mean calibration error: {mean_error_iso:.2f}\n")

    # === COMPARISON ===
    print("=== COMPARISON ===")
    print(f"{'Method':<20} {'Mean Cal Error':<20} {'Brier':<15} {'Rank'}")
    print("-" * 65)
    methods = [
        ("Uncalibrated", mean_error_raw, brier_score_loss(y_test, raw_probs_test)),
        ("Sigmoid", mean_error_sig, brier_score_loss(y_test, probs_sig)),
        ("Isotonic", mean_error_iso, brier_score_loss(y_test, probs_iso)),
    ]
    sorted_methods = sorted(methods, key=lambda x: x[1])
    for rank, (name, cal_err, brier) in enumerate(sorted_methods, 1):
        print(f"{name:<20} {cal_err:<20.4f} {brier:<15.4f} #{rank}")

    best_method = sorted_methods[0][0]
    print(f"\n✓ Best method (by mean calibration error): {best_method}")

if __name__ == "__main__":
    main()
