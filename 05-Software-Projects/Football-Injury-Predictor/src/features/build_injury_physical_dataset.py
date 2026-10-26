"""Build conservative, season-level joins between FBref and Transfermarkt data.

This script never changes the scraped source CSVs. It writes prepared datasets
and a review file to ``prepared_data/``. Injury history pages do not say which
club a player represented on each injury date, so the output keeps the injury
label at player-season level and does not invent an injury team.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "prepared"
PHYSICAL_FILE = DATA_RAW / "master_players_physical_data_2019_2026_clean.csv"
PHYSICAL_BACKFILL_FILE = OUTPUT_DIR / "fbref_backfill_2021_2022.csv"
INJURIES_FILE = DATA_RAW / "transfermarkt_injuries_2019_present.csv"
ROSTERS_FILE = DATA_RAW / "transfermarkt_player_rosters_2019_present.csv"
PLAYER_STATUS_FILE = DATA_RAW / "transfermarkt_player_injury_status.csv"

PHYSICAL_COLUMNS = [
    "Player", "Nation", "Pos", "Age", "MP", "Starts", "Min", "Team", "Season"
]
INJURY_COLUMNS = [
    "player_id", "player", "injury_season", "injury", "date_from", "date_until",
    "days_out", "games_missed", "profile_url", "injury_url",
]
ROSTER_COLUMNS = ["player_id", "player", "team", "roster_season"]
STATUS_COLUMNS = ["player_id", "player", "status", "injury_count", "scraped_at", "error"]
HISTORICAL_LINKS_FILE = DATA_RAW / "top5_teams_links_5years.txt"
RECENT_LINKS_FILE = DATA_RAW / "top5_teams_links_recent.txt"
SUCCESS_STATUSES = {"ok", "no_injuries"}
INVALID_PLAYER_NAMES = {"", "player", "squadtotal", "opponenttotal"}


def read_csv(path: Path, required_columns: list[str]) -> pd.DataFrame:
    """Read one source CSV and stop with a clear message if its schema changed."""
    if not path.is_file():
        raise FileNotFoundError(f"Required source file is missing: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    return frame


def clean_text(value: object) -> str:
    """Normalize accents, case, punctuation and spaces for conservative matching."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def clean_team_tokens(value: object) -> set[str]:
    """Return meaningful club-name tokens used only to resolve name collisions."""
    if pd.isna(value):
        return set()
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    tokens = set(re.findall(r"[a-z0-9]+", text.casefold()))
    return tokens - {"fc", "cf", "sc", "ac", "as", "ss", "us", "cd", "sd", "club"}


def team_similarity(physical_team: str, roster_team: str) -> float:
    """Score shared club-name tokens; this is never used to match a player alone."""
    left = clean_team_tokens(physical_team)
    right = clean_team_tokens(roster_team)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def season_after(season: str) -> str:
    """Convert a season such as 2023-2024 to its following season."""
    match = re.fullmatch(r"(\d{4})-(\d{4})", str(season).strip())
    if not match:
        raise ValueError(f"Unexpected season format: {season!r}")
    start, end = map(int, match.groups())
    return f"{start + 1}-{end + 1}"


def latest_completed_season(today: date | None = None) -> str:
    """Return the most recently finished European football season."""
    today = today or date.today()
    current_start_year = today.year if today.month >= 7 else today.year - 1
    return f"{current_start_year - 1}-{current_start_year}"


def expected_team_season_links() -> tuple[dict[tuple[str, str], str], list[str]]:
    """Read versioned FBref squad links and return their expected season-team keys."""
    pairs: dict[tuple[str, str], str] = {}
    invalid_links: list[str] = []
    for path in (HISTORICAL_LINKS_FILE, RECENT_LINKS_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"Required FBref team link list is missing: {path}")
        for raw_url in path.read_text(encoding="utf-8-sig").splitlines():
            url = raw_url.strip()
            if not url:
                continue
            parts = [part for part in urlparse(url).path.split("/") if part]
            if len(parts) < 5 or parts[1] != "squads":
                invalid_links.append(url)
                continue
            season = parts[3]
            team_slug = parts[4].removesuffix("-Stats")
            pairs[(season, clean_text(team_slug))] = url
    return pairs, invalid_links


