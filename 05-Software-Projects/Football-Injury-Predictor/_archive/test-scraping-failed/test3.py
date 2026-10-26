import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO

print("🚀 Starting Stealth Browser (Bypassing Cloudflare)...")

try:
    # 1. تشغيل المتصفح الشبح (بدون أي إضافات تكشف إننا بوت)
    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options, version_main=153)
    
    url = "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"
    print(f"🔗 Opening URL: {url}")
    driver.get(url)

    print("⏳ Waiting for Cloudflare verification and table loading (up to 20 seconds)...")
    
    # 2. الانتظار الذكي (مزودين الوقت لـ 20 ثانية عشان ندي فرصة لـ Cloudflare يتأكد إننا إنسان)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # 3. سحب كود الجدول تحديداً بعد ما يظهر
    table_element = driver.find_element(By.TAG_NAME, "table")
    table_html = table_element.get_attribute('outerHTML')

    print("📊 Table found! Extracting data...")
    
    # 4. قراءة البيانات بالبانداز وتجهيزها لمشروع الإصابات
    tables = pd.read_html(StringIO(table_html))
    df = tables[0]
    
    df.columns = df.columns.droplevel(0)
    project_data = df[['Player', 'Age', 'Min']]
    project_data = project_data.dropna()

    # 5. حفظ الملف
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