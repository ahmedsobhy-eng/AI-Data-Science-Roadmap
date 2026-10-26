"""Train and evaluate a first time-split injury-risk baseline."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "prepared" / "player_season_injury_model_2019_2026_clean.csv"
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_FILE = MODEL_DIR / "injury_risk_logistic_baseline.joblib"
METRICS_FILE = MODEL_DIR / "baseline_model_metrics.csv"
PREDICTIONS_FILE = MODEL_DIR / "test_predictions_2024_2025.csv"
SPLIT_FILE = MODEL_DIR / "temporal_split_summary.csv"

NUMERIC_FEATURES = ["Age", "MP", "Starts", "Min"]
CATEGORICAL_FEATURES = ["Pos", "Nation"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "target_injured"
TRAIN_SEASONS = {"2019-2020", "2020-2021", "2021-2022", "2022-2023"}
VALIDATION_SEASON = "2023-2024"
TEST_SEASON = "2024-2025"


def make_pipeline() -> Pipeline:
    """Build preprocessing and logistic regression as one saved pipeline."""
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocessing = ColumnTransformer([
        ("numeric", numeric, NUMERIC_FEATURES),
        ("categorical", categorical, CATEGORICAL_FEATURES),
    ])
    return Pipeline([
        ("preprocess", preprocessing),
        ("model", LogisticRegression(
            class_weight="balanced",
            max_iter=3000,
            random_state=42,
        )),
    ])


def choose_balanced_threshold(y_true: pd.Series, probabilities: np.ndarray) -> float:
    """Choose the validation threshold that maximizes balanced accuracy."""
    thresholds = np.linspace(0.05, 0.95, 181)
    scores = [
        balanced_accuracy_score(y_true, probabilities >= threshold)
        for threshold in thresholds
    ]
    return float(thresholds[int(np.argmax(scores))])


def calculate_metrics(
    y_true: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
    split: str,
    model_name: str,
) -> dict[str, object]:
    """Calculate ranking and threshold-based classification metrics."""
    predictions = (probabilities >= threshold).astype("int8")
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    return {
        "split": split,
        "model": model_name,
        "threshold": round(threshold, 4),
        "rows": len(y_true),
        "positive_share_percent": round(float(y_true.mean() * 100), 2),
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y_true, probabilities)), 4),
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, predictions)), 4),
        "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 4),
        "f2": round(float(
            (5 * precision_score(y_true, predictions, zero_division=0)
             * recall_score(y_true, predictions, zero_division=0))
            / (4 * precision_score(y_true, predictions, zero_division=0)
               + recall_score(y_true, predictions, zero_division=0))
        ), 4) if (4 * precision_score(y_true, predictions, zero_division=0)
                  + recall_score(y_true, predictions, zero_division=0)) else 0.0,
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
    }


def main() -> None:
    if not DATA_FILE.is_file():
        raise FileNotFoundError(f"Clean model dataset not found: {DATA_FILE}")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    data = pd.read_csv(DATA_FILE, encoding="utf-8-sig", low_memory=False)
    required = set(FEATURES + [TARGET, "Season", "Player", "transfermarkt_player_id", "target_season"])
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Model dataset is missing columns: {missing}")
    if data[TARGET].isna().any() or not data[TARGET].isin([0, 1]).all():
        raise ValueError("The target must contain complete binary labels only")
    if data.duplicated(["transfermarkt_player_id", "Season"]).any():
        raise ValueError("Duplicate player-season records must be resolved before training")

    data["Season"] = data["Season"].astype(str).str.strip()
    train = data[data["Season"].isin(TRAIN_SEASONS)].copy()
    validation = data[data["Season"].eq(VALIDATION_SEASON)].copy()
    test = data[data["Season"].eq(TEST_SEASON)].copy()
    if train.empty or validation.empty or test.empty:
        raise ValueError("A required chronological split is empty; inspect available seasons")
    for label, part in [("train", train), ("validation", validation), ("test", test)]:
        if part[TARGET].nunique() != 2:
            raise ValueError(f"The {label} split must contain both target classes")

    # Tune the classification threshold on validation data, never on the held-out test season.
    threshold_model = make_pipeline()
    threshold_model.fit(train[FEATURES], train[TARGET].astype("int8"))
    validation_probabilities = threshold_model.predict_proba(validation[FEATURES])[:, 1]
    threshold = choose_balanced_threshold(
        validation[TARGET].astype("int8"), validation_probabilities
    )

    # Refit using all pre-test seasons while leaving the final season untouched.
    train_validation = pd.concat([train, validation], ignore_index=True)
    final_model = make_pipeline()
    final_model.fit(train_validation[FEATURES], train_validation[TARGET].astype("int8"))
    test_y = test[TARGET].astype("int8")
    test_probabilities = final_model.predict_proba(test[FEATURES])[:, 1]

    majority_probability = float(train_validation[TARGET].mean())
    all_positive_probability = np.full(len(test), majority_probability)
    metrics = [
        calculate_metrics(
            test_y,
            all_positive_probability,
            0.5,
            "test_2024-2025",
            "all_positive_reference",
        ),
        calculate_metrics(
            test_y,
            test_probabilities,
            0.5,
            "test_2024-2025",
            "logistic_threshold_0.50",
        ),
        calculate_metrics(
            test_y,
            test_probabilities,
            threshold,
            "test_2024-2025",
            "logistic_validation_balanced_accuracy_threshold",
        ),
        calculate_metrics(
            validation[TARGET].astype("int8"),
            validation_probabilities,
            threshold,
            "validation_2023-2024",
            "logistic_validation_balanced_accuracy_threshold",
        ),
    ]
    pd.DataFrame(metrics).to_csv(METRICS_FILE, index=False, encoding="utf-8-sig")

    test_predictions = test[
        ["Player", "transfermarkt_player_id", "Season", "target_season", TARGET]
    ].copy()
    test_predictions["predicted_injury_probability"] = test_probabilities
    test_predictions["predicted_injury_at_0_50"] = (test_probabilities >= 0.5).astype("int8")
    test_predictions["predicted_injury_at_validation_balanced_threshold"] = (
        test_probabilities >= threshold
    ).astype("int8")
    test_predictions.to_csv(PREDICTIONS_FILE, index=False, encoding="utf-8-sig")

    split_rows = []
    for split_name, frame in [
        ("train", train),
        ("validation", validation),
        ("final_train_including_validation", train_validation),
        ("test", test),
    ]:
        split_rows.append({
            "split": split_name,
            "seasons": ";".join(sorted(frame["Season"].unique())),
            "rows": len(frame),
            "positive_labels": int(frame[TARGET].sum()),
            "positive_share_percent": round(float(frame[TARGET].mean() * 100), 2),
        })
    pd.DataFrame(split_rows).to_csv(SPLIT_FILE, index=False, encoding="utf-8-sig")

    joblib.dump({
        "pipeline": final_model,
        "features": FEATURES,
        "target": TARGET,
        "threshold": threshold,
        "threshold_selection": "max validation balanced accuracy",
        "train_seasons": sorted(TRAIN_SEASONS),
        "validation_season": VALIDATION_SEASON,
        "test_season": TEST_SEASON,
    }, MODEL_FILE)

    print(f"Model saved: {MODEL_FILE}")
    print(f"Metrics saved: {METRICS_FILE}")
    print(f"Test predictions saved: {PREDICTIONS_FILE}")
    print(f"Temporal split summary saved: {SPLIT_FILE}")
    print(f"Validation-selected balanced-accuracy threshold: {threshold:.3f}")
    print(pd.DataFrame(metrics).to_string(index=False))


if __name__ == "__main__":
    main()
