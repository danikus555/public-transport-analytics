"""
scripts/load_reference.py

Loads and updates reference data:
- Scrapes TLT vehicle fleet from tlt.ee (weekly)
- Seeds static lookup tables (operators, line_types, fuel_types, cities)
- Elron fleet added manually (no public fleet page)

Usage:
    python scripts/load_reference.py              # full update
    python scripts/load_reference.py --static     # only static lookups
    python scripts/load_reference.py --fleet      # only fleet scraping

Sources:
    https://tlt.ee/ettevottest/trammid/
    https://tlt.ee/ettevottest/trollid/
    https://tlt.ee/ettevottest/bussid/
    https://elron.ee/elronist/elroni-rongid (manual)
"""

import os
import re
import sys
import argparse
import psycopg2
import requests
from bs4 import BeautifulSoup

from logger import log, get_tech_log

tech = get_tech_log("REFERENCE")

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    try:
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"]
        )
    except KeyError as e:
        log.error(f"Missing env variable: {e}")
        raise
    except psycopg2.OperationalError as e:
        log.error(f"DB connection failed: {e}")
        raise

# ── Static seed data ──────────────────────────────────────────
def load_static(conn):
    """Seed operators, line_types, fuel_types, cities — idempotent."""
    log.info("Loading static reference data...")
    cur = conn.cursor()

    cur.executemany("""
        INSERT INTO reference.operators (code, name, city, website)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
    """, [
        ('TLT',   'Tallinna Linnatransport', 'Tallinn',  'https://tlt.ee'),
        ('Elron', 'Elron',                   'Regional', 'https://elron.ee'),
        ('SEBE',  'SEBE',                    'Regional', 'https://sebe.ee'),
    ])

    cur.executemany("""
        INSERT INTO reference.line_types (code, name, name_et, fuel_category)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (code) DO NOTHING
    """, [
        (1, 'tram',       'tramm', 'electric'),
        (2, 'bus',        'buss',  'mixed'),
        (3, 'trolleybus', 'troll', 'electric'),
    ])

    cur.executemany("""
        INSERT INTO reference.fuel_types (code, name, unit)
        VALUES (%s, %s, %s)
        ON CONFLICT (code) DO NOTHING
    """, [
        ('diesel',        'Diislikütus',    'litre'),
        ('95',            'Bensiin 95',     'litre'),
        ('98',            'Bensiin 98',     'litre'),
        ('electric',      'Elekter',        'kwh'),
        ('gas',           'CNG gaas',       'kg'),
        ('hybrid_diesel', 'Hübriid-diisel', 'litre'),
    ])

    cur.executemany("""
        INSERT INTO reference.cities (code, name, lat_min, lat_max, lon_min, lon_max)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (code) DO NOTHING
    """, [
        ('tallinn',  'Tallinn',     59.35, 59.55, 24.55, 24.95),
        ('tartu',    'Tartu',       58.30, 58.45, 26.60, 26.85),
        ('regional', 'Regionaalne', 57.50, 59.70, 21.50, 28.20),
    ])

    conn.commit()
    log.info("Static reference data loaded.")

# ── Fuel type detection ───────────────────────────────────────
FUEL_MAP = {
    "32tr":      "electric",
    "33tr":      "electric",
    "electric":  "electric",
    "cng":       "gas",
    "hybrid":    "hybrid_diesel",
    "trollino":  "electric",
    "škoda 14":  "electric",
    "tatra":     "electric",
    "pesa":      "electric",
    "caf":       "electric",
    "flirt emu": "electric",
    "flirt":     "diesel",
}

CONSUMPTION_MAP = {
    "pesa twist 147n":               8.5,
    "caf urbos axl":                 8.0,
    "tatra kt4tmr":                  9.0,
    "tatra kt4":                     9.0,
    "tatra kt6tm":                   8.8,
    "škoda 32tr":                    2.5,
    "škoda 33tr":                    3.0,
    "solaris trollino iii 18 ac":    3.0,
    "solaris trollino iii 12 ac":    2.5,
    "škoda 14tr":                    2.8,
    "solaris urbino iv 12 electric": 120.0,
    "solaris urbino iv 12 cng":      32.0,
    "solaris urbino iv 18 cng":      42.0,
    "man a78":                       32.0,
    "man a40":                       42.0,
    "man a21":                       30.0,
    "volvo 7900 hybrid":             24.0,
    "mercedes-benz sprinter":        15.0,
    "stadler flirt emu":              8.0,
    "stadler flirt":                  3.5,
    "škoda 21ev":                     8.0,
}

