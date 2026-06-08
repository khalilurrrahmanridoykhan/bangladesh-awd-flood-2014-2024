"""
Script 05 — Negative Binomial Regression Model
================================================
Input:  data/raw/awd_annual_dghs.csv  (or manual)
        data/raw/flood_annual_division.csv
        data/raw/rainfall_monthly_division.csv
Output: data/processed/table4_regression.csv
        figures/fig5_regression_irr.png  (coefficient forest plot)

Model:
  AWD cases ~ flood_duration_days + monsoon_rainfall_mm
              + division fixed effects + year fixed effects
  Family: Negative binomial (count outcome, handles overdispersion)
  Offset: log(population)
  Interpretation: Incidence Rate Ratio (IRR) per unit change

Run:  python analysis/05_regression_model.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm
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

SYNTHETIC_BASE = {
    "Sylhet": 2850, "Mymensingh": 2450, "Barishal": 2380,
    "Rangpur": 2100, "Dhaka": 1820, "Chattogram": 1650,
    "Khulna": 1320, "Rajshahi": 1180,
}
SEVERE_YEARS = {2017, 2020, 2022}


def load_awd():
    for p in [RAW / "awd_annual_dghs.csv", RAW / "awd_annual_manual.csv"]:
        if p.exists() and p.stat().st_size > 200:
            df = pd.read_csv(p, encoding="utf-8-sig")
            if "awd_cases" in df.columns:
                valid = df[
                    df["division"].isin(DIVISIONS) &
                    df["awd_cases"].apply(lambda x: pd.notna(x) and x >= 1000)
                ]
                if len(valid) >= 10:
                    return valid[["year", "division", "awd_cases"]]
    return None


def load_flood():
    p = RAW / "flood_annual_division.csv"
    if p.exists():
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "flood_duration_days" in df.columns:
            return df[["year", "division", "flood_duration_days", "flood_severity"]]
    return None


def load_rainfall_monsoon():
    """Load rainfall data and compute annual monsoon total (June–October)."""
    p = RAW / "rainfall_monthly_division.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, encoding="utf-8-sig")
    if "rainfall_mm" not in df.columns:
        return None
    monsoon = df[df["month"].isin([6, 7, 8, 9, 10])]
    return monsoon.groupby(["year", "division"])["rainfall_mm"].sum().reset_index().rename(
        columns={"rainfall_mm": "monsoon_rainfall_mm"}
    )


def build_synthetic_panel() -> pd.DataFrame:
    """Build synthetic 80-observation panel for pipeline testing."""
    print("  [INFO] Building synthetic panel for regression testing.")
    rng = np.random.default_rng(42)
    monthly_normals_monsoon = {  # June-October totals
        "Dhaka": 1378, "Chattogram": 2110, "Rajshahi": 1204,
        "Khulna": 1449, "Barishal": 1692, "Sylhet": 3044,
        "Rangpur": 1508, "Mymensingh": 1588,
    }
    flood_base = {
        "Sylhet": 50, "Mymensingh": 42, "Rangpur": 38,
        "Dhaka": 28, "Barishal": 32, "Chattogram": 22,
        "Khulna": 10, "Rajshahi": 8,
    }
    rows = []
    for year in range(2014, 2025):
        flood_mult = 2.2 if year in SEVERE_YEARS else (1.4 if year == 2019 else 1.0)
        rain_bonus = 1.35 if year in SEVERE_YEARS else (1.15 if year == 2019 else 1.0)
        for div in DIVISIONS:
            pop = DIVISION_POP[div]
            flood_days = max(0, flood_base[div] * flood_mult + rng.normal(0, 3))
            monsoon_rain = monthly_normals_monsoon[div] * rain_bonus + rng.normal(0, 80)
            inc = SYNTHETIC_BASE[div] * (1 + 0.008 * flood_days + 0.00015 * monsoon_rain)
            awd_cases = int(max(100, inc * pop / 100_000 + rng.normal(0, inc * pop / 100_000 * 0.08)))
            rows.append({
                "year": year, "division": div,
                "awd_cases": awd_cases, "flood_duration_days": round(flood_days, 1),
                "monsoon_rainfall_mm": round(monsoon_rain, 1),
                "population": pop, "is_synthetic": True,
            })
    return pd.DataFrame(rows)


def build_panel(df_awd, df_flood, df_rain) -> tuple:
    """Merge all sources into regression panel."""
    if df_awd is not None and df_flood is not None and df_rain is not None:
        panel = (
            df_awd
            .merge(df_flood, on=["year", "division"], how="inner")
            .merge(df_rain, on=["year", "division"], how="inner")
        )
        panel["population"] = panel["division"].map(DIVISION_POP)
        panel["is_synthetic"] = False
        if len(panel) >= 20:
            return panel, False
        print(f"  Merged panel only {len(panel)} rows — insufficient. Using synthetic.")

    return build_synthetic_panel(), True


def run_negative_binomial(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Fit negative binomial regression:
      AWD cases ~ flood_days/10 + monsoon_rain/100 + div_FE + year_FE + offset(log(pop))
    Reports IRR (exp(coef)) with 95% CI.
    """
    df = panel.copy()
    df["flood_days_10"] = df["flood_duration_days"] / 10.0
    df["monsoon_rain_100"] = df["monsoon_rainfall_mm"] / 100.0
    df["log_pop"] = np.log(df["population"])
    df["year"] = df["year"].astype(str)

    # Division and year fixed effects (dummy variables; Dhaka and 2014 as reference)
    div_dummies = pd.get_dummies(df["division"], drop_first=False, prefix="div")
    div_dummies = div_dummies.drop(columns=["div_Dhaka"], errors="ignore")
    year_dummies = pd.get_dummies(df["year"], drop_first=False, prefix="year")
    year_dummies = year_dummies.drop(columns=["year_2014"], errors="ignore")

    X = pd.concat([
        df[["flood_days_10", "monsoon_rain_100"]],
        div_dummies,
        year_dummies,
    ], axis=1).astype(float)

    X = sm.add_constant(X)
    y = df["awd_cases"].astype(float)
    offset = df["log_pop"].astype(float)

    result = None
    # Try gradient-based methods first; fall back progressively
    for method, kwargs in [
        ("bfgs",    {"disp": False, "maxiter": 1000}),
        ("lbfgs",   {"disp": False, "maxiter": 2000}),
        ("newton",  {"disp": False, "maxiter": 500}),
        ("nm",      {"disp": False, "maxiter": 2000}),
    ]:
        try:
            m = sm.NegativeBinomial(y, X, exposure=np.exp(offset))
            r = m.fit(method=method, **kwargs)
            # Reject degenerate solution: all main coefs essentially zero
            if abs(r.params.get("flood_days_10", 0)) < 1e-10 and abs(r.params.get("monsoon_rain_100", 0)) < 1e-10:
                print(f"  NB/{method}: degenerate (all betas~0), trying next method")
                continue
            result = r
            print(f"  NB/{method}: converged (AIC={r.aic:.1f})")
            break
        except Exception as e:
            print(f"  NB/{method} failed: {e}")

    if result is None:
        print("  All NB methods failed or degenerate — falling back to Poisson GLM...")
        try:
            model = sm.GLM(y, X, family=sm.families.Poisson(), offset=offset)
            result = model.fit()
            print(f"  Poisson GLM: converged")
        except Exception as e2:
            print(f"  Poisson also failed: {e2}")
            return pd.DataFrame()

    # Extract coefficients of interest
    coef = result.params
    conf = result.conf_int()
    pvals = result.pvalues

    rows = []
    for var in ["const", "flood_days_10", "monsoon_rain_100"]:
        if var not in coef.index:
            continue
        b = coef[var]
        lo, hi = conf.loc[var, 0], conf.loc[var, 1]
        irr = round(np.exp(b), 4)
        irr_lo = round(np.exp(lo), 4)
        irr_hi = round(np.exp(hi), 4)
        p = round(pvals[var], 4)
        label = {
            "const": "Intercept",
            "flood_days_10": "Flood duration (per 10 days)",
            "monsoon_rain_100": "Monsoon rainfall (per 100 mm)",
        }.get(var, var)
        rows.append({
            "variable": label,
            "coef": round(b, 4),
            "IRR": irr,
            "IRR_95CI_lower": irr_lo,
            "IRR_95CI_upper": irr_hi,
            "p_value": p,
            "significant": p < 0.05,
        })

    # Division FEs summary
    div_fe = [(v, coef[v]) for v in coef.index if v.startswith("div_")]
    if div_fe:
        highest = max(div_fe, key=lambda x: x[1])
        rows.append({
            "variable": f"Division FE (highest: {highest[0].replace('div_','')})",
            "coef": round(highest[1], 4),
            "IRR": round(np.exp(highest[1]), 4),
            "IRR_95CI_lower": round(np.exp(conf.loc[highest[0], 0]), 4),
            "IRR_95CI_upper": round(np.exp(conf.loc[highest[0], 1]), 4),
            "p_value": round(pvals[highest[0]], 4),
            "significant": pvals[highest[0]] < 0.05,
        })

    return pd.DataFrame(rows)


