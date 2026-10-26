"""Fit the validated model on all known seasons and rank the latest player cohort.

The output is a club-facing screening list, not a medical diagnosis. Features are
season-level FBref workloads and Transfermarkt injury history; no GPS or daily
training data is available in this project yet.
"""

from __future__ import annotations

import re
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "features"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_injury_physical_dataset import (
    aggregate_player_seasons,
    prepare_physical,
    read_csv,
    resolve_player_ids,
)
from train_injury_risk_model import (
    FEATURES,
    MODEL_DIR,
    TARGET,
    build_feature_cohort,
    make_pipeline,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
PREPARED = PROJECT_ROOT / "data" / "prepared"
MODEL_DIR = PROJECT_ROOT / "models"
PHYSICAL_FILE = DATA_RAW / "master_players_physical_data_2019_2026_clean.csv"
ROSTERS_FILE = DATA_RAW / "transfermarkt_player_rosters_2019_present.csv"
INJURIES_FILE = PREPARED / "transfermarkt_injury_events_deduplicated.csv"
LABELED_COHORT_FILE = PREPARED / "player_season_physical_injury_features.csv"
DEPLOYMENT_MODEL_FILE = MODEL_DIR / "club_physical_injury_risk_model_for_2026_2027.joblib"
RISK_OUTPUT_FILE = PREPARED / "club_risk_screen_2026_2027.csv"
MATCH_REVIEW_FILE = PREPARED / "club_risk_screen_player_match_review.csv"
VALIDATED_MODEL_FILE = MODEL_DIR / "club_physical_injury_risk_model.joblib"

PHYSICAL_COLUMNS = ["Player", "Nation", "Pos", "Age", "MP", "Starts", "Min", "Team", "Season"]
ROSTER_COLUMNS = ["player_id", "player", "team", "roster_season"]
INJURY_COLUMNS = ["player_id", "injury_season", "injury", "days_out", "games_missed"]
VALIDATION_LIMIT = "2024-2025"


def next_season(season: str) -> str:
    """Return the season immediately after an input season."""
    match = re.fullmatch(r"(\d{4})-(\d{4})", season)
    if not match:
        raise ValueError(f"Unexpected season label: {season!r}")
    start, end = map(int, match.groups())
    return f"{start + 1}-{end + 1}"


def main() -> None:
    """Create a deployable full-history model and a ranked next-season list."""
    model_metadata = joblib.load(VALIDATED_MODEL_FILE)
    if model_metadata["model_name"] != "logistic_regression":
        raise ValueError("Selected model changed; update this scoring script before deployment.")

    # Fit the chosen model on all labeled seasons only after historical evaluation.
    labeled = pd.read_csv(LABELED_COHORT_FILE, encoding="utf-8-sig", low_memory=False)
    labeled = labeled.loc[labeled[TARGET].notna()].copy()
    labeled = labeled.loc[labeled["Season"].le(VALIDATION_LIMIT)].copy()
    labeled[TARGET] = labeled[TARGET].astype("int8")
    final_model = make_pipeline(LogisticRegression(
        class_weight="balanced", C=0.5, max_iter=3000, random_state=42
    ))
    final_model.fit(labeled[FEATURES], labeled[TARGET])

    # Resolve current-season FBref players to stable Transfermarkt IDs conservatively.
    physical = read_csv(PHYSICAL_FILE, PHYSICAL_COLUMNS)
    physical = prepare_physical(physical)
    latest_season = str(physical["Season"].dropna().max())
    if latest_season != "2025-2026":
        raise ValueError(f"Expected current physical season 2025-2026, found {latest_season!r}")
    current_physical = physical.loc[physical["Season"].eq(latest_season)].copy()
    rosters = read_csv(ROSTERS_FILE, ROSTER_COLUMNS)
    mapped, _ = resolve_player_ids(current_physical, rosters)
    match_review = mapped.loc[mapped["transfermarkt_player_id"].isna(), [
        "Player", "Team", "Season", "name_match_method", "candidate_transfermarkt_ids",
        "match_review_reason",
    ]].copy()
    match_review.to_csv(MATCH_REVIEW_FILE, index=False, encoding="utf-8-sig")

    mapped = mapped.dropna(subset=["transfermarkt_player_id"])
    current_model_data = aggregate_player_seasons(mapped)
    target_season = next_season(latest_season)
    current_model_data["target_season"] = target_season
    events = read_csv(INJURIES_FILE, INJURY_COLUMNS)
    current_features, _ = build_feature_cohort(current_model_data, events)

    # Do not expose target labels: the current season's injury-history scrape may
    # be incomplete, so target events are deliberately absent from this report.
    scores = final_model.predict_proba(current_features[FEATURES])[:, 1]
    report_columns = [
        "Player", "transfermarkt_player_id", "Team", "Season", "Age", "Pos",
        "MP", "Starts", "Min", "prior_physical_events_last_3_seasons",
        "prior_days_out_before_feature_season", "prior_games_missed_before_feature_season",
        "has_prior_injury_before_feature_season", "name_match_method",
    ]
    report = current_features[report_columns].copy()
    report.insert(4, "target_season", target_season)
    report["risk_score_0_100_uncalibrated"] = (scores * 100).round(1)
    report["screening_flag_at_validated_threshold"] = (
        scores >= float(model_metadata["threshold"])
    )
    report["threshold_used"] = float(model_metadata["threshold"])
    report["model_scope"] = "season-level physical injury event in the following season"
    report["score_interpretation"] = "Use for relative screening priority only; not a calibrated medical probability."
    report = report.sort_values(
        ["risk_score_0_100_uncalibrated", "Min"], ascending=[False, False], kind="stable"
    )
    report.to_csv(RISK_OUTPUT_FILE, index=False, encoding="utf-8-sig")

    joblib.dump({
        **model_metadata,
        "pipeline": final_model,
        "training_seasons": sorted(labeled["Season"].unique()),
        "fit_rows": int(len(labeled)),
        "prediction_feature_season": latest_season,
        "prediction_target_season": target_season,
        "deployment_note": "Screening support only; not a clinical diagnosis or live daily warning.",
    }, DEPLOYMENT_MODEL_FILE)

    matched_count = len(current_model_data)
    print(f"Model fitted on {len(labeled):,} labeled player-seasons through {VALIDATION_LIMIT}.")
    print(f"Players scored for {target_season}: {matched_count:,}; unresolved FBref rows: {len(match_review):,}.")
    print(f"Ranked club screening list: {RISK_OUTPUT_FILE}")
    print(f"Unmatched player review: {MATCH_REVIEW_FILE}")
    print(f"Full-history model: {DEPLOYMENT_MODEL_FILE}")


if __name__ == "__main__":
    main()
