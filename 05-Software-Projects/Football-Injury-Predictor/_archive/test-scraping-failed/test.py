import requests
import pandas as pd
from io import StringIO

print("🚀 Connecting to FBref to extract player data...")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

url = "https://fbref.com/en/squads/18bb7c10/Arsenal-Stats"

try:
    # 1. Fetch the page
    response = requests.get(url, headers=headers)
    
    # Print the server response (200 means OK, 429 means Blocked/Too Many Requests)
    print(f"Server Response Code: {response.status_code}")

    # 2. FBref hides tables in HTML comments. We replace them to expose the tables.
    html_content = response.text.replace('', '')

    # 3. Use StringIO to fix the Future Warning, then read the tables
    tables = pd.read_html(StringIO(html_content))

    # 4. Process the first table
    df = tables[0]
    df.columns = df.columns.droplevel(0)
    
    # 5. Extract only the columns needed for the injury predictor project
    project_data = df[['Player', 'Age', 'Min']]
    project_data = project_data.dropna()

    # 6. Save to CSV
    project_data.to_csv('arsenal_players_data.csv', index=False, encoding='utf-8-sig')

    print("✅ Data extracted successfully! Check 'arsenal_players_data.csv' in your folder.")
    print(project_data.head())

except ValueError as e:
    print(f"❌ Error: {e}")
    print("No tables were found. The website might be blocking the script or the page structure changed.")
except Exception as e:
    print(f"❌ An unexpected error occurred: {e}")