def plot_irr_forest(df_reg: pd.DataFrame, is_synthetic: bool):
    """Forest plot of IRRs for key predictors."""
    # Only plot the main predictors (not intercept)
    to_plot = df_reg[~df_reg.variable.str.contains("Intercept")].copy()
    if to_plot.empty:
        return

    fig, ax = plt.subplots(figsize=(9, max(3, len(to_plot) * 1.3)))

    y_pos = range(len(to_plot))
    colors = ["#c0392b" if sig else "#7f8c8d" for sig in to_plot["significant"]]

    max_x = to_plot["IRR"].max()
    for i, (_, row) in enumerate(to_plot.iterrows()):
        irr = row["IRR"]
        lo, hi = row["IRR_95CI_lower"], row["IRR_95CI_upper"]
        has_ci = pd.notna(lo) and pd.notna(hi)
        if has_ci:
            ax.errorbar(irr, i, xerr=[[irr - lo], [hi - irr]],
                        fmt="o", color=colors[i], ms=8, capsize=4, elinewidth=1.5)
            max_x = max(max_x, hi)
        else:
            ax.plot(irr, i, "o", color=colors[i], ms=8)

        pval = row["p_value"]
        sig_marker = "**" if pd.notna(pval) and pval < 0.01 else ("*" if pd.notna(pval) and pval < 0.05 else "")
        pval_str = f"{pval:.3f}" if pd.notna(pval) else "n/a"
        ci_str = (f"95%CI {lo:.3f}–{hi:.3f} " if has_ci else "")
        ax.text(
            (hi if has_ci else irr) + 0.01, i,
            f"IRR={irr:.3f} {ci_str}p={pval_str}{sig_marker}",
            va="center", fontsize=8,
        )

    ax.axvline(1.0, color="black", lw=1.0, ls="--")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(to_plot["variable"].tolist(), fontsize=9)
    ax.set_xlabel("Incidence Rate Ratio (IRR)", fontsize=10)
    title = "Figure 5: IRR Forest Plot — Negative Binomial Regression\nBangladesh AWD 2014–2024 (reference: Dhaka, 2014)"
    if is_synthetic:
        title += "\n(Synthetic data — for pipeline testing)"
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.grid(True, alpha=0.25, axis="x")
    ax.set_xlim(0.5, max(max_x * 1.6, 3.0))

    plt.tight_layout()
    out = FIG_DIR / "fig5_regression_irr.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out}")


