"""Validate and clean the prepared player-season modeling table."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
PREPARED = PROJECT_ROOT / "data" / "prepared"
SOURCE = PREPARED / "player_season_injury_model_2019_2026.csv"
CLEAN = PREPARED / "player_season_injury_model_2019_2026_clean.csv"
AUDIT = PREPARED / "model_data_quality_audit.csv"

TEXT_COLUMNS = [
    "Player", "Nation", "Pos", "Team", "Season", "name_match_method",
    "target_season", "injury_history_scrape_status", "injury_history_scraped_at",
    "target_label_basis",
]
NUMERIC_COLUMNS = [
    "Age", "MP", "Starts", "Min", "transfermarkt_player_id", "target_injured",
    "target_injury_count", "target_days_out", "target_games_missed",
]
REQUIRED_COLUMNS = TEXT_COLUMNS + NUMERIC_COLUMNS
VALID_STATUSES = {"ok", "no_injuries"}


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Prepared model dataset not found: {SOURCE}")

    data = pd.read_csv(SOURCE, encoding="utf-8-sig", low_memory=False)
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(data.columns))
    if missing_columns:
        raise ValueError(f"Model dataset is missing required columns: {missing_columns}")
    data = data[REQUIRED_COLUMNS].copy()

    for column in TEXT_COLUMNS:
        data[column] = data[column].astype("string").str.strip()
        data[column] = data[column].replace("", pd.NA)

    for column in NUMERIC_COLUMNS:
        original_non_null = data[column].notna()
        data[column] = pd.to_numeric(data[column], errors="coerce")
        if (original_non_null & data[column].isna()).any():
            raise ValueError(f"Non-numeric values found in numeric column {column!r}")

    required_values = [
        "Player", "Team", "Season", "Age", "MP", "Starts", "Min",
        "transfermarkt_player_id", "target_injured", "target_injury_count",
        "injury_history_scrape_status",
    ]
    missing_required = data[required_values].isna().sum()
    if missing_required.any():
        raise ValueError(f"Required values are missing: {missing_required[missing_required > 0].to_dict()}")

    if not data["target_injured"].isin([0, 1]).all():
        raise ValueError("target_injured must contain only 0 or 1")
    if not data["injury_history_scrape_status"].isin(VALID_STATUSES).all():
        invalid_statuses = sorted(data.loc[
            ~data["injury_history_scrape_status"].isin(VALID_STATUSES),
            "injury_history_scrape_status",
        ].dropna().unique())
        raise ValueError(f"Unresolved injury-history statuses are in the model table: {invalid_statuses}")

    label_from_events = data["target_injury_count"].gt(0).astype("int8")
    if not data["target_injured"].astype("int8").eq(label_from_events).all():
        raise ValueError("target_injured disagrees with target_injury_count")
    if data.duplicated(["transfermarkt_player_id", "Season"]).any():
        raise ValueError("Duplicate player-season keys found")

    for column in ["Age", "MP", "Starts", "Min", "transfermarkt_player_id", "target_injured", "target_injury_count"]:
        data[column] = data[column].astype("Int64")

    data = data.sort_values(["Season", "transfermarkt_player_id"], kind="stable").reset_index(drop=True)
    audit_rows: list[dict[str, object]] = [
        {"check": "rows_in_clean_training_table", "value": len(data)},
        {"check": "unique_players", "value": data["transfermarkt_player_id"].nunique()},
        {"check": "duplicate_player_season_keys", "value": int(data.duplicated(["transfermarkt_player_id", "Season"]).sum())},
        {"check": "positive_injury_labels", "value": int(data["target_injured"].eq(1).sum())},
        {"check": "negative_injury_labels", "value": int(data["target_injured"].eq(0).sum())},
        {"check": "positive_label_share_percent", "value": round(float(data["target_injured"].mean() * 100), 2)},
        {"check": "rows_with_missing_nation", "value": int(data["Nation"].isna().sum())},
        {"check": "rows_with_multiple_team_names", "value": int(data["Team"].str.contains(";", regex=False, na=False).sum())},
        {"check": "target_duration_missing_is_retained", "value": int(data[["target_days_out", "target_games_missed"]].isna().any(axis=1).sum())},
        {"check": "earliest_feature_season", "value": data["Season"].min()},
        {"check": "latest_feature_season", "value": data["Season"].max()},
    ]
    for column in TEXT_COLUMNS + NUMERIC_COLUMNS:
        audit_rows.append({"check": f"missing_{column}", "value": int(data[column].isna().sum())})
    for season, group in data.groupby("Season", sort=True):
        audit_rows.extend([
            {"check": f"rows_{season}", "value": len(group)},
            {"check": f"positive_labels_{season}", "value": int(group["target_injured"].eq(1).sum())},
            {"check": f"positive_share_percent_{season}", "value": round(float(group["target_injured"].mean() * 100), 2)},
        ])

    data.to_csv(CLEAN, index=False, encoding="utf-8-sig")
    pd.DataFrame(audit_rows).to_csv(AUDIT, index=False, encoding="utf-8-sig")
    print(f"Clean modeling table saved: {CLEAN}")
    print(f"Data quality audit saved: {AUDIT}")
    print(f"Rows retained: {len(data):,}; seasons: {data['Season'].min()} to {data['Season'].max()}")
    print(f"Injury labels: {int(data['target_injured'].sum()):,} positive / {len(data) - int(data['target_injured'].sum()):,} negative")


if __name__ == "__main__":
    main()
