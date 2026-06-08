"""
Script 03 — Flood Duration vs AWD Incidence Scatter Plot
=========================================================
Input:  data/raw/awd_annual_dghs.csv  (or manual)
        data/raw/flood_annual_division.csv
Output: figures/fig3_flood_vs_awd.png

Method:
  - 80 data points (8 divisions × 10 years)
  - X-axis: flood duration days per year per division
  - Y-axis: AWD incidence per 100,000
  - Spearman rank correlation
  - Linear regression line with 95% CI

Run:  python analysis/03_flood_vs_awd.py
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

DIVISION_COLORS = {
    "Dhaka": "#2980b9", "Chattogram": "#8e44ad", "Rajshahi": "#27ae60",
    "Khulna": "#f39c12", "Barishal": "#c0392b", "Sylhet": "#16a085",
    "Rangpur": "#d35400", "Mymensingh": "#7f8c8d",
}

SEVERE_FLOOD_YEARS = {2017, 2020, 2022}

# Synthetic AWD incidence per 100k by division-year when real data not available
SYNTHETIC_BASE_INCIDENCE = {
    "Sylhet": 2850, "Mymensingh": 2450, "Barishal": 2380,
    "Rangpur": 2100, "Dhaka": 1820, "Chattogram": 1650,
    "Khulna": 1320, "Rajshahi": 1180,
}


def load_data():
    awd_file = None
    for p in [RAW / "awd_annual_dghs.csv", RAW / "awd_annual_manual.csv"]:
        if p.exists() and p.stat().st_size > 200:
            awd_file = p
            break

    flood_file = RAW / "flood_annual_division.csv"

    df_awd = None
    if awd_file:
        df = pd.read_csv(awd_file, encoding="utf-8-sig")
        if "awd_cases" in df.columns and "division" in df.columns:
            valid = df[
                df["division"].isin(DIVISION_POP.keys()) &
                df["awd_cases"].apply(lambda x: pd.notna(x) and x >= 1000)
            ].copy()
            if len(valid) >= 10:
                valid["incidence_per_100k"] = (
                    valid["awd_cases"] / valid["division"].map(DIVISION_POP) * 100_000
                ).round(1)
                df_awd = valid[["year", "division", "awd_cases", "incidence_per_100k"]]

    df_flood = None
    if flood_file.exists():
        df_flood = pd.read_csv(flood_file, encoding="utf-8-sig")

    return df_awd, df_flood


def build_synthetic_panel() -> pd.DataFrame:
    """Build synthetic 8×10 panel dataset for pipeline testing."""
    print("  [INFO] Building synthetic panel (8 div × 10 years = 80 obs)")
    rng = np.random.default_rng(42)
    rows = []
    for year in range(2014, 2025):
        is_severe = year in SEVERE_FLOOD_YEARS
        flood_bonus = 0.30 if is_severe else (0.10 if year == 2019 else 0.0)
        for div in DIVISION_POP.keys():
            base_inc = SYNTHETIC_BASE_INCIDENCE[div]
            noise = rng.normal(0, base_inc * 0.08)
            inc = max(500, base_inc * (1 + flood_bonus) + noise)

            # Rough flood days: correlated with incidence for realism
            base_flood_days = {"Sylhet": 50, "Mymensingh": 42, "Rangpur": 38,
                               "Dhaka": 28, "Barishal": 32, "Chattogram": 22,
                               "Khulna": 10, "Rajshahi": 8}[div]
            flood_mult = 2.2 if is_severe else (1.4 if year == 2019 else 1.0)
            flood_days = max(0, base_flood_days * flood_mult + rng.normal(0, 3))

            rows.append({
                "year": year, "division": div,
                "incidence_per_100k": round(inc, 1),
                "flood_duration_days": round(flood_days, 1),
                "flood_severity": "Severe" if is_severe else ("Moderate" if year == 2019 else "Mild"),
                "is_synthetic": True,
            })
    return pd.DataFrame(rows)


def merge_panel(df_awd, df_flood) -> tuple:
    """Merge AWD and flood data into panel; fall back to synthetic if needed."""
    if df_awd is not None and df_flood is not None:
        panel = df_awd.merge(
            df_flood[["year", "division", "flood_duration_days", "flood_severity"]],
            on=["year", "division"], how="inner"
        )
        panel["is_synthetic"] = False
        if len(panel) >= 10:
            return panel, False

    print("  Insufficient merged data — using synthetic panel.")
    return build_synthetic_panel(), True


def plot_scatter(panel: pd.DataFrame, is_synthetic: bool):
    fig, ax = plt.subplots(figsize=(10, 7))

    for div in DIVISION_POP.keys():
        sub = panel[panel.division == div]
        if sub.empty:
            continue
        ax.scatter(
            sub["flood_duration_days"], sub["incidence_per_100k"],
            color=DIVISION_COLORS.get(div, "#333333"),
            s=70, alpha=0.8, label=div, zorder=3,
        )
        # Annotate severe flood years
        for _, row in sub.iterrows():
            if row["year"] in SEVERE_FLOOD_YEARS:
                ax.annotate(
                    str(int(row["year"])),
                    (row["flood_duration_days"], row["incidence_per_100k"]),
                    textcoords="offset points", xytext=(4, 4),
                    fontsize=6.5, color="#c0392b",
                )

    # Regression line + CI
    x = panel["flood_duration_days"].values
    y = panel["incidence_per_100k"].values
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]

    slope, intercept, r_val, p_val, se = stats.linregress(x, y)
    spearman_r, spearman_p = stats.spearmanr(x, y)

    x_line = np.linspace(x.min(), x.max(), 200)
    y_line = intercept + slope * x_line
    ax.plot(x_line, y_line, color="black", lw=1.8, ls="--", zorder=4)

    # 95% CI band
    n = len(x)
    x_mean = x.mean()
    se_fit = se * np.sqrt(1/n + (x_line - x_mean)**2 / ((x - x_mean)**2).sum())
    t_crit = stats.t.ppf(0.975, df=n-2)
    ax.fill_between(x_line, y_line - t_crit * se_fit * np.sqrt(n),
                    y_line + t_crit * se_fit * np.sqrt(n),
                    alpha=0.12, color="black")

    # Statistics box
    stats_text = (
        f"Spearman r = {spearman_r:.3f} (p {'< 0.001' if spearman_p < 0.001 else f'= {spearman_p:.3f}'})\n"
        f"n = {n} division-year observations\n"
        f"OLS slope: {slope:.1f} cases/100k per flood day"
    )
    ax.text(0.03, 0.97, stats_text, transform=ax.transAxes,
            va="top", ha="left", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"))

    ax.set_xlabel("Flood Duration (days above danger level per year)", fontsize=11)
    ax.set_ylabel("AWD Incidence per 100,000 population", fontsize=11)

    title = "Figure 3: Flood Exposure vs AWD Incidence by Division-Year\nBangladesh 2014–2024"
    if is_synthetic:
        title += "\n(Synthetic data — for pipeline testing)"
    ax.set_title(title, fontsize=12, fontweight="bold")

    ax.legend(title="Division", fontsize=8, title_fontsize=9,
              loc="lower right", ncol=2, framealpha=0.9)
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    out = FIG_DIR / "fig3_flood_vs_awd.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out}")

    return spearman_r, spearman_p


def main():
    print("=" * 65)
    print("Script 03: Flood Duration vs AWD Incidence")
    print("=" * 65)

    df_awd, df_flood = load_data()
    panel, is_synthetic = merge_panel(df_awd, df_flood)

    print(f"  Panel: {len(panel)} observations")
    if not is_synthetic:
        print(f"  Years: {sorted(panel.year.unique())}")
        print(f"  Divisions: {sorted(panel.division.unique())}")

    spearman_r, spearman_p = plot_scatter(panel, is_synthetic)

    # Summary stats for severe vs non-severe flood years
    severe = panel[panel.year.isin(SEVERE_FLOOD_YEARS)]
    non_severe = panel[~panel.year.isin(SEVERE_FLOOD_YEARS)]

    print("\nKey results:")
    print(f"  Spearman r = {spearman_r:.3f} (p {'< 0.001' if spearman_p < 0.001 else f'= {spearman_p:.3f}'})")
    if len(severe) > 0 and len(non_severe) > 0:
        inc_severe = severe["incidence_per_100k"].mean()
        inc_normal = non_severe["incidence_per_100k"].mean()
        pct_diff = (inc_severe - inc_normal) / inc_normal * 100
        print(f"  Severe flood years AWD incidence: {inc_severe:,.0f} per 100k")
        print(f"  Non-flood years AWD incidence:    {inc_normal:,.0f} per 100k")
        print(f"  Difference: +{pct_diff:.1f}% in severe flood years")

    if is_synthetic:
        print("\n  NOTE: All results based on synthetic data.")


if __name__ == "__main__":
    main()
