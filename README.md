# Bangladesh AWD Flood Analysis (2014–2024)

Reproducible code and data for the paper:

> **"Geographic and Environmental Determinants of Acute Watery Diarrhea Burden in Bangladesh: A 10-Year Ecological Analysis of Flood Exposure and Divisional Disease Incidence (2014–2024)"**

## Repository Structure

```
.
├── data/
│   ├── raw/
│   │   ├── awd_annual_paper_sourced.csv   ← AWD cases by division-year (paper-derived)
│   │   ├── flood_annual_division.csv      ← Flood duration by division-year
│   │   ├── rainfall_monthly_division.csv  ← Monthly rainfall by division
│   │   └── bangladesh_divisions.geojson   ← Division boundaries (geoBoundaries CC0)
│   └── processed/
│       ├── table1_seasonal_index.csv
│       ├── table2_division_incidence.csv
│       ├── table3_lag_results.csv
│       └── table4_regression.csv
├── analysis/
│   ├── 01_seasonal_decomposition.py
│   ├── 02_division_incidence_map.py
│   ├── 03_flood_vs_awd.py
│   ├── 04_lag_cross_correlation.py
│   └── 05_regression_model.py
├── figures/
│   ├── fig1_seasonal_decomposition.png
│   ├── fig2_division_map.png
│   ├── fig3_flood_vs_awd.png
│   ├── fig4_lag_ccf.png
│   └── fig5_regression_irr.png
├── paper/
│   └── manuscript.md
├── fetch_paper_data.py    ← Constructs AWD dataset from published papers
├── fetch_flood_data.py    ← Builds flood duration dataset
├── fetch_rainfall.py      ← Builds monthly rainfall dataset
└── README.md
```

## Data Sources

| Data | Source | Citation |
|------|--------|----------|
| AWD cases (2017–2022) | MoHFW DHIS2 via Kabir et al. 2025 | PMC11922245 |
| Division proportions | Kabir et al. 2025 Table 4 + Ali et al. 2023 | PMC11922245, PMC10484282 |
| Cholera positivity | IEDCR Sentinel Surveillance, Ali et al. 2023 | PMC10484282 |
| National AWD baseline | DGHS Health Bulletin 2015 | DGHS/MoHFW |
| Flood duration | BWDB/FFWC literature estimates | BWDB 2022 |
| Rainfall | BMD 1981–2010 climatological normals | BMD 2023 |
| Population | BBS Census 2022 | BBS 2022 |
| Division boundaries | geoBoundaries BGD ADM1 | CC0 1.0 |

## Key Results

| Finding | Value |
|---------|-------|
| Study period | 2014–2024 (11 years, 88 division-year obs) |
| Total estimated AWD cases | 37,280,001 |
| Annual mean (excl. 2020) | 3,520,000/year |
| Highest-burden division | Barishal (4,455/100k/yr) |
| Lowest-burden division | Rangpur (1,151/100k/yr) |
| Peak AWD month | August |
| Trough AWD month | February |
| National rainfall-AWD peak lag | 1 month (r = 0.914) |
| Spearman r (flood vs incidence) | 0.247 (p = 0.020) |
| Barishal vs Dhaka IRR | 2.56 (95% CI 2.55–2.56) |
| Severe flood year excess | +23.8% national AWD burden |

## Reproduction Steps

```bash
# 1. Install dependencies
pip install pandas numpy scipy statsmodels matplotlib geopandas requests lxml

# 2. Fetch paper-sourced AWD data
python fetch_paper_data.py

# 3. Copy to analysis-expected filename
cp data/raw/awd_annual_paper_sourced.csv data/raw/awd_annual_dghs.csv

# 4. Fetch flood and rainfall data
python fetch_flood_data.py
python fetch_rainfall.py

# 5. Run all analysis scripts
python analysis/01_seasonal_decomposition.py
python analysis/02_division_incidence_map.py
python analysis/03_flood_vs_awd.py
python analysis/04_lag_cross_correlation.py
python analysis/05_regression_model.py
```

All outputs are saved to `data/processed/` and `figures/`.

## Limitations

- AWD case estimates derived from national totals distributed by proxy division weights (real EWARS divisional data requires government authentication from IEDCR)
- Flood data are literature-based estimates, not real-time BWDB gauge measurements
- Rainfall data are climatological normals, not station-interpolated fields
- 2020 estimates are reduced by 35% to account for COVID-19 facility disruption

## License

Code: MIT  
Data: See individual source licenses above. All data sources are publicly available or open-access peer-reviewed publications.

## Citation

If you use this code or data, please cite:

> [Author] (2026). Geographic and Environmental Determinants of Acute Watery Diarrhea Burden in Bangladesh: A 10-Year Ecological Analysis of Flood Exposure and Divisional Disease Incidence (2014–2024). *medRxiv* [preprint].
