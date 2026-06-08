"""
Bangladesh AWD / Diarrhea Data Collector
=========================================
Source priority:
  1. IEDCR EWARS dashboard  (live — tries DHIS2 API + HTML scraping)
  2. DGHS Annual Health Bulletins  (PDF scraping, 2014-2024)
  3. IEDCR NBPH published reports  (open-access journal pages)
  4. IEDCR outbreak reports index

Outputs (saved to /Users/khalilur/Documents/AIWORK/diarrhea/data/raw/):
  awd_weekly_ewars.csv       — if EWARS is up
  awd_annual_dghs.csv        — from DGHS bulletins
  awd_source_log.txt         — which sources succeeded / failed
  MANUAL_DATA_GUIDE.txt      — instructions if scraping fails

Run:  python scrape_awd_data.py
"""

import requests
import urllib3
from bs4 import BeautifulSoup
import pdfplumber
import pandas as pd
import io
import re
import time
from datetime import datetime
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT_DIR = Path("/Users/khalilur/Documents/AIWORK/diarrhea/data/raw")
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

DIVISION_MAP = {
    "ঢাকা": "Dhaka", "চট্টগ্রাম": "Chattogram", "রাজশাহী": "Rajshahi",
    "খুলনা": "Khulna", "বরিশাল": "Barishal", "সিলেট": "Sylhet",
    "রংপুর": "Rangpur", "ময়মনসিংহ": "Mymensingh", "মোট": "Total",
    "চট্রগ্রাম": "Chattogram", "রংপু": "Rangpur", "ময়মনসিং": "Mymensingh",
    "Dhaka": "Dhaka", "Chittagong": "Chattogram", "Chattogram": "Chattogram",
    "Rajshahi": "Rajshahi", "Khulna": "Khulna", "Barishal": "Barishal",
    "Barisal": "Barishal", "Sylhet": "Sylhet", "Rangpur": "Rangpur",
    "Mymensingh": "Mymensingh",
}

DIVISIONS_EN = ["Dhaka", "Chittagong", "Chattogram", "Rajshahi", "Khulna",
                "Barishal", "Barisal", "Sylhet", "Rangpur", "Mymensingh"]

AWD_KEYWORDS_EN = ["diarrhea", "diarrhoea", "awd", "acute watery", "cholera"]
AWD_KEYWORDS_BN = ["ডায়রিয়া", "কলেরা", "তীব্র জলীয়"]

# Plausible AWD case count bounds per division per year
AWD_MIN = 100
AWD_MAX = 5_000_000
STUDY_YEARS = set(range(2010, 2026))

SOURCE_LOG = []


# ── Utility helpers ────────────────────────────────────────────────────────────

def bn2en(text: str) -> str:
    return text.translate(BANGLA_DIGITS).strip()


def clean_int(s: str):
    s = bn2en(str(s))
    s = re.sub(r"[,،\s]", "", s)
    return int(s) if re.match(r"^\d+$", s) else None


def is_valid_awd_cases(n) -> bool:
    """
    True if n is a plausible AWD case count (not a year, not a population figure).
    Bangladesh AWD: 100 to 5,000,000 cases per division per year.
    """
    if n is None or n <= 0:
        return False
    if n in STUDY_YEARS:  # 2010-2025 are year numbers, not case counts
        return False
    if n < AWD_MIN or n > AWD_MAX:
        return False
    if n >= 1_000_000 and n % 10_000 == 0:  # round millions = population artifact
        return False
    return True


def is_valid_deaths(n) -> bool:
    if n is None:
        return True
    return 0 <= n <= 10_000 and n not in STUDY_YEARS


def fetch_html(url: str, params=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers=HEADERS, verify=False, timeout=timeout)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    [WARN] GET {url[:70]}: {e}")
        return None


def fetch_bytes(url: str, timeout=60):
    try:
        r = requests.get(url, headers=HEADERS, verify=False, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"    [WARN] download {url[:70]}: {e}")
        return None