CONSUMPTION_UNIT_MAP = {
    "electric":      "kWh/100km",
    "gas":           "kg/100km",
    "diesel":        "l/100km",
    "hybrid_diesel": "l/100km",
}

# Known vehicle amounts — used as fallback if scraper does not find amount
# Sources:
#   TLT trammid: https://en.wikipedia.org/wiki/Trams_in_Tallinn (59 total, 2024)
#   TLT bussid:  https://en.wikipedia.org/wiki/Public_transport_in_Tallinn
#   Elron:       https://elron.ee/elronist/elroni-rongid
KNOWN_AMOUNTS = {
    # TLT trammid (kokku 59)
    ("TLT", 1, "PESA Twist 147N"):               23,
    ("TLT", 1, "CAF Urbos AXL"):                 10,
    ("TLT", 1, "Tatra KT4"):                      8,
    ("TLT", 1, "Tatra KT6TM"):                   10,
    ("TLT", 1, "Tatra KT4TMR"):                   8,
    # TLT trollid (vanad, alles mõned)
    ("TLT", 3, "Solaris Trollino III 18 AC"):     1,
    ("TLT", 3, "Solaris Trollino III 12 AC"):     1,
    ("TLT", 3, "Škoda 14Tr"):                     1,
    # TLT bussid
    ("TLT", 2, "Solaris Urbino IV 12 Electric"):  15,
    ("TLT", 2, "Solaris Urbino IV 12 CNG"):      200,
    ("TLT", 2, "Solaris Urbino IV 18 CNG"):      150,
    ("TLT", 2, "MAN A78 Lion's City LE EL293"):   50,
    ("TLT", 2, "MAN A40 Lion's City GL NG323"):   30,
    ("TLT", 2, "MAN A21 Lion's City NL283"):       5,
    ("TLT", 2, "Volvo 7900 Hybrid"):              10,
    ("TLT", 2, "Mercedes-Benz Sprinter"):          5,
}

def detect_fuel_type(model_name: str) -> str:
    name_lower = model_name.lower()
    for keyword, fuel in FUEL_MAP.items():
        if keyword in name_lower:
            return fuel
    return "diesel"

def detect_consumption(model_name: str) -> float | None:
    name_lower = model_name.lower()
    for keyword, consumption in CONSUMPTION_MAP.items():
        if keyword in name_lower:
            return consumption
    return None

def extract_vehicle_amount(text: str) -> int | None:
    """Extract vehicle count from page text. E.g. '23 tükki' → 23."""
    if not text:
        return None
    match = re.search(r'(\d+)\s+tükk', text.lower())
    if match:
        return int(match.group(1))
    return None

# ── TLT fleet scraping ────────────────────────────────────────
TLT_PAGES = [
    {"url": "https://tlt.ee/ettevottest/trammid/", "line_type": 1, "source": "tlt.ee/trammid"},
    {"url": "https://tlt.ee/ettevottest/trollid/", "line_type": 3, "source": "tlt.ee/trollid"},
    {"url": "https://tlt.ee/ettevottest/bussid/",  "line_type": 2, "source": "tlt.ee/bussid"},
]

SKIP_HEADINGS = {
    "kontakt", "sõidukite tellimine", "bussiveerem",
    "trammiveerem", "trolliveerem", "kasutame küpsiseid"
}

