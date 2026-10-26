"""Collect Transfermarkt rosters and injury histories for top-five league clubs.

Input: tm_top5_teams_updated.txt, containing one Transfermarkt club URL per
club-season (the list generated from the five leagues for 2019/20 onward).

Outputs are checkpointed in this directory. The roster file preserves player
IDs and club-season membership; the injury file contains unique injury events
by Transfermarkt player ID. Injury events are deliberately not assigned to a
team because Transfermarkt's injury-history table does not identify the club
for each past injury.
"""

# Future annotations let type hints refer to types that are only needed by the
# type checker, and also make newer annotation syntax easier to use.
from __future__ import annotations

# `random` adds small pauses between requests so the scraper does not hammer
# Transfermarkt at perfectly regular intervals.
import random
# `re` is used to recognize IDs, dates, URL sections, and normalized headers.
import re
# `os` identifies Windows and supports its registry lookup for Chrome's version.
import os
# `shutil` checks free disk space and helps preserve a safe stopping point.
import shutil
# `subprocess` runs Chrome's version command on non-Windows systems.
import subprocess
# `time` provides the request delays and retry backoff.
import time
# `date` and `datetime` provide season/date filtering and scrape timestamps.
from datetime import date, datetime
# `Path` builds paths relative to this script instead of relying on the terminal's
# current folder.
from pathlib import Path
# `urljoin` makes absolute profile URLs; `urlparse` safely inspects URL paths.
from urllib.parse import urljoin, urlparse

# Pandas reads, normalizes, deduplicates, and writes the CSV data.
import pandas as pd
# Undetected ChromeDriver controls Chrome for pages requiring browser rendering.
import undetected_chromedriver as uc
# BeautifulSoup extracts readable page text and links from HTML.
from bs4 import BeautifulSoup
# StringIO lets pandas treat an HTML string as an in-memory document.
from io import StringIO
# These Selenium exceptions distinguish navigation timeouts from browser errors.
from selenium.common.exceptions import TimeoutException, WebDriverException
# `By` names Selenium selectors; `WebDriverWait` waits for a page condition.
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


# Folder that contains this script and its input/output files.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
# Input list of Transfermarkt club-season URLs to process.
TEAM_URLS_FILE = DATA_RAW / "tm_top5_teams_updated.txt"
# Checkpointed player/team/season membership extracted from squad pages.
ROSTERS_FILE = DATA_RAW / "transfermarkt_player_rosters_2019_present.csv"
# Checkpoint describing which roster pages succeeded or failed.
ROSTER_STATUS_FILE = DATA_RAW / "transfermarkt_roster_status.csv"
# Main output containing unique injury events for players.
INJURIES_FILE = DATA_RAW / "transfermarkt_injuries_2019_present.csv"
# Per-player checkpoint used to resume without repeating completed player pages.
PLAYER_STATUS_FILE = DATA_RAW / "transfermarkt_player_injury_status.csv"

# Injury records before this date are excluded from the output.
CUTOFF_DATE = pd.Timestamp("2019-01-01")
# Maximum wait for the page body/document to become available after navigation.
WAIT_SECONDS = 12
# Maximum time Selenium allows a single navigation to take.
PAGE_TIMEOUT_SECONDS = 45
# Number of attempts for a transient page load failure before reporting failure.
MAX_ATTEMPTS = 3
# Random wait range between successive pages, in seconds.
REQUEST_DELAY_SECONDS = (1.8, 3.5)
# Stop before the disk gets critically full; this leaves room for Chrome and CSVs.
MIN_FREE_SPACE_BYTES = 1024**3  # Keep at least 1 GiB free for Chrome and checkpoints.
# Transfermarkt's URL slugs mapped to its internal competition IDs.
TOP_FIVE_LEAGUES = {
    "premier-league": "GB1",
    "primera-division": "ES1",
    "serie-a": "IT1",
    "1-bundesliga": "L1",
    "ligue-1": "FR1",
}

# Exact output columns for the roster membership checkpoint.
ROSTER_COLUMNS = [
    "player_id", "player", "team_id", "team", "roster_season",
    "profile_url", "injury_url", "roster_url",
]
# Exact output columns for the roster-page progress/error checkpoint.
ROSTER_STATUS_COLUMNS = [
    "roster_url", "team_id", "team", "roster_season", "status",
    "player_count", "scraped_at", "error",
]
# Exact output columns for the injury events dataset.
INJURY_COLUMNS = [
    "player_id", "player", "injury_season", "injury", "date_from",
    "date_until", "days_out", "games_missed", "profile_url", "injury_url",
]
# Exact output columns for the per-player progress/error checkpoint.
PLAYER_STATUS_COLUMNS = [
    "player_id", "player", "status", "injury_count", "scraped_at", "error",
]

