# 1. بنستدعي أداة التحكم (webdriver) من مكتبة سيلينيوم
from selenium import webdriver 

# 2. بنقول لبايثون يفتح متصفح فايرفوكس (Firefox) جديد، وبنربط التحكم فيه بمتغير سميناه driver
driver = webdriver.Firefox() 

# 3. بندي أمر للمتصفح إنه يروح يفتح اللينك ده تحديداً
driver.get("http://www.example.com") 

# -- (سطر إضافي للتوضيح) --
# لو عايزين ندوس على زرار مثلاً بنكتب كود زي ده:
driver.find_element_by_id("login-button").click()