def prepare_physical(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep valid player rows and prepare name keys without altering source names."""
    frame = frame[PHYSICAL_COLUMNS].copy()
    frame["Player"] = frame["Player"].fillna("").astype(str).str.strip()
    frame = frame[~frame["Player"].map(lambda name: clean_text(name) in INVALID_PLAYER_NAMES)].copy()
    frame["Season"] = frame["Season"].fillna("").astype(str).str.strip()
    frame["_name_key"] = frame["Player"].map(clean_text)
    frame["_season_key"] = frame["Season"]
    for column in ("Age", "MP", "Starts", "Min"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def resolve_player_ids(physical: pd.DataFrame, rosters: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match exact normalized player-season names, using club only for collisions."""
    roster = rosters[ROSTER_COLUMNS].copy()
    roster["player_id"] = pd.to_numeric(roster["player_id"], errors="coerce")
    roster = roster.dropna(subset=["player_id"]).copy()
    roster["player_id"] = roster["player_id"].astype("int64")
    roster["_name_key"] = roster["player"].map(clean_text)
    roster["_season_key"] = roster["roster_season"].fillna("").astype(str).str.strip()

    candidates: dict[tuple[str, str], dict[int, tuple[str, ...]]] = {}
    for key, rows in roster.groupby(["_name_key", "_season_key"], sort=False):
        candidate_teams: dict[int, tuple[str, ...]] = {}
        for player_id, player_rows in rows.groupby("player_id", sort=False):
            candidate_teams[int(player_id)] = tuple(
                player_rows["team"].dropna().astype(str).drop_duplicates().tolist()
            )
        candidates[key] = candidate_teams

    resolved_ids: list[object] = []
    methods: list[str] = []
    candidate_text: list[str] = []
    review_reasons: list[str] = []

    rows_to_match = zip(
        physical["_name_key"].tolist(),
        physical["_season_key"].tolist(),
        physical["Team"].tolist(),
    )
    for name_key, season_key, physical_team in rows_to_match:
        key = (name_key, season_key)
        options = candidates.get(key)
        if not options:
            resolved_ids.append(pd.NA)
            methods.append("unmatched")
            candidate_text.append("")
            review_reasons.append("no_exact_name_and_season_match")
            continue

        ids = sorted(options)
        candidate_text.append(";".join(map(str, ids)))
        if len(ids) == 1:
            resolved_ids.append(ids[0])
            methods.append("unique_name_and_season")
            review_reasons.append("")
            continue

        scores = []
        for player_id in ids:
            score = max((team_similarity(physical_team, team) for team in options[player_id]), default=0.0)
            scores.append((score, player_id))
        scores.sort(reverse=True)
        best_score = scores[0][0]
        second_score = scores[1][0]
        if best_score >= 0.5 and best_score - second_score >= 0.2:
            resolved_ids.append(scores[0][1])
            methods.append("name_season_then_distinctive_team_match")
            review_reasons.append("")
        else:
            resolved_ids.append(pd.NA)
            methods.append("ambiguous")
            review_reasons.append("multiple_players_share_name_and_season")

    result = physical.copy()
    result["transfermarkt_player_id"] = pd.array(resolved_ids, dtype="Int64")
    result["name_match_method"] = methods
    result["candidate_transfermarkt_ids"] = candidate_text
    result["match_review_reason"] = review_reasons
    return result, roster


def aggregate_player_seasons(mapped: pd.DataFrame) -> pd.DataFrame:
    """Combine transfers within a season so each player-season appears once."""
    matched = mapped.dropna(subset=["transfermarkt_player_id"]).copy()
    matched["transfermarkt_player_id"] = matched["transfermarkt_player_id"].astype("int64")

    def join_unique(values: pd.Series) -> str:
        return "; ".join(sorted({str(value).strip() for value in values.dropna() if str(value).strip()}))

    def first_value(values: pd.Series) -> object:
        nonempty = values.dropna()
        return nonempty.iloc[0] if not nonempty.empty else pd.NA

    grouped = matched.groupby(["transfermarkt_player_id", "Season"], as_index=False, sort=True).agg(
        Player=("Player", first_value),
        Nation=("Nation", join_unique),
        Pos=("Pos", join_unique),
        Age=("Age", "max"),
        MP=("MP", lambda values: values.sum(min_count=1)),
        Starts=("Starts", lambda values: values.sum(min_count=1)),
        Min=("Min", lambda values: values.sum(min_count=1)),
        Team=("Team", join_unique),
        name_match_method=("name_match_method", join_unique),
    )
    return grouped


def deduplicate_events(events: pd.DataFrame) -> pd.DataFrame:
    """Remove exact repeated injury rows while preserving distinct episodes."""
    events = events[INJURY_COLUMNS].copy()
    events["player_id"] = pd.to_numeric(events["player_id"], errors="coerce")
    events = events.dropna(subset=["player_id"]).copy()
    events["player_id"] = events["player_id"].astype("int64")
    for column in ("injury_season", "injury", "date_from", "date_until"):
        events[column] = events[column].fillna("").astype(str).str.strip()
    events["_injury_key"] = events["injury"].map(clean_text)
    events = events.drop_duplicates(
        ["player_id", "injury_season", "_injury_key", "date_from", "date_until"], keep="first"
    ).copy()
    events["days_out"] = pd.to_numeric(events["days_out"], errors="coerce")
    events["games_missed"] = pd.to_numeric(events["games_missed"], errors="coerce")
    return events


def latest_player_status(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest scrape result per Transfermarkt player ID."""
    status = frame[STATUS_COLUMNS].copy()
    status["player_id"] = pd.to_numeric(status["player_id"], errors="coerce")
    status = status.dropna(subset=["player_id"]).copy()
    status["player_id"] = status["player_id"].astype("int64")
    status["scraped_at"] = pd.to_datetime(status["scraped_at"], errors="coerce")
    return status.sort_values("scraped_at", kind="stable").drop_duplicates("player_id", keep="last")


def main() -> None:
    physical_source = read_csv(PHYSICAL_FILE, PHYSICAL_COLUMNS)
    backfill_rows = 0
    if PHYSICAL_BACKFILL_FILE.is_file():
        backfill = read_csv(PHYSICAL_BACKFILL_FILE, PHYSICAL_COLUMNS)
        backfill = backfill[PHYSICAL_COLUMNS].copy()
        backfill["Season"] = backfill["Season"].fillna("").astype(str).str.strip()
        backfill["Team"] = backfill["Team"].fillna("").astype(str).str.strip()
        backfill = backfill.loc[backfill["Season"].eq("2021-2022")].copy()
        if set(backfill["Team"].map(clean_text)) - {"marseille", "monchengladbach"}:
            raise ValueError(
                f"Unexpected team in {PHYSICAL_BACKFILL_FILE.name}; expected only Marseille "
                "and Monchengladbach for 2021-2022."
            )
        backfill_rows = len(backfill)
        physical_source = pd.concat([physical_source, backfill], ignore_index=True)
        physical_source = physical_source.drop_duplicates(
            subset=["Player", "Team", "Season"], keep="last"
        )
    roster_source = read_csv(ROSTERS_FILE, ROSTER_COLUMNS)
    injury_source = read_csv(INJURIES_FILE, INJURY_COLUMNS)
    status_source = read_csv(PLAYER_STATUS_FILE, STATUS_COLUMNS)

    physical = prepare_physical(physical_source)
    expected_pairs, invalid_links = expected_team_season_links()
    physical["_team_key"] = physical["Team"].map(clean_text)
    physical_pairs = set(zip(physical["Season"], physical["_team_key"]))
    physical["_in_scope"] = [
        (season, team_key) in expected_pairs
        for season, team_key in zip(physical["Season"], physical["_team_key"])
    ]
    scope_review_rows: list[dict[str, object]] = []
    outside = physical.loc[~physical["_in_scope"]].groupby(["Season", "Team"], as_index=False).agg(
        player_team_rows=("Player", "size"), players=("Player", "nunique")
    )
    for row in outside.itertuples(index=False):
        scope_review_rows.append({
            "review_type": "physical_team_season_not_in_versioned_FBref_link_list",
            "Season": row.Season,
            "Team_or_slug": row.Team,
            "player_team_rows": row.player_team_rows,
            "players": row.players,
            "source_url": "",
        })
    missing_pairs = sorted(set(expected_pairs) - physical_pairs)
    for season, team_key in missing_pairs:
        parts = [part for part in urlparse(expected_pairs[(season, team_key)]).path.split("/") if part]
        slug = parts[4].removesuffix("-Stats")
        scope_review_rows.append({
            "review_type": "listed_FBref_team_season_missing_from_physical_data",
            "Season": season,
            "Team_or_slug": slug,
            "player_team_rows": 0,
            "players": 0,
            "source_url": expected_pairs[(season, team_key)],
        })
    for url in invalid_links:
        scope_review_rows.append({
            "review_type": "FBref_link_has_no_explicit_season_and_was_not_used_for_scope_validation",
            "Season": "",
            "Team_or_slug": "",
            "player_team_rows": 0,
            "players": 0,
            "source_url": url,
        })

    # Keep the source files intact; only rows from explicitly listed team-seasons
    # enter the player matching and model build.
    physical = physical.loc[physical["_in_scope"]].copy()
    mapped, _ = resolve_player_ids(physical, roster_source)
    player_seasons = aggregate_player_seasons(mapped)
    events = deduplicate_events(injury_source)
    status = latest_player_status(status_source)

    events["injury_season"] = events["injury_season"].astype(str).str.strip()
    season_events = events.groupby(["player_id", "injury_season"], as_index=False).agg(
        target_injury_count=("injury", "size"),
        target_days_out=("days_out", lambda values: values.sum(min_count=1)),
        target_games_missed=("games_missed", lambda values: values.sum(min_count=1)),
    )

    player_seasons["target_season"] = player_seasons["Season"].map(season_after)
    player_seasons = player_seasons.merge(
        status[["player_id", "status", "scraped_at"]].rename(
            columns={"status": "injury_history_scrape_status", "scraped_at": "injury_history_scraped_at"}
        ),
        left_on="transfermarkt_player_id", right_on="player_id", how="left", validate="many_to_one",
    )
    player_seasons = player_seasons.drop(columns=["player_id"])
    player_seasons = player_seasons.merge(
        season_events.rename(columns={"player_id": "transfermarkt_player_id", "injury_season": "target_season"}),
        on=["transfermarkt_player_id", "target_season"], how="left", validate="one_to_one",
    )
    player_seasons["target_injury_count"] = player_seasons["target_injury_count"].fillna(0).astype("int64")

    complete_through = latest_completed_season()
    eligible = (
        player_seasons["injury_history_scrape_status"].isin(SUCCESS_STATUSES)
        & player_seasons["target_season"].le(complete_through)
    )
    model = player_seasons.loc[eligible].copy()
    model["target_injured"] = model["target_injury_count"].gt(0).astype("int8")
    model["target_label_basis"] = "Transfermarkt injuries in the following completed season"
    model = model[
        PHYSICAL_COLUMNS[:7]
        + ["Team", "Season", "transfermarkt_player_id", "name_match_method", "target_season",
           "target_injured", "target_injury_count", "target_days_out", "target_games_missed",
           "injury_history_scrape_status", "injury_history_scraped_at", "target_label_basis"]
    ].sort_values(["Season", "Player"], kind="stable")

    unresolved = mapped.loc[mapped["transfermarkt_player_id"].isna()].copy()
    unresolved["target_season"] = unresolved["Season"].map(season_after)
    unresolved["review_status"] = unresolved["match_review_reason"]
    unresolved = unresolved[
        ["Player", "Team", "Season", "target_season", "candidate_transfermarkt_ids",
         "name_match_method", "review_status"]
    ].sort_values(["Season", "Player"], kind="stable")

    label_review = player_seasons.loc[~eligible].copy()
    label_review["label_review_reason"] = ""
    bad_status = ~label_review["injury_history_scrape_status"].isin(SUCCESS_STATUSES)
    label_review.loc[bad_status, "label_review_reason"] = label_review.loc[bad_status, "injury_history_scrape_status"].fillna("missing_status").map(
        lambda value: f"injury_history_status_{value}"
    )
    ongoing = label_review["target_season"].gt(complete_through)
    label_review.loc[ongoing, "label_review_reason"] = label_review.loc[ongoing, "label_review_reason"].map(
        lambda value: f"{value};target_season_not_complete" if value else "target_season_not_complete"
    )
    label_review = label_review[
        ["Player", "Team", "Season", "transfermarkt_player_id", "target_season",
         "injury_history_scrape_status", "target_injury_count", "label_review_reason"]
    ].sort_values(["Season", "Player"], kind="stable")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "player_season_injury_model_2019_2026.csv"
    review_path = OUTPUT_DIR / "player_season_match_review_2019_2026.csv"
    events_path = OUTPUT_DIR / "transfermarkt_injury_events_deduplicated.csv"
    label_review_path = OUTPUT_DIR / "player_season_label_review_2019_2026.csv"
    scope_review_path = OUTPUT_DIR / "physical_team_season_scope_review.csv"
    model.to_csv(model_path, index=False, encoding="utf-8-sig")
    unresolved.to_csv(review_path, index=False, encoding="utf-8-sig")
    events.drop(columns=["_injury_key"]).to_csv(events_path, index=False, encoding="utf-8-sig")
    label_review.to_csv(label_review_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(scope_review_rows, columns=[
        "review_type", "Season", "Team_or_slug", "player_team_rows", "players", "source_url"
    ]).to_csv(scope_review_path, index=False, encoding="utf-8-sig")

    match_counts = mapped["name_match_method"].value_counts(dropna=False).to_dict()
    summary = pd.DataFrame([
        {"metric": "physical_source_rows", "value": len(physical_source)},
        {"metric": "fbref_backfill_rows_loaded", "value": backfill_rows},
        {"metric": "physical_rows_in_versioned_link_scope", "value": len(physical)},
        {"metric": "physical_rows_outside_versioned_link_scope", "value": len(physical_source) - len(physical)},
        {"metric": "expected_team_season_pairs_missing_from_physical", "value": len(missing_pairs)},
        {"metric": "physical_rows_matched_to_unique_tm_player", "value": int(mapped["transfermarkt_player_id"].notna().sum())},
        {"metric": "physical_rows_unmatched_or_ambiguous", "value": int(mapped["transfermarkt_player_id"].isna().sum())},
        {"metric": "unique_player_season_model_rows", "value": len(model)},
        {"metric": "matched_player_seasons_excluded_from_model", "value": len(label_review)},
        {"metric": "excluded_status_failed_or_missing", "value": int(bad_status.sum())},
        {"metric": "excluded_target_season_incomplete", "value": int(ongoing.sum())},
        {"metric": "unique_model_players", "value": int(model["transfermarkt_player_id"].nunique())},
        {"metric": "positive_next_season_labels", "value": int(model["target_injured"].sum())},
        {"metric": "negative_next_season_labels", "value": int(model["target_injured"].eq(0).sum())},
        {"metric": "deduplicated_injury_events", "value": len(events)},
        {"metric": "latest_completed_target_season", "value": complete_through},
        {"metric": "match_method_unique_name_season", "value": match_counts.get("unique_name_and_season", 0)},
        {"metric": "match_method_team_resolved_collision", "value": match_counts.get("name_season_then_distinctive_team_match", 0)},
        {"metric": "match_method_ambiguous", "value": match_counts.get("ambiguous", 0)},
        {"metric": "match_method_unmatched", "value": match_counts.get("unmatched", 0)},
    ])
    summary.to_csv(OUTPUT_DIR / "dataset_build_summary.csv", index=False, encoding="utf-8-sig")

    print(f"Prepared dataset: {model_path}")
    print(f"Match review: {review_path}")
    print(f"Label review: {label_review_path}")
    print(f"FBref team-season scope review: {scope_review_path}")
    print(f"Deduplicated injury events: {events_path}")
    print(f"\n{summary.to_string(index=False)}")


if __name__ == "__main__":
    main()