def read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a CSV checkpoint and ensure that its required columns exist."""
    # A missing or zero-byte file means no records have been collected yet.
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)
    # Read the existing checkpoint, accepting a UTF-8 BOM from Excel-friendly CSVs.
    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    # Add required columns absent from an older version of the scraper's schema.
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    # Return columns in a stable order and discard unrelated legacy columns.
    return frame[columns]


def append_csv(frame: pd.DataFrame, path: Path, columns: list[str]) -> None:
    """Append a checkpoint without adding UTF-8 BOMs in the middle of a CSV."""
    # Nothing needs to be written for an empty batch.
    if frame.empty:
        return
    # Align the batch to the expected schema before writing.
    frame = frame.reindex(columns=columns)
    # Append to a nonempty file; create a new file otherwise.
    has_data = path.exists() and path.stat().st_size > 0
    # Only the first write includes a header and UTF-8 BOM; later appends use
    # plain UTF-8 so a BOM is not inserted in the middle of the data file.
    frame.to_csv(
        path,
        mode="a" if has_data else "w",
        index=False,
        header=not has_data,
        encoding="utf-8" if has_data else "utf-8-sig",
    )


def normalize_space(value: object) -> str:
    """Convert any value to text and collapse repeated whitespace."""
    # `split()` removes leading/trailing whitespace and joins internal runs.
    return " ".join(str(value).split()).strip()


def team_metadata(team_url: str) -> tuple[str, str, str, str]:
    """Return roster URL, team ID, team slug, and season label from a club URL."""
    # Split the URL path into meaningful components, ignoring empty slash entries.
    parts = [part for part in urlparse(team_url).path.split("/") if part]
    try:
        # `verein/<id>` identifies the club; `saison_id/<year>` identifies a season.
        team_index = parts.index("verein")
        team_id = parts[team_index + 1]
        season_index = parts.index("saison_id")
        season_code = parts[season_index + 1]
    except (ValueError, IndexError) as exc:
        # Reject malformed URLs with a readable error instead of an obscure list error.
        raise ValueError(f"Not a Transfermarkt club-season URL: {team_url}") from exc

    # The first path section is the team's human-readable URL slug.
    slug = parts[0]
    # Transfermarkt season IDs are start years; convert them to a display label.
    season_start = int(season_code)
    roster_season = f"{season_start}-{season_start + 1}"
    # Convert a club start-page URL into its roster page URL.
    roster_url = f"https://www.transfermarkt.com/{slug}/kader/verein/{team_id}/saison_id/{season_code}/plus/1"
    # Return the roster page, numeric ID, slug, and readable season label.
    return roster_url, team_id, slug, roster_season


def current_season_start() -> int:
    """Return the start year of the football season active today."""
    # Read today's date from the computer's local calendar.
    today = date.today()
    # European football seasons are treated as July-to-June: before July, the
    # current season began in the previous calendar year.
    return today.year if today.month >= 7 else today.year - 1


def require_free_space() -> None:
    """Abort safely if the scraper's drive is nearly full."""
    # Query free bytes on the drive that stores this script and its checkpoints.
    free_bytes = shutil.disk_usage(SCRIPT_DIR).free
    # Do not start another scrape operation if less than the configured reserve remains.
    if free_bytes < MIN_FREE_SPACE_BYTES:
        # Format the remaining space for a useful error message.
        free_gib = free_bytes / (1024**3)
        # Raising here stops the scraper before another browser/CSV write can consume space.
        raise RuntimeError(
            f"Only {free_gib:.2f} GiB is free on the scraper drive; "
            "free at least 1 GiB before continuing. Existing checkpoints are preserved."
        )


def find_chrome_version() -> tuple[str, int]:
    """Find the installed Chrome binary and its major version for UC matching."""
    # Ask undetected_chromedriver where Chrome is installed.
    browser_path = uc.find_chrome_executable()
    # Fail early if the browser executable cannot be found.
    if not browser_path:
        raise FileNotFoundError("Could not locate Google Chrome on this computer")

    # This variable will hold the full version string from Windows or Chrome.
    version_text = ""
    # Windows stores Chrome's installed version in the registry.
    if os.name == "nt":
        # Import Windows registry access only when running on Windows.
        import winreg

        # Check common per-user and machine-wide Chrome registry locations.
        registry_locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Google\Chrome\BLBeacon"),
        )
        # Try each registry location until the Chrome version is found.
        for hive, key_path in registry_locations:
            try:
                # Open the registry key and read the `version` value.
                with winreg.OpenKey(hive, key_path) as key:
                    version_text, _ = winreg.QueryValueEx(key, "version")
                    # Stop after the first successful registry lookup.
                    break
            except OSError:
                # A missing key is normal if Chrome is registered elsewhere.
                continue
    else:
        # On non-Windows systems, ask the Chrome executable to print its version.
        result = subprocess.run(
            [browser_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        # Combine stdout and stderr in case the browser prints its version to either.
        version_text = f"{result.stdout} {result.stderr}"

    # Extract the first four-part Chrome version and keep its major number.
    match = re.search(r"\b(\d+)\.\d+\.\d+\.\d+\b", version_text)
    # Refuse to launch UC with an unknown browser version, which can cause a mismatch.
    if not match:
        raise RuntimeError(
            f"Could not read the installed Chrome version; version value was {version_text!r}"
        )
    # Return Chrome's executable path and integer major version for driver startup.
    return browser_path, int(match.group(1))


def discover_season_team_urls(fetch_page, season_start: int) -> set[str]:
    """Discover club-season pages for a missing year, including the current one."""
    # Accumulate the distinct club-season start pages from all five leagues.
    discovered: set[str] = set()
    # Visit one Transfermarkt competition page per league.
    for league_slug, league_code in TOP_FIVE_LEAGUES.items():
        # Build the league's season-specific homepage URL.
        league_url = (
            f"https://www.transfermarkt.com/{league_slug}/startseite/"
            f"wettbewerb/{league_code}/saison_id/{season_start}"
        )
        # Load the page through the shared browser helper, including its retry logic.
        html = fetch_page(league_url)
        # Parse the returned HTML so team links can be located.
        soup = BeautifulSoup(html, "html.parser")
        # Keep distinct team URLs for this league to avoid counting duplicate links.
        league_teams: set[str] = set()
        # Select links that point to a club's Transfermarkt start page.
        for anchor in soup.select('a[href*="/startseite/verein/"]'):
            # Extract only the URL path; host/query strings are not needed here.
            path = urlparse(anchor.get("href", "")).path
            # Capture the team's slug and numeric club ID from the expected URL shape.
            match = re.search(r"/([^/]+)/startseite/verein/(\d+)", path)
            # Ignore links that do not match the club URL pattern.
            if match:
                # Unpack the readable slug and stable numeric club ID.
                slug, team_id = match.groups()
                # Build a normalized season URL and insert it into the unique set.
                league_teams.add(
                    f"https://www.transfermarkt.com/{slug}/startseite/verein/{team_id}/saison_id/{season_start}"
                )
        # Fewer than 15 clubs is suspicious for a major league and may mean the
        # page was blocked or only partially rendered; do not accept that season.
        if len(league_teams) < 15:
            raise RuntimeError(
                f"Only {len(league_teams)} clubs detected for {league_code} in {season_start}; "
                "refusing to mark an incomplete season as covered."
            )
        # Merge this league's clubs into the result for all five leagues.
        discovered.update(league_teams)
        # Pause before requesting the next league page.
        time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))
    # Return every discovered club-season URL without duplicates.
    return discovered


