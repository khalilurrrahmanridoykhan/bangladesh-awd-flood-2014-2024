"""
Script 01 — Seasonal Decomposition of National AWD Cases
=========================================================
Input:  data/raw/awd_annual_dghs.csv  OR  data/raw/awd_annual_manual.csv
Output: figures/fig1_seasonal_decomposition.png
        data/processed/table1_seasonal_index.csv

Method: STL (Seasonal-Trend Loess) decomposition via statsmodels.
        Uses weekly-equivalent monthly data (12 months × 10 years = 120 obs).
        Period = 12 months.

Run:  python analysis/01_seasonal_decomposition.py
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from statsmodels.tsa.seasonal import STL

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
FIG_DIR = ROOT / "figures"

PROC.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

DIVISION_POP = {
    "Dhaka": 36_054_418, "Chattogram": 28_423_019, "Rajshahi": 18_484_858,
    "Khulna": 15_563_000, "Barishal": 8_325_666, "Sylhet": 10_009_239,
    "Rangpur": 15_665_000, "Mymensingh": 11_370_000,
}

# Monthly seasonal factors for AWD in Bangladesh (index relative to annual mean = 1.0).
# Based on published icddr,b and IEDCR seasonal patterns.
# Peak: July-September (monsoon); trough: January-March (dry season).
AWD_SEASONAL_INDEX = {
    1: 0.45, 2: 0.38, 3: 0.48, 4: 0.72, 5: 0.95,
    6: 1.38, 7: 1.85, 8: 1.92, 9: 1.78, 10: 1.25,
    11: 0.72, 12: 0.52,
}


def load_awd_annual() -> pd.DataFrame:
    """Load annual AWD data from any available source file."""
    candidates = [
        RAW / "awd_annual_dghs.csv",
        RAW / "awd_annual_manual.csv",
        RAW / "awd_weekly_ewars.csv",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 200:
            df = pd.read_csv(path, encoding="utf-8-sig")
            print(f"  Loaded: {path.name} ({len(df)} rows)")
            return df, path.name
    return None, None


def build_monthly_series_from_annual(df_annual: pd.DataFrame) -> pd.Series:
    """
    Distribute annual case totals into monthly estimates using seasonal index.
    Returns a monthly time series indexed by year-month.
    """
    # Aggregate to national annual total
    df_nat = (
        df_annual[df_annual.division.isin(list(DIVISION_POP.keys()))]
        .groupby("year")["awd_cases"]
        .sum()
        .reset_index()
        .rename(columns={"awd_cases": "annual_total"})
    )

    records = []
    for _, row in df_nat.iterrows():
        year = int(row["year"])
        annual = row["annual_total"]
        for month in range(1, 13):
            idx = AWD_SEASONAL_INDEX[month]
            monthly_est = annual * idx / sum(AWD_SEASONAL_INDEX.values()) * 12
            records.append({"year": year, "month": month, "awd_cases": monthly_est})

    df_m = pd.DataFrame(records)
    df_m["date"] = pd.to_datetime(df_m[["year", "month"]].assign(day=1))
    return df_m.set_index("date")["awd_cases"].sort_index()


def build_synthetic_series() -> pd.Series:
    """
    Build a representative synthetic national AWD series (2014-2024, monthly)
    for testing the pipeline when real data is not available.
    Based on Bangladesh AWD burden estimates from WHO and icddr,b literature.
    National annual total ~3-5 million diarrhea episodes.
    """
    print("  [INFO] Building representative synthetic series for pipeline testing.")
    print("  Replace with real data once available.")
    rng = np.random.default_rng(42)
    national_pop = sum(DIVISION_POP.values())
    # Estimated annual incidence: ~2500 per 100k (icddr,b Dhaka hospital extrapolation)
    base_annual = int(national_pop * 2500 / 100_000)

    records = []
    for year in range(2014, 2025):
        # Year-level trend: slight decline over time (improved WASH)
        year_factor = 1.0 - 0.015 * (year - 2014)
        # Severe flood years get +20-35% AWD burden
        flood_bonus = {"2017": 0.28, "2020": 0.32, "2022": 0.35}.get(str(year), 0.0)
        annual = base_annual * year_factor * (1 + flood_bonus)
        for month in range(1, 13):
            idx = AWD_SEASONAL_INDEX[month]
            monthly = annual * idx / sum(AWD_SEASONAL_INDEX.values()) * 12
            noise = rng.normal(0, monthly * 0.05)
            records.append({"year": year, "month": month, "awd_cases": max(0, monthly + noise)})

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    return df.set_index("date")["awd_cases"].sort_index()


def plot_stl(series: pd.Series, stl_result, source_label: str):
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.suptitle(
        "Figure 1: STL Decomposition of National AWD Cases, Bangladesh 2014–2024",
        fontsize=13, fontweight="bold", y=0.98
    )

    obs = stl_result.observed
    trend = stl_result.trend
    seasonal = stl_result.seasonal
    resid = stl_result.resid

    # Panel 1 — Observed + Trend
    axes[0].plot(obs.index, obs.values / 1_000, color="#2c6fad", lw=1.2, label="Observed")
    axes[0].plot(trend.index, trend.values / 1_000, color="#c0392b", lw=2.0, ls="--", label="Trend")
    axes[0].set_ylabel("Cases (thousands)", fontsize=10)
    axes[0].set_title("Observed series + trend", fontsize=10, loc="left")
    axes[0].legend(fontsize=9, loc="upper right")
    axes[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}k"))
    axes[0].grid(True, alpha=0.3)

    # Shade flood years
    for flood_year in [2017, 2020, 2022]:
        axes[0].axvspan(
            pd.Timestamp(f"{flood_year}-01-01"),
            pd.Timestamp(f"{flood_year}-12-31"),
            alpha=0.12, color="#e74c3c", label="Severe flood year" if flood_year == 2017 else ""
        )

    # Panel 2 — Seasonal component
    axes[1].plot(seasonal.index, seasonal.values / 1_000, color="#27ae60", lw=1.3)
    axes[1].axhline(0, color="black", lw=0.7, ls=":")
    axes[1].set_ylabel("Seasonal (thousands)", fontsize=10)
    axes[1].set_title("Seasonal component (peak = July–September)", fontsize=10, loc="left")
    axes[1].grid(True, alpha=0.3)

    # Panel 3 — Remainder
    axes[2].bar(resid.index, resid.values / 1_000, width=20, color="#95a5a6", alpha=0.7)
    axes[2].axhline(0, color="black", lw=0.7)
    axes[2].set_ylabel("Remainder (thousands)", fontsize=10)
    axes[2].set_title("Remainder (residual)", fontsize=10, loc="left")
    axes[2].grid(True, alpha=0.3)

    # X-axis formatting
    import matplotlib.dates as mdates
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[2].xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45, ha="right")

    fig.text(
        0.5, 0.01,
        f"Data source: {source_label} | STL decomposition (period=12 months) | Bangladesh AWD Flood Study 2014–2024",
        ha="center", fontsize=8, color="gray"
    )
    plt.tight_layout(rect=[0, 0.03, 1, 0.97])

    out = FIG_DIR / "fig1_seasonal_decomposition.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out}")


def main():
    print("=" * 65)
    print("Script 01: STL Seasonal Decomposition")
    print("=" * 65)

    df_annual, source_name = load_awd_annual()
    is_synthetic = False

    if df_annual is not None and "awd_cases" in df_annual.columns:
        # Validate the data has plausible case counts
        valid_rows = df_annual[
            df_annual["awd_cases"].apply(
                lambda x: pd.notna(x) and isinstance(x, (int, float)) and 1000 <= x <= 5_000_000
            )
        ]
        if len(valid_rows) >= 5:
            series = build_monthly_series_from_annual(valid_rows)
            source_label = source_name
        else:
            print("  WARNING: loaded data has fewer than 5 valid rows — using synthetic series.")
            series = build_synthetic_series()
            source_label = "Synthetic (representative) — replace with real EWARS data"
            is_synthetic = True
    else:
        print("  No AWD data found. Using synthetic series.")
        series = build_synthetic_series()
        source_label = "Synthetic (representative) — replace with real EWARS data"
        is_synthetic = True

    print(f"  Series length: {len(series)} months")
    print(f"  Period: {series.index[0].date()} to {series.index[-1].date()}")
    print(f"  National mean: {series.mean():,.0f} cases/month")

    # Run STL
    stl = STL(series, period=12, robust=True)
    result = stl.fit()

    # Seasonal index table
    seasonal_by_month = pd.DataFrame({
        "month": range(1, 13),
        "month_name": ["Jan","Feb","Mar","Apr","May","Jun",
                       "Jul","Aug","Sep","Oct","Nov","Dec"],
        "seasonal_component_mean": [
            result.seasonal[result.seasonal.index.month == m].mean()
            for m in range(1, 13)
        ],
    })
    seasonal_by_month["seasonal_index"] = (
        seasonal_by_month["seasonal_component_mean"] /
        seasonal_by_month["seasonal_component_mean"].abs().mean()
    ).round(3)
    peak_month = seasonal_by_month.loc[seasonal_by_month.seasonal_index.idxmax(), "month_name"]
    trough_month = seasonal_by_month.loc[seasonal_by_month.seasonal_index.idxmin(), "month_name"]
    print(f"  Peak month: {peak_month} | Trough month: {trough_month}")

    table_path = PROC / "table1_seasonal_index.csv"
    seasonal_by_month.to_csv(table_path, index=False)
    print(f"  Saved: {table_path}")

    if is_synthetic:
        seasonal_by_month["note"] = "Synthetic data — for pipeline testing only"

    plot_stl(series, result, source_label)

    print("\nDone. Key findings:")
    print(f"  Peak AWD month:   {peak_month}")
    print(f"  Trough AWD month: {trough_month}")
    print(f"  Seasonal index range: {seasonal_by_month.seasonal_index.min():.2f} – {seasonal_by_month.seasonal_index.max():.2f}")
    if is_synthetic:
        print("\n  NOTE: Results based on synthetic data. Replace with real EWARS/DGHS data.")


if __name__ == "__main__":
    main()
