import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO
import time
import random
import os

print("🚀 Starting Transfermarkt Scraper (Extracting Injury Histories)...")

# هنختبر السكريبت على فريق أرسنال بالكامل الأول قبل ما نوسع النطاق
team_url = "https://www.transfermarkt.com/fc-arsenal/kader/verein/11/saison_id/2023"
csv_filename = "transfermarkt_injuries.csv"

options = uc.ChromeOptions()
driver = uc.Chrome(options=options, version_main=153)

try:
    print(f"🔗 Accessing Team Page...")
    driver.get(team_url)
    
    # ننتظر تحميل الصفحة
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
    time.sleep(4)
    
    # 1. سحب روابط اللاعبين وتحويلها لروابط إصابات
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

    print(f"✅ Found {len(player_dict)} players. Starting injury data extraction...\n")

    # 2. الدخول على صفحة كل لاعب لسحب جدول الإصابات
    count = 1
    for player_name, injury_url in player_dict.items():
        print(f"⏳ [{count}/{len(player_dict)}] Extracting data for: {player_name}")
        
        try:
            driver.get(injury_url)
            # تمويه وتقليل الضغط على السيرفر
            time.sleep(random.uniform(4, 7))
            
            html_content = driver.page_source
            tables = pd.read_html(StringIO(html_content))
            
            target_df = None
            for df in tables:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(0)
                    
                # الذكاء الاصطناعي هنا: بنبحث عن الجدول اللي فيه كلمة Injury أو Days (أيام الغياب)
                cols = [str(c).lower() for c in df.columns]
                if any('injury' in c for c in cols) or any('days' in c for c in cols):
                    target_df = df
                    break
            
            # 3. معالجة البيانات وحفظها
            if target_df is not None and not target_df.empty:
                # مسح الصفوف الفارغة
                target_df = target_df.dropna(how='all')
                
                # إضافة عمود باسم اللاعب عشان الدمج في الـ SQL بعدين
                target_df['Player'] = player_name
                
                # الحفظ بنظام الإلحاق (Append)
                file_exists = os.path.isfile(csv_filename)
                target_df.to_csv(csv_filename, mode='a', index=False, encoding='utf-8-sig', header=not file_exists)
                
                print(f"   ✅ Saved {len(target_df)} injury records.")
            else:
                print(f"   ⚠️ No injury records found (Player might have clean history).")
                
        except Exception as e:
            print(f"   ❌ Could not extract data for {player_name}: {e}")
        
        count += 1
        
        # (اختياري) لو عايز تجرب في أول 5 لعيبة بس شيل علامة الـ # من السطرين الجايين:
        # if count > 5:
        #     break

except Exception as e:
    print(f"❌ Critical Error: {e}")

finally:
    driver.quit()
    print(f"\n🏁 Finished! Check your '{csv_filename}' file.")