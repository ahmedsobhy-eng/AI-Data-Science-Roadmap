"""Build a conservative physical-injury cohort and compare temporal ML models."""

from __future__ import annotations

import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
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
PREPARED = PROJECT_ROOT / "data" / "prepared"
MODEL_DIR = PROJECT_ROOT / "models"
COHORT_FILE = PREPARED / "player_season_physical_injury_features.csv"
INJURY_FILE = PREPARED / "transfermarkt_injury_events_deduplicated.csv"
MODEL_FILE = MODEL_DIR / "club_physical_injury_risk_model.joblib"
TYPE_AUDIT_FILE = MODEL_DIR / "injury_type_classification_review.csv"
COHORT_AUDIT_FILE = MODEL_DIR / "physical_injury_cohort_audit.csv"
CV_METRICS_FILE = MODEL_DIR / "walk_forward_model_comparison.csv"
FINAL_METRICS_FILE = MODEL_DIR / "physical_injury_test_metrics.csv"
TEST_PREDICTIONS_FILE = MODEL_DIR / "physical_injury_test_predictions_2024_2025.csv"

NUMERIC_FEATURES = [
    "Age", "MP", "Starts", "Min",
    "prior_events_in_feature_season", "prior_events_last_3_seasons",
    "prior_events_career", "prior_physical_events_last_3_seasons",
    "prior_physical_events_career", "prior_muscle_events_last_3_seasons",
    "prior_muscle_events_career", "prior_lower_limb_events_last_3_seasons",
    "prior_lower_limb_events_career", "prior_days_out_before_feature_season",
    "prior_games_missed_before_feature_season", "prior_seasons_with_injury",
    "has_prior_injury_before_feature_season",
]
CATEGORICAL_FEATURES = ["Pos", "Nation"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "target_physical_injury"
VALIDATION_SEASONS = ["2021-2022", "2022-2023", "2023-2024"]
FINAL_TEST_SEASON = "2024-2025"

# Explicit illness, availability and administrative labels are not physical injuries.
NON_PHYSICAL_PATTERNS = [
    r"\bcorona\b", r"\bcovid\b", r"\bvirus\b", r"\binfluenza\b",
    r"\bflu\b", r"\bfever\b", r"\binfection\b", r"\bquarantine\b",
    r"\bill\b", r"\billness\b", r"\bsick\b", r"\bcold\b",
    r"\bfitness\b", r"\brest\b", r"\bsuspension\b", r"\bpersonal\b",
    r"\bnot in squad\b", r"\bpneumonia\b", r"\bbronchitis\b",
    r"\bmalaria\b", r"\bmononucleosis\b", r"\bcancer\b",
    r"\bdepression\b", r"\bangina\b", r"\bappendicitis\b",
    r"\bfood poisoning\b", r"\btoothache\b", r"\bstomach\b",
    r"\bappendectomy\b",
    r"\btuberculosis\b", r"\bmeningitis\b", r"\ballergic\b",
    r"\bchickenpox\b", r"\bskin disease\b", r"\bblood poisoning\b",
    r"\bheart condition\b", r"\brespiratory\b",
]
PHYSICAL_PATTERNS = [
    r"\binjury\b", r"\bproblem(s)?\b", r"\bpain\b", r"\bstrain\b",
    r"\btear\b", r"\btorn\b", r"\bfracture\b", r"\bbroken\b",
    r"\bsprain\b", r"\bbruise(d)?\b", r"\bcontusion\b", r"\bknock\b",
    r"\bsurgery\b", r"\bdislocation\b", r"\brupture(d)?\b", r"\btendon\b",
    r"\bligament\b", r"\bmuscle\b", r"\bhamstring\b", r"\bcalf\b",
    r"\badductor\b", r"\bthigh\b", r"\bknee\b", r"\bankle\b",
    r"\bgroin\b", r"\bback\b", r"\bfoot\b", r"\bshoulder\b",
    r"\bhip\b", r"\bleg\b", r"\bconcussion\b", r"\bdead leg\b",
    r"\bpubalgia\b", r"\bmeniscus\b", r"\blumbago\b", r"\brib(s)?\b",
    r"\bhand\b", r"\btoe\b", r"\bnose\b", r"\bneck\b", r"\barm\b",
    r"\belbow\b", r"\bwrist\b", r"\bfinger\b", r"\bbone\b",
    r"\bcartilage\b", r"\bcruciate\b", r"\bachilles\b", r"\bquadriceps\b",
    r"\bmetatarsal\b", r"\bfibula\b", r"\btibia\b", r"\bshin\b",
    r"\babdominal muscle(s)?\b", r"\bhead injury\b", r"\beye injury\b",
    r"\bmouth injury\b", r"\bchest injury\b", r"\bhernia\b",
    r"\bcontracture\b", r"\boverstretching\b", r"\bwound\b",
    r"\blaceration\b", r"\bbursitis\b", r"\btendinopathy\b",
    r"\bpinched nerve\b", r"\btraffic accident\b", r"\bpelvic contusion\b",
    r"\binflammation of pubic bone\b", r"\btesticle rupture\b",
    r"\bcollapsed lung\b", r"\bpneumothorax\b", r"\bcombustion\b",
    r"\binsect bite\b", r"\bremove screws\b",
]
NON_PHYSICAL_RE = re.compile("|".join(NON_PHYSICAL_PATTERNS), re.IGNORECASE)
PHYSICAL_RE = re.compile("|".join(PHYSICAL_PATTERNS), re.IGNORECASE)
MUSCLE_RE = re.compile(
    r"hamstring|muscle|calf|adductor|groin|thigh|quadriceps|achilles|tendon|"
    r"pubalgia|abdominal muscle|metatarsal", re.IGNORECASE,
)
LOWER_LIMB_RE = re.compile(
    r"hamstring|calf|adductor|groin|thigh|quadriceps|knee|ankle|foot|hip|leg|"
    r"achilles|meniscus|cruciate|metatarsal|fibula|tibia|shin", re.IGNORECASE,
)


def classify_injury_type(value: object) -> str:
    """Classify only clear physical/non-physical labels; keep uncertainty explicit."""
    text = "" if pd.isna(value) else str(value).strip()
    if not text or re.search(r"\bunknown\b", text, re.IGNORECASE):
        return "ambiguous"
    if NON_PHYSICAL_RE.search(text):
        return "non_physical"
    if PHYSICAL_RE.search(text):
        return "physical"
    return "ambiguous"


def build_injury_type_review(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize every source label and the rule-based class assigned to it."""
    counts = events.groupby("injury", dropna=False).agg(
        event_count=("player_id", "size"),
        days_out_known=("days_out", "count"),
        games_missed_known=("games_missed", "count"),
    ).reset_index()
    counts["assigned_class"] = counts["injury"].map(classify_injury_type)
    counts["review_note"] = counts["assigned_class"].map({
        "physical": "Included as an explicit physical injury event",
        "non_physical": "Excluded from physical-injury target",
        "ambiguous": "Not used as positive or negative without manual review",
    })
    return counts.sort_values(["assigned_class", "event_count"], ascending=[True, False])


def build_feature_cohort(model_data: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add past injury history using events no later than the feature season."""
    data = model_data.copy()
    data["Season"] = data["Season"].astype(str).str.strip()
    data["target_season"] = data["target_season"].astype(str).str.strip()
    data["feature_year"] = pd.to_numeric(data["Season"].str.slice(0, 4), errors="coerce").astype("Int64")
    data["target_year"] = pd.to_numeric(data["target_season"].str.slice(0, 4), errors="coerce").astype("Int64")

    events = events.copy()
    events["player_id"] = pd.to_numeric(events["player_id"], errors="coerce").astype("Int64")
    events["injury_year"] = pd.to_numeric(
        events["injury_season"].astype("string").str.extract(r"^(\d{4})")[0],
        errors="coerce",
    ).astype("Int64")
    events["days_out"] = pd.to_numeric(events["days_out"], errors="coerce")
    events["games_missed"] = pd.to_numeric(events["games_missed"], errors="coerce")
    events["assigned_class"] = events["injury"].map(classify_injury_type)
    events["is_muscle"] = events["injury"].fillna("").astype(str).map(lambda x: bool(MUSCLE_RE.search(x)))
    events["is_lower_limb"] = events["injury"].fillna("").astype(str).map(lambda x: bool(LOWER_LIMB_RE.search(x)))
    events = events.dropna(subset=["player_id", "injury_year"])
    events["player_id"] = events["player_id"].astype("int64")
    events["injury_year"] = events["injury_year"].astype("int64")

    # Outcome events are looked up by the following target season only.
    target_events = events.merge(
        data[["transfermarkt_player_id", "target_year"]].drop_duplicates(),
        left_on=["player_id", "injury_year"],
        right_on=["transfermarkt_player_id", "target_year"],
        how="inner",
    )
    outcome_summary = target_events.groupby(
        ["player_id", "injury_year"], as_index=False
    ).agg(
        target_physical_event_count=("assigned_class", lambda values: int(values.eq("physical").sum())),
        target_ambiguous_event_count=("assigned_class", lambda values: int(values.eq("ambiguous").sum())),
        target_non_physical_event_count=("assigned_class", lambda values: int(values.eq("non_physical").sum())),
    )
    outcome_summary = outcome_summary.rename(columns={
        "player_id": "transfermarkt_player_id",
        "injury_year": "target_year",
    })
    data = data.merge(
        outcome_summary,
        on=["transfermarkt_player_id", "target_year"],
        how="left",
        validate="one_to_one",
    )
    for column in ["target_physical_event_count", "target_ambiguous_event_count", "target_non_physical_event_count"]:
        data[column] = data[column].fillna(0).astype("int64")

    has_physical = data["target_physical_event_count"].gt(0)
    has_uncertainty = data["target_ambiguous_event_count"].gt(0)
    data[TARGET] = pd.Series(pd.NA, index=data.index, dtype="Int64")
    data.loc[has_physical, TARGET] = 1
    data.loc[~has_physical & ~has_uncertainty, TARGET] = 0
    data["target_label_quality"] = np.select(
        [has_physical, has_uncertainty],
        ["explicit_physical_positive", "ambiguous_target_excluded"],
        default="clear_negative_no_physical_event",
    )

    player_events = {
        int(player_id): group.sort_values("injury_year")
        for player_id, group in events.groupby("player_id", sort=False)
    }
    history_rows: list[dict[str, int]] = []
    for row in data[["transfermarkt_player_id", "feature_year"]].itertuples(index=False):
        player_id = int(row.transfermarkt_player_id)
        year = int(row.feature_year)
        player_history = player_events.get(player_id)
        if player_history is None:
            visible = events.iloc[0:0]
            completed = events.iloc[0:0]
        else:
            # Current feature-season counts are known before predicting next season.
            visible = player_history[player_history["injury_year"].le(year)]
            # Duration totals stop at prior seasons to avoid using a still-active
            # injury's eventual future recovery time as a predictor.
            completed = player_history[player_history["injury_year"].lt(year)]
        gaps = year - visible["injury_year"] if not visible.empty else pd.Series(dtype="int64")
        recent3 = visible.loc[gaps.ge(0) & gaps.lt(3)] if not visible.empty else visible
        completed_gaps = year - completed["injury_year"] if not completed.empty else pd.Series(dtype="int64")
        completed3 = completed.loc[completed_gaps.ge(1) & completed_gaps.le(3)] if not completed.empty else completed
        # No earlier events means zero missed days/games; if earlier events exist
        # but every duration is unknown, preserve NaN for the model imputer.
        prior_days_out = completed["days_out"].sum(min_count=1) if not completed.empty else 0
        prior_games_missed = completed["games_missed"].sum(min_count=1) if not completed.empty else 0
        history_rows.append({
            "prior_events_in_feature_season": int(visible["injury_year"].eq(year).sum()),
            "prior_events_last_3_seasons": int(len(recent3)),
            "prior_events_career": int(len(visible)),
            "prior_physical_events_last_3_seasons": int(recent3["assigned_class"].eq("physical").sum()),
            "prior_physical_events_career": int(visible["assigned_class"].eq("physical").sum()),
            "prior_muscle_events_last_3_seasons": int(recent3["is_muscle"].sum()),
            "prior_muscle_events_career": int(visible["is_muscle"].sum()),
            "prior_lower_limb_events_last_3_seasons": int(recent3["is_lower_limb"].sum()),
            "prior_lower_limb_events_career": int(visible["is_lower_limb"].sum()),
            "prior_days_out_before_feature_season": float(prior_days_out) if pd.notna(prior_days_out) else np.nan,
            "prior_games_missed_before_feature_season": float(prior_games_missed) if pd.notna(prior_games_missed) else np.nan,
            "prior_seasons_with_injury": int(completed["injury_year"].nunique()),
            "has_prior_injury_before_feature_season": int(not completed.empty),
        })
    history = pd.DataFrame(history_rows, index=data.index)
    data = pd.concat([data, history], axis=1)
    audit_rows = []
    for season, group in data.groupby("Season", sort=True):
        usable = group[TARGET].notna()
        audit_rows.append({
            "feature_season": season,
            "total_rows": len(group),
            "usable_clear_target_rows": int(usable.sum()),
            "ambiguous_target_rows_excluded": int((~usable).sum()),
            "clear_physical_positive": int(group[TARGET].eq(1).sum()),
            "clear_negative": int(group[TARGET].eq(0).sum()),
            "positive_share_in_usable_rows_percent": round(float(group.loc[usable, TARGET].mean() * 100), 2) if usable.any() else np.nan,
        })
    return data, pd.DataFrame(audit_rows)


def make_preprocessor() -> ColumnTransformer:
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32)),
    ])
    return ColumnTransformer([
        ("numeric", numeric, NUMERIC_FEATURES),
        ("categorical", categorical, CATEGORICAL_FEATURES),
    ])


