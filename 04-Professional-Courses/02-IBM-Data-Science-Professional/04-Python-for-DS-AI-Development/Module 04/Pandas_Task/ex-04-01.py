import pandas as pd 
xx="data.csv"
df=pd.read_csv(xx)
print(df)
df.describe()