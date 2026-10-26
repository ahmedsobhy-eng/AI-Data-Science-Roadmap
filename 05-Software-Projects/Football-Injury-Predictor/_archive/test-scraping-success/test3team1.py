import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO
import time
import random
import os

print("🚀 Starting Master Scraper (Top 5 Leagues Data Pipeline)...")

# 1. قائمة الروابط (عينة مبدئية للتجربة قبل ما نحط الـ 500 رابط)
# هنحط لينك أرسنال السنة دي، أرسنال السنة اللي فاتت، ومانشستر سيتي عشان نجرب الدمج
urls_to_scrape = [
    {"team": "Arsenal", "season": "2023-2024", "url": "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"},
    {"team": "Arsenal", "season": "2022-2023", "url": "https://fbref.com/en/squads/18bb7c10/2022-2023/Arsenal-Stats"},
    {"team": "Man City", "season": "2023-2024", "url": "https://fbref.com/en/squads/b8fd03ef/Manchester-City-Stats"}
]

csv_filename = "master_players_data.csv"

try:
    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options, version_main=153)
    
    # 2. الحلقة التكرارية (For Loop) اللي هتلف على كل الروابط
    for item in urls_to_scrape:
        team_name = item["team"]
        season = item["season"]
        link = item["url"]
        
        print(f"\n⏳ Processing: {team_name} ({season})")
        
        try:
            driver.get(link)
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(5) # انتظار إضافي لضمان تحميل كل الجداول
            
            html_content = driver.page_source
            tables = pd.read_html(StringIO(html_content))
            target_df = None

            # البحث عن الجدول الصحيح
            for df in tables:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(0)
                if 'Player' in df.columns and 'Age' in df.columns and 'Min' in df.columns:
                    target_df = df
                    break

            if target_df is not None:
                # فلترة وتنظيف
                project_data = target_df[['Player', 'Age', 'Min']].copy()
                project_data = project_data.dropna()
                
                # إضافة عواميد جديدة عشان نعرف الداتا دي بتاعة مين وسنة كام
                project_data['Team'] = team_name
                project_data['Season'] = season

                # 3. حفظ متكرر (Append): لو الملف مش موجود هيكتبه، لو موجود هيلزق الداتا تحته
                file_exists = os.path.isfile(csv_filename)
                project_data.to_csv(csv_filename, mode='a', index=False, encoding='utf-8-sig', header=not file_exists)
                
                print(f"✅ Saved {len(project_data)} players for {team_name} ({season})")
            else:
                print(f"❌ Table not found for {team_name} ({season})")
        
        except Exception as inner_e:
            print(f"⚠️ Error skipping {team_name} ({season}): {inner_e}")
            continue # كمل الفريق اللي بعده متوقفش البرنامج
            
        # 4. التمويه (Random Sleep): استنى وقت عشوائي بين 5 لـ 12 ثانية قبل الفريق الجديد
        sleep_time = random.uniform(5, 12)
        print(f"💤 Sleeping for {sleep_time:.1f} seconds to avoid Cloudflare ban...")
        time.sleep(sleep_time)

except Exception as e:
    print(f"❌ Critical Error: {e}")

finally:
    try:
        driver.quit()
        print("\n🏁 Scraping Session Finished! Browser closed.")
    except:
        pass