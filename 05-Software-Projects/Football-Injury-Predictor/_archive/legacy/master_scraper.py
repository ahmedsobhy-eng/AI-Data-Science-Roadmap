import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO
import time
import random
import os
import re

print("🚀 Starting Data Pipeline (Extracting Enhanced Physical Features for 488 Teams)...")

# قراءة الـ 488 رابط
with open('top5_teams_links_5years.txt', 'r') as file:
    links = [line.strip() for line in file if line.strip()]

csv_filename = "master_players_physical_data.csv"

try:
    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options, version_main=153)
    
    for index, link in enumerate(links, start=1):
        team_name = link.split('/')[-1].replace('-Stats', '').replace('-', ' ')
        season_match = re.search(r'(\d{4}-\d{4})', link)
        season = season_match.group(1) if season_match else "2023-2024"

        print(f"\n⏳ [{index}/{len(links)}] Processing: {team_name} ({season})")
        
        try:
            driver.get(link)
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            time.sleep(4) 
            
            html_content = driver.page_source
            tables = pd.read_html(StringIO(html_content))
            target_df = None

            for df in tables:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(0)
                if 'Player' in df.columns and 'Age' in df.columns and 'Min' in df.columns:
                    target_df = df
                    break

            if target_df is not None:
                # ====== التعديل الجديد (Feature Engineering) ======
                # هنطلب عواميد أكتر بتأثر على الإرهاق والإصابات:
                # Pos (المركز), MP (المباريات الملعوبة), Starts (المباريات كأساسي)
                desired_columns = ['Player', 'Nation', 'Pos', 'Age', 'MP', 'Starts', 'Min']
                
                # هنتأكد إن العواميد دي موجودة فعلاً في الجدول عشان الكود ميضربش
                actual_columns = [col for col in desired_columns if col in target_df.columns]
                
                project_data = target_df[actual_columns].copy()
                # هنحذف الصفوف الفاضية بناءً على العواميد الأساسية بس
                project_data = project_data.dropna(subset=['Player', 'Age', 'Min'])
                # ===================================================
                
                project_data['Team'] = team_name
                project_data['Season'] = season

                file_exists = os.path.isfile(csv_filename)
                project_data.to_csv(csv_filename, mode='a', index=False, encoding='utf-8-sig', header=not file_exists)
                
                print(f"✅ Saved {len(project_data)} players with extended features.")
            else:
                print(f"❌ Table not found.")
        
        except Exception as inner_e:
            print(f"⚠️ Error, skipping: {inner_e}")
            continue
            
        sleep_time = random.uniform(5, 10)
        print(f"💤 Sleeping for {sleep_time:.1f} seconds...")
        time.sleep(sleep_time)

except Exception as e:
    print(f"❌ Critical Error: {e}")

finally:
    try:
        driver.quit()
        print("\n🏁 FBref Mission Complete! Browser closed.")
    except:
        pass