def scrape_tlt_fleet() -> list[dict]:
    """Scrape vehicle models from tlt.ee fleet pages."""
    models = []
    headers = {"User-Agent": "Mozilla/5.0 (transport-analytics-bot/1.0)"}

    for page in TLT_PAGES:
        log.info(f"Scraping {page['source']}...")
        try:
            r = requests.get(page["url"], headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            for h2 in soup.find_all("h2"):
                model_name = h2.get_text(strip=True)

                if len(model_name) < 5:
                    continue
                if model_name.lower() in SKIP_HEADINGS:
                    continue
                if any(m["model"] == model_name for m in models):
                    continue

                # get raw text from next sibling for vehicle count
                raw_text = ""
                next_el = h2.find_next_sibling()
                if next_el and next_el.name in ["p", "div", "ul"]:
                    raw_text = next_el.get_text(strip=True)

                fuel_type      = detect_fuel_type(model_name)
                consumption    = detect_consumption(model_name)
                cons_unit      = CONSUMPTION_UNIT_MAP.get(fuel_type, "l/100km")
                scraped_amount = extract_vehicle_amount(raw_text)
                key            = ("TLT", page["line_type"], model_name)

                # use scraped amount if found, otherwise fall back to known static amount
                vehicle_amount = scraped_amount if scraped_amount is not None else KNOWN_AMOUNTS.get(key)

                models.append({
                    "operator_code":    "TLT",
                    "line_type_code":   page["line_type"],
                    "model":            model_name,
                    "fuel_type_code":   fuel_type,
                    "consumption":      consumption,
                    "consumption_unit": cons_unit,
                    "vehicle_amount":   vehicle_amount,
                })
                log.info(
                    f"  Found: {model_name} "
                    f"({fuel_type}, {consumption} {cons_unit}"
                    f"{', n=' + str(vehicle_amount) if vehicle_amount else ''})"
                )

        except Exception as e:
            log.error(f"Failed to scrape {page['source']}: {e}")

    # ── Elron — manual (no public fleet page) ────────────────
    # Source: https://elron.ee/elronist/elroni-rongid
    models += [
        {
            "operator_code":    "Elron",
            "line_type_code":   2,
            "model":            "Stadler FLIRT DMU",
            "fuel_type_code":   "diesel",
            "consumption":      3.5,
            "consumption_unit": "l/100km",
            "vehicle_amount":   20,
        },
        {
            "operator_code":    "Elron",
            "line_type_code":   2,
            "model":            "Stadler FLIRT EMU",
            "fuel_type_code":   "electric",
            "consumption":      8.0,
            "consumption_unit": "kWh/100km",
            "vehicle_amount":   18,
        },
        {
            "operator_code":    "Elron",
            "line_type_code":   2,
            "model":            "Škoda 21Ev (pikamaa)",
            "fuel_type_code":   "electric",
            "consumption":      8.0,
            "consumption_unit": "kWh/100km",
            "vehicle_amount":   11,
        },
        {
            "operator_code":    "Elron",
            "line_type_code":   2,
            "model":            "Škoda 21Ev (linnalähirong)",
            "fuel_type_code":   "electric",
            "consumption":      6.0,
            "consumption_unit": "kWh/100km",
            "vehicle_amount":   5,
        },
    ]

    return models

# ── Load fleet to DB ──────────────────────────────────────────
def load_fleet(conn, models: list[dict]):
    """Upsert fleet models into reference.vehicle_models."""
    if not models:
        log.warning("No models to load.")
        return

    cur      = conn.cursor()
    inserted = 0
    updated  = 0

    try:
        for m in models:
            # Sprinter is social transport — exclude from cost calculations
            active = m["model"] != "Mercedes-Benz Sprinter"

            cur.execute("""
                INSERT INTO reference.vehicle_models
                    (operator_code, line_type_code, model,
                     fuel_type_code, consumption, consumption_unit, vehicle_amount, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (operator_code, line_type_code, model)
                DO UPDATE SET
                    fuel_type_code   = EXCLUDED.fuel_type_code,
                    consumption      = EXCLUDED.consumption,
                    consumption_unit = EXCLUDED.consumption_unit,
                    vehicle_amount   = EXCLUDED.vehicle_amount,
                    active           = EXCLUDED.active,
                    updated_at       = NOW()
            """, (
                m["operator_code"],
                m["line_type_code"],
                m["model"],
                m["fuel_type_code"],
                m["consumption"],
                m.get("consumption_unit", "l/100km"),
                m.get("vehicle_amount"),
                active,
            ))
            if cur.rowcount == 1:
                inserted += 1
            else:
                updated += 1

        conn.commit()
        log.info(f"Fleet loaded: {inserted} inserted, {updated} updated.")

    except Exception as e:
        conn.rollback()
        log.error(f"Fleet load failed: {e}")
        raise

# ── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Load reference data")
    parser.add_argument("--static", action="store_true", help="Only static lookups")
    parser.add_argument("--fleet",  action="store_true", help="Only fleet data")
    args = parser.parse_args()

    run_static = not args.fleet
    run_fleet  = not args.static

    log.info("=" * 50)
    log.info("Starting reference data load")
    log.info(f"  static={run_static}  fleet={run_fleet}")
    log.info("=" * 50)

    conn = None
    try:
        conn = get_conn()

        if run_static:
            load_static(conn)

        if run_fleet:
            models = scrape_tlt_fleet()
            log.info(f"Scraped {len(models)} vehicle models total")
            load_fleet(conn, models)

        log.info("Reference data load complete.")

    except Exception as e:
        log.error(f"Reference load failed: {e}")
        if conn:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()