def model_candidates() -> dict[str, object]:
    return {
        "logistic_regression": LogisticRegression(
            class_weight="balanced", C=0.5, max_iter=3000, random_state=42
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=350,
            min_samples_leaf=12,
            max_features=0.8,
            class_weight="balanced",
            # Keep one worker for reliable execution on Windows environments
            # where process/thread pool creation can be restricted.
            n_jobs=1,
            random_state=42,
        ),
    }


def make_pipeline(estimator: object) -> Pipeline:
    return Pipeline([
        ("preprocess", make_preprocessor()),
        ("model", estimator),
    ])


def metrics_for(y_true: pd.Series, probabilities: np.ndarray, threshold: float) -> dict[str, object]:
    predictions = (probabilities >= threshold).astype("int8")
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
    return {
        "rows": len(y_true),
        "positive_share_percent": round(float(y_true.mean() * 100), 2),
        "threshold": round(float(threshold), 4),
        "roc_auc": round(float(roc_auc_score(y_true, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y_true, probabilities)), 4),
        "brier_score": round(float(brier_score_loss(y_true, probabilities)), 4),
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, predictions)), 4),
        "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 4),
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
    }


def best_balanced_threshold(y_true: pd.Series, probabilities: np.ndarray) -> float:
    thresholds = np.linspace(0.05, 0.95, 181)
    scores = [balanced_accuracy_score(y_true, probabilities >= threshold) for threshold in thresholds]
    return float(thresholds[int(np.argmax(scores))])


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_data = pd.read_csv(
        PREPARED / "player_season_injury_model_2019_2026_clean.csv",
        encoding="utf-8-sig",
        low_memory=False,
    )
    source_events = pd.read_csv(INJURY_FILE, encoding="utf-8-sig", low_memory=False)
    source_events["assigned_class"] = source_events["injury"].map(classify_injury_type)
    type_review = build_injury_type_review(source_events)
    type_review.to_csv(TYPE_AUDIT_FILE, index=False, encoding="utf-8-sig")

    cohort, cohort_audit = build_feature_cohort(model_data, source_events)
    cohort.to_csv(COHORT_FILE, index=False, encoding="utf-8-sig")
    cohort_audit.to_csv(COHORT_AUDIT_FILE, index=False, encoding="utf-8-sig")

    labeled = cohort.loc[cohort[TARGET].notna()].copy()
    labeled[TARGET] = labeled[TARGET].astype("int8")
    labeled["feature_year"] = pd.to_numeric(labeled["Season"].str.slice(0, 4), errors="coerce").astype(int)
    test = labeled[labeled["Season"].eq(FINAL_TEST_SEASON)].copy()
    if test.empty or test[TARGET].nunique() != 2:
        raise ValueError("Final 2024-2025 physical-injury test cohort is missing a target class")

    fold_results: list[dict[str, object]] = []
    fold_probabilities: dict[tuple[str, str], tuple[pd.Index, np.ndarray]] = {}
    candidates = model_candidates()
    for validation_season in VALIDATION_SEASONS:
        validation = labeled[labeled["Season"].eq(validation_season)].copy()
        validation_year = int(validation_season[:4])
        fold_train = labeled[labeled["feature_year"].lt(validation_year)].copy()
        if validation.empty or validation[TARGET].nunique() != 2 or fold_train[TARGET].nunique() != 2:
            continue
        for model_name, estimator in candidates.items():
            pipeline = make_pipeline(estimator)
            pipeline.fit(fold_train[FEATURES], fold_train[TARGET])
            probabilities = pipeline.predict_proba(validation[FEATURES])[:, 1]
            fold_probabilities[(model_name, validation_season)] = (
                validation.index.copy(), probabilities
            )
            row = {
                "model": model_name,
                "validation_season": validation_season,
                "training_seasons": ";".join(sorted(fold_train["Season"].unique())),
            }
            row.update(metrics_for(validation[TARGET], probabilities, 0.5))
            fold_results.append(row)

    fold_metrics = pd.DataFrame(fold_results)
    if fold_metrics.empty:
        raise ValueError("No valid forward-chaining validation folds could be built")
    fold_metrics.to_csv(CV_METRICS_FILE, index=False, encoding="utf-8-sig")
    ranking = fold_metrics.groupby("model").agg(
        mean_validation_average_precision=("average_precision", "mean"),
        mean_validation_roc_auc=("roc_auc", "mean"),
        mean_validation_balanced_accuracy=("balanced_accuracy", "mean"),
        evaluated_folds=("validation_season", "nunique"),
    ).sort_values(
        ["mean_validation_average_precision", "mean_validation_balanced_accuracy"],
        ascending=False,
    )
    selected_name = str(ranking.index[0])

    # Choose the operating threshold only from selected-model walk-forward
    # predictions; the final test season is never used for model/threshold choice.
    oof_parts = []
    for validation_season in VALIDATION_SEASONS:
        item = fold_probabilities.get((selected_name, validation_season))
        if item is None:
            continue
        indices, probabilities = item
        oof_parts.append(pd.DataFrame({
            "target": labeled.loc[indices, TARGET].to_numpy(),
            "probability": probabilities,
        }))
    oof = pd.concat(oof_parts, ignore_index=True)
    threshold = best_balanced_threshold(oof["target"], oof["probability"].to_numpy())

    final_train = labeled[labeled["feature_year"].lt(int(FINAL_TEST_SEASON[:4]))].copy()
    final_model = make_pipeline(model_candidates()[selected_name])
    final_model.fit(final_train[FEATURES], final_train[TARGET])
    test_y = test[TARGET].astype("int8")
    test_probabilities = final_model.predict_proba(test[FEATURES])[:, 1]
    prevalence = float(final_train[TARGET].mean())
    metrics = [
        {"model": "all_positive_reference", "split": "test_2024-2025", **metrics_for(
            test_y, np.full(len(test), prevalence), 0.5
        )},
        {"model": selected_name, "split": "test_2024-2025_threshold_0.50", **metrics_for(
            test_y, test_probabilities, 0.5
        )},
        {"model": selected_name, "split": "test_2024-2025_walk_forward_balanced_threshold", **metrics_for(
            test_y, test_probabilities, threshold
        )},
        {"model": selected_name, "split": "walk_forward_validation_oof", **metrics_for(
            oof["target"].astype("int8"), oof["probability"].to_numpy(), threshold
        )},
    ]
    pd.DataFrame(metrics).to_csv(FINAL_METRICS_FILE, index=False, encoding="utf-8-sig")

    prediction_columns = [
        "Player", "transfermarkt_player_id", "Season", "target_season",
        "target_injured", TARGET, "target_label_quality",
        "target_physical_event_count", "target_ambiguous_event_count",
    ]
    predictions = test[prediction_columns].copy()
    predictions["physical_injury_probability"] = test_probabilities
    predictions["predicted_physical_injury_at_0_50"] = (test_probabilities >= 0.5).astype("int8")
    predictions["predicted_physical_injury_at_walk_forward_threshold"] = (
        test_probabilities >= threshold
    ).astype("int8")
    predictions.to_csv(TEST_PREDICTIONS_FILE, index=False, encoding="utf-8-sig")

    joblib.dump({
        "pipeline": final_model,
        "model_name": selected_name,
        "features": FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "target": TARGET,
        "threshold": threshold,
        "threshold_selection": "maximum balanced accuracy on selected-model walk-forward validation predictions",
        "training_seasons": sorted(final_train["Season"].unique()),
        "test_season": FINAL_TEST_SEASON,
        "injury_history_cutoff": "events through the feature season; no event from the target season is used",
        "outcome_definition": "at least one explicitly classified physical Transfermarkt injury event in the following season; ambiguous-only outcomes excluded",
    }, MODEL_FILE)

    print("Injury type counts by class:")
    print(type_review.groupby("assigned_class")["event_count"].sum().to_string())
    print("\nModel cohort by season:")
    print(cohort_audit.to_string(index=False))
    print("\nWalk-forward model ranking (higher average precision is better):")
    print(ranking.round(4).to_string())
    print(f"\nSelected model: {selected_name}; validation threshold: {threshold:.3f}")
    print("\nHeld-out test metrics:")
    print(pd.DataFrame(metrics).to_string(index=False))
    print(f"\nModel: {MODEL_FILE}")
    print(f"Feature cohort: {COHORT_FILE}")


if __name__ == "__main__":
    main()
