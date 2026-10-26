"""Resume recent-season FBref collection from season-specific top-five links."""

import random
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from io import StringIO
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
LINKS_FILE = DATA_RAW / "top5_teams_links_recent.txt"
CLEAN_FILE = DATA_RAW / "master_players_physical_data_recent_clean.csv"
REQUIRED = {"Player", "Min"}
PLAYER_COLUMNS = ["Player", "Nation", "Pos", "Age", "MP", "Starts", "Min"]
INVALID_PLAYER_ROWS = {"player", "squad total", "opponent total"}
OUTPUT_COLUMNS = PLAYER_COLUMNS + ["Season", "Team"]


def team_name_from_url(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) < 5 or parts[1] != "squads":
        raise ValueError(f"Unrecognized FBref squad URL: {url}")
    slug = parts[4]
    return slug.removesuffix("-Stats").replace("-", " ").title()


def season_from_url(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        season_index = parts.index("squads") + 2
        return parts[season_index]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Season missing from FBref squad URL: {url}") from exc


def valid_player_rows(frame):
    frame = frame.dropna(how="all").copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    if "Player" not in frame.columns:
        return frame.iloc[0:0]
    labels = frame["Player"].fillna("").astype(str).str.strip().str.casefold()
    frame = frame.loc[frame["Player"].notna() & ~labels.isin(INVALID_PLAYER_ROWS)].copy()
    if {"MP", "Starts", "Min"}.issubset(frame.columns):
        mp = pd.to_numeric(frame["MP"], errors="coerce")
        starts = pd.to_numeric(frame["Starts"], errors="coerce")
        unplayed = frame["Min"].isna() & mp.eq(0) & starts.eq(0)
        frame.loc[unplayed, "Min"] = 0
    return frame


def parse_player_table(soup):
    tables = []
    standard = soup.find("table", id="stats_standard")
    if standard is not None:
        tables.append(standard)
    tables.extend(table for table in soup.find_all("table") if table is not standard)

    for table in tables:
        try:
            frame = pd.read_html(StringIO(str(table)))[0]
        except (ValueError, IndexError):
            continue
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [
                next(
                    (
                        str(level).strip()
                        for level in reversed(column)
                        if str(level).strip() and not str(level).startswith("Unnamed: ")
                    ),
                    "",
                )
                for column in frame.columns
            ]
        frame.columns = [str(column).strip() for column in frame.columns]
        if REQUIRED.issubset(frame.columns):
            return valid_player_rows(frame)
    return None


def load_existing_output():
    if CLEAN_FILE.exists() and CLEAN_FILE.stat().st_size:
        frame = pd.read_csv(CLEAN_FILE, encoding="utf-8-sig", low_memory=False)
    else:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    if not set(OUTPUT_COLUMNS).issubset(frame.columns):
        raise ValueError(f"Existing output has an unexpected schema: {list(frame.columns)}")
    frame = frame[OUTPUT_COLUMNS].copy()
    frame = valid_player_rows(frame)

    expected_pairs = {
        (season_from_url(url), team_name_from_url(url))
        for url in LINKS_FILE.read_text(encoding="utf-8-sig").splitlines()
        if url.strip()
    }
    allowed = pd.Series(
        [(str(row.Season), str(row.Team)) in expected_pairs for row in frame.itertuples()],
        index=frame.index,
    )
    frame = frame.loc[allowed].drop_duplicates(["Player", "Team", "Season"], keep="first")
    frame.to_csv(CLEAN_FILE, index=False, encoding="utf-8-sig")
    return frame


def main():
    if not LINKS_FILE.is_file():
        raise FileNotFoundError(f"Missing season-specific team links: {LINKS_FILE}")
    links = sorted(
        {line.strip() for line in LINKS_FILE.read_text(encoding="utf-8-sig").splitlines() if line.strip()}
    )
    if not links:
        raise ValueError(f"No team links found in {LINKS_FILE}")

    output = load_existing_output()
    complete_pairs = set(zip(output["Season"].astype(str), output["Team"].astype(str)))
    pending = [
        url for url in links
        if (season_from_url(url), team_name_from_url(url)) not in complete_pairs
    ]
    print(
        f"Season-specific links: {len(links)}; already collected: "
        f"{len(links) - len(pending)}; to fetch: {len(pending)}"
    )

    driver = None
    saved_keys = set(zip(output.Player.astype(str), output.Team.astype(str), output.Season.astype(str)))
    try:
        driver = uc.Chrome(options=uc.ChromeOptions(), version_main=153)
        for index, url in enumerate(pending, start=1):
            season = season_from_url(url)
            team = team_name_from_url(url)
            print(f"[{index}/{len(pending)}] {season}: {team}")
            try:
                driver.get(url)
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
                time.sleep(random.uniform(2, 4))
                frame = parse_player_table(BeautifulSoup(driver.page_source, "html.parser"))
                if frame is None or frame.empty:
                    print(f"  No valid Player/Min table found: {url}")
                    continue

                available = [column for column in PLAYER_COLUMNS if column in frame.columns]
                frame = frame[available].copy()
                frame["Season"] = season
                frame["Team"] = team
                frame = frame[OUTPUT_COLUMNS]
                keys = list(zip(frame.Player.astype(str), frame.Team.astype(str), frame.Season.astype(str)))
                frame = frame.loc[[key not in saved_keys for key in keys]]
                if frame.empty:
                    continue

                has_content = CLEAN_FILE.exists() and CLEAN_FILE.stat().st_size > 0
                with CLEAN_FILE.open(
                    "a", encoding="utf-8" if has_content else "utf-8-sig", newline=""
                ) as csv_file:
                    frame.to_csv(csv_file, index=False, header=not has_content)
                saved_keys.update(
                    zip(frame.Player.astype(str), frame.Team.astype(str), frame.Season.astype(str))
                )
                print(f"  Saved {len(frame)} player rows")
            except Exception as exc:
                print(f"  Failed this team; it can be resumed later: {exc}")
            time.sleep(random.uniform(2, 4))

        print(f"Recent-season clean data saved to: {CLEAN_FILE}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                print(f"Browser cleanup failed safely: {exc}")


if __name__ == "__main__":
    main()