def discover_top_club_urls(fetch_page, league_slug: str, league_code: str, season_start: int) -> list[str]:
    """Return the current-season squads of the five most valuable clubs in a league."""
    # Build the market-value ranking URL for the requested competition.
    market_url = (
        f"https://www.transfermarkt.com/{league_slug}/marktwerteverein/"
        f"wettbewerb/{league_code}/plus/1"
    )
    # Download and parse the ranking page.
    html = fetch_page(market_url)
    soup = BeautifulSoup(html, "html.parser")
    # Prefer club links inside the ranking table to avoid unrelated page links.
    anchors = soup.select("table.items a[href*='/startseite/verein/']")
    # Fall back to any club start-page link if the page uses different markup.
    if not anchors:
        anchors = soup.select("a[href*='/startseite/verein/']")

    # Preserve clubs in page order, which is the value ranking order.
    clubs: list[tuple[str, str]] = []
    # Track club IDs because the page may link to the same club more than once.
    seen_ids: set[str] = set()
    # Inspect each candidate link until five distinct clubs have been found.
    for anchor in anchors:
        # Parse the slug and numeric club ID from the anchor's path.
        match = re.search(r"/([^/]+)/startseite/verein/(\d+)", urlparse(anchor.get("href", "")).path)
        # Ignore links with an unexpected URL format.
        if not match:
            continue
        # Extract the two parts needed to build a canonical club URL.
        slug, team_id = match.groups()
        # Skip clubs already seen elsewhere on the same page.
        if team_id in seen_ids:
            continue
        # Record the ID and add this club to the ordered result.
        seen_ids.add(team_id)
        clubs.append((slug, team_id))
        # Stop when the requested five unique clubs have been collected.
        if len(clubs) == 5:
            break

    # Fail if the page did not provide all five clubs; using a partial list would
    # silently make the intended priority coverage incomplete.
    if len(clubs) != 5:
        raise RuntimeError(
            f"Found only {len(clubs)} club links on {league_code}'s market-value page; "
            "cannot safely determine the top five clubs. Check Transfermarkt consent/access."
        )
    # Convert each club into its current-season start-page URL for roster collection.
    return [
        f"https://www.transfermarkt.com/{slug}/startseite/verein/{team_id}/saison_id/{season_start}"
        for slug, team_id in clubs
    ]


def discover_world_cup_team_urls(fetch_page) -> list[str]:
    """Get start-page URLs for the 2026 World Cup participating national teams."""
    # This is the Transfermarkt page listing teams participating in the tournament.
    participants_url = (
        "https://www.transfermarkt.com/world-cup/teilnehmer/"
        "pokalwettbewerb/FIWC/saison_id/2025"
    )
    # Load and parse the participant page.
    html = fetch_page(participants_url)
    soup = BeautifulSoup(html, "html.parser")
    # Prefer national-team links inside the participants table.
    anchors = soup.select("table.items a[href*='/startseite/verein/']")
    # Support the same links if Transfermarkt changes the surrounding markup.
    if not anchors:
        anchors = soup.select("a[href*='/startseite/verein/']")

    # Keep teams in page order while removing duplicate links.
    teams: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    # Parse every candidate team URL and keep its slug and numeric ID.
    for anchor in anchors:
        match = re.search(r"/([^/]+)/startseite/verein/(\d+)", urlparse(anchor.get("href", "")).path)
        # Ignore unrelated links that do not point to a team start page.
        if not match:
            continue
        # Extract the team's display slug and stable ID.
        slug, team_id = match.groups()
        # Keep each participating team only once.
        if team_id in seen_ids:
            continue
        # Remember this team so the returned list contains no repeated squads.
        seen_ids.add(team_id)
        teams.append((slug, team_id))

    # The 2026 tournament has 48 teams. Fail closed rather than pretending a
    # consent page or partial result is a complete set of national squads.
    # Expect close to the tournament's 48 teams; a much smaller list is likely
    # an access/consent/markup problem and must not be treated as complete.
    if len(teams) < 40:
        raise RuntimeError(
            f"Found only {len(teams)} World Cup team links; expected 48. "
            "Check Transfermarkt consent/access before continuing."
        )
    # Convert every discovered national team into its 2025/26 squad URL.
    return [
        f"https://www.transfermarkt.com/{slug}/startseite/verein/{team_id}/saison_id/2025"
        for slug, team_id in teams
    ]


def player_links_from_roster(html: str, roster_url: str) -> list[dict[str, str]]:
    """Extract unique player profile records from one club or national roster."""
    # Build a searchable DOM tree from the squad page HTML.
    soup = BeautifulSoup(html, "html.parser")
    # Parse the roster URL so team and season metadata can be attached to players.
    team_url = urlparse(roster_url)
    # Split its path into sections such as team slug, `verein`, ID, and season ID.
    parts = [part for part in team_url.path.split("/") if part]
    # Read the team ID, season code, and slug from those known URL components.
    team_id = parts[parts.index("verein") + 1]
    season_code = parts[parts.index("saison_id") + 1]
    slug = parts[0]
    start = int(season_code)
    # Convert the numeric season code into a readable year range.
    roster_season = f"{start}-{start + 1}"
    # Create a readable team label from the URL slug.
    team_name = slug.replace("-", " ").title()

    # Index players by stable Transfermarkt ID to remove duplicate profile links.
    found: dict[str, dict[str, str]] = {}
    # Select links whose paths point to player profiles.
    for anchor in soup.select('a[href*="/profil/spieler/"]'):
        # Read the link target; empty links are ignored by the parser below.
        href = anchor.get("href", "")
        # Capture the numeric player ID from the profile URL.
        match = re.search(r"/profil/spieler/(\d+)", urlparse(href).path)
        # Skip links that are not valid player-profile URLs.
        if not match:
            continue
        # Stable ID used to join this player across teams and seasons.
        player_id = match.group(1)
        # The visible anchor text normally contains the player's name.
        name = normalize_space(anchor.get_text(" ", strip=True))
        # Reject empty names and links that display only an ID.
        if not name or name.isdecimal():
            continue

        # Make the profile URL absolute even when the HTML contains a relative path.
        profile_url = urljoin("https://www.transfermarkt.com", urlparse(href).path)
        # Derive the injury-history page by replacing the profile page path segment.
        injury_url = re.sub(r"/profil/spieler/", "/verletzungen/spieler/", profile_url)
        # Save player identity, team membership, season, and both relevant URLs.
        found[player_id] = {
            "player_id": player_id,
            "player": name,
            "team_id": team_id,
            "team": team_name,
            "roster_season": roster_season,
            "profile_url": profile_url,
            "injury_url": injury_url,
            "roster_url": roster_url,
        }
    # Return each player once; dict insertion order preserves page order.
    return list(found.values())


def flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert HTML table headers, including multi-row headers, to plain strings."""
    # Pandas represents grouped/multi-row HTML headings as a MultiIndex.
    if isinstance(frame.columns, pd.MultiIndex):
        # For each multi-level heading, use its last meaningful non-empty label.
        frame.columns = [
            next(
                (
                    normalize_space(level)
                    for level in reversed(column)
                    if normalize_space(level) and not str(level).startswith("Unnamed")
                ),
                "",
            )
            for column in frame.columns
        ]
    # Normalize whitespace from every final heading, whether multi-level or not.
    frame.columns = [normalize_space(column) for column in frame.columns]
    # Return the same data with easier-to-compare string column names.
    return frame


def header_key(value: object) -> str:
    """Normalize a column heading to lowercase letters for robust comparison."""
    # Remove spaces, punctuation, and capitalization differences from a heading.
    return re.sub(r"[^a-z]", "", normalize_space(value).casefold())


def find_injury_table(html: str) -> pd.DataFrame | None:
    """Find the injury history table by its headers, not by table position."""
    try:
        # Parse all HTML tables because Transfermarkt may change their page order.
        tables = pd.read_html(StringIO(html))
    except Exception:
        # No readable HTML tables means this page cannot be parsed as injury history.
        return None

    # Map common heading variations to a small, stable internal schema.
    aliases = {
        "injury": {"injury", "injuries"},
        "from": {"from", "start", "fromdate", "startdate"},
        "until": {"until", "to", "untildate", "end", "enddate"},
        "season": {"season"},
        "days": {"days", "daysout"},
        "games_missed": {"gamesmissed", "missedgames"},
    }
    # Examine every parsed table, not just the first one.
    for frame in tables:
        # Copy the table and simplify its headings before matching columns.
        frame = flatten_columns(frame.copy())
        # This dictionary will map internal field names to actual source headings.
        mapped: dict[str, str] = {}
        # Compare every table heading with the aliases listed above.
        for column in frame.columns:
            # Normalize the heading so punctuation and spaces do not matter.
            key = header_key(column)
            # Assign an internal name when this heading matches a known alias.
            for field, names in aliases.items():
                if key in names:
                    mapped[field] = column
        # Injury, start date, and end date are required to identify an injury table.
        if not {"injury", "from", "until"}.issubset(mapped):
            continue

        # Create a normalized output table, retaining the source row indices.
        result = pd.DataFrame(index=frame.index)
        # Copy each recognized column; absent optional fields become missing values.
        for field in aliases:
            result[field] = frame[mapped[field]] if field in mapped else pd.NA
        # Drop rows that are entirely blank across injury name and dates.
        return result.dropna(how="all", subset=["injury", "from", "until"])
    # None of the page tables had the required injury-history headings.
    return None


def page_diagnostic(driver, url: str) -> str:
    """Return a short, useful reason when a profile did not render its table."""
    try:
        # Chrome's page title often reveals a consent page, CAPTCHA, or error screen.
        title = normalize_space(driver.title)
    except WebDriverException:
        # The browser may be disconnected, in which case no title is available.
        title = ""
    try:
        # Redirects can take the browser away from the requested player page.
        final_url = normalize_space(driver.current_url)
    except WebDriverException:
        # Use the requested URL as a fallback if Chrome cannot report its URL.
        final_url = url
    try:
        # Flatten visible page text for quick detection of common access barriers.
        text = BeautifulSoup(driver.page_source, "html.parser").get_text(" ", strip=True).casefold()
    except WebDriverException:
        # An unavailable session cannot provide diagnostic page content.
        text = ""

    # Consent pages do not contain the player's injury table; report that distinctly.
    if any(term in text for term in ("accept & continue", "welcome! how would you like to use transfermarkt", "consent required")):
        return "Transfermarkt is showing its consent screen; choose a consent option in Chrome, then rerun."
    # Avoid treating block pages as ordinary players with no recorded injuries.
    if any(term in text for term in ("too many requests", "access denied", "captcha")):
        return "Transfermarkt returned a block or CAPTCHA page."
    # Include the title and final URL so a user can diagnose unexpected redirects/layouts.
    return f"No injury table rendered (title={title!r}, final_url={final_url!r})."


def season_label(value: object) -> str:
    """Normalize Transfermarkt season text such as `19/20` to `2019-2020`."""
    # Convert the source cell to clean text and find a slash-separated year pair.
    raw = normalize_space(value)
    match = re.search(r"(\d{2,4})\s*/\s*(\d{2,4})", raw)
    # If the value does not look like a season, preserve its cleaned text.
    if not match:
        return raw
    # Extract the start and end year tokens.
    first, second = match.groups()
    # Expand two-digit start years into the 2000s; retain four-digit years.
    start = int(first) if len(first) == 4 else 2000 + int(first)
    # Expand two-digit end years into the start year's century.
    end = int(second) if len(second) == 4 else (start // 100) * 100 + int(second)
    # Correct the century if a season crosses from 2099 to 2100, etc.
    if end < start:
        end += 100
    # Return a consistent YYYY-YYYY season label.
    return f"{start}-{end}"


def parse_date(value: object) -> str:
    """Parse a source date into ISO format, or return an empty string if invalid."""
    # Convert the table cell to text and normalize its whitespace.
    raw = normalize_space(value)
    # Missing-value markers are not real calendar dates.
    if not raw or raw.casefold() in {"nan", "-", "?", "unknown"}:
        return ""
    # Transfermarkt often uses day-first dates; invalid strings become NaT.
    parsed = pd.to_datetime(raw, dayfirst=True, errors="coerce")
    # Output YYYY-MM-DD when parsing succeeds, otherwise an empty string.
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def numeric_value(value: object) -> str:
    """Keep the first integer from a cell, stripping thousands separators."""
    # Remove commas used as digit grouping and search for a signed integer.
    match = re.search(r"-?\d+", normalize_space(value).replace(",", ""))
    # Return the number as text for a stable CSV schema; return blank if absent.
    return match.group(0) if match else ""


def make_injury_records(
    frame: pd.DataFrame,
    player_id: str,
    player: str,
    profile_url: str,
    injury_url: str,
) -> list[dict[str, str]]:
    """Filter parsed injury rows to the requested period and build output records."""
    # This list will hold only validated injury events for this player.
    records = []
    # Use today's date to avoid accidentally keeping future-dated records.
    today = pd.Timestamp(date.today())
    # Process each row in the normalized injury table.
    for row in frame.to_dict("records"):
        # Read and parse the injury start date and season label.
        raw_from = normalize_space(row.get("from", ""))
        date_from = parse_date(raw_from)
        label = season_label(row.get("season", ""))
        # Convert the normalized date to a Timestamp, or NaT when unknown.
        parsed_from = pd.to_datetime(date_from, errors="coerce") if date_from else pd.NaT

        # When an exact start date exists, enforce the 2019-to-today window.
        if not pd.isna(parsed_from):
            if parsed_from < CUTOFF_DATE or parsed_from > today:
                continue
        # If the date is missing, use a valid season label to determine whether
        # the record is within scope.
        elif label:
            start_year = int(label[:4]) if re.match(r"^\d{4}-\d{4}$", label) else None
            if start_year is None or start_year < CUTOFF_DATE.year:
                continue
        # Reject undated records when there is no usable season to place them in time.
        else:
            # Keep undated events only if the table explicitly places them in
            # a post-cutoff season. Otherwise their time period is unknown.
            continue

        # Normalize the injury description and reject blank placeholder values.
        injury = normalize_space(row.get("injury", ""))
        if not injury or injury.casefold() in {"nan", "-"}:
            continue
        # Preserve the player ID/name, injury details, dates, and source URLs.
        records.append(
            {
                "player_id": player_id,
                "player": player,
                "injury_season": label,
                "injury": injury,
                "date_from": date_from,
                "date_until": parse_date(row.get("until", "")),
                "days_out": numeric_value(row.get("days", "")),
                "games_missed": numeric_value(row.get("games_missed", "")),
                "profile_url": profile_url,
                "injury_url": injury_url,
            }
        )
    # Return all valid injury events found for this player.
    return records


def safely_get(driver, url: str) -> str:
    """Load one URL with retries and return HTML after the page body is ready."""
    # Keep the final exception so a useful message can be raised after retries.
    last_error: Exception | None = None
    # Attempt the navigation up to the configured maximum number of times.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # Ask Chrome to navigate to the requested Transfermarkt page.
            driver.get(url)
            # Some valid injury pages have no table (no recorded injuries), and
            # a consent/block page has a different layout. Waiting specifically
            # for any table hides that distinction and wastes 75+ seconds per
            # player. Wait for the document/body, then let the column-aware
            # injury parser decide whether the page contains a usable table.
            # Wait until the document is interactive/complete and its body exists.
            # A table is deliberately not required here: the parser below must
            # distinguish an empty injury history from a blocked or changed page.
            WebDriverWait(driver, WAIT_SECONDS).until(
                lambda current: current.execute_script("return document.readyState") in ("interactive", "complete")
                and current.find_elements(By.TAG_NAME, "body")
            )
            # Read the fully rendered HTML for table parsing.
            html = driver.page_source
            # Convert page content to plain lowercase text for block detection.
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).casefold()
            # Raise instead of misclassifying a CAPTCHA or access-denied screen.
            if any(term in text for term in ("too many requests", "access denied", "captcha")):
                raise RuntimeError("Transfermarkt returned a block or CAPTCHA page")
            # Return HTML; the caller validates the injury table's actual columns.
            return html
        except (TimeoutException, WebDriverException, RuntimeError) as exc:
            # Save the last failure for the final diagnostic.
            last_error = exc
            # A dead WebDriver session cannot recover by retrying the same
            # driver. Let fetch_page replace it immediately instead.
            # A disconnected session cannot be repaired by retrying this instance;
            # re-raise so the outer fetch helper can restart Chrome.
            if is_lost_browser_session(exc):
                raise
            # Back off before another attempt, reducing pressure on the site.
            if attempt < MAX_ATTEMPTS:
                time.sleep((2 ** attempt) + random.uniform(1, 3))
    # Selenium timeouts often have no message, so add page title/URL diagnostics.
    if isinstance(last_error, TimeoutException):
        diagnostic = page_diagnostic(driver, url)
        raise RuntimeError(f"Failed to load {url}: {diagnostic}") from last_error
    # Include exception type and text for other navigation failures.
    raise RuntimeError(
        f"Failed to load {url}: {type(last_error).__name__}: {last_error}"
    ) from last_error


class BrowserSessionRecoveryError(RuntimeError):
    """Raised when Chrome cannot be recovered without risking bad checkpoints."""


def append_status(path: Path, columns: list[str], row: dict[str, object]) -> None:
    """Append one progress record to a roster or player status file."""
    # Keep append-only checkpoints so a long run does not rewrite the entire
    # status file once for every team or player.
    # Reuse the common CSV writer to keep schema and encoding consistent.
    append_csv(pd.DataFrame([row]), path, columns)


def safe_quit(driver) -> None:
    """Attempt to close Chrome without allowing teardown errors to crash the run."""
    # There is no browser process to close if startup never completed.
    if driver is None:
        return
    try:
        # Ask Selenium/UC to close its browser and driver resources.
        driver.quit()
    except Exception as exc:
        # Teardown errors (including Windows invalid-handle errors) are warnings;
        # data has already been checkpointed, so they should not mask scrape results.
        print(f"Browser shutdown warning (ignored): {exc}")


class SafeChrome(uc.Chrome):
    """Catch undetected_chromedriver's unguarded Windows destructor quit."""

    def __del__(self) -> None:
        try:
            # UC also calls quit during object finalization; attempt cleanup once more.
            self.quit()
        except Exception:
            # UC 3.5.x may raise WinError 6 while finalizing an already-closed
            # Chrome process. The scrape has already checkpointed its data.
            # Ignore destructor errors because Python may be shutting down and the
            # Windows console/process handles may already be invalid.
            pass


