from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO

print("🚀 Starting Selenium...")

# إعدادات المتصفح
options = webdriver.ChromeOptions()
# options.add_argument('--headless') # ممكن تفعل السطر ده لو مش عايز المتصفح يظهر قدامك

try:
    # 1. تشغيل المتصفح
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    url = "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"
    print(f"🔗 Opening URL: {url}")
    driver.get(url)

    print("⏳ Waiting for the stats table to load on the page (up to 15 seconds)...")
    
    # 2. الانتظار الذكي: الكود هيستنى لحد 15 ثانية كحد أقصى لحد ما يلاقي أول جدول
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # 3. تحديد الجدول وسحب كود הـ HTML بتاعه تحديداً
    table_element = driver.find_element(By.TAG_NAME, "table")
    table_html = table_element.get_attribute('outerHTML')

    print("📊 Table found! Extracting data...")
    
    # 4. قراءة الجدول باستخدام Pandas
    tables = pd.read_html(StringIO(table_html))
    df = tables[0]
    
    # مسح العنوان الإضافي اللي فوق الأعمدة وتحديد الأعمدة المطلوبة لمشروعنا
    df.columns = df.columns.droplevel(0)
    project_data = df[['Player', 'Age', 'Min']]
    
    # تنظيف البيانات من أي صفوف فاضية
    project_data = project_data.dropna()

    # 5. حفظ البيانات في ملف CSV
    project_data.to_csv('arsenal_players_data.csv', index=False, encoding='utf-8-sig')

    print("✅ Success! Data saved to 'arsenal_players_data.csv'")
    print(project_data.head())

except Exception as e:
    print(f"❌ Error occurred: {e}")

finally:
    # 6. قفل المتصفح لتوفير موارد الجهاز
    try:
        driver.quit()
    except:
        pass