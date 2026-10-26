import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO

print("🚀 Starting Stealth Browser (Bypassing Cloudflare)...")

try:
    options = uc.ChromeOptions()
    # حددنا إصدار 153 عشان يتوافق مع جهازك
    driver = uc.Chrome(options=options, version_main=153)
    
    url = "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"
    print(f"🔗 Opening URL: {url}")
    driver.get(url)

    print("⏳ Waiting for Cloudflare verification and table loading (up to 20 seconds)...")
    
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    table_element = driver.find_element(By.TAG_NAME, "table")
    table_html = table_element.get_attribute('outerHTML')

    print("📊 Table found! Extracting data...")
    
    tables = pd.read_html(StringIO(table_html))
    df = tables[0]
    
    # -------- التعديل الذكي لحل مشكلة الـ Pandas --------
    # بنسأل بايثون: هل الجدول ده متكون من طبقتين من العناوين؟
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(0) # لو أيوة، امسح الطبقة الأولى
    # -----------------------------------------------------

    project_data = df[['Player', 'Age', 'Min']]
    project_data = project_data.dropna()

    project_data.to_csv('arsenal_players_data.csv', index=False, encoding='utf-8-sig')

    print("✅ Success! Cloudflare bypassed and data saved to 'arsenal_players_data.csv'")
    print(project_data.head())

except Exception as e:
    print(f"❌ Error occurred: {e}")

finally:
    try:
        driver.quit()
    except:
        pass