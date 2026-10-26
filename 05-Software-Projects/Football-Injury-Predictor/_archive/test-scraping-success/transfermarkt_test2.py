import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

print("🚀 Testing Transfermarkt Security Bypass (Arsenal Squad)...")

url = "https://www.transfermarkt.com/fc-arsenal/kader/verein/11/saison_id/2023"

options = uc.ChromeOptions()
driver = uc.Chrome(options=options, version_main=153)

try:
    print(f"🔗 Opening URL: {url}")
    driver.get(url)
    
    print("⏳ Waiting for page to load...")
    
    # نستنى أي جدول يظهر كدليل إن الصفحة حملت
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )
    time.sleep(4)
    
    # التكتيك الجديد: نسحب كل الروابط اللي في الصفحة
    links = driver.find_elements(By.TAG_NAME, "a")
    
    print("\n✅ Successfully loaded! Extracting player links...\n")
    
    count = 0
    seen_players = set()
    
    for el in links:
        try:
            href = el.get_attribute("href")
            
            # نصطاد بس الروابط اللي بتشاور على "بروفايل لاعب"
            if href and "/profil/spieler/" in href:
                # نستخرج اسم اللاعب من الرابط نفسه (عشان نتفادى مشاكل الصور)
                # مثال للرابط: transfermarkt.com/bukayo-saka/profil/...
                raw_name = href.split(".com/")[1].split("/profil")[0]
                name = raw_name.replace("-", " ").title()
                
                # نتأكد إننا مش بنكرر نفس اللاعب
                if name not in seen_players:
                    injury_link = href.replace("profil", "verletzungen")
                    
                    print(f"👤 Player: {name}")
                    print(f"🔗 Injury Link: {injury_link}\n")
                    
                    seen_players.add(name)
                    count += 1
                    
                    if count == 5: # هنجرب على أول 5 لعيبة بس
                        break
        except:
            continue

except Exception as e:
    print(f"❌ Error: {e}")

finally:
    driver.quit()
    print("🏁 Test Finished.")
    