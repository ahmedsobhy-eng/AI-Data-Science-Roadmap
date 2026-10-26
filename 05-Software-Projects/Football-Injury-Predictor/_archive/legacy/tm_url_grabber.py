import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random

print("🚀 Starting Transfermarkt URL Grabber (Top 5 Leagues - 5 Years History)...")

# المواسم المطلوبة (من 2019 لحد 2023)
seasons = ["2019", "2020", "2021", "2022", "2023"]

# أكواد الدوريات الخمسة الكبرى في Transfermarkt
leagues = {
    "premier-league": "GB1",
    "primera-division": "ES1",
    "serie-a": "IT1",
    "1-bundesliga": "L1",
    "ligue-1": "FR1"
}

# استخدام Set لمنع تكرار الفرق اللي استمرت أكتر من موسم
team_links = set()

options = uc.ChromeOptions()
driver = uc.Chrome(options=options, version_main=153)

try:
    for season in seasons:
        for league_name, league_code in leagues.items():
            url = f"https://www.transfermarkt.com/{league_name}/startseite/wettbewerb/{league_code}/saison_id/{season}"
            print(f"\n🔗 Accessing: {league_name.upper()} (Season {season})")
            
            driver.get(url)
            
            # ننتظر تحميل جدول الترتيب
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(3)
            
            # استخراج روابط الفرق
            links = driver.find_elements(By.XPATH, "//table[@class='items']//td[@class='hauptlink no-border-links']//a")
            
            count = 0
            for el in links:
                href = el.get_attribute('href')
                # فلترة الروابط الإضافية عشان ناخد رابط الفريق الأساسي بس
                if href and '/spielplan/' not in href:
                    team_links.add(href)
                    count += 1
                    
            print(f"✅ Extracted links. Total UNIQUE teams so far: {len(team_links)}")
            
            # تمويه قوي لأننا هنلف على 25 صفحة
            sleep_time = random.uniform(5, 8)
            print(f"💤 Sleeping for {sleep_time:.1f} seconds...")
            time.sleep(sleep_time)

    # حفظ الروابط الفريدة في ملف Text
    with open('tm_top5_teams_5years.txt', 'w') as file:
        for link in team_links:
            file.write(f"{link}\n")
            
    print(f"\n🎯 BOOM! Mission Accomplished. Saved {len(team_links)} UNIQUE team links to 'tm_top5_teams_5years.txt'")

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    try:
        driver.quit()
    except:
        pass