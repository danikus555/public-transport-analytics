"""
scripts/ingest_gps.py

Fetches live GPS data from Tallinn public transport feed.
Saves to:
  - bronze.vehicle_positions (PostgreSQL)
  - IN/gps/YYYY/mmmYYYY/DDMMYYYY/DDMMYYYY_HHMM.txt

GPS feed format (comma-separated, no header):
  cols[0] = line_type      (2=bus, 3=tram)
  cols[1] = line_number    (36, 12, 5, 42 etc)
  cols[2] = lon * 1000000
  cols[3] = lat * 1000000
  cols[4] = empty
  cols[5] = bearing
  cols[6] = vehicle_id
  cols[7] = low_floor      (Z=yes, false=no)
  cols[8] = ??? (seems unused)
  cols[9] = destination
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("GPS")

# ── Config ───────────────────────────────────────────────────
GPS_URL  = os.environ["GPS_URL"]
OPERATOR = os.environ.get("GPS_OPERATOR", "TLT")
IN_BASE  = os.environ["IN_BASE"]

ESTONIA_BOUNDS = {
    "lat_min": 57.50, "lat_max": 60.00,
    "lon_min": 21.50, "lon_max": 28.50,
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
    """IN/gps/2026/may2026/27052026/27052026_1000.txt"""
    folder = (
        Path(IN_BASE) / "gps"
        / now.strftime("%Y")
        / now.strftime("%b%Y").lower()
        / now.strftime("%d%m%Y")
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (now.strftime("%d%m%Y_%H%M") + ".txt")

# ── Parse one GPS line ────────────────────────────────────────
def parse_line(line: str) -> dict | None:
    """Parse one CSV line from GPS feed. Returns dict or None if invalid."""
    try:
        cols = line.strip().split(",")
        if len(cols) < 10:
            return None

        lon = int(cols[2]) / 1_000_000
        lat = int(cols[3]) / 1_000_000

        # validate coordinates within Estonia
        if not (
            ESTONIA_BOUNDS["lat_min"] <= lat <= ESTONIA_BOUNDS["lat_max"] and
            ESTONIA_BOUNDS["lon_min"] <= lon <= ESTONIA_BOUNDS["lon_max"]
        ):
            return None

        return {
            "vehicle_id":  int(cols[6]) if cols[6].strip() else None,
            "line_type":   int(cols[0]),
            "line_number": cols[1].strip(),
            "destination": cols[9].strip(),
            "lat":         lat,
            "lon":         lon,
            "bearing":     int(cols[5]) if cols[5].strip() else None,
            "low_floor":   cols[7].strip().upper() == "Z",
            "operator":    OPERATOR,
        }

    except (ValueError, IndexError):
        return None

# ── Fetch GPS feed ────────────────────────────────────────────
def fetch_gps() -> list[dict]:
    """Fetch and parse GPS feed. Returns list of vehicle dicts."""
    t_start = time.time()
    try:
        r = requests.get(GPS_URL, timeout=10)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("GPS", GPS_URL, r.status_code, ms)
    except Exception as e:
        tech.error(f"Fetch failed: {e}")
        return []

    rows    = []
    skipped = 0
    for line in r.text.splitlines():
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed:
            rows.append(parsed)
        else:
            skipped += 1

    log.debug(f"Parsed {len(rows)} rows, skipped {skipped} invalid")
    return rows

# ── Save to file ──────────────────────────────────────────────
def save_to_file(rows: list[dict], now: datetime) -> Path:
    """Save rows to archive file."""
    filepath  = build_archive_path(now)
    timestamp = now.isoformat()

    with open(filepath, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                f"{timestamp},"
                f"{row['vehicle_id']},"
                f"{row['line_type']},"
                f"{row['line_number']},"
                f"{row['destination']},"
                f"{row['lat']},"
                f"{row['lon']},"
                f"{row['bearing']},"
                f"{row['low_floor']},"
                f"{row['operator']}\n"
            )

    log.debug(f"Saved to {filepath}")
    return filepath

# ── Save to DB ────────────────────────────────────────────────
def save_to_db(rows: list[dict], conn) -> int:
    """Insert rows into bronze.vehicle_positions."""
    if not rows:
        return 0

    cur = conn.cursor()
    cur.executemany("""
        INSERT INTO bronze.vehicle_positions
            (vehicle_id, line_type, line_number, destination,
             lat, lon, bearing, low_floor, operator)
        VALUES
            (%(vehicle_id)s, %(line_type)s, %(line_number)s, %(destination)s,
             %(lat)s, %(lon)s, %(bearing)s, %(low_floor)s, %(operator)s)
    """, rows)
    conn.commit()
    return len(rows)

# ── Main entry point ──────────────────────────────────────────
def ingest_gps():
    """Fetch GPS feed → save to file archive + DB."""
    now   = datetime.now()
    start = time.time()

    rows = fetch_gps()
    if not rows:
        log.warning("GPS fetch returned 0 rows — skipping")
        return

    try:
        filepath = save_to_file(rows, now)
    except Exception as e:
        log.error(f"File save failed: {e}")
        filepath = None

    conn = None
    try:
        conn    = get_conn()
        log_db_connected(
            os.environ["DB_HOST"],
            os.environ["DB_NAME"],
            os.environ["DB_USER"]
        )
        count   = save_to_db(rows, conn)
        elapsed = (time.time() - start) * 1000
        log.info(
            f"GPS ingest OK — {count} vehicles → bronze.vehicle_positions"
            f" | file={filepath.name if filepath else 'none'}"
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
    ingest_gps()