def fetch_json(url: str, params=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers=HEADERS, verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"    [WARN] JSON {url[:70]}: {e}")
        return None


def match_division(text: str):
    for key, val in DIVISION_MAP.items():
        if key and key in text:
            return val
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1: IEDCR EWARS
# ─────────────────────────────────────────────────────────────────────────────

EWARS_BASE = "https://ewars.iedcr.gov.bd"


def collect_from_ewars():
    print("\n[SOURCE 1] IEDCR EWARS")
    print("-" * 40)
    try:
        r = requests.get(EWARS_BASE, headers=HEADERS, verify=False, timeout=10)
        is_up = r.status_code < 500
    except Exception as e:
        print(f"    EWARS OFFLINE: {e}")
        SOURCE_LOG.append("EWARS: OFFLINE")
        print("    To get EWARS data: email iedcr@iedcr.gov.bd requesting divisional AWD data 2014-2024.")
        return None

    if not is_up:
        SOURCE_LOG.append(f"EWARS: HTTP {r.status_code}")
        return None

    print(f"    EWARS UP (status {r.status_code}) — trying public data access...")

    # Try DHIS2 API (requires auth — expected to fail publicly)
    me = fetch_json(f"{EWARS_BASE}/api/me")
    if me:
        data = fetch_json(f"{EWARS_BASE}/api/analytics.json", params={
            "dimension": "dx:AWD;ou:LEVEL-2",
            "filter": "pe:2014;2015;2016;2017;2018;2019;2020;2021;2022;2023;2024",
        })
        if data and "rows" in data:
            df = pd.DataFrame(data["rows"])
            df.to_csv(OUT_DIR / "awd_weekly_ewars.csv", index=False, encoding="utf-8-sig")
            SOURCE_LOG.append(f"EWARS: SUCCESS via DHIS2 ({len(df)} rows)")
            return df

    SOURCE_LOG.append("EWARS: ONLINE but requires authentication — data not accessible publicly")
    print("    EWARS requires login. See MANUAL_DATA_GUIDE.txt for how to request the data.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2: DGHS Annual Health Bulletins (PDF)
# ─────────────────────────────────────────────────────────────────────────────

DGHS_BASE = "http://old.dghs.gov.bd"

DGHS_KNOWN_BULLETINS = [
    {"url": "http://old.dghs.gov.bd/images/docs/Publicaations/Health%20Bulletin%202019%20Print%20Version%20(2)-Final.pdf", "year": 2019},
    {"url": "http://old.dghs.gov.bd/images/docs/Publicaations/HB%202018%20v2.pdf", "year": 2018},
    {"url": "http://old.dghs.gov.bd/images/docs/vpr/lhb_2020.pdf", "year": 2020},
]


def _parse_disease_table(tbl: list, year: int, page_num: int) -> list:
    """
    Parse one PDF table to extract AWD division-level case counts.

    Two possible layouts:
      A — rows=diseases, columns=divisions (header row has division names)
      B — rows=divisions, columns include AWD cases column
    """
    if not tbl or len(tbl) < 2:
        return []

    flat = " ".join(str(c) for r in tbl for c in (r or []) if c).lower()
    has_awd = any(k in flat for k in AWD_KEYWORDS_EN) or any(k in flat for k in AWD_KEYWORDS_BN)
    has_div = any(d.lower() in flat for d in DIVISIONS_EN) or "ঢাকা" in flat

    if not has_awd or not has_div:
        return []

    # Layout A: header row contains division names, find AWD data row
    rows_a = _layout_a(tbl, year, page_num)
    if rows_a:
        return rows_a

    # Layout B: first column has division names, find AWD column in header
    return _layout_b(tbl, year, page_num)


def _layout_a(tbl, year, page_num):
    """Rows = diseases; columns = divisions."""
    rows = []
    header_divs = []  # list of (col_idx, div_name)

    for i, row in enumerate(tbl):
        if not row:
            continue
        found = [(j, match_division(str(c or ""))) for j, c in enumerate(row) if match_division(str(c or ""))]
        found = [(j, d) for j, d in found if d and d != "Total"]
        if len(found) >= 3:
            header_divs = found
            header_row_idx = i
            break

    if len(header_divs) < 3:
        return rows

    for row in tbl[header_row_idx + 1:]:
        if not row:
            continue
        first = str(row[0] or "").lower()
        second = str(row[1] if len(row) > 1 else "").lower()
        is_awd = any(k in first or k in second for k in AWD_KEYWORDS_EN + AWD_KEYWORDS_BN)
        if not is_awd:
            continue
        for col_idx, div_name in header_divs:
            if col_idx >= len(row):
                continue
            val = clean_int(str(row[col_idx] or ""))
            if is_valid_awd_cases(val):
                rows.append({"year": year, "division": div_name, "awd_cases": val,
                              "awd_deaths": None, "source": f"DGHS Bulletin p{page_num} layout-A"})
    return rows


def _layout_b(tbl, year, page_num):
    """Rows = divisions; one column has AWD cases."""
    rows = []
    if not tbl:
        return rows

    header = tbl[0]
    awd_col = None
    death_col = None
    for j, cell in enumerate(header or []):
        t = str(cell or "").lower()
        if any(k in t for k in AWD_KEYWORDS_EN + AWD_KEYWORDS_BN):
            if "death" in t or "মৃত" in str(cell or ""):
                death_col = j
            elif awd_col is None:
                awd_col = j

    if awd_col is None:
        return rows

    for row in tbl[1:]:
        if not row:
            continue
        div_name = None
        for ci in [0, 1]:
            if ci < len(row):
                div_name = match_division(str(row[ci] or ""))
                if div_name:
                    break
        if not div_name:
            continue
        val = clean_int(str(row[awd_col])) if awd_col < len(row) else None
        deaths = None
        if death_col and death_col < len(row):
            d = clean_int(str(row[death_col] or ""))
            if is_valid_deaths(d):
                deaths = d
        if is_valid_awd_cases(val):
            rows.append({"year": year, "division": div_name, "awd_cases": val,
                         "awd_deaths": deaths, "source": f"DGHS Bulletin p{page_num} layout-B"})
    return rows


def extract_awd_from_bulletin_pdf(pdf_bytes: bytes, year: int) -> list:
    rows = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                for tbl in (page.extract_tables() or []):
                    rows.extend(_parse_disease_table(tbl, year, page_num))
    except Exception as e:
        print(f"    [WARN] PDF parse error: {e}")
    return rows


def extract_year_from_bytes(pdf_bytes: bytes):
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
            m = re.search(r"20(1[4-9]|2[0-4])", text)
            return int(m.group()) if m else None
    except Exception:
        return None


def find_bulletin_pdf_links() -> list:
    pdf_links = []
    soup = fetch_html(f"{DGHS_BASE}/index.php/en/publications")
    if not soup:
        return pdf_links
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"]
        if not any(k in text for k in ["bulletin", "annual", "বার্ষিক"]):
            continue
        full_url = href if href.startswith("http") else DGHS_BASE + href
        year_m = re.search(r"20(1[4-9]|2[0-4])", text + " " + href)
        year = int(year_m.group()) if year_m else None
        pdf_links.append({"url": full_url, "year": year})
    seen, unique = set(), []
    for item in pdf_links:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


def collect_from_dghs_bulletins():
    print("\n[SOURCE 2] DGHS Annual Health Bulletins")
    print("-" * 40)

    pdf_links = list(DGHS_KNOWN_BULLETINS)
    known_urls = {p["url"] for p in pdf_links}
    for item in find_bulletin_pdf_links():
        if item["url"] not in known_urls:
            pdf_links.append(item)
            known_urls.add(item["url"])

    all_rows = []
    found_pdfs = 0

    for item in pdf_links:
        year = item.get("year")
        if year and year < 2014:
            continue
        print(f"    year={year} → {item['url'][-60:]}...")
        pdf_bytes = fetch_bytes(item["url"], timeout=45)
        if not pdf_bytes or len(pdf_bytes) < 5000:
            continue
        found_pdfs += 1
        print(f"    Downloaded {len(pdf_bytes)//1024} KB — parsing...")
        year_to_use = year or extract_year_from_bytes(pdf_bytes)
        extracted = extract_awd_from_bulletin_pdf(pdf_bytes, year_to_use or 0)
        if extracted:
            print(f"    Extracted {len(extracted)} valid rows for year {year_to_use}")
            all_rows.extend(extracted)
        else:
            print(f"    No valid AWD table found (may be scanned image, not searchable text).")
        time.sleep(0.5)

    if not all_rows:
        SOURCE_LOG.append(
            f"DGHS Bulletins: {found_pdfs} PDFs downloaded, no valid AWD data extracted. "
            "PDFs likely use image scans (not selectable text). Manual extraction needed."
        )
        print(f"    {found_pdfs} PDFs tried — no validated data. See MANUAL_DATA_GUIDE.txt.")
        return None

    df = pd.DataFrame(all_rows).drop_duplicates(subset=["year", "division"]).sort_values(["year", "division"])
    df.to_csv(OUT_DIR / "awd_annual_dghs.csv", index=False, encoding="utf-8-sig")
    SOURCE_LOG.append(f"DGHS Bulletins: SUCCESS — {len(df)} rows from {found_pdfs} PDFs")
    print(f"    Saved: awd_annual_dghs.csv ({len(df)} rows)")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3: IEDCR NBPH Reports
# ─────────────────────────────────────────────────────────────────────────────

def collect_from_nbph():
    print("\n[SOURCE 3] IEDCR NBPH Published Reports")
    print("-" * 40)
    soup = fetch_html("http://nbph.iedcr.gov.bd/topic-index/")
    if not soup:
        SOURCE_LOG.append("NBPH: Not accessible")
        return None
    articles = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if any(k in text for k in ["diarrhea", "diarrhoea", "cholera", "awd", "watery"]):
            href = a["href"]
            full_url = href if href.startswith("http") else "http://nbph.iedcr.gov.bd" + href
            articles.append({"url": full_url, "title": a.get_text(strip=True)})
    if not articles:
        SOURCE_LOG.append("NBPH: No AWD articles found")
        print("    No AWD articles found.")
        return None
    all_rows = []
    for art in articles[:5]:
        print(f"    {art['title'][:60]}")
        s = fetch_html(art["url"])
        if not s:
            continue
        for tbl in s.find_all("table"):
            tbl_text = tbl.get_text().lower()
            if not any(d.lower() in tbl_text for d in DIVISIONS_EN):
                continue
            header = [th.get_text(strip=True) for th in tbl.find("tr").find_all(["th", "td"])]
            for tr in tbl.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    all_rows.append(dict(zip(header, cells)))
        time.sleep(0.4)
    if not all_rows:
        SOURCE_LOG.append("NBPH: Articles found but no extractable tables")
        return None
    df = pd.DataFrame(all_rows)
    df.to_csv(OUT_DIR / "awd_nbph.csv", index=False, encoding="utf-8-sig")
    SOURCE_LOG.append(f"NBPH: SUCCESS — {len(df)} rows")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 4: IEDCR Outbreak Reports
# ─────────────────────────────────────────────────────────────────────────────

def collect_from_iedcr_outbreak_page():
    print("\n[SOURCE 4] IEDCR Outbreak Reports Index")
    print("-" * 40)
    soup = fetch_html("http://www.iedcr.gov.bd/index.php/outbreak")
    if not soup:
        SOURCE_LOG.append("IEDCR Outbreak: Page not accessible")
        return None
    rows = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if not any(k in text.lower() for k in ["diarrhea", "diarrhoea", "cholera", "awd", "ডায়রিয়া"]):
            continue
        href = a["href"]
        full_url = href if href.startswith("http") else "https://iedcr.gov.bd" + href
        year_m = re.search(r"20(1[4-9]|2[0-4])", text)
        rows.append({"title": text, "url": full_url, "year": int(year_m.group()) if year_m else None})
    if not rows:
        SOURCE_LOG.append("IEDCR Outbreak: No AWD reports found")
        return None
    print(f"    Found {len(rows)} AWD/cholera outbreak reports")
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "iedcr_awd_reports_index.csv", index=False, encoding="utf-8-sig")
    SOURCE_LOG.append(f"IEDCR Outbreak: {len(rows)} report links saved")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL DATA GUIDE
