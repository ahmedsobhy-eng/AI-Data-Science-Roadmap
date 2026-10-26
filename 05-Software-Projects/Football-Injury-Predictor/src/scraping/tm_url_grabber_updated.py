import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pathlib import Path
import time
import random

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"

print("🚀 Updating Transfermarkt URL Grabber (Up to 2025/2026 Season)...")

# مدين النطاق الزمني لحد 2025 عشان نغطي أحدث المواسم
seasons = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]

leagues = {
    "premier-league": "GB1",
    "primera-division": "ES1",
    "serie-a": "IT1",
    "1-bundesliga": "L1",
    "ligue-1": "FR1"
}

team_links = set()

options = uc.ChromeOptions()
driver = uc.Chrome(options=options, version_main=153)

try:
    for season in seasons:
        for league_name, league_code in leagues.items():
            url = f"https://www.transfermarkt.com/{league_name}/startseite/wettbewerb/{league_code}/saison_id/{season}"
            print(f"\n🔗 Accessing: {league_name.upper()} (Season {season})")
            
            driver.get(url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(3)
            
            links = driver.find_elements(By.XPATH, "//table[@class='items']//td[@class='hauptlink no-border-links']//a")
            
            count = 0
            for el in links:
                href = el.get_attribute('href')
                if href and '/spielplan/' not in href:
                    team_links.add(href)
                    count += 1
                    
            print(f"✅ Total UNIQUE teams so far: {len(team_links)}")
            time.sleep(random.uniform(4, 7))

    # حفظ الروابط المحدثة في ملف جديد
    with open(DATA_RAW / 'tm_top5_teams_updated.txt', 'w') as file:
        for link in team_links:
            file.write(f"{link}\n")
            
    print(f"\n🎯 BOOM! Saved {len(team_links)} UNIQUE team links to 'tm_top5_teams_updated.txt'")

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    try:
        driver.quit()
    except:
        pass