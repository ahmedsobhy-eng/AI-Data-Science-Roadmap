"""Fetch only the two missing FBref squad tables for 2021-2022."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pandas as pd
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from io import StringIO
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import sys
from pathlib import Path

# Add src/scraping to path for cross-folder imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fbref_recent_scraper import parse_player_table
from transfermarkt_injury_scraper import SafeChrome, find_chrome_version, safe_quit


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
OUTPUT = PROJECT_ROOT / "data" / "prepared" / "fbref_backfill_2021_2022.csv"
URLS = {
    "Marseille": "https://fbref.com/en/squads/5725cc7b/2021-2022/Marseille-Stats",
    "Monchengladbach": "https://fbref.com/en/squads/32f3ee20/2021-2022/Monchengladbach-Stats",
}
PLAYER_COLUMNS = ["Player", "Nation", "Pos", "Age", "MP", "Starts", "Min"]
OUTPUT_COLUMNS = PLAYER_COLUMNS + ["Season", "Team"]


def main() -> None:
    """Scrape the two known gaps and save a standalone, reviewable CSV."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    browser_path, chrome_major = find_chrome_version()
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1440,1000")
    driver = None
    collected: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []

    try:
        driver = SafeChrome(
            options=options,
            browser_executable_path=browser_path,
            version_main=chrome_major,
        )
        driver.set_page_load_timeout(45)
        for team, url in URLS.items():
            print(f"Fetching 2021-2022 {team}: {url}", flush=True)
            try:
                driver.get(url)
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "table"))
                )
                time.sleep(random.uniform(2, 4))
                frame = parse_player_table(
                    BeautifulSoup(driver.page_source, "html.parser")
                )
                if frame is None or frame.empty:
                    raise RuntimeError("No player statistics table with Player and Min was found")
                for column in PLAYER_COLUMNS:
                    if column not in frame.columns:
                        frame[column] = pd.NA
                frame = frame[PLAYER_COLUMNS].copy()
                frame["Season"] = "2021-2022"
                frame["Team"] = team
                frame = frame.loc[
                    frame["Player"].notna()
                    & ~frame["Player"].astype(str).str.strip().str.casefold().isin(
                        {"player", "squad total", "opponent total"}
                    )
                ]
                frame = frame.drop_duplicates(["Player", "Team", "Season"])
                if frame.empty:
                    raise RuntimeError("The player table was found but had no player rows")
                collected.append(frame[OUTPUT_COLUMNS])
                print(f"  Validated {len(frame)} player rows", flush=True)
            except Exception as exc:
                failures.append((team, str(exc)))
                title = ""
                page_hint = ""
                if driver is not None:
                    try:
                        title = driver.title
                        page_hint = " ".join(driver.find_element(By.TAG_NAME, "body").text.split())[:500]
                    except Exception:
                        pass
                print(
                    f"  Failed {team}: {type(exc).__name__}: {exc}\n"
                    f"  Page title: {title!r}; page text: {page_hint!r}",
                    flush=True,
                )
            time.sleep(random.uniform(3, 5))
    finally:
        safe_quit(driver)

    if collected:
        backfill = pd.concat(collected, ignore_index=True)
        backfill.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
        print(f"Saved {len(backfill)} rows to {OUTPUT}", flush=True)
        print(backfill.groupby(["Season", "Team"]).size().to_string(), flush=True)
    else:
        print("No data was saved because neither team produced a valid table.", flush=True)

    if failures:
        print("Teams needing a retry:", flush=True)
        for team, reason in failures:
            print(f"- {team}: {reason}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
