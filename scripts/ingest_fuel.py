"""
scripts/ingest_fuel.py

Scrapes and fetches fuel prices from multiple sources.
Saves to:
  - bronze.fuel_prices (PostgreSQL)
  - IN/fuel/YYYY/mmmYYYY/DDMMYYYY.json

Sources:
  teadmiseks.ee  → 95, 98, Diesel  (daily)
  elering.ee     → electric kWh     (every 15 min, Nord Pool)
  alexela.ee     → CNG kg           (weekly, changes rarely)

CNG scraping notes:
  Alexela CNG page uses JavaScript — price not in static HTML.
  Instead: scrape the Alexela news page for CNG price announcements.
  URL uses current year dynamically — no hardcoded year.
  Regex anchored to "CNG hind" context to avoid matching other prices.
  Fallback: if scraping fails, use last known price from DB.
  CNG price changes ~3-4 times per year.
"""

import os
import json
import time
import re
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("FUEL")

# ── Config — all from env ─────────────────────────────────────
FUEL_URL     = os.environ["FUEL_URL"]
ELECTRIC_URL = os.environ.get("ELECTRIC_URL", "https://dashboard.elering.ee/api/nps/price")
# ALEXELA_URL base — year appended dynamically in fetch_cng_price()
ALEXELA_URL_BASE = os.environ.get(
    "ALEXELA_URL",
    "https://www.alexela.ee/et/uudised-vana?year={year}&category=78"
)
IN_BASE = os.environ["IN_BASE"]

FUEL_TYPE_MAP = {
    "bensiin 95":  "95",
    "bensiin 98":  "98",
    "diislikütus": "Diesel",
    "diisel":      "Diesel",
}

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
        tech.error(f"Missing env variable: {e}")
        raise
    except psycopg2.OperationalError as e:
        tech.error(f"DB connection failed: {e}")
        raise

