import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression

# ==========================================
# 1. Raw Data (استدعاء البيانات)
# ==========================================
df = pd.read_csv("players_data-2026_2027.csv")

# ==========================================
# 2. Data Cleaning (تنظيف البيانات)
# ==========================================
df.dropna(inplace=True)          # مسح النواقص عشان الموديل ميضربش إيرور 
df.drop_duplicates(inplace=True) # مسح التكرار عشان الموديل ميحفظش داتا متكررة ويغش

# ==========================================
# 3. Feature Engineering (ابتكار ميزات جديدة)
# ==========================================
# بنخلق نسب ذكية تفيد الموديل زي معدل التهديف
df['Goals_per_Match'] = df['Gls'] / df['MP']

# ==========================================
# 4. Encoding (تحويل النصوص لأرقام)
# ==========================================
# الموديل بيفهم أرقام بس، فبنحول مركز اللاعب (نص) لأصفار ووحايد
df = pd.get_dummies(df, columns=["Pos"], dtype=int)

# ==========================================
# 5. X / y Separation (فصل المعطيات عن الهدف)
# ==========================================
# بنعزل عمود الأهداف (النتيجة) لوحده، وباقي الأرقام لوحدها (المعطيات)
# اخترنا العواميد الرقمية بس عشان الموديل ميقراش أسامي اللعيبة ويضرب إيرور
numeric_cols = df.select_dtypes(include=['int64', 'float64', 'int32']).columns
X = df[numeric_cols].drop("Gls", axis=1) # المعطيات (كل الأرقام ما عدا الأهداف)
y = df["Gls"]                            # الهدف (الأهداف بس)

# ==========================================
# 6. Train / Test Split (التقسيم)
# ==========================================
# بنعزل 20% من اللعيبة كـ "امتحان" عشان نختبر الموديل في داتا أول مرة يشوفها
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42)

# ==========================================
# 7. Feature Scaling (توحيد المقاسات)
# ==========================================
# بنضغط كل الأرقام عشان الموديل ميفتكرش إن الرقم الكبير أهم من الرقم الصغير
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train) 
X_test_scaled = scaler.transform(X_test)



# 1. بنستدعي نموذج الذكاء الاصطناعي (الكشاف بتاعنا) ونسجله في كلمة model
model = LinearRegression()

# 2. التدريب (fit): بنديله إحصائيات 1600 لاعب (المعطيات) وأهدافهم (النتيجة) ونقوله: ذاكر واكتشف السر!
model.fit(X_train_scaled, y_train)

# 3. الامتحان (predict): بنجيبله أرقام الـ 20% لعيبة الجداد اللي مخبينهم، ونقوله: توقع كده كل واحد فيهم هيجيب كام هدف؟
predictions = model.predict(X_test_scaled)