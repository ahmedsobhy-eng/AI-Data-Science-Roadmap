"""Collect exact FBref squad URLs for the two recent seasons."""

import random
import time
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SEASONS = ("2024-2025", "2025-2026")
LEAGUES = {
    "Premier-League": 9,
    "La-Liga": 12,
    "Serie-A": 11,
    "Bundesliga": 20,
    "Ligue-1": 13,
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "data" / "raw" / "top5_teams_links_recent.txt"


def main():
    driver = None
    team_links = set()
    try:
        driver = uc.Chrome(options=uc.ChromeOptions(), version_main=153)
        for season in SEASONS:
            for league_name, competition_id in LEAGUES.items():
                url = (
                    f"https://fbref.com/en/comps/{competition_id}/{season}/"
                    f"{season}-{league_name}-Stats"
                )
                print(f"Fetching league teams: {season} {league_name}")
                driver.get(url)
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "td[data-stat='team'] a"))
                )
                for link in driver.find_elements(
                    By.CSS_SELECTOR, "td[data-stat='team'] a[href*='/squads/']"
                ):
                    href = link.get_attribute("href")
                    if href:
                        team_links.add(href.split("#")[0])
                time.sleep(random.uniform(2, 4))

        if not team_links:
            raise RuntimeError("FBref returned no squad links; refusing to replace the link file.")

        OUTPUT.write_text("\n".join(sorted(team_links)) + "\n", encoding="utf-8-sig")
        print(f"Saved {len(team_links)} season-specific squad links to {OUTPUT}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                print(f"Browser cleanup failed safely: {exc}")


if __name__ == "__main__":
    main()
