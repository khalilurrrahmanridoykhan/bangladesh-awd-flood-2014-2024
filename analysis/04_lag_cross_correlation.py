"""
Script 04 — Rainfall-AWD Lag Cross-Correlation Analysis
=========================================================
Input:  data/raw/awd_annual_dghs.csv  (or manual)
        data/raw/rainfall_monthly_division.csv
Output: figures/fig4_lag_ccf.png
        data/processed/table3_lag_results.csv

Method:
  - Cross-correlation function (CCF) between monthly rainfall and monthly AWD
  - Lags tested: 0–8 months
  - Expected: peak CCF at lag 2–4 months (AWD surges 2–4 months after peak rainfall)
  - Separate CCF computed per division; combined national CCF shown

Run:  python analysis/04_lag_cross_correlation.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

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

DIVISIONS = list(DIVISION_POP.keys())
MAX_LAG = 8

# Seasonal index for AWD (monthly weight relative to annual mean)
AWD_SEASONAL_INDEX = {
    1: 0.45, 2: 0.38, 3: 0.48, 4: 0.72, 5: 0.95,
    6: 1.38, 7: 1.85, 8: 1.92, 9: 1.78, 10: 1.25,
    11: 0.72, 12: 0.52,
}


def load_awd_monthly():
    """Load or construct monthly AWD series from available data."""
    for p in [RAW / "awd_annual_dghs.csv", RAW / "awd_annual_manual.csv"]:
        if p.exists() and p.stat().st_size > 200:
            df = pd.read_csv(p, encoding="utf-8-sig")
            if "awd_cases" in df.columns:
                valid = df[
                    df["division"].isin(DIVISIONS) &
                    df["awd_cases"].apply(lambda x: pd.notna(x) and x >= 1000)
                ]
                if len(valid) >= 10:
                    return _expand_to_monthly(valid), True
    return None, False


def _expand_to_monthly(df_annual) -> pd.DataFrame:
    """Distribute annual cases to monthly using seasonal index."""
    rows = []
    si_sum = sum(AWD_SEASONAL_INDEX.values())
    for _, row in df_annual.iterrows():
        for month in range(1, 13):
            cases = row["awd_cases"] * AWD_SEASONAL_INDEX[month] / si_sum * 12
            rows.append({"year": int(row["year"]), "month": month,
                         "division": row["division"], "awd_cases": cases})
    return pd.DataFrame(rows)


def load_rainfall():
    p = RAW / "rainfall_monthly_division.csv"
    if p.exists():
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "rainfall_mm" in df.columns:
            return df
    return None


def build_synthetic_monthly() -> tuple:
    """Build synthetic monthly AWD and rainfall series."""
    print("  [INFO] Building synthetic monthly series for CCF analysis.")
    rng = np.random.default_rng(42)
    monthly_normals = {
        "Dhaka":      [8,15,24,63,136,324,380,316,244,114,19,4],
        "Chattogram": [9,20,38,85,252,546,613,485,314,152,38,9],
        "Rajshahi":   [9,18,19,30,76,218,356,323,237,70,8,4],
        "Khulna":     [15,24,30,55,124,283,370,328,268,148,38,12],
        "Barishal":   [18,25,42,75,168,365,432,395,318,182,48,14],
        "Sylhet":     [22,40,120,265,465,828,762,598,428,218,58,18],
        "Rangpur":    [10,20,32,65,165,312,416,378,280,122,15,5],
        "Mymensingh": [12,22,40,80,192,365,420,368,295,140,22,6],
    }
    base_incidence = {
        "Sylhet": 2850, "Mymensingh": 2450, "Barishal": 2380,
        "Rangpur": 2100, "Dhaka": 1820, "Chattogram": 1650,
        "Khulna": 1320, "Rajshahi": 1180,
    }
    severe_years = {2017, 2020, 2022}
    si_sum = sum(AWD_SEASONAL_INDEX.values())

    awd_rows, rain_rows = [], []
    for year in range(2014, 2025):
        flood_bonus = 0.30 if year in severe_years else (0.10 if year == 2019 else 0.0)
        for div in DIVISIONS:
            pop = DIVISION_POP[div]
            base_ann = base_incidence[div] * pop / 100_000 * (1 + flood_bonus)
            for month in range(1, 13):
                si = AWD_SEASONAL_INDEX[month]
                awd = base_ann * si / si_sum * 12 + rng.normal(0, base_ann * si / si_sum * 0.1)
                awd_rows.append({"year": year, "month": month, "division": div,
                                 "awd_cases": max(0, awd)})

                rain_base = monthly_normals[div][month - 1]
                # Rainfall peaks earlier than AWD (2-3 month lead)
                rain_noise = rng.normal(0, rain_base * 0.12)
                rain_rows.append({"year": year, "month": month, "division": div,
                                  "rainfall_mm": max(0, rain_base + rain_noise),
                                  "data_quality": "synthetic"})

    return pd.DataFrame(awd_rows), pd.DataFrame(rain_rows)


def compute_ccf(x: np.ndarray, y: np.ndarray, max_lag: int = 8) -> dict:
    """
    Compute cross-correlation between x (rainfall) and y (AWD cases) for lags 0 to max_lag.
    Positive lag k means: rainfall at time t correlates with AWD at time t+k.
    Returns dict: lag → Pearson r, p-value.
    """
    x = (x - x.mean()) / (x.std() + 1e-10)
    y = (y - y.mean()) / (y.std() + 1e-10)
    results = {}
    for lag in range(0, max_lag + 1):
        if lag == 0:
            r, p = stats.pearsonr(x, y)
        else:
            r, p = stats.pearsonr(x[:-lag], y[lag:])
        results[lag] = {"r": round(r, 4), "p": round(p, 4)}
    return results


def run_ccf_analysis(df_awd: pd.DataFrame, df_rain: pd.DataFrame) -> pd.DataFrame:
    """Run CCF for each division and nationally."""
    table_rows = []

    for div in DIVISIONS + ["National"]:
        if div == "National":
            awd_div = df_awd.groupby(["year", "month"])["awd_cases"].sum().reset_index()
            awd_div["division"] = "National"
            rain_div = df_rain.groupby(["year", "month"])["rainfall_mm"].mean().reset_index()
            rain_div["division"] = "National"
        else:
            awd_div = df_awd[df_awd.division == div]
            rain_div = df_rain[df_rain.division == div]

        merged = awd_div.merge(rain_div, on=["year", "month"])
        if len(merged) < 24:
            continue

        x = merged["rainfall_mm"].values
        y = merged["awd_cases"].values
        ccf = compute_ccf(x, y, MAX_LAG)

        peak_lag = max(ccf, key=lambda k: ccf[k]["r"])
        for lag, vals in ccf.items():
            table_rows.append({
                "division": div,
                "lag_months": lag,
                "correlation_r": vals["r"],
                "p_value": vals["p"],
                "significant": vals["p"] < 0.05,
                "is_peak": lag == peak_lag,
            })

    return pd.DataFrame(table_rows)


def plot_ccf(df_ccf: pd.DataFrame, is_synthetic: bool):
    divisions_to_plot = ["National"] + DIVISIONS[:8]
    divisions_in_data = [d for d in divisions_to_plot if d in df_ccf.division.values]
    n = len(divisions_in_data)
    ncols = 3
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows), sharey=False)
    axes = axes.flatten()

    for i, div in enumerate(divisions_in_data):
        ax = axes[i]
        sub = df_ccf[df_ccf.division == div].sort_values("lag_months")
        lags = sub["lag_months"].values
        rs = sub["correlation_r"].values
        pvals = sub["p_value"].values

        # Bar color: significant = darker
        colors = ["#2980b9" if p < 0.05 else "#bdc3c7" for p in pvals]
        ax.bar(lags, rs, color=colors, width=0.7, edgecolor="white")
        ax.axhline(0, color="black", lw=0.7)

        # 95% CI bound for significance
        n_obs = 120  # approximate
        ci_bound = 1.96 / np.sqrt(n_obs)
        ax.axhline(ci_bound, color="#e74c3c", lw=0.9, ls="--", alpha=0.7)
        ax.axhline(-ci_bound, color="#e74c3c", lw=0.9, ls="--", alpha=0.7)

        peak_lag = sub.loc[sub.correlation_r.idxmax(), "lag_months"]
        ax.set_title(f"{div}\n(Peak lag = {int(peak_lag)} months)", fontsize=9, fontweight="bold")
        ax.set_xlabel("Lag (months)" if i >= n - ncols else "", fontsize=8)
        ax.set_ylabel("Pearson r" if i % ncols == 0 else "", fontsize=8)
        ax.set_xticks(lags)
        ax.grid(True, alpha=0.2, axis="y")
        ax.set_ylim(-0.3, 1.0)

    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    title = "Figure 4: Cross-Correlation Between Monthly Rainfall and AWD Cases by Division\nBangladesh 2014–2024 (lags 0–8 months)"
    if is_synthetic:
        title += "\n(Synthetic data — for pipeline testing)"
    fig.suptitle(title, fontsize=11, fontweight="bold", y=1.01)

    legend_patches = [
        plt.Rectangle((0, 0), 1, 1, color="#2980b9"),
        plt.Rectangle((0, 0), 1, 1, color="#bdc3c7"),
        plt.Line2D([0], [0], color="#e74c3c", ls="--"),
    ]
    fig.legend(legend_patches, ["Significant (p<0.05)", "Non-significant", "95% CI bound"],
               loc="lower center", ncol=3, fontsize=8, bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    out = FIG_DIR / "fig4_lag_ccf.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out}")


def main():
    print("=" * 65)
    print("Script 04: Rainfall-AWD Lag Cross-Correlation")
    print("=" * 65)

    df_awd_monthly, has_real_awd = load_awd_monthly()
    df_rain = load_rainfall()
    is_synthetic = False

    if df_awd_monthly is None or df_rain is None:
        print("  Insufficient data — building synthetic series.")
        df_awd_monthly, df_rain = build_synthetic_monthly()
        is_synthetic = True
    else:
        print(f"  AWD monthly: {len(df_awd_monthly)} rows")
        print(f"  Rainfall: {len(df_rain)} rows")

    print("  Running CCF analysis...")
    df_ccf = run_ccf_analysis(df_awd_monthly, df_rain)

    table_path = PROC / "table3_lag_results.csv"
    df_ccf.to_csv(table_path, index=False)
    print(f"  Saved: {table_path}")

    print("\nPeak lag by division:")
    peak_lags = df_ccf[df_ccf.is_peak].sort_values("division")[["division", "lag_months", "correlation_r", "p_value"]]
    print(peak_lags.to_string(index=False))

    plot_ccf(df_ccf, is_synthetic)

    national = df_ccf[df_ccf.division == "National"]
    if not national.empty:
        peak = national.loc[national.correlation_r.idxmax()]
        print(f"\nNational peak: lag = {int(peak.lag_months)} months (r = {peak.correlation_r:.3f})")

    if is_synthetic:
        print("\n  NOTE: Results based on synthetic data.")


if __name__ == "__main__":
    main()
