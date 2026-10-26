import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO
from pathlib import Path
import time
import random
import os

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"

print("🚀 Starting MASTER Transfermarkt Scraper (Using Updated Teams List)...")

# قراءة الروابط من الملف المحدث اللي لسه مخلصه
with open(DATA_RAW / 'tm_top5_teams_updated.txt', 'r') as file:
    team_links = [line.strip() for line in file if line.strip()]

csv_filename = str(DATA_RAW / "master_transfermarkt_injuries.csv")

options = uc.ChromeOptions()
driver = uc.Chrome(options=options, version_main=153)

try:
    for team_index, team_url in enumerate(team_links, start=1):
        team_name = team_url.split('/')[3].replace('-', ' ').title()
        print(f"\n⚙️ [{team_index}/{len(team_links)}] Processing Team: {team_name}")
        
        try:
            driver.get(team_url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(3)
            
            links = driver.find_elements(By.TAG_NAME, "a")
            player_dict = {} 
            
            for el in links:
                try:
                    href = el.get_attribute("href")
                    if href and "/profil/spieler/" in href:
                        raw_name = href.split(".com/")[1].split("/profil")[0]
                        name = raw_name.replace("-", " ").title()
                        
                        if name not in player_dict:
                            injury_link = href.replace("profil", "verletzungen")
                            player_dict[name] = injury_link
                except:
                    continue

            print(f"   👥 Found {len(player_dict)} players in {team_name}. Extracting injuries...")

            for player_name, injury_url in player_dict.items():
                try:
                    driver.get(injury_url)
                    time.sleep(random.uniform(4, 7))
                    
                    html_content = driver.page_source
                    tables = pd.read_html(StringIO(html_content))
                    
                    target_df = None
                    for df in tables:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(0)
                            
                        cols = [str(c).lower() for c in df.columns]
                        if any('injury' in c for c in cols) or any('days' in c for c in cols):
                            target_df = df
                            break
                    
                    if target_df is not None and not target_df.empty:
                        target_df = target_df.dropna(how='all')
                        target_df['Player'] = player_name
                        target_df['Team'] = team_name 
                        
                        file_exists = os.path.isfile(csv_filename)
                        target_df.to_csv(csv_filename, mode='a', index=False, encoding='utf-8-sig', header=not file_exists)
                        
                except Exception:
                    continue 
                
        except Exception as e:
            print(f"   ❌ Error processing team {team_name}: {e}")
            continue
            
except Exception as e:
    print(f"❌ Critical Error: {e}")

finally:
    driver.quit()
    print(f"\n🏁 Finished ALL TEAMS! Data saved to '{csv_filename}'.")