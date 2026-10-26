# ⚽🏥 Football Injury Predictor

A machine learning system that predicts the likelihood of football (soccer) player injuries in the upcoming season. Built using real data scraped from **FBref** and **Transfermarkt**.

> **Note**: This is a club-facing screening tool, not a medical diagnosis. It ranks players by relative injury risk to support preventive planning.

---

## 📊 How It Works

```
1. Data Collection     →  Scrape player stats (FBref) + injury history (Transfermarkt)
2. Data Preparation    →  Match players across sources, clean & engineer features
3. Model Training      →  Walk-forward temporal validation (no data leakage)
4. Risk Scoring        →  Rank players by predicted injury probability for next season
```

## 🗂️ Project Structure

```
Football-Injury-Predictor/
│
├── README.md                  ← You are here
├── DATASET_MAP.md             ← Detailed data lineage & column descriptions
│
├── src/                       ← All source code
│   ├── scraping/              ← Web scraping scripts (FBref + Transfermarkt)
│   ├── features/              ← Data cleaning, matching & feature engineering
│   └── modeling/              ← Model training, evaluation & scoring
│
├── data/                      ← All data files
│   ├── raw/                   ← Raw scraped CSVs & team URL lists
│   └── prepared/              ← Cleaned, joined & model-ready datasets
│
├── models/                    ← Trained model files (.joblib) & metrics (.csv)
│
└── _archive/                  ← Old test scripts & legacy code (not in use)
```

## 📈 Model Performance

| Metric | Test (2024-2025) |
|--------|-----------------|
| **ROC-AUC** | 0.668 |
| **Average Precision** | 0.738 |
| **Balanced Accuracy** | 0.621 |

The selected model is **Logistic Regression** with balanced class weights, chosen via walk-forward validation across 3 seasons.

## 🔧 Key Features Used

- **Player stats**: Age, matches played, starts, minutes
- **Injury history**: Prior events (total, physical, muscle, lower-limb), days out, games missed
- **Categorical**: Position, nationality

## 🚀 Usage

### 1. Scrape Data
```bash
# Collect FBref physical stats
python src/scraping/fbref_recent_scraper.py

# Collect Transfermarkt injury data
python src/scraping/transfermarkt_injury_scraper.py
```

### 2. Build Features
```bash
# Merge & clean the master physical dataset
python src/features/build_physical_master.py

# Join FBref + Transfermarkt into model-ready dataset
python src/features/build_injury_physical_dataset.py
python src/features/clean_model_dataset.py
```

### 3. Train & Evaluate
```bash
# Train with walk-forward temporal validation
python src/modeling/train_injury_risk_model.py
```

### 4. Score Next Season
```bash
# Generate risk rankings for 2026-2027
python src/modeling/score_next_season_risk.py
```

## 📦 Requirements

- Python 3.10+
- pandas, scikit-learn, joblib
- selenium, undetected-chromedriver, beautifulsoup4 (for scraping)

## 📋 Data Sources

- **[FBref](https://fbref.com/)** — Player match statistics (minutes, starts, appearances)
- **[Transfermarkt](https://www.transfermarkt.com/)** — Injury history, rosters, player IDs

## ⚠️ Disclaimer

This tool provides **relative risk screening** only. It is not a calibrated medical probability and should not replace professional medical assessment.