def create_driver(browser_path: str, chrome_major: int):
    """Start a Chrome session pinned to the installed browser version."""
    # Create a UC Chrome instance using the installed browser executable and version.
    driver = SafeChrome(
        options=uc.ChromeOptions(),
        browser_executable_path=browser_path,
        version_main=chrome_major,
    )
    # Bound each navigation so a stalled page cannot block forever.
    driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)
    # Return the ready-to-use browser instance.
    return driver


def is_lost_browser_session(error: Exception) -> bool:
    """Return True when an exception message indicates Chrome's session is dead."""
    # Normalize the message once for case-insensitive matching.
    message = str(error).casefold()
    # These Selenium/Chrome phrases indicate the current driver cannot be reused.
    return any(
        marker in message
        for marker in (
            "invalid session id",
            "session not created",
            "chrome not reachable",
            "disconnected: not connected to devtools",
            "target window already closed",
        )
    )


def main() -> None:
    # Announce the job and flush immediately so progress appears in the terminal.
    print("Starting Transfermarkt injury collection (2019 to current season)...", flush=True)
    # Refuse to begin when saving another checkpoint could fill the drive.
    require_free_space()
    # Require the input team-season URL list before initializing the browser.
    if not TEAM_URLS_FILE.is_file():
        raise FileNotFoundError(f"Missing team-season URL list: {TEAM_URLS_FILE}")
    # Read URLs, remove inline comments/trailing slashes, and ignore blank lines.
    source_urls = {
        line.strip().split("#", 1)[0].rstrip("/")
        for line in TEAM_URLS_FILE.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }
    # Keep only club-season URLs; league overview URLs cannot identify one roster.
    team_urls = {
        url for url in source_urls
        if "/verein/" in urlparse(url).path and "/saison_id/" in urlparse(url).path
    }
    # Count the source links excluded by the club-season URL filter.
    ignored_urls = len(source_urls) - len(team_urls)
    # Report the number of usable links and ignored overview links.
    print(f"Loaded {len(team_urls)} club-season links; ignoring {ignored_urls} non-club links.", flush=True)

    # Hold the browser object so the finally block can always close it.
    driver = None
    try:
        # UC's default can download the newest driver, which may be newer than
        # the installed Chrome. Pin its major version to the local browser.
        # Find the installed Chrome path and major version.
        browser_path, chrome_major = find_chrome_version()
        # Show which local Chrome installation the scraper will control.
        print(f"Chrome {chrome_major}: {browser_path}", flush=True)
        # Start the browser with a driver matching that Chrome version.
        driver = create_driver(browser_path, chrome_major)

        def fetch_page(url: str) -> str:
            # The browser variable may be replaced if its session is lost.
            nonlocal driver
            try:
                # Load the requested URL using timeout/retry handling.
                return safely_get(driver, url)
            except Exception as exc:
                # Ordinary page errors are handled by the caller; only restart
                # Chrome when Selenium reports that its session is no longer usable.
                if not is_lost_browser_session(exc):
                    raise
                # Tell the user that browser recovery is starting.
                print(
                    f"Chrome session was lost while fetching {url}; restarting browser and retrying.",
                    flush=True,
                )
                # Close the dead browser if possible and discard its reference.
                safe_quit(driver)
                driver = None
                try:
                    # Create a fresh Chrome session with the same executable/version.
                    driver = create_driver(browser_path, chrome_major)
                except Exception as startup_exc:
                    # Stop without corrupting checkpoints if Chrome cannot restart.
                    raise BrowserSessionRecoveryError(
                        f"Could not restart Chrome; stopping safely at {url}. "
                        "Completed checkpoints are preserved; rerun after fixing Chrome. "
                        f"Details: {startup_exc}"
                    ) from startup_exc
                try:
                    # Retry the original URL once using the new browser instance.
                    return safely_get(driver, url)
                except Exception as retry_exc:
                    # Let non-session errors reach normal caller handling.
                    if not is_lost_browser_session(retry_exc):
                        raise
                    # A second lost session is a reason to stop, not loop indefinitely.
                    raise BrowserSessionRecoveryError(
                        f"Chrome session failed again after restart; stopping safely at {url}. "
                        "Completed checkpoints are preserved; rerun after fixing Chrome. "
                        f"Details: {retry_exc}"
                    ) from retry_exc

        # Extract the start year from every valid input team URL.
        known_years = {
            int(team_metadata(url)[3][:4])
            for url in team_urls
        }
        # Determine the season active today.
        current_year = current_season_start()
        # Calculate which seasons from 2019 through the current one are missing.
        missing_years = sorted(set(range(CUTOFF_DATE.year, current_year + 1)) - known_years)
        # Discover missing club links by visiting each league's season page.
        for year in missing_years:
            # Report each year before requesting its five league pages.
            print(f"Discovering top-five club lists for missing season {year}-{year + 1}...")
            # Fetch all qualifying clubs for the missing season.
            additions = discover_season_team_urls(fetch_page, year)
            # Do not proceed if Transfermarkt returned no usable club list.
            if not additions:
                raise RuntimeError(
                    f"Could not discover any top-five league teams for season {year}-{year + 1}. "
                    "Check Transfermarkt access before scraping injuries."
                )
            # Include the newly found URLs in the complete club-season set.
            team_urls.update(additions)

        # Confirm the input/discovered list includes the current season.
        if current_year not in {int(team_metadata(url)[3][:4]) for url in team_urls}:
            raise RuntimeError(
                f"The club list does not include the current season {current_year}-{current_year + 1}."
            )

        # Build a focused current-squad seed list before the historical scrape:
        # top five clubs by Transfermarkt squad value in each top-five league,
        # plus all 2026 World Cup national-team squads.
        # Use a set because one club can appear in multiple discovery sources.
        focus_team_urls: set[str] = set()
        # Discover and prioritize the five highest-valued clubs in each league.
        for league_slug, league_code in TOP_FIVE_LEAGUES.items():
            # Get the current-season team start pages in market-value order.
            league_top_five = discover_top_club_urls(
                fetch_page, league_slug, league_code, current_year
            )
            # Add these teams to the high-priority roster collection set.
            focus_team_urls.update(league_top_five)
            # Print the chosen club slugs for transparency.
            print(
                f"Priority clubs found for {league_code}: "
                f"{', '.join(urlparse(url).path.split('/')[1] for url in league_top_five)}",
                flush=True,
            )
            # Pause between league ranking requests.
            time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))

        # Discover all participating national teams for the 2026 World Cup.
        world_cup_team_urls = discover_world_cup_team_urls(fetch_page)
        # Add national squads to the same high-priority team set.
        focus_team_urls.update(world_cup_team_urls)
        # Report how many national teams were found.
        print(
            f"Priority national teams found for World Cup 2026: {len(world_cup_team_urls)}",
            flush=True,
        )
        # Ensure focus teams are included even when absent from the historical URL list.
        team_urls.update(focus_team_urls)
        # Convert focus start pages to roster pages for priority matching below.
        focus_roster_urls = {
            team_metadata(url)[0] for url in focus_team_urls
        }
        # Sort team URLs to make subsequent runs follow a consistent order.
        team_urls = sorted(team_urls)

        # Read previous roster progress so successful pages are not downloaded again.
        roster_status = read_csv(ROSTER_STATUS_FILE, ROSTER_STATUS_COLUMNS)
        # Treat only rows explicitly marked `ok` as successfully completed rosters.
        completed_rosters = set(
            roster_status.loc[roster_status["status"].eq("ok"), "roster_url"].dropna().astype(str)
        )
        # Load roster rows already saved by this and earlier runs.
        rosters = read_csv(ROSTERS_FILE, ROSTER_COLUMNS)
        # Build player/team/season keys to avoid appending duplicate roster membership.
        roster_keys = set(
            zip(rosters["player_id"].astype(str), rosters["team_id"].astype(str), rosters["roster_season"].astype(str))
        ) if not rosters.empty else set()

        # Collect every roster page not marked successful in the status checkpoint.
        pending_rosters = []
        # Convert each start URL to its canonical roster URL and metadata.
        for team_url in team_urls:
            roster_url, team_id, team_slug, roster_season = team_metadata(team_url)
            # Add pages not already complete to the work queue.
            if roster_url not in completed_rosters:
                pending_rosters.append((roster_url, team_id, team_slug, roster_season))
        # Process priority current clubs/national squads before historical club rosters.
        pending_rosters.sort(key=lambda item: item[0] not in focus_roster_urls)

        # Count pending priority pages for the progress message.
        priority_rosters_pending = sum(
            roster_url in focus_roster_urls
            for roster_url, _, _, _ in pending_rosters
        )
        # Show remaining roster work and the subset that has priority.
        print(
            f"Roster pages to fetch: {len(pending_rosters)} / {len(team_urls)} "
            f"({priority_rosters_pending} priority club/national squads first)",
            flush=True,
        )
        # Scrape each pending club or national-team roster page.
        for index, (roster_url, team_id, team_slug, roster_season) in enumerate(pending_rosters, start=1):
            # Check disk space before fetching/writing another page.
            require_free_space()
            try:
                # Download the roster page with the common browser/retry handler.
                html = fetch_page(roster_url)
                # Extract the player profiles and their roster metadata.
                players = player_links_from_roster(html, roster_url)
                # An empty result usually signals blocked or changed page markup.
                if not players:
                    raise RuntimeError("No Transfermarkt player profile links found on roster page")

                # This list contains roster rows not already checkpointed.
                new_players = []
                # Compare each scraped player against the composite duplicate key.
                for player in players:
                    key = (player["player_id"], player["team_id"], player["roster_season"])
                    # Save only unseen player/team/season combinations.
                    if key not in roster_keys:
                        new_players.append(player)
                        roster_keys.add(key)
                # Append new roster memberships without rewriting earlier data.
                append_csv(pd.DataFrame(new_players), ROSTERS_FILE, ROSTER_COLUMNS)
                # Record that this roster page completed successfully.
                append_status(
                    ROSTER_STATUS_FILE,
                    ROSTER_STATUS_COLUMNS,
                    {
                        "roster_url": roster_url,
                        "team_id": team_id,
                        "team": team_slug.replace("-", " ").title(),
                        "roster_season": roster_season,
                        "status": "ok",
                        "player_count": len(players),
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "error": "",
                    },
                )
                # Print the squad's season, URL slug, and number of found players.
                print(f"[Roster {index}/{len(pending_rosters)}] {roster_season} {team_slug}: {len(players)} players")
            except Exception as exc:
                # Browser-recovery failures must stop the run; continuing would reuse
                # a dead driver for every remaining team.
                if isinstance(exc, BrowserSessionRecoveryError):
                    raise
                # Also stop if free disk space fell below the safety reserve.
                if shutil.disk_usage(SCRIPT_DIR).free < MIN_FREE_SPACE_BYTES:
                    raise RuntimeError(
                        "Disk space dropped below 1 GiB while saving rosters; "
                        "stopping safely. Checkpoints are preserved."
                    ) from exc
                # For a page-level failure, checkpoint the error and continue later.
                append_status(
                    ROSTER_STATUS_FILE,
                    ROSTER_STATUS_COLUMNS,
                    {
                        "roster_url": roster_url,
                        "team_id": team_id,
                        "team": team_slug.replace("-", " ").title(),
                        "roster_season": roster_season,
                        "status": "failed",
                        "player_count": 0,
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "error": str(exc)[:500],
                    },
                )
                # Report the failed URL without hiding the original exception.
                print(f"[Roster failed] {roster_url}: {exc}")
            # Space out requests whether this roster succeeded or failed.
            time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))

        # Reload the saved roster file so older and newly collected players are included.
        rosters = read_csv(ROSTERS_FILE, ROSTER_COLUMNS)
        # Keep one representative roster row per player for injury-page scraping.
        players = rosters.drop_duplicates("player_id", keep="last")
        # Read player-page statuses from previous runs.
        player_status = read_csv(PLAYER_STATUS_FILE, PLAYER_STATUS_COLUMNS)
        # Only successful pages and confirmed no-injury pages count as complete.
        completed_players = set(
            player_status.loc[
                player_status["status"].isin(["ok", "no_injuries"]), "player_id"
            ].dropna().astype(str)
        )
        # Load injury events already saved, so reruns can avoid duplicates.
        existing_injuries = read_csv(INJURIES_FILE, INJURY_COLUMNS)
        # This set holds event keys already present in the injury output.
        injury_keys = set()
        # Build keys only when there are existing event rows.
        if not existing_injuries.empty:
            # An injury event is considered the same when player, start/end dates,
            # and injury description match.
            injury_keys = set(
                zip(
                    existing_injuries["player_id"].astype(str),
                    existing_injuries["date_from"].fillna("").astype(str),
                    existing_injuries["date_until"].fillna("").astype(str),
                    existing_injuries["injury"].fillna("").astype(str),
                )
            )

        # Queue players whose injury page has not already completed successfully.
        pending_players = [
            row for row in players.to_dict("records")
            if str(row["player_id"]) not in completed_players
        ]
        # Read the current season start year for the focus-squad lookup below.
        current_year = current_season_start()
        # Identify players who belong to one of the priority current squads.
        focus_player_ids = set(
            rosters.loc[rosters["roster_url"].astype(str).isin(focus_roster_urls), "player_id"]
            .dropna()
            .astype(str)
        )
        # Scrape priority-squad players first, then continue with the broader roster set.
        pending_players.sort(key=lambda row: str(row["player_id"]) not in focus_player_ids)
        # Count priority players still pending.
        priority_players_pending = sum(
            str(row["player_id"]) in focus_player_ids for row in pending_players
        )
        # Report total pending players and priority subset before the long scrape.
        print(
            f"Player injury pages to fetch: {len(pending_players)} / {len(players)} "
            f"({priority_players_pending} from priority club/national squads first)",
            flush=True,
        )
        # Visit each uncompleted player's injury history page.
        for index, player in enumerate(pending_players, start=1):
            # Do not start another page if the output drive is almost full.
            require_free_space()
            # Extract the stable player ID, cleaned name, and injury-page URL.
            player_id = str(player["player_id"])
            player_name = normalize_space(player["player"])
            injury_url = normalize_space(player["injury_url"])
            try:
                # Load the individual injury-history page.
                html = fetch_page(injury_url)
                # Find the table by its Injury/From/Until headings.
                table = find_injury_table(html)
                # A missing matching table is an error, not proof of no injuries.
                if table is None:
                    # Read the page text to distinguish consent and block screens.
                    page_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).casefold()
                    # Explain when the user needs to choose a Transfermarkt consent option.
                    if any(term in page_text for term in (
                        "accept & continue",
                        "welcome! how would you like to use transfermarkt",
                        "consent required",
                    )):
                        reason = "Transfermarkt consent screen is open; choose an option in Chrome and rerun."
                    # Mark anti-bot or access-denied pages with a specific reason.
                    elif any(term in page_text for term in ("too many requests", "access denied", "captcha")):
                        reason = "Transfermarkt returned a block or CAPTCHA page."
                    # Otherwise report the expected table headings that were missing.
                    else:
                        reason = "No injury-history table with Injury/From/Until columns was found."
                    # Raise so this player is marked failed and retried on a later run.
                    raise RuntimeError(reason)
                # Convert the parsed table rows into validated event records since 2019.
                records = make_injury_records(
                    table,
                    player_id,
                    player_name,
                    normalize_space(player["profile_url"]),
                    injury_url,
                )
                # Store only event records not already in the dataset.
                new_records = []
                # Examine each normalized event for duplicate status.
                for record in records:
                    # Build a stable event key from player, dates, and injury name.
                    key = (
                        record["player_id"], record["date_from"],
                        record["date_until"], record["injury"],
                    )
                    # Append unseen events and immediately reserve their keys.
                    if key not in injury_keys:
                        new_records.append(record)
                        injury_keys.add(key)
                # Persist new injury rows immediately so an interruption loses little work.
                append_csv(pd.DataFrame(new_records), INJURIES_FILE, INJURY_COLUMNS)
                # Record success or a confirmed empty history in the player checkpoint.
                append_status(
                    PLAYER_STATUS_FILE,
                    PLAYER_STATUS_COLUMNS,
                    {
                        "player_id": player_id,
                        "player": player_name,
                        "status": "ok" if records else "no_injuries",
                        "injury_count": len(records),
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "error": "",
                    },
                )
                # Show how many in-scope injuries were found for this player.
                print(f"[Player {index}/{len(pending_players)}] {player_name}: {len(records)} injuries since 2019")
            except Exception as exc:
                # Stop immediately if browser recovery failed; do not continue with a dead session.
                if isinstance(exc, BrowserSessionRecoveryError):
                    raise
                # If storage is critically low, stop with all prior checkpoints intact.
                if shutil.disk_usage(SCRIPT_DIR).free < MIN_FREE_SPACE_BYTES:
                    raise RuntimeError(
                        "Disk space dropped below 1 GiB while saving injuries; "
                        "stopping safely. Checkpoints are preserved."
                    ) from exc
                # Record this player as failed so a later run can try again.
                append_status(
                    PLAYER_STATUS_FILE,
                    PLAYER_STATUS_COLUMNS,
                    {
                        "player_id": player_id,
                        "player": player_name,
                        "status": "failed",
                        "injury_count": 0,
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "error": str(exc)[:500],
                    },
                )
                # Print a concise player-specific error in the terminal.
                print(f"[Player failed] {player_name} ({player_id}): {exc}")
            # Pause before the next player to reduce request rate.
            time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))

        # Print the final locations of the main outputs and progress checkpoints.
        print(f"\nDone. Rosters: {ROSTERS_FILE}")
        print(f"Injury events since 2019: {INJURIES_FILE}")
        print(f"Resume status files: {ROSTER_STATUS_FILE}, {PLAYER_STATUS_FILE}")
    except Exception as exc:
        # Surface fatal failures with their exception class and message, then preserve
        # normal Python error propagation for a full traceback in the terminal.
        print(f"Scraper stopped: {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        # Always try to close Chrome, even when scraping ended with an exception.
        safe_quit(driver)


# Run `main()` only when this file is executed directly, not when imported elsewhere.
if __name__ == "__main__":
    # Start the complete roster and injury-history collection workflow.
    main()
