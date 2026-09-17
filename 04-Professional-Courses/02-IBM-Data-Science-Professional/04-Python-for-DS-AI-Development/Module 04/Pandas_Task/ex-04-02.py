import pandas as pd
# Create a Series from a list
data = [10, 20, 30, 40, 50]
s = pd.Series(data)
print(s)
print(s[2])
print(s.iloc[3]) 

data2 = {'Name':["Ahemd","Sobhy","Omar","Gebril"]
        ,"Players’s age":[18,20,30,40]}
s2=pd.DataFrame(data2)
print(s2)
print(s2['Name'])
print(s2.iloc[2])   # Access the third row by position
print(s2.loc[1])    # Access the second row by label
