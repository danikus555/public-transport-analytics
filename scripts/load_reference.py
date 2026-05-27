"""
scripts/load_reference.py

Loads and updates reference data:
- Scrapes TLT vehicle fleet from tlt.ee (weekly)
- Seeds static lookup tables (operators, line_types, fuel_types, cities)
- Can be run manually or via scheduler

Usage:
    python scripts/load_reference.py              # full update
    python scripts/load_reference.py --static     # only static lookups
    python scripts/load_reference.py --fleet      # only fleet scraping

Sources:
    https://tlt.ee/ettevottest/trammid/
    https://tlt.ee/ettevottest/trollid/
    https://tlt.ee/ettevottest/bussid/
"""

import os
import sys
import logging
import argparse
import psycopg2
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [load_reference] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/pipeline.log")
    ]
)
log = logging.getLogger(__name__)

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "transport_db"),
        user=os.getenv("DB_USER", "transport_user"),
        password=os.getenv("DB_PASSWORD", "changeme")
    )

# ── Static seed data ──────────────────────────────────────────
def load_static(conn):
    """Seed operators, line_types, fuel_types, cities — idempotent."""
    log.info("Loading static reference data...")
    cur = conn.cursor()

    cur.executemany("""
        INSERT INTO reference.operators (code, name, city, website)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            updated_at = NOW()
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
        ('diesel',   'Diislikütus', 'litre'),
        ('95',       'Bensiin 95',  'litre'),
        ('98',       'Bensiin 98',  'litre'),
        ('electric', 'Elekter',     'kwh'),
        ('gas',      'CNG gaas',    'kg'),
    ])

    cur.executemany("""
        INSERT INTO reference.cities
            (code, name, lat_min, lat_max, lon_min, lon_max)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (code) DO NOTHING
    """, [
        ('tallinn',  'Tallinn',     59.35, 59.55, 24.55, 24.95),
        ('tartu',    'Tartu',       58.30, 58.45, 26.60, 26.85),
        ('regional', 'Regionaalne', 57.50, 59.70, 21.50, 28.20),
    ])

    conn.commit()
    log.info("Static reference data loaded.")


# ── Known fuel types per model keyword ───────────────────────
FUEL_MAP = {
    "electric":  "electric",
    "32tr":      "electric",    # Škoda 32Tr akutroll
    "33tr":      "electric",    # Škoda 33Tr akutroll
    "cng":       "gas",
    "hybrid":    "diesel",      # hybrid uses diesel + electric
    "trollino":  "electric",
    "škoda 14":  "electric",
    "tatra":     "electric",
    "pesa":      "electric",
    "caf":       "electric",
    "elron":     "diesel",
    "flirt emu": "electric",
    "flirt":     "diesel",
}

# Known consumption per model (l or kWh per 100km)
CONSUMPTION_MAP = {
    # trams
    "pesa twist 147n":              8.5,
    "caf urbos axl":                8.0,
    "tatra kt4tmr":                 9.0,
    "tatra kt4":                    9.0,
    "tatra kt6tm":                  8.8,
    # new trolleybuses
    "škoda 32tr":                   2.5,
    "škoda 33tr":                   3.0,
    # old trolleybuses
    "solaris trollino iii 18 ac":   3.0,
    "solaris trollino iii 12 ac":   2.5,
    "škoda 14tr":                   2.8,
    # buses electric
    "solaris urbino iv 12 electric":120.0,
    # buses gas
    "solaris urbino iv 12 cng":     32.0,
    "solaris urbino iv 18 cng":     42.0,
    # buses diesel
    "man a78":                      32.0,
    "man a40":                      42.0,
    "man a21":                      30.0,
    # hybrid
    "volvo 7900 hybrid":            24.0,
    # minibus
    "mercedes-benz sprinter":       15.0,
    # trains
    "stadler flirt emu":             8.0,
    "stadler flirt":                 3.5,
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


# ── TLT fleet scraping ────────────────────────────────────────
TLT_PAGES = [
    {
        "url":       "https://tlt.ee/ettevottest/trammid/",
        "line_type": 1,
        "source":    "tlt.ee/trammid"
    },
    {
        "url":       "https://tlt.ee/ettevottest/trollid/",
        "line_type": 3,
        "source":    "tlt.ee/trollid"
    },
    {
        "url":       "https://tlt.ee/ettevottest/bussid/",
        "line_type": 2,
        "source":    "tlt.ee/bussid"
    },
]

# Headings to skip — not vehicle model names
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

                # skip short or known non-model headings
                if len(model_name) < 5:
                    continue
                if model_name.lower() in SKIP_HEADINGS:
                    continue
                # skip duplicate h2 (TLT page repeats model name twice)
                if any(m["model"] == model_name for m in models):
                    continue

                # get notes from next sibling
                notes = ""
                next_el = h2.find_next_sibling()
                if next_el and next_el.name in ["p", "div", "ul"]:
                    text = next_el.get_text(strip=True)
                    notes = text.split(".")[0][:150] if text else ""

                fuel_type   = detect_fuel_type(model_name)
                consumption = detect_consumption(model_name)

                models.append({
                    "operator_code":  "TLT",
                    "line_type_code": page["line_type"],
                    "model":          model_name,
                    "fuel_type_code": fuel_type,
                    "consumption":    consumption,
                    "notes":          notes,
                    "source":         page["source"],
                })
                log.info(f"  Found: {model_name} ({fuel_type}, {consumption} /100km)")

        except Exception as e:
            log.error(f"Failed to scrape {page['source']}: {e}")

    # Add Elron manually — no public fleet page to scrape
    models += [
        {
            "operator_code":  "Elron",
            "line_type_code": 2,
            "model":          "Stadler FLIRT",
            "fuel_type_code": "diesel",
            "consumption":    3.5,
            "notes":          "Diiselrong, Tallinn-Tartu/Narva/Viljandi",
            "source":         "elron.ee (manual)",
        },
        {
            "operator_code":  "Elron",
            "line_type_code": 2,
            "model":          "Stadler FLIRT EMU",
            "fuel_type_code": "electric",
            "consumption":    8.0,
            "notes":          "Elektrirongid",
            "source":         "elron.ee (manual)",
        },
    ]

    return models


def load_fleet(conn, models: list[dict]):
    """Upsert scraped fleet models into reference.vehicle_models."""
    if not models:
        log.warning("No models to load.")
        return

    cur = conn.cursor()
    inserted = 0
    updated  = 0

    for m in models:
        cur.execute("""
            SELECT id FROM reference.vehicle_models
            WHERE operator_code  = %s
              AND line_type_code  = %s
              AND model           = %s
        """, (m["operator_code"], m["line_type_code"], m["model"]))

        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE reference.vehicle_models SET
                    fuel_type_code = %s,
                    consumption    = %s,
                    notes          = %s,
                    updated_at     = NOW()
                WHERE id = %s
            """, (m["fuel_type_code"], m["consumption"], m["notes"], existing[0]))
            updated += 1
        else:
            cur.execute("""
                INSERT INTO reference.vehicle_models
                    (operator_code, line_type_code, model,
                     fuel_type_code, consumption, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                m["operator_code"], m["line_type_code"], m["model"],
                m["fuel_type_code"], m["consumption"], m["notes"]
            ))
            inserted += 1

    conn.commit()
    log.info(f"Fleet loaded: {inserted} inserted, {updated} updated.")


# ── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Load reference data into transport analytics DB"
    )
    parser.add_argument(
        "--static", action="store_true",
        help="Load only static lookups (operators, line_types, fuel_types, cities)"
    )
    parser.add_argument(
        "--fleet", action="store_true",
        help="Load only fleet data (scrape tlt.ee)"
    )
    args = parser.parse_args()

    run_static = not args.fleet   # default: run both
    run_fleet  = not args.static

    log.info("=" * 50)
    log.info("Starting reference data load")
    log.info(f"  static={run_static}  fleet={run_fleet}")
    log.info("=" * 50)

    conn = get_conn()
    try:
        if run_static:
            load_static(conn)

        if run_fleet:
            models = scrape_tlt_fleet()
            log.info(f"Scraped {len(models)} vehicle models total")
            load_fleet(conn, models)

        log.info("Reference data load complete.")

    except Exception as e:
        log.error(f"Reference load failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()