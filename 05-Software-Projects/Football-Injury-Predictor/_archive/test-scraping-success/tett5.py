import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from io import StringIO
import time

print("🚀 Starting Stealth Browser (Bypassing Cloudflare)...")

try:
    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options, version_main=153)
    
    url = "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"
    print(f"🔗 Opening URL: {url}")
    driver.get(url)

    print("⏳ Waiting for page to load (up to 20 seconds)...")
    
    # نستنى لحد ما الجدول يظهر
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # نزود وقت انتظار بسيط عشان نتأكد إن كل حاجة حملت (خصوصاً لو في جداول مخفية بتظهر بعد ثواني)
    time.sleep(5)

    print("📊 Page loaded! Searching for the correct player table...")
    
    # نسحب الصفحة كلها
    html_content = driver.page_source
    
    # نستخرج كل الجداول اللي في الصفحة
    tables = pd.read_html(StringIO(html_content))
    
    target_df = None

    # الكود هنا بيلف على كل الجداول اللي سحبها
    for i, df in enumerate(tables):
        # بننظف العناوين لو مزدوجة عشان نعرف نقرأها
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(0)
            
        # بنسأل: هل الجدول ده فيه العواميد اللي إحنا عايزينها؟
        if 'Player' in df.columns and 'Age' in df.columns and 'Min' in df.columns:
            target_df = df
            print(f"✅ Found the correct table at index {i}!")
            break # أول ما يلاقيه، يوقف تدوير

    # لو لقى الجدول المطلوب، يسحب منه الداتا
    if target_df is not None:
        project_data = target_df[['Player', 'Age', 'Min']]
        project_data = project_data.dropna()

        # نحفظ الملف
        project_data.to_csv('arsenal_players_data.csv', index=False, encoding='utf-8-sig')
        print("✅ Data saved successfully to 'arsenal_players_data.csv'")
        print(project_data.head())
    else:
        print("❌ Could not find a table with 'Player', 'Age', and 'Min' columns. The website structure might have changed drastically.")

except Exception as e:
    print(f"❌ Error occurred: {e}")

finally:
    try:
        driver.quit()
    except:
        pass