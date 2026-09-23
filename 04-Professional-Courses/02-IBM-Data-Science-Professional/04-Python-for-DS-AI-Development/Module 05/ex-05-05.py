import pandas as pd
import numpy as np

# ==========================================
# 0. Create Mock Data (Simulating the scraped web table)
# ==========================================
data = {
    0: ['World', 'United States', 'China', 'Germany', 'Japan', 'India', 'UK', 'France', 'Italy', 'Brazil', 'Canada'],
    1: ['-', 'North America', 'Asia', 'Europe', 'Asia', 'Asia', 'Europe', 'Europe', 'Europe', 'South America', 'North America'],
    2: [100000000.0, 26949643.0, 17700899.0, 4429838.0, 4230862.0, 3732224.0, 3332059.0, 3049016.0, 2186082.0, 2126832.0, 2117805.0]
}
df = pd.DataFrame(data)

print("--- Original Scraped Data ---")
print(df.head())
print("\n")

# ==========================================
# 1. Data Filtering (Rows & Columns)
# ==========================================
# Retain columns with index 0 and 2 (Country name and GDP value)
df = df[[0, 2]] 

# Retain rows with index 1 to 10 (Top 10 economies, excluding 'World')
df = df.iloc[1:11, :] 

# Assign clear column names
df.columns = ['Country', 'GDP (Million USD)'] 

# ==========================================
# 2. Data Transformation (Data types & Math operations)
# ==========================================
# Change data type of GDP column to integer
df['GDP (Million USD)'] = df['GDP (Million USD)'].astype(int) 

# Convert GDP value from Million USD to Billion USD
df[['GDP (Million USD)']] = df[['GDP (Million USD)']] / 1000 

# Round the values to 2 decimal places using numpy
df[['GDP (Million USD)']] = np.round(df[['GDP (Million USD)']], 2) 

# Rename the column header to reflect the new scale (Billion USD)
df = df.rename(columns={'GDP (Million USD)': 'GDP (Billion USD)'}) 

print("--- Cleaned and Transformed Data ---")
print(df)
print("\n")

# ==========================================
# 3. Export Data
# ==========================================
# Load the final DataFrame to a CSV file (index=False prevents saving the row numbers)
df.to_csv("Largest_economies.csv", index=False) 
print("File successfully saved as: Largest_economies.csv")