# ── Archive path ──────────────────────────────────────────────
def build_archive_path(now: datetime) -> Path:
    """IN/fuel/2026/may2026/27052026.json — one file per day."""
    folder = (
        Path(IN_BASE) / "fuel"
        / now.strftime("%Y")
        / now.strftime("%b%Y").lower()
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (now.strftime("%d%m%Y") + ".json")

# ── Scrape 95/98/Diesel from teadmiseks.ee ───────────────────
def scrape_fuel_prices() -> list[dict]:
    """Scrape 95, 98, Diesel from teadmiseks.ee."""
    t_start = time.time()
    headers = {"User-Agent": "Mozilla/5.0 (transport-analytics-bot/1.0)"}

    try:
        r = requests.get(FUEL_URL, headers=headers, timeout=15)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("FUEL", FUEL_URL, r.status_code, ms)
    except Exception as e:
        tech.error(f"Fuel fetch failed: {e}")
        return []

    soup   = BeautifulSoup(r.text, "html.parser")
    prices = []
    today  = date.today().isoformat()

    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        name       = cells[0].get_text(strip=True).lower()
        price_text = cells[1].get_text(strip=True)

        fuel_type = None
        for key, val in FUEL_TYPE_MAP.items():
            if key in name:
                fuel_type = val
                break

        if not fuel_type:
            continue

        price_str = re.sub(r"[^\d.,]", "", price_text).replace(",", ".")
        if not price_str:
            continue

        try:
            price = float(price_str)
        except ValueError:
            continue

        if not (0.5 <= price <= 3.0):
            log.warning(f"Suspicious price {price} for {fuel_type} — skipping")
            continue

        prices.append({
            "fuel_type":   fuel_type,
            "price_eur":   price,
            "source_date": today,
            "source":      "teadmiseks.ee",
        })

    return prices

# ── Fetch electric price from Elering ────────────────────────
def fetch_electric_price() -> dict | None:
    """
    Fetch current Nord Pool electricity price from Elering API.
    Returns price in €/kWh (converted from €/MWh).
    Updates every 15 minutes.
    Note: this is the wholesale spot price, not real consumer price.
    Real consumer all-in price is set via client_discounts override.
    """
    try:
        now_utc   = datetime.now(timezone.utc)
        start_utc = now_utc.strftime("%Y-%m-%dT%H:00:00Z")
        end_utc   = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z")

        url = f"{ELECTRIC_URL}?start={start_utc}&end={end_utc}"
        t_start = time.time()
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("FUEL", url, r.status_code, ms)

        data = r.json()
        ee_prices = data.get("data", {}).get("ee", [])
        if not ee_prices:
            log.warning("Elering returned no EE prices")
            return None

        # get latest price, convert €/MWh → €/kWh
        latest    = ee_prices[-1]
        price_kwh = round(latest["price"] / 1000, 6)

        return {
            "fuel_type":   "electric",
            "price_eur":   price_kwh,
            "source_date": date.today().isoformat(),
            "source":      "elering.ee",
        }
    except Exception as e:
        tech.error(f"Elering fetch failed: {e}")
        return None

# ── Fetch CNG price — DB fallback only ──────────────────────
def fetch_cng_price(conn=None) -> dict | None:
    """
    CNG price for Estonia (Alexela, only supplier, 11 stations).

    No public API or scrapeable page exists:
      - Alexela CNG price page uses JavaScript rendering
      - News page scraping unreliable (finds old articles with wrong prices)
      - No third-party API for Estonian CNG (fuelo.net blocks scrapers,
        GlobalPetrolPrices requires paid API key)

    Strategy: use last known price from DB.
    Price changes ~3-4x per year — last known is almost always current.

    Manual update when Alexela announces a price change:
      1. Check: https://www.alexela.ee/et/uudised-vana?year=YYYY&category=78
      2. Run in DBeaver:
           INSERT INTO bronze.fuel_prices (fuel_type, price_eur, source_date, source)
           VALUES ('CNG', <new_price>, CURRENT_DATE, 'alexela_manual');
    """
    if conn:
        return _get_last_known_cng(conn)

    log.warning("CNG: no DB connection available for fallback — skipping")
    return None


def _get_last_known_cng(conn) -> dict | None:
    """Return last known CNG price from DB as today's fallback."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT price_eur, source_date
            FROM bronze.fuel_prices
            WHERE UPPER(fuel_type) = 'CNG'
            ORDER BY source_date DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            price, last_date = row
            log.info(
                f"CNG fallback: using last known price {price} €/kg "
                f"from {last_date}"
            )
            return {
                "fuel_type":   "CNG",
                "price_eur":   float(price),
                "source_date": date.today().isoformat(),
                "source":      f"last_known_fallback_{last_date}",
            }
    except Exception as e:
        log.error(f"CNG DB fallback failed: {e}")
    return None

# ── Save to file ──────────────────────────────────────────────
def save_to_file(prices: list[dict], now: datetime) -> Path:
    filepath = build_archive_path(now)
    data = {
        "date":       now.date().isoformat(),
        "scraped_at": now.isoformat(),
        "prices":     {p["fuel_type"]: p["price_eur"] for p in prices}
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.debug(f"Saved to {filepath}")
    return filepath

# ── Save to DB ────────────────────────────────────────────────
def save_to_db(prices: list[dict], conn) -> int:
    if not prices:
        return 0

    cur      = conn.cursor()
    inserted = 0

    for p in prices:
        cur.execute("""
            SELECT id FROM bronze.fuel_prices
            WHERE fuel_type = %s AND source_date = %s
        """, (p["fuel_type"], p["source_date"]))

        if cur.fetchone():
            log.debug(f"Already have {p['fuel_type']} for {p['source_date']} — skipping")
            continue

        cur.execute("""
            INSERT INTO bronze.fuel_prices (fuel_type, price_eur, source_date, source)
            VALUES (%s, %s, %s, %s)
        """, (p["fuel_type"], p["price_eur"], p["source_date"], p.get("source", "")))
        inserted += 1

    conn.commit()
    return inserted

# ── One-time data correction ─────────────────────────────────
def correct_cng_price(conn):
    """
    Fix historically wrong CNG prices caused by broken scraper URL.
    The scraper was returning petrol price (~1.996) instead of CNG price.
    Real Alexela CNG price since 04.05.2026: 1.199 €/kg.

    This runs on every startup but only updates rows where price > 1.5 €/kg
    (i.e. clearly wrong — real CNG is 0.8-1.5 €/kg range).
    Safe to run repeatedly — no-op when prices are already correct.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE bronze.fuel_prices
            SET price_eur = 1.199,
                source    = 'alexela_corrected_04052026'
            WHERE UPPER(fuel_type) = 'CNG'
              AND price_eur > 1.5
        """)
        rows = cur.rowcount
        conn.commit()
        if rows > 0:
            log.info(f"CNG price correction applied: {rows} rows fixed (1.996 → 1.199 €/kg)")
        else:
            log.debug("CNG price correction: no rows needed fixing")
    except Exception as e:
        conn.rollback()
        log.error(f"CNG price correction failed: {e}")


# ── Main entry point ──────────────────────────────────────────
def ingest_fuel():
    now   = datetime.now()
    start = time.time()

    # 1. Scrape 95/98/Diesel
    prices = scrape_fuel_prices()

    # 2. Fetch electric price from Elering
    electric = fetch_electric_price()
    if electric:
        prices.append(electric)

    # Open DB connection early — needed for CNG fallback
    conn = None
    try:
        conn = get_conn()
        log_db_connected(
            os.environ["DB_HOST"],
            os.environ["DB_NAME"],
            os.environ["DB_USER"]
        )

        # 0. Fix any historically wrong CNG prices from broken scraper
        correct_cng_price(conn)

        # 3. Fetch CNG price — pass conn for DB fallback
        cng = fetch_cng_price(conn=conn)
        if cng:
            prices.append(cng)

        if not prices:
            log.warning("Fuel ingest returned 0 prices — skipping")
            return

        # save to file
        try:
            save_to_file(prices, now)
        except Exception as e:
            log.error(f"File save failed: {e}")

        # save to DB
        count   = save_to_db(prices, conn)
        elapsed = (time.time() - start) * 1000
        summary = ", ".join(
            f"{p['fuel_type']}={p['price_eur']}EUR" for p in prices
        )
        log.info(
            f"Fuel ingest OK — {count} prices → bronze.fuel_prices"
            f" | {summary}"
            f" | {elapsed:.0f}ms"
        )

    except Exception as e:
        log.error(f"DB save failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    ingest_fuel()