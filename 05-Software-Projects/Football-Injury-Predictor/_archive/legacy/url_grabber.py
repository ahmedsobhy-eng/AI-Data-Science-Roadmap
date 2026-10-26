import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random

print("🚀 Starting URL Grabber (Collecting Top 5 Leagues Team Links for 5 Years)...")

# 1. تحديد المواسم الخمسة
seasons = ["2019-2020", "2020-2021", "2021-2022", "2022-2023", "2023-2024"]

# 2. أرقام الدوريات الخمسة الكبرى في موقع FBref
# 9=Premier League, 12=La Liga, 11=Serie A, 20=Bundesliga, 13=Ligue 1
league_codes = {
    "Premier-League": 9,
    "La-Liga": 12,
    "Serie-A": 11,
    "Bundesliga": 20,
    "Ligue-1": 13
}

league_urls = []

# 3. توليد الروابط أوتوماتيكياً لكل دوري في كل موسم
for season in seasons:
    for league_name, code in league_codes.items():
        url = f"https://fbref.com/en/comps/{code}/{season}/{season}-{league_name}-Stats"
        league_urls.append(url)

all_team_links = set()

try:
    options = uc.ChromeOptions()
    # حددنا إصدار 153 المتوافق مع جهازك
    driver = uc.Chrome(options=options, version_main=153)

    for league_url in league_urls:
        print(f"\n🔗 Accessing League: {league_url.split('/')[-1]}")
        driver.get(league_url)
        
        # بنستنى لحد ما جدول الترتيب يظهر
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(3)
        
        # بنقوله هات أي لينك (a) جوه خانة (td) نوعها (team) .. دي بتصطاد لينكات الفرق بس!
        elements = driver.find_elements(By.XPATH, "//td[@data-stat='team']//a")
        
        count = 0
        for el in elements:
            href = el.get_attribute('href')
            if href and '/squads/' in href:
                all_team_links.add(href)
                count += 1
                
        print(f"✅ Extracted {count} team links from this league.")
        
        # تمويه عشوائي لـ Cloudflare عشان ميحسش إننا بوت سريع
        sleep_time = random.uniform(4, 8)
        print(f"💤 Sleeping for {sleep_time:.1f} seconds...")
        time.sleep(sleep_time)

    # 4. حفظ كل اللينكات اللي جمعناها في ملف Text
    with open('top5_teams_links_5years.txt', 'w') as file:
        for link in all_team_links:
            file.write(f"{link}\n")
            
    print(f"\n🎯 BOOM! Mission Accomplished. Saved {len(all_team_links)} unique team links to 'top5_teams_links_5years.txt'")

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    try:
        driver.quit()
    except:
        pass