# ─────────────────────────────────────────────────────────────────────────────

def write_manual_instructions():
    guide = f"""MANUAL DATA COLLECTION GUIDE
==============================
Generated: {datetime.now().strftime("%Y-%m-%d")}

EWARS (AWD cases) — automated scraping not possible (auth required)
  Email: iedcr@iedcr.gov.bd
  Request: weekly or annual AWD cases by division, 2014-2024

  OR: Download IEDCR Annual Reports from https://iedcr.gov.bd/index.php/publication
      Extract diarrhea/AWD table by division; save as data/raw/awd_annual_manual.csv
      Columns: year, division, awd_cases, awd_deaths

BWDB FFWC (flood data)
  Visit: https://ffwc.bwdb.gov.bd/ → Reports → Annual Flood Reports
  Extract: flood-affected area (km2) and flood duration (days) by division
  Save as: data/raw/flood_annual_division.csv
  Columns: year, division, flood_affected_km2, flood_duration_days, flood_severity

BMD ENACTS (rainfall data)
  Register at: https://dataportal.bmd.gov.bd/
  Download: monthly rainfall by division, 2014-2024
  Save as: data/raw/rainfall_monthly_division.csv
  Columns: year, month, division, rainfall_mm

Once data is collected, run analysis scripts in order:
  python analysis/01_seasonal_decomposition.py
  python analysis/02_division_incidence_map.py
  python analysis/03_flood_vs_awd.py
  python analysis/04_lag_cross_correlation.py
  python analysis/05_regression_model.py
"""
    path = OUT_DIR / "MANUAL_DATA_GUIDE.txt"
    with open(path, "w") as f:
        f.write(guide)
    print(f"\n  Manual guide: {path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("Bangladesh AWD / Diarrhea Data Collector")
    print(f"Output: {OUT_DIR}")
    print("=" * 65)

    results = {
        "ewars": collect_from_ewars(),
        "dghs_bulletins": collect_from_dghs_bulletins(),
        "nbph": collect_from_nbph(),
        "iedcr_outbreak": collect_from_iedcr_outbreak_page(),
    }

    any_awd_data = any(results[k] is not None for k in ["ewars", "dghs_bulletins", "nbph"])
    if not any_awd_data:
        write_manual_instructions()

    log_path = OUT_DIR / "awd_source_log.txt"
    with open(log_path, "w") as f:
        f.write(f"Run: {datetime.now().isoformat()}\n\n")
        for entry in SOURCE_LOG:
            f.write(f"  {entry}\n")
        if not any_awd_data:
            f.write("\n  ACTION REQUIRED: See MANUAL_DATA_GUIDE.txt\n")

    print("\n" + "=" * 65)
    print("COLLECTION SUMMARY")
    print("=" * 65)
    for source, df in results.items():
        status = f"OK ({len(df)} rows)" if df is not None else "NOT COLLECTED"
        print(f"  {source:30s} {status}")

    if not any_awd_data:
        print("\n  AWD case data requires manual collection.")
        print(f"  See: {OUT_DIR}/MANUAL_DATA_GUIDE.txt")


if __name__ == "__main__":
    main()
