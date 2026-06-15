import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# Mock data
np.random.seed(42)
feature_names = [f"f_{i}" for i in range(10)]
# Create some highly correlated features
X = np.random.rand(200, 10)
X[:, 1] = X[:, 0] * 0.99 + np.random.rand(200) * 0.01  # f_1 highly correlated with f_0
y = np.random.randint(0, 2, size=200)

split_idx = 160
X_train, X_holdout = X[:split_idx], X[split_idx:]
y_train, y_holdout = y[:split_idx], y[split_idx:]

# 1. Feature Correlation Check
df_train = pd.DataFrame(X_train, columns=feature_names)
corr_matrix = df_train.corr(method="spearman").abs()
upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
to_drop = [column for column in upper.columns if any(upper[column] > 0.85)]

selected_features = [f for f in feature_names if f not in to_drop]
print(f"[Correlation] Drop {len(to_drop)} features: {to_drop}")

sel_indices = [feature_names.index(f) for f in selected_features]
X_train_sel = X_train[:, sel_indices]
X_holdout_sel = X_holdout[:, sel_indices]
X_sel = X[:, sel_indices]

print(f"X_train_sel shape: {X_train_sel.shape}")

# 2. Hyperparameter Tuning with Optuna
def objective(trial):
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 10, 50, step=10),
        "max_depth": trial.suggest_int("max_depth", 3, 5),
        "min_samples_leaf": trial.suggest_int("min_samples_leaf", 3, 5),
        "class_weight": "balanced",
        "random_state": 42,
        "n_jobs": -1,
    }
    model = RandomForestClassifier(**params)
    tscv = TimeSeriesSplit(n_splits=3)
    scores = cross_val_score(model, X_train_sel, y_train, cv=tscv, scoring="roc_auc")
    return scores.mean()

print("[Optuna] Start optimization...")
study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=2)
print(f"[Optuna] Best params: {study.best_params}")
