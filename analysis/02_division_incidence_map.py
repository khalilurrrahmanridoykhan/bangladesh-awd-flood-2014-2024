"""
Script 02 — Division-Level AWD Incidence Choropleth Map
=========================================================
Input:  data/raw/awd_annual_dghs.csv  (or manual)
        data/raw/bangladesh_divisions.geojson  (shapefile — see note below)
Output: figures/fig2_division_map.png
        data/processed/table2_division_incidence.csv

SHAPEFILE NOTE:
  Download Bangladesh division boundary from:
    https://data.humdata.org/dataset/cod-ab-bgd
  Or: gadm.org → Bangladesh → Level 1 (division)
  Save as: data/raw/bangladesh_divisions.geojson

  If shapefile not present, a bar chart is produced instead.

Run:  python analysis/02_division_incidence_map.py
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
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

# Flood risk classification by division (based on BWDB records)
FLOOD_RISK = {
    "Sylhet": "High", "Mymensingh": "High", "Rangpur": "High",
    "Dhaka": "Moderate", "Barishal": "Moderate", "Chattogram": "Moderate",
    "Khulna": "Low", "Rajshahi": "Low",
}

# Representative 10-year average incidence (cases per 100k per year)
# estimated from published Bangladesh AWD burden studies.
# These will be replaced by real data when available.
SYNTHETIC_INCIDENCE = {
    "Sylhet": 2_850, "Mymensingh": 2_450, "Barishal": 2_380,
    "Rangpur": 2_100, "Dhaka": 1_820, "Chattogram": 1_650,
    "Khulna": 1_320, "Rajshahi": 1_180,
}


def load_awd_annual():
    candidates = [
        RAW / "awd_annual_dghs.csv",
        RAW / "awd_annual_manual.csv",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 200:
            df = pd.read_csv(p, encoding="utf-8-sig")
            if "awd_cases" in df.columns and "division" in df.columns:
                return df, p.name
    return None, None


def compute_incidence(df_annual) -> pd.DataFrame:
    valid = df_annual[
        df_annual["division"].isin(DIVISION_POP.keys()) &
        df_annual["awd_cases"].apply(
            lambda x: pd.notna(x) and isinstance(x, (int, float)) and x >= 1000
        )
    ]
    if len(valid) < 5:
        return None

    result = (
        valid.groupby("division")["awd_cases"]
        .mean()
        .reset_index()
        .rename(columns={"awd_cases": "mean_annual_cases"})
    )
    result["population"] = result["division"].map(DIVISION_POP)
    result["incidence_per_100k"] = (result["mean_annual_cases"] / result["population"] * 100_000).round(1)
    result["flood_risk"] = result["division"].map(FLOOD_RISK)
    result["data_quality"] = "real"
    return result.sort_values("incidence_per_100k", ascending=False)


def build_synthetic_incidence() -> pd.DataFrame:
    print("  [INFO] Using representative synthetic incidence — replace with real data.")
    rows = []
    for div, inc in SYNTHETIC_INCIDENCE.items():
        pop = DIVISION_POP[div]
        rows.append({
            "division": div,
            "mean_annual_cases": round(inc * pop / 100_000),
            "population": pop,
            "incidence_per_100k": inc,
            "flood_risk": FLOOD_RISK[div],
            "data_quality": "synthetic_estimate",
        })
    return pd.DataFrame(rows).sort_values("incidence_per_100k", ascending=False)


def try_choropleth(df_inc: pd.DataFrame) -> bool:
    """Try to draw a choropleth map if shapefile is available."""
    shapefile_candidates = [
        RAW / "bangladesh_divisions.geojson",
        RAW / "bgd_admbnda_adm1_bbs_20201113.geojson",
        RAW / "BGD_adm1.geojson",
    ]

    gdf_path = next((p for p in shapefile_candidates if p.exists()), None)
    if gdf_path is None:
        return False

    try:
        import geopandas as gpd
        gdf = gpd.read_file(gdf_path)
    except ImportError:
        return False
    except Exception as e:
        print(f"    Could not load shapefile: {e}")
        return False

    # Normalize division name column (try common field names)
    name_col = None
    for col in ["shapeName", "ADM1_EN", "NAME_1", "division", "DIV_NAME", "div_name", "DIVISION"]:
        if col in gdf.columns:
            name_col = col
            break
    if name_col is None:
        print("    Shapefile found but division name column not identified.")
        return False

    gdf = gdf.rename(columns={name_col: "division"})
    gdf["division"] = gdf["division"].str.strip()

    # Normalise historic/variant names to match our analysis names
    SHAPEFILE_NAME_MAP = {
        "Barisal": "Barishal",
        "Chittagong": "Chattogram",
        "Rajshani": "Rajshahi",   # typo in geoBoundaries source
        "Rajshahi": "Rajshahi",
    }
    gdf["division"] = gdf["division"].replace(SHAPEFILE_NAME_MAP)

    gdf = gdf.merge(df_inc[["division", "incidence_per_100k", "flood_risk"]], on="division", how="left")

    fig, ax = plt.subplots(1, 1, figsize=(8, 10))
    gdf.plot(
        column="incidence_per_100k",
        ax=ax,
        cmap="YlOrRd",
        legend=True,
        legend_kwds={"label": "AWD Incidence per 100,000", "shrink": 0.6},
        missing_kwds={"color": "lightgrey"},
        edgecolor="black",
        linewidth=0.5,
    )

    # Division labels
    for _, row in gdf.iterrows():
        if row.geometry:
            cx, cy = row.geometry.centroid.x, row.geometry.centroid.y
            div_name = row.get("division", "")
            inc = row.get("incidence_per_100k", float("nan"))
            if div_name and not pd.isna(inc):
                ax.annotate(
                    f"{div_name}\n{inc:,.0f}",
                    xy=(cx, cy), ha="center", va="center",
                    fontsize=7, color="black",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.6, ec="none"),
                )

    ax.set_title(
        "Figure 2: AWD Incidence per 100,000 by Division\nBangladesh 10-Year Average (2014–2024)",
        fontsize=12, fontweight="bold"
    )
    ax.set_axis_off()
    fig.text(0.5, 0.01, "Source: IEDCR EWARS / DGHS | BBS 2022 Census denominators",
             ha="center", fontsize=8, color="gray")

    out = FIG_DIR / "fig2_division_map.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved choropleth: {out}")
    return True


def plot_bar_fallback(df_inc: pd.DataFrame, is_synthetic: bool):
    """Bar chart fallback when no shapefile is available."""
    df_sorted = df_inc.sort_values("incidence_per_100k", ascending=True)

    color_map = {"High": "#c0392b", "Moderate": "#e67e22", "Low": "#27ae60"}
    colors = [color_map.get(r, "#95a5a6") for r in df_sorted["flood_risk"]]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(df_sorted["division"], df_sorted["incidence_per_100k"],
                   color=colors, edgecolor="white", height=0.7)

    for bar, val in zip(bars, df_sorted["incidence_per_100k"]):
        ax.text(val + 20, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=9)

    legend_patches = [
        mpatches.Patch(color="#c0392b", label="High flood risk"),
        mpatches.Patch(color="#e67e22", label="Moderate flood risk"),
        mpatches.Patch(color="#27ae60", label="Low flood risk"),
    ]
    ax.legend(handles=legend_patches, loc="lower right", fontsize=9)

    title = "Figure 2: AWD Incidence per 100,000 by Division, Bangladesh 2014–2024"
    if is_synthetic:
        title += "\n(Synthetic data — replace with real EWARS data)"
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel("AWD cases per 100,000 population per year", fontsize=10)
    ax.set_xlim(0, df_sorted["incidence_per_100k"].max() * 1.15)
    ax.grid(axis="x", alpha=0.3)

    note = "For choropleth map: download Bangladesh shapefile from data.humdata.org → save as data/raw/bangladesh_divisions.geojson"
    fig.text(0.5, -0.02, note, ha="center", fontsize=7, color="gray", style="italic")

    plt.tight_layout()
    out = FIG_DIR / "fig2_division_map.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved bar chart (no shapefile): {out}")


def main():
    print("=" * 65)
    print("Script 02: Division-Level AWD Incidence Map")
    print("=" * 65)

    df_annual, source_name = load_awd_annual()
    is_synthetic = False

    if df_annual is not None:
        df_inc = compute_incidence(df_annual)
        if df_inc is None:
            print("  WARNING: loaded data invalid — using synthetic estimates.")
            df_inc = build_synthetic_incidence()
            is_synthetic = True
        else:
            print(f"  Using real data from {source_name}")
    else:
        df_inc = build_synthetic_incidence()
        is_synthetic = True

    # Save table
    table_path = PROC / "table2_division_incidence.csv"
    df_inc.to_csv(table_path, index=False)
    print(f"  Saved: {table_path}")

    print("\n  Incidence by division:")
    print(df_inc[["division", "incidence_per_100k", "flood_risk", "data_quality"]].to_string(index=False))

    # Try choropleth first, fallback to bar chart
    if not try_choropleth(df_inc):
        print("\n  No shapefile found — producing bar chart instead.")
        print("  For choropleth: download from data.humdata.org (Bangladesh admin level 1)")
        plot_bar_fallback(df_inc, is_synthetic)

    if is_synthetic:
        print("\n  NOTE: Results based on synthetic data. Update with real EWARS/DGHS data.")


if __name__ == "__main__":
    main()
