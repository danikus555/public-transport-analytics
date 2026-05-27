"""
scripts/ingest_fuel.py

Scrapes fuel prices from teadmiseks.ee.
Saves to:
  - bronze.fuel_prices (PostgreSQL)
  - IN/fuel/YYYY/mmmYYYY/DDMMYYYY.json
"""

import os
import json
import time
import re
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("FUEL")

# ── Config ───────────────────────────────────────────────────
FUEL_URL = os.getenv("FUEL_URL", "https://www.teadmiseks.ee/kasulikku/kutusehinnad/")
IN_BASE  = os.getenv("IN_BASE", "IN")

FUEL_TYPE_MAP = {
    "bensiin 95":  "95",
    "bensiin 98":  "98",
    "diislikütus": "Diesel",
    "diisel":      "Diesel",
}

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST",         "localhost"),
        port=int(os.getenv("DB_PORT",     5432)),
        dbname=os.getenv("DB_NAME",       "transport_db"),
        user=os.getenv("DB_USER",         "transport_user"),
        password=os.getenv("DB_PASSWORD", "changeme")
    )

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

# ── Scrape fuel prices ────────────────────────────────────────
def scrape_fuel() -> list[dict]:
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
        })
        log.debug(f"Scraped: {fuel_type} = {price} EUR")

    if not prices:
        tech.warning("No prices found — page structure may have changed")

    return prices

# ── Save to file ──────────────────────────────────────────────
def save_to_file(prices: list[dict], now: datetime) -> Path:
    filepath = build_archive_path(now)
    data = {
        "date":       now.date().isoformat(),
        "scraped_at": now.isoformat(),
        "source":     FUEL_URL,
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
            INSERT INTO bronze.fuel_prices (fuel_type, price_eur, source_date)
            VALUES (%s, %s, %s)
        """, (p["fuel_type"], p["price_eur"], p["source_date"]))
        inserted += 1

    conn.commit()
    return inserted

# ── Main entry point ──────────────────────────────────────────
def ingest_fuel():
    now   = datetime.now()
    start = time.time()

    prices = scrape_fuel()
    if not prices:
        log.warning("Fuel scrape returned 0 prices — skipping")
        return

    try:
        filepath = save_to_file(prices, now)
    except Exception as e:
        log.error(f"File save failed: {e}")
        filepath = None

    try:
        conn    = get_conn()
        log_db_connected(
            os.getenv("DB_HOST", "localhost"),
            os.getenv("DB_NAME", "transport_db"),
            os.getenv("DB_USER", "transport_user")
        )
        count   = save_to_db(prices, conn)
        conn.close()
        elapsed = (time.time() - start) * 1000

        # build summary without backslash in f-string
        summary = ", ".join(p["fuel_type"] + "=" + str(p["price_eur"]) + "EUR" for p in prices)
        log.info(f"Fuel ingest OK — {count} prices → bronze.fuel_prices | {summary} | {elapsed:.0f}ms")

    except Exception as e:
        log.error(f"DB save failed: {e}")


if __name__ == "__main__":
    ingest_fuel()