import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

print("🚀 Testing Transfermarkt Security Bypass (Arsenal Squad)...")

# رابط صفحة فريق أرسنال لموسم 2023
url = "https://www.transfermarkt.com/fc-arsenal/kader/verein/11/saison_id/2023"

options = uc.ChromeOptions()
# بنستخدم نفس إصدار المتصفح بتاعك
driver = uc.Chrome(options=options, version_main=153)

try:
    print(f"🔗 Opening URL: {url}")
    driver.get(url)
    
    print("⏳ Waiting for page to load and bypassing security...")
    
    # بنستنى لحد ما جدول اللعيبة (اللي الكلاس بتاعه items) يظهر
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "items"))
    )
    time.sleep(3)
    
    # اللوجيك الهندسي: بنصطاد لينكات اللعيبة، ونبدل كلمة (profil) بكلمة (verletzungen) عشان تودينا لصفحة الإصابات
    player_elements = driver.find_elements(By.XPATH, "//table[@class='items']//td[@class='hauptlink']//a")
    
    print("\n✅ Successfully bypassed security! Here are the first 5 players and their injury links:\n")
    
    count = 0
    # هنستخدم Set عشان نمنع تكرار أسماء اللعيبة
    seen_players = set()
    
    for el in player_elements:
        href = el.get_attribute("href")
        name = el.text.strip()
        
        if href and name and "profil" in href and name not in seen_players:
            injury_link = href.replace("profil", "verletzungen")
            print(f"👤 Player: {name}")
            print(f"🔗 Injury Link: {injury_link}\n")
            
            seen_players.add(name)
            count += 1
            if count == 5: # هنجرب على أول 5 لعيبة بس كاختبار
                break

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    driver.quit()
    print("🏁 Test Finished.")