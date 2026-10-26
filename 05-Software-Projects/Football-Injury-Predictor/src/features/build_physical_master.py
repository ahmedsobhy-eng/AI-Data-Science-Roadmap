"""Build the cleaned 2019-2026 FBref physical-data master file."""

from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
HISTORICAL_FILE = DATA_RAW / "master_players_physical_data_historical_clean.csv"
RECENT_FILE = DATA_RAW / "master_players_physical_data_recent_clean.csv"
RECENT_LINKS = DATA_RAW / "top5_teams_links_recent.txt"
OUTPUT_FILE = DATA_RAW / "master_players_physical_data_2019_2026_clean.csv"
COLUMNS = ["Player", "Nation", "Pos", "Age", "MP", "Starts", "Min", "Team", "Season"]
INVALID = {"player", "squad total", "opponent total"}


def team_name(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) < 5 or parts[1] != "squads":
        raise ValueError(f"Invalid recent squad URL: {url}")
    return parts[4].removesuffix("-Stats").replace("-", " ").title()


def season_name(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[3]


def load_clean(path):
    if not path.is_file():
        raise FileNotFoundError(f"Required cleaned source is missing: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Unexpected columns in {path.name}: {sorted(missing)}")
    frame = frame[COLUMNS].copy()
    labels = frame["Player"].fillna("").astype(str).str.strip().str.casefold()
    frame = frame.loc[frame["Player"].notna() & ~labels.isin(INVALID)].copy()
    frame["Season"] = frame["Season"].astype(str).str.strip()
    frame["Team"] = frame["Team"].astype(str).str.strip()
    mp = pd.to_numeric(frame["MP"], errors="coerce")
    starts = pd.to_numeric(frame["Starts"], errors="coerce")
    unplayed = frame["Min"].isna() & mp.eq(0) & starts.eq(0)
    frame.loc[unplayed, "Min"] = 0
    return frame


def main():
    urls = [
        line.strip()
        for line in RECENT_LINKS.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    expected_pairs = {(season_name(url), team_name(url)) for url in urls}
    recent = load_clean(RECENT_FILE)
    available_pairs = set(zip(recent["Season"], recent["Team"]))
    missing_pairs = expected_pairs - available_pairs
    if missing_pairs:
        preview = sorted(missing_pairs)[:20]
        raise RuntimeError(
            f"Recent scrape is incomplete: {len(missing_pairs)} team-season pairs missing. "
            f"Examples: {preview}"
        )
    unexpected_pairs = available_pairs - expected_pairs
    if unexpected_pairs:
        recent = recent.loc[
            [(season, team) in expected_pairs for season, team in zip(recent.Season, recent.Team)]
        ].copy()

    historical = load_clean(HISTORICAL_FILE)
    combined = pd.concat([historical, recent], ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(["Player", "Team", "Season"], keep="first")
    combined = combined.sort_values(["Season", "Team", "Player"], kind="stable")
    combined.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    report = combined.groupby("Season").agg(
        player_team_season_rows=("Player", "size"),
        teams=("Team", "nunique"),
        missing_minutes=("Min", lambda values: int(values.isna().sum())),
    )
    print(f"Saved {OUTPUT_FILE}")
    print(f"Rows: {len(combined)}; duplicate keys removed: {before - len(combined)}")
    print(report.to_string())
    if unexpected_pairs:
        print(f"Out-of-scope recent pairs filtered: {len(unexpected_pairs)}")


if __name__ == "__main__":
    main()
