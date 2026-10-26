import pandas as pd
import time
import random
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from io import StringIO

print("🚀 Starting Precise FBref Updater (Targeting Player Physical Columns)...")

# المواسم الجديدة المطلوبة
recent_seasons = ["2024-2025", "2025-2026"]

# Read the source links relative to this script, so launching it from another
# working directory does not make the input/output paths unexpectedly change.
script_dir = Path(__file__).resolve().parent
input_filename = 'top5_teams_links_5years.txt'
# In this project the scraper is in a subfolder while its link list and data
# files live in the project root. Also support keeping the link list beside
# the script by falling back to script_dir when it is not in the parent.
project_dir = script_dir.parent if (script_dir.parent / input_filename).is_file() else script_dir
links_file = project_dir / input_filename
if not links_file.is_file():
    raise FileNotFoundError(f"Required squad link file was not found: {links_file}")
with links_file.open('r', encoding='utf-8-sig') as file:
    old_links = [line.strip() for line in file if line.strip()]

# استخراج كود الفريق واسمه لديناميكية تتبع المواسم الجديدة
team_base_urls = set()
for link in old_links:
    parts = [part for part in urlparse(link).path.split('/') if part]
    try:
        squads_index = parts.index('squads')
        squad_parts = parts[squads_index + 1:]
        squad_id = squad_parts[0]
        # Accept both /squads/{id}/{team} and
        # /squads/{id}/{season}/{team} FBref URL formats.
        if len(squad_parts) >= 3 and squad_parts[1].count('-') == 1:
            team_name_slug = squad_parts[2]
        else:
            team_name_slug = squad_parts[1]
    except (ValueError, IndexError):
        print(f"⚠️ Skipping unrecognized FBref squad URL: {link}")
        continue
    if squad_id and team_name_slug:
        team_base_urls.add((squad_id, team_name_slug))

if not team_base_urls:
    raise ValueError(f"No valid squad links found in '{links_file}'.")
team_base_urls = sorted(team_base_urls)

output_csv = project_dir / "master_players_physical_data_updated.csv"

# الأعمدة المطلوبة بدقة كما حددتها
desired_columns = ['Player', 'Nation', 'Pos', 'Age', 'MP', 'Starts', 'Min']
summary_rows = {'player', 'squad total', 'opponent total'}

def record_key(row):
    """Stable key used to make appending safe when a scrape is resumed."""
    return (
        str(row['Player']).strip().casefold(),
        str(row['Team']).strip().casefold(),
        str(row['Season']).strip(),
    )


# Load existing keys once so a later run can safely resume without appending
# the same player/team/season records again.
saved_keys = set()
if output_csv.exists() and output_csv.stat().st_size > 0:
    existing_df = pd.read_csv(output_csv, encoding='utf-8-sig', low_memory=False)
    if 'Player' in existing_df.columns:
        player_labels = existing_df['Player'].fillna('').astype(str).str.strip().str.casefold()
        existing_df = existing_df.loc[~player_labels.isin(summary_rows)].copy()
        # Remove aggregate rows left by earlier scraper versions before resume.
        existing_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    existing_df = existing_df[['Player', 'Team', 'Season']]
    saved_keys = {record_key(row) for _, row in existing_df.iterrows()}

options = uc.ChromeOptions()
driver = None

try:
    # The installed browser shown in the current environment is Chrome 153.
    # Pin the matching driver major to avoid UC selecting driver 154.
    driver = uc.Chrome(options=options, version_main=153)
    for season in recent_seasons:
        print(f"\n📅 Processing Season: {season}")
        
        for squad_id, team_slug in team_base_urls:
            target_url = f"https://fbref.com/en/squads/{squad_id}/{season}/{team_slug}"
            print(f"🔗 Fetching: {target_url}")
            
            try:
                driver.get(target_url)
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                time.sleep(4)
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                target_df = None
                candidate_tables = []

                # Prefer FBref's standard player stats table. As a fallback,
                # inspect other tables but accept only one with both required
                # player-stat headers (standings tables do not qualify).
                stats_table = soup.find('table', id='stats_standard')
                if stats_table is not None:
                    candidate_tables.append(stats_table)
                candidate_tables.extend(
                    table for table in soup.find_all('table') if table is not stats_table
                )

                for table in candidate_tables:
                    try:
                        parsed = pd.read_html(StringIO(str(table)))[0]
                    except (ValueError, IndexError):
                        continue

                    if isinstance(parsed.columns, pd.MultiIndex):
                        parsed.columns = [
                            next((str(level).strip() for level in reversed(column)
                                  if str(level).strip() and not str(level).startswith('Unnamed: ')), '')
                            for column in parsed.columns
                        ]

                    parsed.columns = [str(column).strip() for column in parsed.columns]
                    if {'Player', 'Min'}.issubset(parsed.columns):
                        target_df = parsed
                        break
                
                if target_df is not None and not target_df.empty:
                    target_df = target_df.dropna(how='all')
                    target_df = target_df[target_df['Player'].notna()]
                    player_labels = target_df['Player'].astype(str).str.strip().str.casefold()
                    target_df = target_df.loc[~player_labels.isin(summary_rows)]
                    
                    # اختيار الأعمدة الموجودة فقط من القائمة المطلوبة لضمان عدم حدوث أخطاء
                    actual_columns = [col for col in desired_columns if col in target_df.columns]
                    cleaned_df = target_df[actual_columns].copy()
                    
                    # إضافة أعمدة إضافية للتنظيم والدمج لاحقاً
                    cleaned_df['Season'] = season
                    cleaned_df['Team'] = team_slug.replace('-Stats', '').replace('-', ' ').title()

                    # Keep the scraper resumable: a rerun only appends records
                    # that are not already present in the master update file.
                    row_keys = cleaned_df.apply(record_key, axis=1)
                    cleaned_df = cleaned_df.loc[~row_keys.isin(saved_keys)].copy()
                    if cleaned_df.empty:
                        print(f"   ↪ Already collected: {team_slug} ({season})")
                        continue
                    
                    # الحفظ المباشر
                    # utf-8-sig writes the BOM only when creating/initializing
                    # the file. Use plain UTF-8 on later appends to avoid an
                    # embedded BOM before every appended header/data block.
                    has_content = output_csv.exists() and output_csv.stat().st_size > 0
                    with output_csv.open(
                        'a', encoding='utf-8' if has_content else 'utf-8-sig', newline=''
                    ) as csv_file:
                        cleaned_df.to_csv(csv_file, index=False, header=not has_content)
                    saved_keys.update(record_key(row) for _, row in cleaned_df.iterrows())
                    print(f"   ✅ Saved accurate physical data for: {team_slug}")
                    
            except Exception as e:
                print(f"   ⚠️ Error processing link: {e}")
                continue
                
            time.sleep(random.uniform(3, 6))

    print(f"\n🏁 Finished updating physical stats with requested columns! Saved to '{output_csv}'.")

except Exception as e:
    print(f"❌ Critical Error: {e}")

finally:
    if driver is not None:
        try:
            driver.quit()
        except Exception as teardown_error:
            # Chrome may already have exited, or Windows may report an invalid
            # console handle while undetected_chromedriver shuts down.
            print(f"⚠️ Browser cleanup failed safely: {teardown_error}")
