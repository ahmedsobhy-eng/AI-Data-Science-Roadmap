import pandas as pd
import numpy as np

# ==========================================
# 1. Creating the DataFrame
# ==========================================
# Generate a 3x3 matrix using numpy and assign column names 'a', 'b', and 'c'
df = pd.DataFrame(np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), columns=['a', 'b', 'c'])

print("--- Original DataFrame ---")
print(df)
print("\n")

# ==========================================
# 2. Using transform() with a Lambda Function
# ==========================================
# Add 10 to every single element in the DataFrame simultaneously
df_transformed = df.transform(func=lambda x: x + 10)

print("--- After Adding 10 (Using Lambda) ---")
print(df_transformed)
print("\n")

# ==========================================
# 3. Using transform() with a built-in function
# ==========================================
# Calculate the square root (sqrt) for every element in the updated DataFrame
result = df_transformed.transform(func=['sqrt'])

print("--- After Calculating Square Root ---")
print(result)