def main():
    print("=" * 65)
    print("Script 05: Negative Binomial Regression Model")
    print("=" * 65)

    df_awd = load_awd()
    df_flood = load_flood()
    df_rain = load_rainfall_monsoon()

    panel, is_synthetic = build_panel(df_awd, df_flood, df_rain)
    print(f"  Panel: {len(panel)} observations | synthetic={is_synthetic}")

    print("  Fitting negative binomial model...")
    df_reg = run_negative_binomial(panel)

    if df_reg.empty:
        print("  Model fitting failed. Check data completeness.")
        return

    if is_synthetic:
        df_reg["data_note"] = "synthetic_data"

    table_path = PROC / "table4_regression.csv"
    df_reg.to_csv(table_path, index=False)
    print(f"  Saved: {table_path}")

    print("\nRegression results:")
    print(df_reg[["variable", "IRR", "IRR_95CI_lower", "IRR_95CI_upper", "p_value", "significant"]].to_string(index=False))

    # Interpret flood effect
    flood_row = df_reg[df_reg.variable.str.contains("Flood duration")]
    if not flood_row.empty:
        irr = flood_row.iloc[0]["IRR"]
        pct = (irr - 1) * 100
        print(f"\nKey finding: Each additional 10 flood days → {pct:+.1f}% change in AWD incidence (IRR={irr:.3f})")

    plot_irr_forest(df_reg, is_synthetic)

    if is_synthetic:
        print("\n  NOTE: All results based on synthetic data. Replace with real EWARS/DGHS/BWDB data.")


if __name__ == "__main__":
    main()
